from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from config import OUTPUTS_ROOT, ROOT
import model_manager
import yue2_engine

log = logging.getLogger("yue2.sfx")


MODEL_ROOT = ROOT / "models" / "sound_effects" / "stable-audio-3-small-sfx"
MODEL_FILE = MODEL_ROOT / "model.safetensors"
MODEL_CONFIG = MODEL_ROOT / "model_config.json"
TEXT_ENCODER_ROOT = MODEL_ROOT / "t5gemma-b-b-ul2"
TEXT_ENCODER_FILES = (
    "config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
)
RUNTIME_PYTHON = ROOT / "python" / "sfx_runtime" / "Scripts" / "python.exe"
RUNTIME_PACKAGE = ROOT / "python" / "sfx_runtime" / "Lib" / "site-packages" / "stable_audio_3"
WORKER = ROOT / "python" / "stable_sfx_worker.py"
EFFECTS_ROOT = OUTPUTS_ROOT / "effects"

# Woosh is intentionally independent of Stable Audio.  It has its own GPU
# runtime and checkpoints, so a missing Stable installation must never make a
# ready Woosh installation unavailable.
WOOSH_ROOT = ROOT / "models" / "sound_effects" / "woosh"
WOOSH_CHECKPOINTS = WOOSH_ROOT / "checkpoints"
WOOSH_COMPONENTS = ("Woosh-Flow", "Woosh-AE", "TextConditionerA")
WOOSH_RUNTIME = ROOT / "python" / "woosh_runtime" / "Scripts" / "python.exe"
WOOSH_VENDOR = ROOT / "python" / "vendor" / "Woosh"
WOOSH_WORKER = ROOT / "python" / "woosh_worker.py"


def stable_status() -> dict[str, Any]:
    """Readiness for the original CPU Stable Audio engine only."""
    missing: list[str] = []
    if not MODEL_FILE.is_file():
        missing.append("model.safetensors")
    if not MODEL_CONFIG.is_file():
        missing.append("model_config.json")
    for name in TEXT_ENCODER_FILES:
        if not (TEXT_ENCODER_ROOT / name).is_file():
            missing.append(f"t5gemma-b-b-ul2/{name}")
    runtime_ready = RUNTIME_PYTHON.is_file() and RUNTIME_PACKAGE.is_dir()
    if missing:
        detail = f"Sound model incomplete: {len(missing)} local file(s) still missing"
    elif not runtime_ready:
        detail = "Model found. Run Setup Sound Effects.bat once to install its private CPU runtime."
    else:
        detail = "Stable Audio 3 Small SFX ready · local CPU generation · YuE2 stays loaded"
    return {
        "ready": not missing and runtime_ready,
        "model": "Stable Audio 3 Small SFX",
        "root": str(MODEL_ROOT), "detail": detail, "runtime_ready": runtime_ready,
        "present": 2 + len(TEXT_ENCODER_FILES) - len(missing), "required": 2 + len(TEXT_ENCODER_FILES),
        "missing": missing,
        "size_bytes": sum(path.stat().st_size for path in (MODEL_FILE, MODEL_CONFIG, *(TEXT_ENCODER_ROOT / name for name in TEXT_ENCODER_FILES)) if path.is_file()),
        "processor": "CPU",
    }


def woosh_status() -> dict[str, Any]:
    """Readiness for the optional Sony Woosh-Flow GPU engine only."""
    missing = [f"checkpoints/{name}/weights.safetensors" for name in WOOSH_COMPONENTS
               if not (WOOSH_CHECKPOINTS / name / "weights.safetensors").is_file()]
    runtime_ready = WOOSH_RUNTIME.is_file() and (WOOSH_VENDOR / "woosh").is_dir()
    worker_ready = WOOSH_WORKER.is_file()
    if missing:
        detail = f"Woosh-Flow incomplete: {len(missing)} checkpoint folder(s) still missing"
    elif not runtime_ready:
        detail = "Woosh checkpoints found. Its private GPU runtime is not ready."
    elif not worker_ready:
        detail = "Woosh runtime found. The local Woosh worker is not installed yet."
    else:
        detail = "Woosh-Flow ready · local GPU generation · YuE2 unloads before generation"
    size = sum(path.stat().st_size for path in WOOSH_CHECKPOINTS.rglob("*") if path.is_file()) if WOOSH_CHECKPOINTS.is_dir() else 0
    return {
        "ready": not missing and runtime_ready and worker_ready,
        "model": "Woosh-Flow", "root": str(WOOSH_ROOT), "detail": detail,
        "runtime_ready": runtime_ready, "present": len(WOOSH_COMPONENTS) - len(missing),
        "required": len(WOOSH_COMPONENTS), "missing": missing, "size_bytes": size,
        "processor": "CUDA GPU", "max_duration": 5,
    }


def status() -> dict[str, Any]:
    stable, woosh = stable_status(), woosh_status()
    # Keep the legacy top-level contract tied to Stable Audio: other screens
    # use it as their original Stable-only availability gate.  Effects reads
    # the exact selected model from `models`, so Woosh never depends on Small.
    return {**stable, "models": {"stable": stable, "woosh": woosh}}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return cleaned[:42] or "generated-sound"


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.terminate()


def cancel(job) -> None:
    process = job.client
    if isinstance(process, subprocess.Popen):
        _stop_process(process)


def _effect_folder(effect_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}", effect_id):
        raise ValueError("Invalid sound-effect identifier")
    return EFFECTS_ROOT / effect_id


def list_effects() -> list[dict[str, Any]]:
    EFFECTS_ROOT.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for folder in EFFECTS_ROOT.iterdir():
        manifest = folder / "effect.json"
        audio = folder / "effect.wav"
        if not folder.is_dir() or not manifest.is_file() or not audio.is_file():
            continue
        try:
            item = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(item, dict):
                continue
            item["id"] = folder.name
            item["url"] = f"/api/effects/{folder.name}/audio"
            items.append(item)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def get_effect(effect_id: str) -> tuple[Path, dict[str, Any]]:
    folder = _effect_folder(effect_id)
    manifest, audio = folder / "effect.json", folder / "effect.wav"
    if not manifest.is_file() or not audio.is_file():
        raise FileNotFoundError(effect_id)
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    metadata.update({"id": effect_id, "url": f"/api/effects/{effect_id}/audio"})
    return audio, metadata


def delete_effect(effect_id: str) -> None:
    folder = _effect_folder(effect_id)
    if not (folder / "effect.json").is_file():
        raise FileNotFoundError(effect_id)
    shutil.rmtree(folder)


def add_to_song(effect_id: str, song_dir: Path) -> dict[str, Any]:
    source, effect = get_effect(effect_id)
    tracks_dir = song_dir / "studio" / "tracks"
    tracks_dir.mkdir(parents=True, exist_ok=True)
    seed = int(effect["seed"]) if effect.get("seed") is not None else 0
    filename = f"{time.strftime('%H%M%S')}_{seed}_{_slug(str(effect['name']))}_{uuid.uuid4().hex[:6]}.wav"
    target = tracks_dir / filename
    shutil.copy2(source, target)
    manifest = song_dir / "song.json"
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    entry = {
        "file": filename,
        "name": str(effect["name"]),
        "source": str(effect.get("source") or "stable-audio-3-small-sfx"),
        "effect_id": effect_id,
        "prompt": str(effect["prompt"]),
        "negative_prompt": str(effect.get("negative_prompt") or ""),
        "duration": float(effect["duration"]),
        "seed": seed,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    metadata.setdefault("studio_imports", []).append(entry)
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {**entry, "url": f"/api/library/{song_dir.name}/studio/tracks/{filename}"}


def generate(job, song_dir: Path | None = None) -> dict[str, Any]:
    if str(job.params.get("engine") or "stable") == "woosh":
        return _generate_woosh(job, song_dir)

    current = stable_status()
    if not current["ready"]:
        raise RuntimeError(current["detail"])

    prompt = str(job.params["prompt"]).strip()
    duration = float(job.params["duration"])
    seed = int(job.params["seed"])
    negative_prompt = str(job.params.get("negative_prompt") or "").strip()
    steps = int(job.params.get("steps", 8))
    sampler = str(job.params.get("sampler", "pingpong"))
    chunked_decode = bool(job.params.get("chunked_decode", True))
    display_name = str(job.params.get("name") or "").strip() or prompt[:48]
    EFFECTS_ROOT.mkdir(parents=True, exist_ok=True)
    effect_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{seed}-{_slug(display_name)}-{uuid.uuid4().hex[:6]}"
    effect_dir = EFFECTS_ROOT / effect_id
    effect_dir.mkdir(parents=True, exist_ok=False)
    target = effect_dir / "effect.wav"
    log.info("Generating sound effect %r · %.1fs · seed %s", display_name, duration, seed)

    command = [
        str(RUNTIME_PYTHON), str(WORKER),
        "--model-root", str(MODEL_ROOT),
        "--output", str(target),
        "--prompt", prompt,
        "--duration", f"{duration:.3f}",
        "--seed", str(seed),
        "--steps", str(steps),
        "--sampler", sampler,
    ]
    if not chunked_decode:
        command.append("--full-decode")
    log.info("SFX settings: steps=%s sampler=%s chunked_decode=%s cfg=1 (fixed)", steps, sampler, chunked_decode)
    if negative_prompt:
        command.extend(["--negative-prompt", negative_prompt])
    process = subprocess.Popen(
        command,
        cwd=str(ROOT / "python"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    job.client = process
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    threading.Thread(target=read_output, name=f"sfx-output-{job.id[:8]}", daemon=True).start()
    recent: list[str] = []
    last_phase = ""
    output_closed = False
    while process.poll() is None or not output_closed:
        if job.cancel.is_set():
            _stop_process(process)
            shutil.rmtree(effect_dir, ignore_errors=True)
            log.info("Sound effect job %s cancelled", job.id[:8])
            raise RuntimeError("Sound generation cancelled")
        try:
            line = lines.get(timeout=0.15)
        except queue.Empty:
            continue
        if line is None:
            output_closed = True
            continue
        if line.startswith("SFX_PROGRESS "):
            try:
                event = json.loads(line.removeprefix("SFX_PROGRESS "))
                job.phase = str(event.get("phase") or job.phase)
                job.progress = max(job.progress, min(0.98, float(event.get("progress", job.progress))))
                job.stage_progress = event.get("stage_progress")
                job.emit()
                if job.phase and job.phase != last_phase:
                    log.info("[sfx] %s", job.phase)
                    last_phase = job.phase
            except (ValueError, TypeError, json.JSONDecodeError):
                recent.append(line)
                log.info("[sfx] %s", line)
        else:
            recent.append(line)
            recent = recent[-30:]
            if line.strip():
                log.info("[sfx] %s", line)

    return_code = process.wait()
    job.client = None
    if return_code != 0 or not target.is_file() or target.stat().st_size < 1024:
        shutil.rmtree(effect_dir, ignore_errors=True)
        reason = "\n".join(recent[-12:]).strip() or f"Sound worker exited with code {return_code}"
        log.error("Sound effect worker failed: %s", reason)
        raise RuntimeError(reason)

    entry = {
        "id": effect_id,
        "name": display_name,
        "source": "stable-audio-3-small-sfx",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "duration": duration,
        "seed": seed,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    entry.update(steps=steps, sampler=sampler, chunked_decode=chunked_decode)
    (effect_dir / "effect.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Saved sound effect: %s", target)
    result = {**entry, "url": f"/api/effects/{effect_id}/audio"}
    if song_dir is not None:
        result["studio_track"] = add_to_song(effect_id, song_dir)
    return result


def _generate_woosh(job, song_dir: Path | None = None) -> dict[str, Any]:
    """Generate with Woosh in its isolated runtime, leaving Stable untouched."""
    current = woosh_status()
    if not current["ready"]:
        raise RuntimeError(current["detail"])

    prompt = str(job.params["prompt"]).strip()
    duration = min(5.0, float(job.params["duration"]))
    seed = int(job.params["seed"])
    negative_prompt = str(job.params.get("negative_prompt") or "").strip()
    steps = int(job.params.get("steps", 32))
    cfg = float(job.params.get("cfg", 4.5))
    sampler = str(job.params.get("sampler") or "dopri5")
    if sampler not in {"dopri5", "euler"}:
        raise ValueError("Woosh supports DOPRI5 or Euler sampling.")
    display_name = str(job.params.get("name") or "").strip() or prompt[:48]
    EFFECTS_ROOT.mkdir(parents=True, exist_ok=True)
    effect_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{seed}-{_slug(display_name)}-{uuid.uuid4().hex[:6]}"
    effect_dir = EFFECTS_ROOT / effect_id
    effect_dir.mkdir(parents=True, exist_ok=False)
    target = effect_dir / "effect.wav"
    command = [
        str(WOOSH_RUNTIME), str(WOOSH_WORKER), "--model-root", str(WOOSH_ROOT),
        "--output", str(target), "--prompt", prompt, "--duration", f"{duration:.3f}",
        "--seed", str(seed), "--steps", str(steps), "--cfg", f"{cfg:.3f}", "--sampler", sampler,
    ]
    if negative_prompt:
        command.extend(["--negative-prompt", negative_prompt])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WOOSH_VENDOR) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    log.info("Generating Woosh effect %r · %.1fs · seed %s · steps=%s · cfg=%s", display_name, duration, seed, steps, cfg)

    # Woosh is GPU-based.  The job queue serializes generation, and this lock
    # also prevents an installer from taking the runtime while YuE2 is released.
    with model_manager.activity_lock:
        yue2_engine.unload()
        process = subprocess.Popen(command, cwd=str(ROOT / "python"), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    job.client = process
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    threading.Thread(target=read_output, name=f"woosh-output-{job.id[:8]}", daemon=True).start()
    recent: list[str] = []
    output_closed = False
    while process.poll() is None or not output_closed:
        if job.cancel.is_set():
            _stop_process(process); shutil.rmtree(effect_dir, ignore_errors=True)
            raise RuntimeError("Sound generation cancelled")
        try:
            line = lines.get(timeout=0.15)
        except queue.Empty:
            continue
        if line is None:
            output_closed = True
            continue
        if line.startswith("SFX_PROGRESS "):
            try:
                event = json.loads(line.removeprefix("SFX_PROGRESS "))
                job.phase = str(event.get("phase") or job.phase)
                job.progress = max(job.progress, min(0.98, float(event.get("progress", job.progress))))
                job.stage_progress = event.get("stage_progress")
                job.emit()
            except (ValueError, TypeError, json.JSONDecodeError):
                recent.append(line)
        else:
            recent.append(line); recent = recent[-30:]
            if line.strip(): log.info("[woosh] %s", line)
    return_code = process.wait(); job.client = None
    if return_code != 0 or not target.is_file() or target.stat().st_size < 1024:
        shutil.rmtree(effect_dir, ignore_errors=True)
        reason = "\n".join(recent[-12:]).strip() or f"Woosh worker exited with code {return_code}"
        log.error("Woosh worker failed: %s", reason)
        raise RuntimeError(reason)

    entry = {"id": effect_id, "name": display_name, "source": "woosh-flow", "prompt": prompt,
             "negative_prompt": negative_prompt, "duration": duration, "seed": seed,
             "steps": steps, "cfg": cfg, "sampler": sampler, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (effect_dir / "effect.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    result = {**entry, "url": f"/api/effects/{effect_id}/audio"}
    if song_dir is not None:
        result["studio_track"] = add_to_song(effect_id, song_dir)
    log.info("Saved Woosh sound effect: %s", target)
    return result
