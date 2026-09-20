"""Local known-lyrics alignment for YuE2 Studio library songs."""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
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
_STREAM_END = object()
# MiniMax-style WhisperX CTC on a 4-minute song finishes well under this.
# If CUDA hangs, the host kills the worker and retries on CPU.
WORKER_TIMEOUT_SECONDS = int(os.environ.get("YUE2_LYRICS_SYNC_TIMEOUT", "480"))


def status() -> dict[str, Any]:
    ready = RUNTIME_PYTHON.is_file() and WORKER.is_file() and (MODEL_ROOT / "whisper-large-v3-turbo" / "model.bin").is_file()
    return {
        "ready": ready,
        "runtime": str(RUNTIME_PYTHON),
        "model_root": str(MODEL_ROOT),
        "model": "Whisper vocal word timing",
        "detail": (
            "Whisper vocal recognition and WhisperX timing are ready. Other languages may download alignment models on first sync."
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


_INLINE_TAG = re.compile(
    r"(?i)\s*(\[(?:Intro|Verse[^\]]*|Pre-Chorus|Chorus|Post-Chorus|Bridge|Interlude|"
    r"Instrumental|Solo|Outro|Double|Singer [AB])\])\s*"
)


def normalize_lyrics(text: str) -> str:
    """Put section/singer tags on their own lines so karaoke is not one paragraph."""
    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    body = _INLINE_TAG.sub(lambda match: "\n" + match.group(1) + "\n", body)
    lines = [re.sub(r" +", " ", line).strip() for line in body.split("\n")]
    return "\n".join(line for line in lines if line)


def _split_sung_line(line: str) -> list[str]:
    chunks: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", line):
        words = part.split()
        if not words:
            continue
        if len(words) <= 12:
            chunks.append(" ".join(words))
            continue
        for index in range(0, len(words), 10):
            chunks.append(" ".join(words[index:index + 10]))
    return chunks


def display_lines(text: str) -> list[str]:
    from lyric_format import sung_lines
    return [chunk for line in sung_lines(text) for chunk in _split_sung_line(line)]


def attach_translations(payload: dict[str, Any], translation_text: str) -> dict[str, Any]:
    translations = display_lines(translation_text)
    lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
    for index, line in enumerate(lines):
        if isinstance(line, dict):
            source_index = int(line.get("index", index + 1)) - 1
            line["translation"] = translations[source_index] if 0 <= source_index < len(translations) else ""
    payload["translation_language"] = "en" if translations else ""
    payload["translation_line_count"] = len(translations)
    return payload


def _stop_process(process: subprocess.Popen[str] | None = None) -> None:
    global _PROCESS
    with _LOCK:
        target = process or _PROCESS
        if target is None:
            return
        if target is _PROCESS:
            _PROCESS = None
    # The reader may hold stdout's buffer lock while waiting for another line.
    # Closing it here would wait forever before we could terminate the worker.
    # The reader owns the pipe; ending the process releases its blocking read.
    if target.poll() is None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(target.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=_NO_WINDOW, timeout=2,
                )
            else:
                target.kill()
        except Exception:
            pass
        if target.poll() is None:
            try:
                target.kill()
            except Exception:
                pass
        try:
            target.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def cancel() -> None:
    _stop_process()


def _read_worker_output(stream: Any, lines: queue.Queue[object]) -> None:
    """Keep the pipe draining without making cancellation wait for new output.

    WhisperX can spend a while loading an alignment model or aligning a long
    recording without writing a line.  Reading the pipe directly in ``run``
    made that silence uninterruptible: a cancel request was only observed when
    the worker printed again.  A small reader thread leaves the job loop free
    to check cancellation while preserving line-by-line progress events.
    """
    try:
        for raw in stream:
            lines.put(raw)
    finally:
        try:
            stream.close()
        except Exception:
            pass
        lines.put(_STREAM_END)


def run(job: Any, song_dir: Path, metadata: dict[str, Any], *, progress_base: float = 0.0, progress_span: float = 1.0) -> dict[str, Any]:
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
    last_error: Exception | None = None
    for device in ("auto", "cpu"):
        try:
            return _run_worker(
                job, song_dir, metadata, lyrics_file, language, device,
                progress_base=progress_base, progress_span=progress_span,
            )
        except RuntimeError as error:
            last_error = error
            if job.cancel.is_set() or "timed out" not in str(error).lower():
                raise
            if device == "cpu":
                raise
            job.phase = "WhisperX timed out on GPU, retrying on CPU"
            job.emit()
    raise last_error or RuntimeError("Lyric synchronization failed")


def _run_worker(
    job: Any,
    song_dir: Path,
    metadata: dict[str, Any],
    lyrics_file: Path,
    language: str,
    device: str,
    *,
    progress_base: float,
    progress_span: float,
) -> dict[str, Any]:
    global _PROCESS
    command = [
        str(RUNTIME_PYTHON), str(WORKER),
        "--audio", str(Path(song_dir) / str(metadata.get("audio") or "song.wav")),
        "--lyrics-file", str(lyrics_file),
        "--output-dir", str(Path(song_dir) / "lyrics_sync"),
        "--title", str(metadata.get("title") or "Untitled Song"),
        "--language", language,
        "--device", device,
        "--model-name", str(MODEL_ROOT / "whisper-large-v3-turbo"),
    ]
    environment = os.environ.copy()
    environment.update({
        "HF_HOME": str(MODEL_ROOT / "huggingface"),
        "TORCH_HOME": str(MODEL_ROOT / "torch"),
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
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
    started = time.monotonic()
    reader: threading.Thread | None = None
    try:
        assert process.stdout is not None
        output_lines: queue.Queue[object] = queue.Queue()
        reader = threading.Thread(
            target=_read_worker_output,
            args=(process.stdout, output_lines),
            name="yue2-lyrics-output",
            daemon=True,
        )
        reader.start()
        while True:
            if job.cancel.is_set():
                _stop_process(process)
                raise RuntimeError("cancelled")
            if time.monotonic() - started > WORKER_TIMEOUT_SECONDS:
                _stop_process(process)
                raise RuntimeError(f"Lyric sync timed out on {device}")
            try:
                raw = output_lines.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if raw is _STREAM_END:
                break
            assert isinstance(raw, str)
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
                job.progress = max(job.progress, progress_base + progress_span * phase_progress.get(phase, 0.08))
                job.emit()
            elif event.get("event") == "result":
                result_event = event
                break
        if result_event is None:
            try:
                return_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _stop_process(process)
                raise RuntimeError(f"Lyric sync timed out on {device}")
            if job.cancel.is_set():
                raise RuntimeError("cancelled")
            if return_code != 0:
                raise RuntimeError(tail[-1] if tail else "Lyric synchronization failed")
            raise RuntimeError(tail[-1] if tail else "Lyric synchronization failed")
        _stop_process(process)

        result_file = Path(str(result_event.get("json_path") or result_path(song_dir)))
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        payload = attach_translations(payload, str(metadata.get("english_translation") or ""))
        result_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        metadata["needs_lyric_sync"] = False
        metadata.pop("lyrics_sync_error", None)
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
        if reader is not None:
            reader.join(timeout=1)
