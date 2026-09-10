"""Resident YuE2 inference worker supervision for YuE2 Studio."""
from __future__ import annotations

import audioop
import json
import logging
import os
import subprocess
import sys
import threading
import time
import wave
from collections import deque
from pathlib import Path

from config import MODEL_ROOT, VAE_ROOT, WORKER_PYTHON
import gpu_profile

log = logging.getLogger("yue2.engine")
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_PROCESS: subprocess.Popen[str] | None = None
_LOCK = threading.RLock()
_START_LOCK = threading.Lock()
_GPU_POLICY: dict | None = None

MODEL_FILES = {
    "model": MODEL_ROOT / "model.safetensors",
    "config": MODEL_ROOT / "config.json",
    "tokenizer": MODEL_ROOT / "qwen.tiktoken",
    "vae": VAE_ROOT / "model.safetensors",
    "vae_config": VAE_ROOT / "config.json",
}

INSTRUMENTAL_LYRICS = """[Intro]
(instrumental)
[Verse]
(instrumental)
[Chorus]
(instrumental)
[Bridge]
(instrumental)
[Outro]
(instrumental)"""


def _event(line: str, marker: str) -> str | None:
    token = marker + " "
    return line.split(token, 1)[1].strip() if token in line else None


def model_status() -> dict:
    components, total = [], 0
    for kind, path in MODEL_FILES.items():
        present = path.is_file()
        size = path.stat().st_size if present else 0
        total += size
        components.append({"kind": kind, "path": str(path), "present": present, "size_bytes": size})
    return {"root": str(MODEL_ROOT), "vae_root": str(VAE_ROOT), "ready": all(x["present"] for x in components),
            "present": sum(x["present"] for x in components), "required": len(components),
            "missing": [x["kind"] for x in components if not x["present"]], "size_bytes": total,
            "components": components, "source": "https://huggingface.co/m-a-p/YuE2-3B"}


def runtime_status() -> dict:
    package = WORKER_PYTHON.parent.parent / "Lib" / "site-packages" / "yue2"
    return {"ready": WORKER_PYTHON.is_file() and package.is_dir(), "python": str(WORKER_PYTHON),
            "package": str(package),
            "worker_loaded": _alive(), "standalone": True, "backend": "torch-eager"}


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                "YUE2_MODEL_ROOT": str(MODEL_ROOT), "YUE2_VAE_ROOT": str(VAE_ROOT)})
    if sys.platform != "win32":
        env.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    return env


def set_gpu_policy(policy: dict) -> None:
    global _GPU_POLICY
    _GPU_POLICY = policy


def gpu_policy() -> dict:
    return {**(_GPU_POLICY or gpu_profile.probe()), "measured": _GPU_POLICY is not None}


def _alive() -> bool:
    return _PROCESS is not None and _PROCESS.poll() is None


def _stop_process(expected: subprocess.Popen[str] | None = None) -> None:
    global _PROCESS
    with _LOCK:
        proc = expected or _PROCESS
        if proc is _PROCESS:
            _PROCESS = None
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW, check=False)
    else:
        proc.kill()
    try: proc.wait(timeout=10)
    except Exception: pass


def _start(cancel_event: threading.Event | None = None) -> subprocess.Popen[str]:
    global _PROCESS
    with _START_LOCK:
        with _LOCK:
            if _alive(): return _PROCESS  # type: ignore[return-value]
        if not WORKER_PYTHON.is_file():
            raise RuntimeError("YuE2 runtime is not installed. Run Setup YuE2 Studio.bat.")
        proc = subprocess.Popen([str(WORKER_PYTHON), str(Path(__file__).with_name("yue2_worker.py"))],
            cwd=str(Path(__file__).parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=_env(), creationflags=_NO_WINDOW)
        with _LOCK: _PROCESS = proc
        assert proc.stdout is not None
        tail = deque(maxlen=40)
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set(): raise RuntimeError("cancelled")
                line = proc.stdout.readline()
                if not line: raise RuntimeError("YuE2 worker exited during startup: " + " | ".join(tail))
                line = line.strip(); tail.append(line); log.info("[worker] %s", line)
                if line == "YUE2_READY": return proc
        except Exception:
            _stop_process(proc); raise


def unload() -> dict:
    had_worker = _alive(); _stop_process(); return {"cleared": True, "had_worker": had_worker}


def cancel() -> None: unload()


def count_prompt_tokens(style: str, lyrics: str, cot: str = "full", abc: str | None = None) -> dict:
    if not MODEL_FILES["tokenizer"].is_file(): raise RuntimeError("YuE2 tokenizer is not installed")
    command = [str(WORKER_PYTHON), str(Path(__file__).with_name("yue2_token_count.py"))]
    payload = json.dumps({"model_root": str(MODEL_ROOT), "style": style, "lyrics": lyrics, "cot": cot, "abc": abc}, ensure_ascii=False)
    result = subprocess.run(command, input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=20, env=_env(), creationflags=_NO_WINDOW)
    if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Could not count YuE2 prompt tokens")
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1]); return {"tokens": int(value["tokens"]), "maximum": int(value["maximum"])}
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("YuE2 tokenizer returned an invalid result") from error


def inspect_wav(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size <= 44: raise RuntimeError("YuE2 did not produce audio")
    with wave.open(str(path), "rb") as handle:
        rate, frames, width, channels = handle.getframerate(), handle.getnframes(), handle.getsampwidth(), handle.getnchannels()
        peak = 0
        while data := handle.readframes(65536): peak = max(peak, audioop.max(data, width))
    if rate <= 0 or frames <= 0 or channels <= 0: raise RuntimeError("YuE2 produced empty audio")
    return {"sample_rate": rate, "duration": frames / rate, "peak_pcm": peak}


def _lyrics_for_generation(request: dict) -> str:
    return INSTRUMENTAL_LYRICS if request.get("instrumental") else str(request.get("rendered_lyrics", request.get("lyrics", "")))


def _request_payload(request: dict, output: Path) -> dict:
    payload = {"style": str(request.get("generation_description", request["description"])), "lyrics": _lyrics_for_generation(request),
               "cot": str(request.get("cot_mode", "full")), "abc": request.get("abc_score") or None,
               "seed": int(request["seed"]), "cfg_scale": float(request.get("cfg", 1.0)),
               "steps": int(request.get("steps", 32)), "temperature": float(request.get("temperature", 1.0)),
               "top_k": int(request.get("top_k", 100)), "output": str(output)}
    if payload["cot"] not in {"full", "melody", "off"}: raise ValueError("cot_mode must be full, melody, or off")
    return payload


def generate(job, request: dict, output: Path) -> dict:
    status = model_status()
    if not status["ready"]: raise RuntimeError("YuE2 model files are missing: " + ", ".join(status["missing"]))
    if not runtime_status()["ready"]: raise RuntimeError("YuE2 runtime is not installed.")
    payload = _request_payload(request, output)
    started = time.monotonic(); job.phase, job.progress, job.eta_seconds = "Starting YuE2 worker", .01, None; job.emit()
    proc = _start(job.cancel)
    with _LOCK:
        if job.cancel.is_set() or proc is not _PROCESS or proc.poll() is not None: raise RuntimeError("cancelled")
        assert proc.stdin is not None; proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n"); proc.stdin.flush()
    assert proc.stdout is not None; tail = deque(maxlen=100)
    while True:
        line = proc.stdout.readline()
        if not line: _stop_process(); raise RuntimeError("YuE2 worker stopped unexpectedly: " + " | ".join(tail))
        line = line.rstrip()
        if not line: continue
        tail.append(line); log.info("[worker] %s", line)
        value = _event(line, "YUE2_GPU")
        if value:
            try: set_gpu_policy(json.loads(value))
            except json.JSONDecodeError: pass
            continue
        value = _event(line, "YUE2_PROGRESS")
        if value:
            try:
                event = json.loads(value); job.phase = str(event.get("message") or "Generating with YuE2")
                job.progress = max(0., min(1., float(event.get("progress", 0.))))
                job.eta_seconds = event.get("eta_seconds"); job.emit()
            except (ValueError, TypeError, json.JSONDecodeError): pass
        elif line.strip() == "YUE2_DONE":
            result = inspect_wav(output); result["generation_timing"] = {"compose_seconds": time.monotonic() - started, "refine_seconds": 0.}; return result
        else:
            value = _event(line, "YUE2_ERROR")
            if value is not None:
                message = value
                try:
                    failure = json.loads(value)
                    message = str(failure.get("error") or value)
                    log.error("YuE2 generation failed: %s\n%s", failure.get("error", value), failure.get("traceback", ""))
                    if failure.get("cuda_memory"):
                        log.error("CUDA memory at failure:\n%s", failure["cuda_memory"])
                except (ValueError, TypeError, AttributeError):
                    log.error("YuE2 generation failed: %s", value)
                _stop_process(); raise RuntimeError(message)
        if job.cancel.is_set(): _stop_process(); raise RuntimeError("cancelled")
