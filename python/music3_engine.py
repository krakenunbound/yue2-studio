"""Standalone MiniMax Music 3 worker supervision.

This module deliberately does not connect to a ComfyUI process.  It launches a
private worker owned by MiniMaxM3 and uses a pinned copy of the upstream model
implementation as a Python inference library.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import audioop
import wave
from collections import deque
from pathlib import Path

from config import ENGINE_ROOT, MODEL_ROOT, WORKER_PYTHON
import generation_timing

log = logging.getLogger("music3.engine")
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_PROCESS: subprocess.Popen[str] | None = None
_LOCK = threading.RLock()
_START_LOCK = threading.Lock()

MODEL_FILES = {
    "diffusion": MODEL_ROOT / "diffusion_models" / "minimax_music3_dit_int8_convrot.safetensors",
    "text_encoder": MODEL_ROOT / "text_encoders" / "minimax_music3_text_encoder_pruned_int8_convrot.safetensors",
    "decoder": MODEL_ROOT / "vae" / "minimax_music3_dav.safetensors",
}

# A lone [Instrumental] tag leaves the lyrics conditioner effectively empty,
# which makes the autoregressive stage finish at its shortest completion. Keep
# real section/content pairs so instrumental requests can develop as songs;
# duration remains an upper bound and the model may still stop early.
INSTRUMENTAL_LYRICS = """[Intro]
(instrumental)
[Verse]
(instrumental)
[Pre-Chorus]
(instrumental)
[Chorus]
(instrumental)
[Verse]
(instrumental)
[Chorus]
(instrumental)
[Instrumental]
(instrumental)
[Bridge]
(instrumental)
[Chorus]
(instrumental)
[Outro]
(instrumental)"""


# tqdm redraws and per-frame progress events are thousands of lines per song.
# They belong at DEBUG; sending them to the UI ring buffer buries real messages
# and makes the Logs panel re-render constantly during generation.
_NOISE = ("MUSIC3_PROGRESS", "it/s]", "s/it]", "%|")


def _log_worker_line(line: str) -> None:
    if any(token in line for token in _NOISE):
        log.debug("[worker] %s", line)
    else:
        log.info("[worker] %s", line)


def _worker_event(line: str, marker: str) -> str | None:
    """Return an event payload even when tqdm prepends a carriage-return line."""
    token = marker + " "
    if token in line:
        return line.split(token, 1)[1].strip()
    # A bare marker has no JSON payload. Treat it as an ordinary log line.
    return None


def model_status() -> dict:
    components = []
    total = 0
    for kind, path in MODEL_FILES.items():
        present = path.is_file()
        size = path.stat().st_size if present else 0
        total += size
        components.append({"kind": kind, "path": str(path), "present": present, "size_bytes": size})
    return {
        "root": str(MODEL_ROOT),
        "ready": all(item["present"] for item in components),
        "present": sum(bool(item["present"]) for item in components),
        "required": len(components),
        "missing": [item["kind"] for item in components if not item["present"]],
        "size_bytes": total,
        "components": components,
        "source": "https://huggingface.co/Comfy-Org/MiniMax-Music-3",
    }


def runtime_status() -> dict:
    return {
        "ready": WORKER_PYTHON.is_file() and (ENGINE_ROOT / "comfy" / "sd.py").is_file(),
        "python": str(WORKER_PYTHON),
        "engine": str(ENGINE_ROOT),
        "worker_loaded": _PROCESS is not None and _PROCESS.poll() is None,
        "standalone": True,
    }


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Both the controller and worker exchange JSON through redirected pipes.
    # Windows otherwise gives the child cp1252 stdin/stdout while the parent
    # writes UTF-8, corrupting smart quotes and other non-ASCII lyrics.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["MINIMAX_MUSIC3_MODEL_ROOT"] = str(MODEL_ROOT)
    # Dynamic loading streams only the layers needed by the GPU. Display
    # headroom is decided per-card in gpu_profile, not by an allocator setting.
    #
    # garbage_collection_threshold:0.80 used to live here. During the AR stage
    # the KV cache grows steadily, so the allocator crossed that line over and
    # over and called cudaFree, which synchronises the device -- measurable as
    # throughput decaying from ~16.2 it/s to ~13.9 it/s across one song.
    # expandable_segments lets a block grow in place instead, which removes the
    # churn without changing a single value the model computes.
    env.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    return env


_GPU_POLICY: dict | None = None


def set_gpu_policy(policy: dict) -> None:
    """Record what the worker actually chose, for the System panel."""
    global _GPU_POLICY
    _GPU_POLICY = policy
    log.info(
        "Music 3 VRAM policy: %.1f GB card, %.1f GB reserved for the desktop, %.1f GB budget",
        policy.get("total_gb", 0.0), policy.get("reserved_gb", 0.0), policy.get("budget_gb", 0.0),
    )


def gpu_policy() -> dict:
    """The live policy if a worker has run, otherwise a prediction."""
    if _GPU_POLICY:
        return {**_GPU_POLICY, "measured": True}
    import gpu_profile
    return {**gpu_profile.probe(), "measured": False}


def _alive() -> bool:
    return _PROCESS is not None and _PROCESS.poll() is None


def _start(cancel_event: threading.Event | None = None) -> subprocess.Popen[str]:
    global _PROCESS
    with _START_LOCK:
        with _LOCK:
            if _alive():
                return _PROCESS  # type: ignore[return-value]
        if not WORKER_PYTHON.is_file():
            raise RuntimeError("Music 3 runtime is not installed. Run Setup MiniMax Music 3.bat.")
        command = [str(WORKER_PYTHON), str(Path(__file__).with_name("music3_worker.py"))]
        proc = subprocess.Popen(
            command,
            cwd=str(Path(__file__).parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_env(),
            creationflags=_NO_WINDOW,
        )
        # Publish the PID before model loading begins. Cancel can now terminate
        # startup immediately instead of waiting behind the generation lock.
        with _LOCK:
            _PROCESS = proc
        assert proc.stdout is not None
        startup = deque(maxlen=50)
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    _stop_process(proc)
                    raise RuntimeError("cancelled")
                line = proc.stdout.readline()
                if not line:
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("cancelled")
                    raise RuntimeError(f"Music 3 worker exited during startup: {' | '.join(startup)}")
                line = line.strip()
                startup.append(line)
                log.info("[worker] %s", line)
                if line == "MUSIC3_READY":
                    return proc
        except Exception:
            _stop_process(proc)
            raise


def _stop_process(expected: subprocess.Popen[str] | None = None) -> None:
    global _PROCESS
    with _LOCK:
        proc = _PROCESS
        if expected is not None and proc is not expected:
            proc = expected
        elif proc is not None:
            _PROCESS = None
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
            check=False,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def unload() -> dict:
    had_worker = _alive()
    _stop_process()
    return {"cleared": True, "had_worker": had_worker}


def cancel() -> None:
    # Generation is isolated in this worker. Killing its process is immediate,
    # reliable cancellation and releases all CUDA allocations with it.
    unload()


def count_prompt_tokens(caption: str, lyrics: str) -> dict:
    """Use the checkpoint's embedded tokenizer without loading model weights."""
    checkpoint = MODEL_FILES["text_encoder"]
    if not checkpoint.is_file():
        raise RuntimeError("Music 3 text encoder is not installed")
    command = [str(WORKER_PYTHON), str(Path(__file__).with_name("music3_token_count.py"))]
    payload = json.dumps({
        "caption": caption,
        "lyrics": lyrics,
        "checkpoint": str(checkpoint),
        "engine_root": str(ENGINE_ROOT),
    }, ensure_ascii=False)
    result = subprocess.run(
        command, input=payload, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=20, env=_env(), creationflags=_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Could not count Music 3 prompt tokens")
    try:
        counted = json.loads(result.stdout.strip().splitlines()[-1])
        return {"tokens": int(counted["tokens"]), "maximum": 5000}
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Music 3 tokenizer returned an invalid result") from error


def inspect_wav(path: Path) -> dict:
    """Return actual duration and verify that a structurally valid WAV exists."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 44:
        raise RuntimeError("Music 3 did not produce an audio file")
    total_squared = 0.0
    total_samples = 0
    peak = 0
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.getnframes()
        width = handle.getsampwidth()
        channels = handle.getnchannels()
        while True:
            block = handle.readframes(65536)
            if not block: break
            count = len(block) // max(1, width)
            rms = audioop.rms(block, width)
            peak = max(peak, audioop.max(block, width))
            total_squared += float(rms * rms) * count
            total_samples += count
    rms = (total_squared / max(1, total_samples)) ** 0.5
    if frames <= 0 or rate <= 0 or channels <= 0:
        raise RuntimeError("Music 3 produced an empty WAV; please try another seed")
    return {"sample_rate": rate, "duration": frames / rate, "peak_pcm": peak, "rms_pcm": rms}


def _lyrics_for_generation(request: dict) -> str:
    """Return structured conditioning lyrics, preserving non-instrumental input."""
    if request["instrumental"]:
        return INSTRUMENTAL_LYRICS
    return request.get("rendered_lyrics", request["lyrics"])


def generate(job, request: dict, output: Path) -> dict:
    status = model_status()
    if not status["ready"]:
        raise RuntimeError("Music 3 model files are missing: " + ", ".join(status["missing"]))
    if not runtime_status()["ready"]:
        raise RuntimeError("Music 3 standalone runtime is not installed.")
    caption = request.get("generation_description", request["description"])
    lyrics = _lyrics_for_generation(request)
    if not isinstance(caption, str) or not isinstance(lyrics, str):
        raise TypeError(f"Music 3 caption and lyrics must be text, got {type(caption).__name__} and {type(lyrics).__name__}")
    payload = {
        "caption": caption,
        "lyrics": lyrics,
        "duration": float(request["duration"]),
        "seed": int(request["seed"]),
        "steps": int(request["steps"]),
        "cfg": float(request["cfg"]),
        "top_k": int(request.get("top_k", 50)),
        "tiled_decode": bool(request["tiled_decode"]),
        "output": str(output),
        "models": {name: str(path) for name, path in MODEL_FILES.items()},
    }
    timing_profile = generation_timing.predict(request)
    generation_started = time.monotonic()
    current_stage = "startup"
    stage_started = generation_started
    refine_started: float | None = None
    job.eta_seconds = timing_profile.total_seconds
    job.emit()
    proc = _start(job.cancel)
    with _LOCK:
        if job.cancel.is_set() or proc is not _PROCESS or proc.poll() is not None:
            _stop_process(proc)
            raise RuntimeError("cancelled")
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()
    tail = deque(maxlen=100)
    while True:
        line = proc.stdout.readline()
        if not line:
            _stop_process()
            raise RuntimeError("Music 3 worker stopped unexpectedly: " + " | ".join(tail))
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        _log_worker_line(line)
        gpu_payload = _worker_event(line, "MUSIC3_GPU")
        if gpu_payload:
            try:
                set_gpu_policy(json.loads(gpu_payload))
            except json.JSONDecodeError:
                log.warning("Ignoring malformed Music 3 GPU event: %s", gpu_payload)
            continue
        progress_payload = _worker_event(line, "MUSIC3_PROGRESS")
        error_payload = _worker_event(line, "MUSIC3_ERROR")
        if progress_payload:
            try:
                event = json.loads(progress_payload)
            except json.JSONDecodeError:
                log.warning("Ignoring malformed Music 3 progress event: %s", progress_payload)
                continue
            job.phase = str(event.get("message") or "Generating")
            job.progress = max(0.0, min(1.0, float(event.get("progress", 0.0))))
            lowered = job.phase.casefold()
            if "composing" in lowered or "loading" in lowered or "reusing" in lowered:
                stage = "compose"
            elif "refining" in lowered:
                stage = "refine"
            elif "decoding" in lowered:
                stage = "decode"
            else:
                stage = current_stage
            now = time.monotonic()
            if stage != current_stage:
                current_stage, stage_started = stage, now
                if stage == "refine" and refine_started is None:
                    refine_started = now
            raw_eta = event.get("eta_seconds")
            live_eta = max(0.0, float(raw_eta)) if raw_eta is not None else None
            job.eta_seconds = generation_timing.remaining(
                timing_profile, stage, now - stage_started, live_eta,
            )
            job.emit()
        # DONE is deliberately a payload-free control signal.  Do not route it
        # through _worker_event(), which correctly rejects bare progress lines.
        elif line.strip() == "MUSIC3_DONE":
            finished = time.monotonic()
            compose_seconds = (refine_started or finished) - generation_started
            result = inspect_wav(output)
            result["generation_timing"] = {
                "compose_seconds": compose_seconds,
                "refine_seconds": max(0.0, finished - (refine_started or finished)),
            }
            return result
        elif error_payload is not None:
            raw = error_payload
            try:
                detail = str(json.loads(raw).get("error") or raw)
            except (json.JSONDecodeError, AttributeError):
                detail = raw
            _stop_process()
            raise RuntimeError(detail)
        if job.cancel.is_set():
            _stop_process()
            raise RuntimeError("cancelled")
