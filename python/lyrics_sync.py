"""Local known-lyrics alignment for YuE2 Studio library songs."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from config import ROOT

RUNTIME_PYTHON = Path(os.environ.get(
    "YUE2_LYRICS_PYTHON",
    ROOT / "python" / "lyrics_runtime" / "Scripts" / "python.exe" if os.name == "nt"
    else ROOT / "python" / "lyrics_runtime" / "bin" / "python",
)).expanduser()
WORKER = ROOT / "python" / "lyrics_align_worker.py"
MODEL_ROOT = ROOT / "models" / "lyrics"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_PROCESS: subprocess.Popen[str] | None = None
_LOCK = threading.RLock()


def status() -> dict[str, Any]:
    ready = RUNTIME_PYTHON.is_file() and WORKER.is_file()
    return {
        "ready": ready,
        "runtime": str(RUNTIME_PYTHON),
        "model_root": str(MODEL_ROOT),
        "model": "WhisperX forced alignment",
        "detail": (
            "GPU lyric timing is ready. Install Whisper in Models for transcription fallback. Other languages may download alignment models on first sync."
            if ready else "Open Models to install Whisper lyrics and karaoke."
        ),
    }


def result_path(song_dir: Path) -> Path:
    return Path(song_dir) / "lyrics_sync" / "timed_lyrics.json"


def load(song_dir: Path) -> dict[str, Any] | None:
    path = result_path(song_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def display_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or re.fullmatch(r"\[[^\]]+\]", line):
            continue
        line = re.sub(r"^\[[^\]]+\]\s*", "", line).strip()
        if line:
            lines.append(line)
    return lines


def attach_translations(payload: dict[str, Any], translation_text: str) -> dict[str, Any]:
    translations = display_lines(translation_text)
    lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
    for index, line in enumerate(lines):
        if isinstance(line, dict):
            line["translation"] = translations[index] if index < len(translations) else ""
    payload["translation_language"] = "en" if translations else ""
    payload["translation_line_count"] = len(translations)
    return payload


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


def run(job: Any, song_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    global _PROCESS
    runtime = status()
    if not runtime["ready"]:
        raise RuntimeError(runtime["detail"])
    lyrics = str(metadata.get("lyrics") or "").strip()
    if not lyrics:
        raise RuntimeError("This song does not have written lyrics to synchronize")

    sync_dir = Path(song_dir) / "lyrics_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    lyrics_file = sync_dir / "lyrics.txt"
    lyrics_file.write_text(lyrics, encoding="utf-8")
    language = str(metadata.get("lyrics_language") or "en").strip().lower() or "en"
    command = [
        str(RUNTIME_PYTHON), str(WORKER),
        "--audio", str(Path(song_dir) / str(metadata.get("audio") or "song.wav")),
        "--lyrics-file", str(lyrics_file),
        "--output-dir", str(sync_dir),
        "--title", str(metadata.get("title") or "Untitled Song"),
        "--language", language,
        "--device", "auto",
        "--model-name", str(MODEL_ROOT / "whisper-large-v3-turbo"),
    ]
    environment = os.environ.copy()
    environment.update({
        "HF_HOME": str(MODEL_ROOT / "huggingface"),
        "TORCH_HOME": str(MODEL_ROOT / "torch"),
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
    })
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
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
    phase_progress = {"stems": 0.10, "transcribe": 0.22, "align": 0.55, "map": 0.84, "write": 0.95}
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
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "progress":
                phase = str(event.get("phase") or "align")
                job.phase = str(event.get("message") or "Synchronizing lyrics")
                job.progress = phase_progress.get(phase, max(0.08, job.progress))
                job.emit()
            elif event.get("event") == "result":
                result_event = event
        return_code = process.wait(timeout=30)
        if job.cancel.is_set():
            raise RuntimeError("cancelled")
        if return_code != 0 or result_event is None:
            raise RuntimeError(tail[-1] if tail else "Lyric synchronization failed")

        result_file = Path(str(result_event.get("json_path") or result_path(song_dir)))
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        payload = attach_translations(payload, str(metadata.get("english_translation") or ""))
        result_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        metadata["lyrics_sync"] = {
            "status": "ready", "language": payload.get("language", language),
            "line_count": payload.get("line_count", len(payload.get("lines") or [])),
            "word_count": payload.get("word_count", 0),
            "alignment_method": payload.get("alignment_method", ""),
            "updated_at": payload.get("created_at", ""),
        }
        (Path(song_dir) / "song.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"folder": Path(song_dir).name, "timed_lyrics": payload, **metadata["lyrics_sync"]}
    finally:
        with _LOCK:
            if process is _PROCESS:
                _PROCESS = None
        if process.poll() is None:
            _stop_process(process)
