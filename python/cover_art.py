"""Automatic post-song cover generation with isolated failure and progress."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from config import ROOT, WORKER_PYTHON

RENDERER = ROOT / "python" / "cover_art_renderer.py"
MODEL = ROOT / "models" / "cover_art" / "juggernaut_aftermath.safetensors"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def available() -> bool:
    return RENDERER.is_file() and MODEL.is_file() and WORKER_PYTHON.is_file()


def status() -> dict:
    return {
        "ready": available(),
        "model": str(MODEL),
        "filename": MODEL.name,
        "size_bytes": MODEL.stat().st_size if MODEL.is_file() else 0,
        "source": "https://civitai.com/models/46422/juggernaut?modelVersionId=127207",
        "detail": "Automatic 512×512 thumbnails enabled" if available() else f"Place {MODEL.name} in {MODEL.parent}",
    }


def build_prompt(title: str, description: str, lyrics: str, direction: str = "") -> str:
    lyric_lines = [
        re.sub(r"\s+", " ", line).strip(" -–—")
        for line in lyrics.splitlines()
        if line.strip() and not line.lstrip().startswith("[")
    ]
    subject = ", ".join(lyric_lines[:3])
    description_fields: list[str] = []
    for label in ("Basic Attributes", "Global Emotional Progression", "Application Scenarios & Imagery", "Sonics & Production Profile"):
        match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+)$", description)
        if match:
            description_fields.append(match.group(1).strip())
    if not description_fields:
        headings = {"global metadata", "vocal details", "arrangement"}
        description_fields = [
            line.strip() for line in description.splitlines()
            if line.strip().casefold().strip("#: ") not in headings and line.strip()
        ][:2]
    style = ", ".join(description_fields)
    pieces = ["professional square album cover", "literal visual storytelling", direction.strip(), title.strip(), subject, style]
    prompt = ", ".join(piece for piece in pieces if piece)
    return prompt[:420] + ", cinematic lighting, detailed composition, no text, no lettering, no logo"


def render(
    job, title: str, description: str, lyrics: str, output: Path,
    direction: str = "", progress_base: float = 0.91, progress_span: float = 0.08,
) -> dict:
    if not available():
        raise RuntimeError("Local thumbnail model is not installed")
    command = [str(WORKER_PYTHON), str(RENDERER), "--prompt", build_prompt(title, description, lyrics, direction), "--output", str(output)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    assert process.stdout is not None
    result: dict = {}
    started = time.monotonic()
    for raw in process.stdout:
        line = raw.strip()
        if line.startswith("COVER_PROGRESS "):
            event = json.loads(line.split(" ", 1)[1]); step = int(event.get("step", 0)); total = max(1, int(event.get("total", 30)))
            job.phase = str(event.get("message") or "Generating thumbnail")
            job.progress = progress_base + progress_span * (step / total)
            job.stage_progress = step / total
            elapsed = max(0.001, time.monotonic() - started)
            job.eta_seconds = ((total - step) * (elapsed / step)) if step > 0 else None
            job.emit()
        elif line.startswith("COVER_DONE "):
            result = json.loads(line.split(" ", 1)[1])
        elif line.startswith("COVER_ERROR "):
            result["error"] = json.loads(line.split(" ", 1)[1]).get("error")
        if job.cancel.is_set():
            process.kill(); process.wait(timeout=10); raise RuntimeError("cancelled")
    code = process.wait()
    if code != 0 or not output.is_file():
        raise RuntimeError(str(result.get("error") or f"Thumbnail renderer exited with code {code}"))
    job.stage_progress = 1.0
    return result
