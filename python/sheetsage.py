"""SheetSage2 audio-to-ABC transcription for YuE2 covers."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from config import ROOT

log = logging.getLogger("yue2.sheetsage")
RUNTIME_PYTHON = Path(os.environ.get(
    "YUE2_SHEETSAGE_PYTHON",
    ROOT / "python" / "sheetsage_runtime" / "Scripts" / "python.exe" if os.name == "nt"
    else ROOT / "python" / "sheetsage_runtime" / "bin" / "python",
)).expanduser()
WORKER = ROOT / "python" / "sheetsage_worker.py"
MODEL_ROOT = ROOT / "models" / "sheetsage2"
MERT_ROOT = MODEL_ROOT / "mert"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_PROCESS: subprocess.Popen[str] | None = None
_LOCK = threading.RLock()


def prepare_local_parent() -> None:
    """Point SheetSage2 at the local MERT snapshot so inference stays offline."""
    config_path = MODEL_ROOT / "config.json"
    if not config_path.is_file() or not MERT_ROOT.is_dir():
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    parent = str(MERT_ROOT.resolve())
    if config.get("base_model_name_or_path") == parent:
        return
    config["base_model_name_or_path"] = parent
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def status() -> dict[str, Any]:
    weights = (MODEL_ROOT / "model.safetensors").is_file() and (MERT_ROOT / "model.safetensors").is_file()
    ready = RUNTIME_PYTHON.is_file() and WORKER.is_file() and weights
    return {
        "ready": ready,
        "runtime": str(RUNTIME_PYTHON),
        "model_root": str(MODEL_ROOT),
        "model": "SheetSage2",
        "detail": (
            "GPU cover transcription is ready. YuE2 waits while SheetSage2 reads a recording."
            if ready else "Open Models to install SheetSage2 cover-from-audio."
        ),
    }


def score_path(song_dir: Path, melody_only: bool) -> Path:
    name = "melody.abc" if melody_only else "score.abc"
    return Path(song_dir) / "sheetsage" / name


def load_score(song_dir: Path, melody_only: bool) -> str:
    path = score_path(song_dir, melody_only)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _stop_process(process: subprocess.Popen[str] | None = None) -> None:
    global _PROCESS
    with _LOCK:
        target = process or _PROCESS
        if target is None:
            return
        if target.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(target.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                        creationflags=_NO_WINDOW,
                    )
                else:
                    target.kill()
            except Exception:
                target.kill()
        if target is _PROCESS:
            _PROCESS = None


def cancel() -> None:
    _stop_process()


def run(job: Any, song_dir: Path, audio: Path, melody_only: bool) -> dict[str, Any]:
    global _PROCESS
    runtime = status()
    if not runtime["ready"]:
        raise RuntimeError(runtime["detail"])
    if not audio.is_file():
        raise RuntimeError("The source WAV file is missing")
    prepare_local_parent()
    output_dir = Path(song_dir) / "sheetsage"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(RUNTIME_PYTHON), str(WORKER),
        "--audio", str(audio),
        "--model-root", str(MODEL_ROOT),
        "--mert-root", str(MERT_ROOT),
        "--output-dir", str(output_dir),
        "--melody-only" if melody_only else "--full",
    ]
    environment = os.environ.copy()
    environment.update({
        "HF_HOME": str(MODEL_ROOT / "huggingface"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    })
    process = subprocess.Popen(
        command, cwd=str(ROOT), env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=_NO_WINDOW,
    )
    with _LOCK:
        _PROCESS = process
    result_event: dict[str, Any] | None = None
    tail: list[str] = []
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            if job.cancel.is_set():
                _stop_process(process)
                raise RuntimeError("cancelled")
            line = raw.strip()
            if not line:
                continue
            tail.append(line)
            tail = tail[-40:]
            log.info("[sheetsage] %s", line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "progress":
                job.phase = str(event.get("message") or "Transcribing melody")
                job.progress = max(0.08, min(0.95, float(event.get("progress") or job.progress)))
                job.emit()
            elif event.get("event") == "result":
                result_event = event
        return_code = process.wait(timeout=30)
        if job.cancel.is_set():
            raise RuntimeError("cancelled")
        if return_code != 0 or result_event is None:
            raise RuntimeError(tail[-1] if tail else "SheetSage2 transcription failed")
        abc = str(result_event.get("abc") or "").strip()
        if not abc:
            raise RuntimeError("Transcription did not produce a usable melody score")
        target = score_path(song_dir, melody_only)
        target.write_text(abc, encoding="utf-8")
        warnings = result_event.get("warnings") if isinstance(result_event.get("warnings"), list) else []
        return {
            "folder": Path(song_dir).name,
            "abc": abc,
            "melody_only": melody_only,
            "warnings": [str(item) for item in warnings],
            "path": str(target),
        }
    finally:
        _stop_process(process)
