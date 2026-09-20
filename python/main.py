from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import atexit
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from config import LAN_PORT, LIBRARY_ROOT, LOGS_ROOT, OUTPUTS_ROOT, SIDECAR_HOST, SIDECAR_PORT
from jobs import Job, manager
from log_buffer import install, ring
import yue2_engine
import cover_art
import lyrics_sync
import sheetsage
import generation_timing
import stable_sfx
import ai_vault
import ai_assist
import caption_library
import voice_profiles
import model_manager
import lan_access

install(LOGS_ROOT)
log = logging.getLogger("yue2.studio")
app = FastAPI(title="YuE2 Studio", version="0.6.2")

# The MCP process is deliberately a separate client of this local service.  Keep
# a compact, in-memory audit trail so its actions are visible in Studio instead
# of becoming invisible background automation.
mcp_activity: deque[dict] = deque(maxlen=200)
mcp_activity_lock = threading.Lock()


@app.middleware("http")
async def protect_lan(request: Request, call_next):
    blocked = lan_access.gate(request)
    if blocked is not None:
        return blocked
    return await call_next(request)


@app.middleware("http")
async def protect_installation(request: Request, call_next):
    path = request.url.path
    uses_runtime = path in {"/api/generate", "/api/effects/generate", "/api/video/render"} or (
        path.startswith("/api/library/") and path.endswith(("/cover", "/stems", "/lyrics-sync", "/cover-transcribe", "/studio/generate-sfx", "/studio/bounce")))
    if request.method == "POST" and uses_runtime and model_manager.busy():
        return Response(content=json.dumps({"detail":"A model installation is running. Wait for it to finish before generating."}), status_code=409, media_type="application/json")
    return await call_next(request)


class ModelInstallRequest(BaseModel):
    token: str = Field(default="", max_length=500)


@app.exception_handler(model_manager.InstallationBusyError)
async def installation_busy_handler(request: Request, error: Exception):
    return Response(content=json.dumps({"detail": str(error)}), status_code=409, media_type="application/json")


@app.get("/api/models")
def installed_models():
    return model_manager.list_models()


@app.post("/api/models/{model_id}/install")
def install_model(model_id: str, request: ModelInstallRequest = ModelInstallRequest()):
    if model_id not in model_manager.DEFINITIONS:
        raise HTTPException(404, "Unknown model")
    with model_manager.activity_lock:
        if any(job.status in {"queued", "running"} for job in manager.list()):
            raise HTTPException(409, "Finish or cancel the active job before installing models.")
        try:
            yue2_engine.unload()
            return model_manager.start(model_id, request.token)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error


@app.post("/api/models/{model_id}/cancel")
def cancel_model_install(model_id: str):
    try:
        return model_manager.cancel(model_id)
    except KeyError:
        raise HTTPException(404, "Unknown model")


@app.on_event("shutdown")
def stop_model_installations():
    model_manager.shutdown()
    ai_assist.abort_writing(shutdown=True)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class TauriWebViewCORSMiddleware(BaseHTTPMiddleware):
    """Let the Tauri WebView2 UI call this sidecar.

    GET /api/status is a simple request so it works. POST /api/generate is
    preflighted. WebView2 also flags https://tauri.localhost -> 127.0.0.1 as a
    private-network request. Without Allow-Private-Network the preflight is
    dropped, fetch() throws, and the UI shows 'service is not running'
    even while this process is healthy.
    """

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin") or "*"
        if request.method == "OPTIONS":
            requested = request.headers.get("access-control-request-headers") or "*"
            return Response(status_code=204, headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
                "Access-Control-Allow-Headers": requested,
                "Access-Control-Allow-Private-Network": "true",
                "Access-Control-Max-Age": "600",
            })
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        if request.url.path.startswith("/video-studio"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(TauriWebViewCORSMiddleware)
VIDEO_STUDIO_ROOT = Path(__file__).resolve().parent / "video_studio"
VIDEO_RENDER_ROOT = OUTPUTS_ROOT / "videos"
app.mount("/video-studio-static", StaticFiles(directory=VIDEO_STUDIO_ROOT), name="video-studio-static")


def is_expected_windows_disconnect(context: dict) -> bool:
    """Identify the harmless Proactor callback raised when a local UI socket closes."""
    error = context.get("exception")
    message = str(context.get("message") or "")
    return (
        isinstance(error, ConnectionResetError)
        and getattr(error, "winerror", None) == 10054
        and "_ProactorBasePipeTransport._call_connection_lost" in message
    )


def cleanup_orphan_library() -> int:
    """Remove incomplete job folders left by an interrupted older process."""
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    removed = 0
    for folder in LIBRARY_ROOT.iterdir():
        if not folder.is_dir() or (folder / "song.json").is_file():
            continue
        # Genre folders contain song directories but do not have their own
        # manifest. Only remove a truly incomplete top-level song folder.
        if any(child.is_dir() for child in folder.iterdir()):
            continue
        try:
            shutil.rmtree(folder)
            removed += 1
            log.info("Removed incomplete song folder: %s", folder.name)
        except OSError as error:
            log.warning("Could not remove incomplete song folder %s: %s", folder.name, error)
    return removed


@app.on_event("startup")
async def quiet_expected_windows_disconnects() -> None:
    cleanup_orphan_library()
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def handle_exception(active_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        if is_expected_windows_disconnect(context):
            return
        if previous is not None:
            previous(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_exception)

class GenerateRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    artist: str = Field(default="", max_length=160)
    album: str = Field(default="", max_length=160)
    genre: str = Field(default="", max_length=120)
    description: str = Field(min_length=1, max_length=12000)
    lyrics: str = Field(default="", max_length=24000)
    instrumental: bool = False
    seed: int | None = None
    cot_mode: str = Field(default="full", pattern="^(full|melody|off)$")
    abc_score: str | None = Field(default=None, max_length=24000)
    steps: int = Field(default=32, ge=1, le=200)
    cfg: float = Field(default=1.0, ge=0.0, le=20.0)
    top_k: int = Field(default=100, ge=1, le=16384)
    temperature: float = Field(default=1.0, ge=0.0, le=5.0)
    exclude_styles: str = Field(default="", max_length=2000)
    vocal_gender: str = Field(default="auto", pattern="^(auto|female|male)$")
    english_translation: str = Field(default="", max_length=24000)
    lyrics_language: str = Field(default="en", min_length=2, max_length=12)
    voice_slots: dict[str, str] = Field(default_factory=dict)
    voice_snapshots: list[dict] = Field(default_factory=list)


class SongRatingRequest(BaseModel):
    rating: int = Field(ge=0, le=5, strict=True)


class SongUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    artist: str = Field(default="", max_length=160)
    album: str = Field(default="", max_length=160)
    genre: str = Field(default="", max_length=120)
    year: str = Field(default="", pattern="^$|^[0-9]{4}$")
    track_number: str = Field(default="", pattern="^$|^[0-9]{1,3}(/[0-9]{1,3})?$")
    description: str = Field(default="", max_length=12000)
    lyrics: str = Field(default="", max_length=24000)
    english_translation: str = Field(default="", max_length=24000)
    lyrics_language: str = Field(default="en", min_length=2, max_length=12)


class PlaylistCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class AiProviderUpdate(BaseModel):
    key: str | None = Field(default=None, max_length=4000)
    base_url: str | None = Field(default=None, max_length=200)
    clear: bool = False


class AiCapabilityUpdate(BaseModel):
    enabled: bool | None = None
    provider: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=80)


class AiKeysUpdate(BaseModel):
    providers: dict[str, AiProviderUpdate] = Field(default_factory=dict)
    capabilities: dict[str, AiCapabilityUpdate] = Field(default_factory=dict)


class WritingAssistRequest(BaseModel):
    action: str = Field(pattern="^(generate|optimize|title|describe|compose|effect|translate)$")
    idea: str = Field(default="", max_length=4000)
    random: bool = False
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=12000)
    lyrics: str = Field(default="", max_length=24000)
    language: str = Field(default="en", max_length=12)
    instrumental: bool = False
    effect_engine: str = Field(default="stable", pattern="^(stable|woosh)$")


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatAssistRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    language: str = Field(default="en", max_length=12)
    instrumental: bool = False


class VoiceProfilePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(default="any", max_length=16)
    vocal_register: str = Field(default="", max_length=800, alias="register")
    timbre: str = Field(default="", max_length=800)
    delivery: str = Field(default="", max_length=800)
    accent: str = Field(default="", max_length=800)
    vibrato: str = Field(default="", max_length=800)
    dynamics: str = Field(default="", max_length=800)
    harmony: str = Field(default="", max_length=800)
    effects: str = Field(default="", max_length=800)
    audition_notes: str = Field(default="", max_length=800)
    expanded: str = Field(default="", max_length=800)
    tag: str = Field(default="", max_length=80)
    avatar: str = Field(default="", max_length=32)
    archived: bool = False


class VoiceCompileRequest(BaseModel):
    slots: dict[str, str] = Field(default_factory=dict)
    lyrics: str = Field(default="", max_length=24000)
    description: str = Field(default="", max_length=12000)
    snapshots: list[dict] = Field(default_factory=list)


class VoiceImportRequest(BaseModel):
    profiles: list[dict] = Field(default_factory=list)


class CoverArtRequest(BaseModel):
    direction: str = Field(default="", max_length=1200)


class StemRequest(BaseModel):
    mode: str = Field(default="2", pattern="^(2|4)$")


class CoverTranscribeRequest(BaseModel):
    melody_only: bool = True
    reuse_cached: bool = True


class SoundEffectRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)
    name: str = Field(default="", max_length=80)
    negative_prompt: str = Field(default="music, speech, singing, narration, clipping, distortion", max_length=500)
    duration: float = Field(default=5.0, ge=0.5, le=120.0)
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    steps: int = Field(default=8, ge=1, le=100)
    sampler: str = Field(default="pingpong", pattern="^(pingpong|euler|rk4|dpmpp|dopri5)$")
    chunked_decode: bool = True
    engine: str = Field(default="stable", pattern="^(stable|woosh)$")
    cfg: float = Field(default=4.5, ge=0.0, le=10.0)


class StudioRange(BaseModel):
    start: float = Field(ge=0.0, le=10800.0)
    end: float = Field(gt=0.0, le=10800.0)


class StudioEffectRegion(StudioRange):
    id: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(gain_up|gain_down|echo|reverb|auto_level|normalize|clarity|compressor|auto_pan|low_pass|high_pass|telephone|saturation|tremolo|stereo_widen|limiter)$")
    amount: float = Field(default=0.5, ge=0.0, le=1.0)
    instance: int | None = Field(default=None, ge=1, le=10000)
    fade_in: float = Field(default=0.18, ge=0.0, le=120.0)
    fade_out: float = Field(default=0.18, ge=0.0, le=120.0)


class StudioClip(BaseModel):
    """One movable, razor-cuttable region of a source file on the Studio timeline."""

    id: str = Field(default="", max_length=80)
    start: float = Field(default=0.0, ge=0.0, le=10800.0)
    source_in: float = Field(default=0.0, ge=0.0, le=10800.0)
    source_out: float | None = Field(default=None, gt=0.0, le=10800.0)
    fade_in: float = Field(default=0.0, ge=0.0, le=120.0)
    fade_out: float = Field(default=0.0, ge=0.0, le=120.0)
    gain: float = Field(default=1.0, ge=0.0, le=4.0)
    gain_left: float = Field(default=1.0, ge=0.0, le=4.0)
    gain_right: float = Field(default=1.0, ge=0.0, le=4.0)


class StudioTrackState(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lane: str | None = Field(default=None, min_length=1, max_length=80)
    gain: float = Field(default=1.0, ge=0.0, le=1.0)
    muted: bool = False
    solo: bool = False
    offset: float = Field(default=0.0, ge=0.0, le=10800.0)
    trim_start: float = Field(default=0.0, ge=0.0, le=10800.0)
    trim_end: float | None = Field(default=None, gt=0.0, le=10800.0)
    fade_in: float = Field(default=0.0, ge=0.0, le=120.0)
    fade_out: float = Field(default=0.0, ge=0.0, le=120.0)
    cuts: list[StudioRange] = Field(default_factory=list, max_length=64)
    effects: list[StudioEffectRegion] = Field(default_factory=list)
    clips: list[StudioClip] = Field(default_factory=list, max_length=256)
    use_clips: bool = False


class StudioSessionRequest(BaseModel):
    tracks: list[StudioTrackState] = Field(default_factory=list)


class StudioCombineRequest(StudioSessionRequest):
    files: list[str] = Field(min_length=2, max_length=64)
    name: str = Field(default="Combined sounds", min_length=1, max_length=80)


class StudioBounceRequest(StudioSessionRequest):
    variant: str = Field(default="custom", pattern="^(custom|instrumental|acapella)$")
    selection: StudioRange | None = None
    # The audible end of the edited song. amix runs to the longest input, so
    # without this a trimmed song still exported at its original length.
    content_end: float | None = Field(default=None, gt=0, le=3600)


STEMS_ROOT = Path(__file__).resolve().parent.parent / "models" / "stems"
STEM_MODEL = STEMS_ROOT / "955717e8-8726e21a.th"
STEM_CONFIG = STEMS_ROOT / "htdemucs.yaml"

STRUCTURE_TAGS = {
    "intro": "Intro",
    "verse": "Verse",
    "pre chorus": "Pre-Chorus",
    "prechorus": "Pre-Chorus",
    "pre-chorus": "Pre-Chorus",
    "chorus": "Chorus",
    "final chorus": "Chorus",
    "post chorus": "Post-Chorus",
    "postchorus": "Post-Chorus",
    "post-chorus": "Post-Chorus",
    "bridge": "Bridge",
    "interlude": "Interlude",
    "break": "Interlude",
    "breakdown": "Interlude",
    "hook": "Hook",
    "instrumental": "Instrumental",
    "inst": "Instrumental",
    "solo": "Solo",
    "outro": "Outro",
}
PERFORMANCE_TAGS = {
    "spoken": "Spoken",
    "spoken countdown": "Spoken Countdown",
    "whispered": "Whispered",
    "chanted": "Chanted",
    "rapped": "Rapped",
    "call and response": "Call and Response",
}


_STYLE_FIELD = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(Basic Attributes|Global Emotional Progression|"
    r"Vocal Gender & Timbre|Vocal Style|Instrument Lifecycle|"
    r"Sonics & Production Profile|Groove & Foundation Progression)\s*:\s*(.+)$"
)
_STYLE_HEADING = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(Global Metadata|Vocal Details|Arrangement)\s*:?\s*$"
)
_ABC_HEADER = re.compile(r"(?i)^(X:|T:|M:|L:|Q:|V:|K:|%)")


def looks_structured_style(text: str) -> bool:
    return bool(_STYLE_HEADING.search(text or ""))


def _first_clause(value: str, cap: int = 140) -> str:
    text = re.sub(r"\s+", " ", value or "").strip().rstrip(".,;:")
    if not text:
        return ""
    cut = re.search(r"[.;](\s|$)", text)
    if cut:
        text = text[: cut.start()].strip()
    if len(text) > cap:
        text = text[:cap].rsplit(" ", 1)[0].strip()
    return text


def flatten_style(description: str, *, keep_vocal_fields: bool = True) -> str:
    """Turn leftover MiniMax caption essays into one YuE2 comma-separated style line."""
    text = (description or "").strip()
    if not text:
        return ""
    if not looks_structured_style(text):
        return re.sub(r"\s+", " ", text).strip()
    found: dict[str, str] = {}
    for match in _STYLE_FIELD.finditer(text):
        found.setdefault(match.group(1), match.group(2).strip())
    order = (
        "Basic Attributes", "Vocal Gender & Timbre", "Vocal Style",
        "Instrument Lifecycle", "Global Emotional Progression",
        "Sonics & Production Profile", "Groove & Foundation Progression",
    )
    if not keep_vocal_fields:
        order = tuple(name for name in order if name not in {"Vocal Gender & Timbre", "Vocal Style"})
    parts = [_first_clause(found[name]) for name in order if found.get(name)]
    leftovers = []
    section = ""
    for line in text.splitlines():
        heading = _STYLE_HEADING.match(line)
        if heading:
            section = heading.group(1)
            continue
        if _STYLE_FIELD.match(line):
            continue
        if section in {"Global Metadata", "Vocal Details"}:
            continue
        clause = _first_clause(line)
        if clause:
            leftovers.append(clause)
    combined = [part for part in (*parts, *leftovers) if part]
    return ", ".join(combined)


def melody_only_abc(abc: str) -> str:
    """Remove quoted chord symbols from music lines; keep native Vocal/Ins headers."""
    lines = []
    for line in (abc or "").splitlines(keepends=True):
        if _ABC_HEADER.match(line.lstrip()):
            lines.append(line)
            continue
        lines.append(re.sub(r'"[^"\n]*"', "", line))
    return "".join(lines)


def native_cfg_scale(cot: str, cfg: float) -> float:
    """Official semantic CFG is 1.0 for full/melody and 1.01 for off."""
    if cot == "off" and abs(cfg - 1.0) < 1e-9:
        return 1.01
    return cfg


from lyric_format import control_lines, sung_lines, SPEAKER


def prepare_music3_lyrics(value: str) -> tuple[str, list[str]]:
    """Keep lyrics as sung words. Move bracket performance notes into the style prompt."""
    output: list[str] = []
    directions: list[str] = []
    last_tag = ""
    current_section = ""
    normalized_lines = control_lines(value)
    for line_index, raw_line in enumerate(normalized_lines):
        match = re.fullmatch(r"\s*\[([^\[\]\n]{1,500})\]\s*", raw_line)
        if not match:
            if "[" in raw_line or "]" in raw_line:
                raise HTTPException(422, "A lyric tag is missing a bracket. Fix the tag before generating.")
            output.extend(sung_lines(raw_line) if raw_line.strip() else [""])
            last_tag = ""
            continue
        content = re.sub(r"\s+", " ", match.group(1)).strip()
        parts = re.split(r"\s+[-–—]\s+", content, maxsplit=1)
        head = re.sub(r"\s+", " ", re.sub(r"\d+$", "", parts[0]).strip()).casefold()
        detail = parts[1].strip() if len(parts) > 1 else ""
        if head in {"start", "end"}:
            continue
        if head == "fade in":
            directions.append("Opening: fade in")
            continue
        if head == "fade out":
            directions.append("Ending: fade out")
            continue
        section_head = re.sub(r"^(verse|chorus|bridge|intro|outro)\s+[a-z]$", r"\1", head)
        tag = STRUCTURE_TAGS.get(section_head)
        if tag:
            current_section = tag
            rendered = f"[{tag}]"
            if rendered != last_tag:
                output.append(rendered)
                last_tag = rendered
            if detail:
                directions.append(f"{tag}: {detail}")
            continue
        performance = PERFORMANCE_TAGS.get(head)
        if performance:
            note = detail or "perform the following lyric line in this style"
            directions.append(f"{current_section}, {performance}: {note}" if current_section else f"{performance}: {note}")
            continue
        if re.fullmatch(SPEAKER, head, re.I):
            label = {"female": "Singer A (Female)", "woman": "Singer A (Female)",
                     "male": "Singer B (Male)", "man": "Singer B (Male)",
                     "both": "Both singers", "duet": "Both singers"}.get(head, parts[0].strip())
            upcoming = next((line for line in normalized_lines[line_index + 1:] if line and not line.startswith("[")), "")
            note = detail or (f'passage beginning "{upcoming[:90]}"' if upcoming else "")
            if note:
                singer_note = f"{label}: {note}"
                directions.append(f"{current_section}, {singer_note}" if current_section else singer_note)
            continue
        directions.append(f"{current_section}: {content}" if current_section else content)

    cleaned: list[str] = []
    for line in output:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return "\n".join(cleaned).strip(), directions


def music3_caption(description: str, directions: list[str]) -> str:
    """Append performance notes to a compact YuE2 style string. Never invent MiniMax headings."""
    style = flatten_style(description)
    if not directions:
        return style
    notes = "; ".join(directions)[:1500]
    extra = f"{notes}. These notes are style, not lyrics"
    if extra.casefold() in style.casefold():
        return style
    if not style:
        return extra
    return f"{style.rstrip().rstrip(',')}, {extra}"


_MUSIC3_PUNCTUATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u00ab": '"', "\u00bb": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2026": "...", "\u00a0": " ", "\u202f": " ", "\ufeff": "",
})


def music3_safe_text(value: str) -> str:
    """Normalize punctuation rejected by the bundled Music 3 tokenizer.

    The checkpoint tokenizer currently raises ``TextInputSequence must be str``
    for typographic double quotes even though the input is a Python string.
    Smart punctuation is common in pasted lyrics, so normalize the generation
    copy while preserving the user's original text in song metadata.
    """
    return value.translate(_MUSIC3_PUNCTUATION)


def prepare_generation_params(params: dict) -> dict:
    """Create and validate the exact native YuE2 style/lyric request."""
    prepared = dict(params)
    safe_description = str(prepared["description"]).replace("\ufeff", "").strip()
    safe_lyrics = str(prepared["lyrics"]).replace("\ufeff", "").strip()
    style = flatten_style(safe_description)
    if prepared["instrumental"]:
        prepared["rendered_lyrics"] = yue2_engine.INSTRUMENTAL_LYRICS
        lock = yue2_engine.INSTRUMENTAL_STYLE_LOCK
        style = re.sub(r"(?i)\bSinger [AB]\s*(?:\([^)]+\))?,?\s*", "", style).strip(" ,")
        prepared["generation_description"] = (
            style if style.casefold().startswith(lock.casefold())
            else f"{lock}. {style}".strip(" .")
        )
        prepared["voice_snapshots"] = []
    else:
        lyrics, directions = prepare_music3_lyrics(safe_lyrics)
        compiled = voice_profiles.compile_for_generation(
            style, prepared.get("voice_slots") or {}, lyrics, prepared.get("voice_snapshots")
        )
        if compiled["applied"]:
            style = compiled["description"]
            prepared["voice_snapshots"] = compiled["snapshots"]
        else:
            prepared["voice_snapshots"] = []
        prepared["rendered_lyrics"] = lyrics
        prepared["generation_description"] = music3_caption(style, directions)
    prepared["abc_score"] = str(prepared.get("abc_score") or "").strip() or None
    if prepared["abc_score"] and prepared["cot_mode"] == "off":
        raise HTTPException(422, detail="An ABC score requires Full or Melody planning mode.")
    counted = yue2_engine.count_prompt_tokens(prepared["generation_description"], prepared["rendered_lyrics"],
                                               prepared["cot_mode"], prepared["abc_score"])
    prepared["prompt_tokens"] = counted["tokens"]
    if counted["tokens"] > counted["maximum"]:
        raise HTTPException(
            422,
            detail=(
                f"Style, lyrics, and score use {counted['tokens']:,} YuE2 tokens; "
                f"YuE2 accepts at most {counted['maximum']:,} before generated music tokens. Shorten the prompt or score."
            ),
        )
    return prepared


def resolve_song_title(params: dict) -> str:
    """Blank titles are named by Writing when a key is available. Otherwise the user must type one."""
    title = str(params.get("title") or "").strip()
    if title and title.casefold() not in {"untitled song", "untitled"}:
        return title[:120]
    try:
        named = ai_assist.write(
            "title",
            description=str(params.get("description") or ""),
            lyrics="" if params.get("instrumental") else str(params.get("lyrics") or ""),
            language=str(params.get("lyrics_language") or "en"),
        )
        proposed = str(named.get("title") or "").strip()
        if proposed and proposed.casefold() not in {"untitled song", "untitled"}:
            log.info("Writing assistant named the song: %s", proposed)
            return proposed[:120]
        raise HTTPException(422, "Writing did not return a song title. Type one and try again.")
    except HTTPException:
        raise
    except PermissionError:
        raise HTTPException(422, "Type a song title, or save a Writing key in KEYS to auto-name blank titles.")
    except Exception as error:
        raise HTTPException(502, f"Could not auto-title the song: {error}") from error


def ffmpeg_path() -> str | None:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        return bundled if Path(bundled).is_file() else None
    except (ImportError, OSError):
        return None


def stems_status() -> dict:
    check = (yue2_engine.WORKER_PYTHON.parent.parent / "Lib" / "site-packages" / "demucs").is_dir()
    ready = bool(check and STEM_MODEL.is_file() and STEM_CONFIG.is_file())
    return {"ready": ready, "model": "htdemucs", "root": str(STEMS_ROOT), "detail": "GPU stem extraction ready" if ready else f"Install htdemucs in {STEMS_ROOT}"}


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result[:64] or "untitled-song"


RESERVED_FILE_STEMS = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def safe_title_stem(title: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", (title or "").strip()).strip(" .")[:120] or "song"
    if safe.casefold() in RESERVED_FILE_STEMS:
        safe = f"{safe}-audio"
    return safe


def create_song_directory(title: str, genre: str | None = None) -> Path:
    """Reserve a readable title folder without overwriting an existing take."""
    stem = safe_title_stem(title).rstrip(" .") or "song"
    if stem.split(".", 1)[0].casefold() in RESERVED_FILE_STEMS:
        stem = "Song " + stem
    if genre is None:
        # Keep this helper's historical root-level behavior for callers that
        # are not creating a generated song with a genre.
        genre_dir = LIBRARY_ROOT
    else:
        genre_stem = safe_title_stem(str(genre).strip() or "Uncategorized").rstrip(" .") or "Uncategorized"
        genre_dir = LIBRARY_ROOT / genre_stem
        genre_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = genre_dir / (stem if index == 1 else f"{stem} ({index})")
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            index += 1


def download_filename(song_dir: Path, suffix: str) -> str:
    title = "song"
    try:
        metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
        title = str(metadata.get("title") or title)
    except (OSError, json.JSONDecodeError):
        pass
    return f"{safe_title_stem(title)}{suffix.lower()}"


ORIGINAL_MIX_BACKUP = Path("studio") / "original_mix.wav"


def song_audio_file(song_dir: Path, metadata: dict | None = None) -> Path:
    name = "song.wav"
    if metadata is None:
        try:
            metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
    if metadata:
        name = str(metadata.get("audio") or "song.wav")
    candidate = song_dir / Path(name).name
    if candidate.is_file():
        return candidate
    fallback = song_dir / "song.wav"
    return fallback if fallback.is_file() else candidate


def song_audio_url(folder_name: str, audio: Path) -> str:
    url = f"/api/library/{quote(folder_name, safe='')}/{quote(audio.name, safe='')}"
    try:
        return f"{url}?v={audio.stat().st_mtime_ns}"
    except OSError:
        return url


def song_folder_name(song_dir: Path) -> str:
    """Return the stable library-relative identifier used by the API/UI."""
    try:
        return song_dir.resolve().relative_to(LIBRARY_ROOT.resolve()).as_posix()
    except ValueError:
        return song_dir.name


def original_mix_backup_path(song_dir: Path) -> Path:
    return song_dir / ORIGINAL_MIX_BACKUP


def original_mix_url(folder_name: str, song_dir: Path) -> str | None:
    backup = original_mix_backup_path(song_dir)
    return f"/api/library/{quote(folder_name, safe='')}/studio/original-mix" if backup.is_file() else None


def _promote_custom_mix(song_dir: Path, metadata: dict, mix_path: Path) -> Path:
    """Make a full custom bounce the song listeners and Video Studio hear."""
    master = song_audio_file(song_dir, metadata)
    backup = original_mix_backup_path(song_dir)
    if master.is_file() and master.resolve() != mix_path.resolve():
        if not backup.is_file():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(master, backup)
            metadata["original_audio"] = ORIGINAL_MIX_BACKUP.as_posix()
            log.info("Preserved dry original mix at %s", backup)
        try:
            shutil.copy2(mix_path, master)
            log.info("Promoted custom mix onto song audio %s", master.name)
            return master
        except OSError as error:
            dest = song_dir / mix_path.name
            if dest.resolve() != mix_path.resolve():
                shutil.copy2(mix_path, dest)
            metadata["audio"] = dest.name
            log.warning("Could not replace locked song audio %s (%s); installed mix as %s", master.name, error, dest.name)
            return dest
    dest_name = Path(str(metadata.get("audio") or "song.wav")).name
    dest = song_dir / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mix_path, dest)
    metadata["audio"] = dest.name
    log.info("Installed custom mix as song audio %s", dest.name)
    return dest


STUDIO_MIX_SUFFIX = "Studio Mix"


def _studio_mix_title(base_title: str, existing_titles: set[str]) -> str:
    """`Song (Studio Mix)`, numbering repeats so the library stays readable."""
    base = (base_title or "Untitled Song").strip() or "Untitled Song"
    candidate = f"{base} ({STUDIO_MIX_SUFFIX})"
    if candidate not in existing_titles:
        return candidate
    index = 2
    while f"{base} ({STUDIO_MIX_SUFFIX} {index})" in existing_titles:
        index += 1
    return f"{base} ({STUDIO_MIX_SUFFIX} {index})"


def _existing_song_titles() -> set[str]:
    titles: set[str] = set()
    if not LIBRARY_ROOT.is_dir():
        return titles
    for manifest in LIBRARY_ROOT.rglob("song.json"):
        try:
            titles.add(str(json.loads(manifest.read_text(encoding="utf-8")).get("title") or ""))
        except (OSError, json.JSONDecodeError):
            continue
    return titles


def _export_custom_mix_as_song(song_dir: Path, metadata: dict, mix_path: Path) -> dict:
    """Save a full studio bounce as a new library entry.

    The original song is left completely untouched -- the point of Studio is to
    try things, and an export that overwrites the take you were working from
    gives you nowhere to go back to. The new song carries the original's
    metadata so it looks right in the library, plus a pointer back to its source.
    """
    title = _studio_mix_title(str(metadata.get("title") or ""), _existing_song_titles())
    new_id = uuid.uuid4().hex
    new_dir = create_song_directory(title, metadata.get("genre"))

    audio_name = f"{safe_title_stem(title)}.wav"
    shutil.copy2(mix_path, new_dir / audio_name)

    cover_name = str(metadata.get("cover") or "")
    if cover_name and (song_dir / Path(cover_name).name).is_file():
        shutil.copy2(song_dir / Path(cover_name).name, new_dir / "cover.png")
        cover_name = "cover.png"
    else:
        cover_name = ""

    fresh = dict(metadata)
    # Everything below belongs to the source take, not to this bounce.
    for key in ("studio", "studio_mixes", "studio_imports", "stems",
                "original_audio", "timed_lyrics"):
        fresh.pop(key, None)
    fresh.update({
        "id": new_id,
        "title": title,
        "audio": audio_name,
        "cover": cover_name or None,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "studio_source": song_folder_name(song_dir),
        "studio_source_title": str(metadata.get("title") or ""),
    })
    try:
        fresh["duration"] = yue2_engine.inspect_wav(new_dir / audio_name)["duration"]
    except Exception:
        log.exception("Could not measure the exported studio mix")
    (new_dir / "song.json").write_text(json.dumps(fresh, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Exported studio mix as a new song: %s", new_dir.name)
    new_folder_name = song_folder_name(new_dir)
    return {"folder_name": new_folder_name, "title": title,
            "audio_url": song_audio_url(new_folder_name, new_dir / audio_name)}


def align_audio_to_title(song_dir: Path, metadata: dict, title: str) -> Path:
    """Keep the master WAV named after the song title. Falls back if the file is locked."""
    current = song_audio_file(song_dir, metadata)
    target = song_dir / f"{safe_title_stem(title)}.wav"
    if not current.is_file():
        metadata["audio"] = target.name
        return target
    if current.resolve() == target.resolve():
        metadata["audio"] = current.name
        return current
    if target.exists():
        stem = safe_title_stem(title)
        index = 2
        while True:
            alt = song_dir / f"{stem}-{index}.wav"
            if not alt.exists() or alt.resolve() == current.resolve():
                target = alt
                break
            index += 1
    try:
        current.replace(target)
        metadata["audio"] = target.name
        return target
    except OSError:
        metadata["audio"] = current.name
        return current


def gpu_status() -> dict:
    result = {"detected": False, "name": None, "vram_total_mb": None, "vram_free_mb": None, "usage": None, "temperature": None, "driver": None}
    try:
        line = subprocess.check_output([
            "nvidia-smi", "--query-gpu=name,memory.total,memory.free,utilization.gpu,temperature.gpu,driver_version",
            "--format=csv,noheader,nounits",
        ], text=True, timeout=5).splitlines()[0]
        values = [item.strip() for item in line.split(",")]
        result.update({"detected": True, "name": values[0], "vram_total_mb": int(values[1]), "vram_free_mb": int(values[2]), "usage": int(values[3]), "temperature": int(values[4]), "driver": values[5]})
    except Exception: pass
    try:
        result["policy"] = yue2_engine.gpu_policy()
    except Exception:
        log.exception("Could not read the YuE2 VRAM policy")
    return result


def generate(job: Job) -> dict:
    request = job.params
    try:
        request["title"] = ai_assist.ensure_unique_title(
            str(request.get("title") or ""),
            description=str(request.get("description") or ""),
            lyrics="" if request.get("instrumental") else str(request.get("lyrics") or ""),
            language=str(request.get("lyrics_language") or "en"),
            for_generation=True,
        )
    except PermissionError:
        if ai_assist._title_taken(str(request.get("title") or ""), ai_assist._taken_titles()):
            raise RuntimeError(f"Song title already exists: {request.get('title')}")
    song_dir = create_song_directory(request["title"], request.get("genre"))
    output = song_dir / "song.wav"
    manifest = song_dir / "song.json"
    try:
        job.phase, job.progress = "Starting YuE2 worker", 0.01; job.emit()
        engine_result = yue2_engine.generate(job, request, output)
        if job.cancel.is_set(): raise RuntimeError("cancelled")
        audio_name = align_audio_to_title(song_dir, {"audio": output.name}, request["title"]).name
        metadata = {
            "id": job.id, "title": request["title"], "description": request["description"],
            "artist": request.get("artist", ""), "album": request.get("album", ""),
            "genre": request.get("genre", ""), "year": time.strftime("%Y"), "track_number": "",
            "lyrics": lyrics_sync.normalize_lyrics(request.get("lyrics") or ""), "instrumental": request["instrumental"],
            "seed": request["seed"], "duration": engine_result["duration"],
            "cot_mode": request["cot_mode"], "abc_score": request.get("abc_score"),
            "steps": request["steps"], "cfg": request["cfg"], "top_k": request.get("top_k", 100),
            "temperature": request.get("temperature", 1.0), "exclude_styles": request.get("exclude_styles", ""),
            "vocal_gender": request.get("vocal_gender", "auto"), "prompt_tokens": request.get("prompt_tokens"),
            "english_translation": request.get("english_translation", ""),
            "lyrics_language": request.get("lyrics_language", "en"),
            "voice_slots": request.get("voice_slots") or {},
            "voice_snapshots": request.get("voice_snapshots") or [],
            "generation_description": request.get("generation_description") or "",
            "sample_rate": engine_result["sample_rate"], "audio": audio_name,
            "cover": None, "cover_error": None, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Saved YuE2 song: %s", output)
        cover_seconds: float | None = None
        timing_profile = generation_timing.predict(request)
        if cover_art.available():
            cover_started = time.monotonic()
            job.phase, job.progress, job.eta_seconds, job.stage_progress = "Generating thumbnail", 0.91, timing_profile.cover_seconds, 0.0; job.emit()
            try:
                cover_source = request.get("generation_description") if request.get("instrumental") else request["description"]
                cover_art.render(job, request["title"], cover_source, request["lyrics"], song_dir / "cover.png", progress_span=0.04)
                metadata["cover"] = "cover.png"
                cover_seconds = time.monotonic() - cover_started
            except Exception as error:
                if job.cancel.is_set(): raise
                metadata["cover_error"] = str(error); log.warning("Song saved, but thumbnail failed: %s", error)
        else:
            log.info("Cover model is not installed; skipping automatic thumbnail")
        metadata["needs_lyric_sync"] = bool(
            not request.get("instrumental")
            and lyrics_sync.display_lines(str(metadata.get("lyrics") or ""))
        )
        # Persist the thumbnail before alignment writes the updated manifest.
        manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        if job.cancel.is_set():
            raise RuntimeError("cancelled")
        if metadata["needs_lyric_sync"]:
            state = lyrics_sync.status()
            if state.get("ready"):
                job.phase, job.progress = "Synchronizing lyrics with WhisperX", 0.96
                job.eta_seconds, job.stage_progress = None, None
                job.emit()
                try:
                    # YuE2 has finished; free its local GPU allocation for WhisperX.
                    # This does not touch the separate Ollama server.
                    yue2_engine.cancel()
                    lyrics_sync.run(job, song_dir, metadata, progress_base=0.96, progress_span=0.035)
                    metadata["needs_lyric_sync"] = False
                    metadata.pop("lyrics_sync_error", None)
                except Exception as error:
                    if job.cancel.is_set():
                        raise
                    metadata["lyrics_sync_error"] = str(error)
                    log.warning("Song saved, but automatic lyric sync failed: %s", error)
            else:
                metadata["lyrics_sync_error"] = state.get("detail") or "WhisperX is not installed"
                log.info("Skipping automatic lyric sync: %s", metadata["lyrics_sync_error"])
        measured = engine_result.get("generation_timing") or {}
        if measured:
            generation_timing.record(
                request,
                float(measured.get("compose_seconds") or 0.0),
                float(measured.get("refine_seconds") or 0.0),
                cover_seconds,
            )
        manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        audio_path = song_dir / audio_name
        folder_name = song_folder_name(song_dir)
        return {**metadata, "folder": str(song_dir), "folder_name": folder_name, "audio_url": song_audio_url(folder_name, audio_path) if audio_path.is_file() else f"/api/library/{quote(folder_name, safe='')}/{quote(audio_name, safe='')}", "cover_url": f"/api/library/{quote(folder_name, safe='')}/cover.png" if metadata["cover"] else None, "timed_lyrics": lyrics_sync.load(song_dir)}
    except Exception:
        if not manifest.is_file():
            shutil.rmtree(song_dir, ignore_errors=True)
            if song_dir.parent != LIBRARY_ROOT and song_dir.parent.is_dir():
                try:
                    song_dir.parent.rmdir()
                except OSError:
                    pass
        raise


ABC_SCORE_MAX = 24000


def read_song_abc(song_dir: Path, metadata: dict | None = None) -> str:
    """Prefer the planned score YuE2 wrote, then any ABC saved with the request."""
    score_path = song_dir / "score.abc"
    if score_path.is_file():
        try:
            text = score_path.read_text(encoding="utf-8").strip()
            if text:
                return text[:ABC_SCORE_MAX]
        except (OSError, UnicodeError):
            pass
    return str((metadata or {}).get("abc_score") or "").strip()[:ABC_SCORE_MAX]


def library() -> list[dict]:
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    items = []
    for manifest in LIBRARY_ROOT.rglob("song.json"):
        try:
            item = json.loads(manifest.read_text(encoding="utf-8"))
            audio = song_audio_file(manifest.parent, item)
            if audio.is_file():
                aligned = align_audio_to_title(manifest.parent, item, str(item.get("title") or "song"))
                if aligned != audio or item.get("audio") != aligned.name:
                    manifest.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
                audio = aligned
                planned = read_song_abc(manifest.parent, item)
                folder_name = song_folder_name(manifest.parent)
                items.append({
                    **item,
                    "has_score": bool(planned),
                    "folder": str(manifest.parent),
                    "folder_name": folder_name,
                    "audio_url": song_audio_url(folder_name, audio),
                    "original_audio_url": original_mix_url(folder_name, manifest.parent),
                    "cover_url": f"/api/library/{quote(folder_name, safe='')}/{quote(item['cover'], safe='')}?v={(manifest.parent / item['cover']).stat().st_mtime_ns}" if item.get("cover") and (manifest.parent / item["cover"]).is_file() else None,
                    "timed_lyrics": lyrics_sync.load(manifest.parent),
                })
        except (OSError, json.JSONDecodeError): pass
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


PLAYLISTS_FILE = OUTPUTS_ROOT / "playlists.json"
PLAYLISTS_LOCK = threading.RLock()
WORKSPACES_FILE = OUTPUTS_ROOT / "workspaces.json"
WORKSPACES_LOCK = threading.RLock()


def load_playlists() -> list[dict]:
    with PLAYLISTS_LOCK:
        try:
            payload = json.loads(PLAYLISTS_FILE.read_text(encoding="utf-8"))
            items = payload.get("playlists", []) if isinstance(payload, dict) else []
            return [item for item in items if isinstance(item, dict) and item.get("id") and item.get("name") and isinstance(item.get("song_ids"), list)]
        except (OSError, json.JSONDecodeError):
            return []


def save_playlists(items: list[dict]) -> None:
    with PLAYLISTS_LOCK:
        PLAYLISTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = PLAYLISTS_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"playlists": items}, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, PLAYLISTS_FILE)


def find_playlist(items: list[dict], playlist_id: str) -> dict:
    playlist = next((item for item in items if item["id"] == playlist_id), None)
    if playlist is None:
        raise HTTPException(404, "Playlist not found")
    return playlist


def load_workspaces() -> list[dict]:
    with WORKSPACES_LOCK:
        try:
            payload = json.loads(WORKSPACES_FILE.read_text(encoding="utf-8"))
            items = payload.get("workspaces", []) if isinstance(payload, dict) else []
            items = [item for item in items if isinstance(item, dict) and item.get("id") and item.get("name") and isinstance(item.get("song_ids"), list)]
        except (OSError, json.JSONDecodeError):
            items = []
        if not any(item["id"] == "my-workspace" for item in items):
            items.insert(0, {"id": "my-workspace", "name": "My Workspace", "song_ids": [], "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        valid_song_ids = {str(song.get("id")) for song in library() if song.get("id")}
        assigned: set[str] = set()
        changed = False
        for item in items:
            unique = []
            for song_id in item["song_ids"]:
                if song_id in valid_song_ids and song_id not in assigned:
                    unique.append(song_id); assigned.add(song_id)
            changed = changed or unique != item["song_ids"]
            item["song_ids"] = unique
        default = next(item for item in items if item["id"] == "my-workspace")
        missing = sorted(valid_song_ids - assigned)
        if missing:
            default["song_ids"].extend(missing); changed = True
        if changed or not WORKSPACES_FILE.is_file(): save_workspaces(items)
        return items


def save_workspaces(items: list[dict]) -> None:
    with WORKSPACES_LOCK:
        WORKSPACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = WORKSPACES_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"workspaces": items}, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, WORKSPACES_FILE)


def find_workspace(items: list[dict], workspace_id: str) -> dict:
    workspace = next((item for item in items if item["id"] == workspace_id), None)
    if workspace is None: raise HTTPException(404, "Workspace not found")
    return workspace


def inference_status() -> dict:
    model = yue2_engine.model_status()
    runtime = yue2_engine.runtime_status()
    online = bool(model["ready"] and runtime["ready"])
    if not runtime["ready"]:
        detail = "YuE2 runtime is not installed. Run Setup YuE2 Studio.bat."
    elif not model["ready"]:
        detail = "Install the YuE2-3B model and YuE2-Vae decoder."
    else:
        detail = "Standalone single-GPU YuE2 engine ready"
    return {"online": online, "url": "local worker", "detail": detail, **runtime}


class LanUpdateRequest(BaseModel):
    enabled: bool | None = None


@app.get("/api/lan/status")
def lan_status(request: Request):
    return lan_access.status(request)


@app.post("/api/lan/settings")
def lan_settings(request: Request, payload: LanUpdateRequest):
    if not lan_access.is_local(request):
        raise HTTPException(403, "Change LAN settings on the studio PC.")
    return lan_access.update(enabled=payload.enabled)


@app.get("/health")
def health(): return {"ok": True, "service": "YuE2 Studio", "protocol": 3, "outputs_root": str(OUTPUTS_ROOT), "model": yue2_engine.model_status(), "inference": inference_status()}


@app.get("/video-studio")
def video_studio_page():
    return FileResponse(VIDEO_STUDIO_ROOT / "index.html", media_type="text/html")


@app.post("/api/video/prepare")
def prepare_video_render():
    """Drop the YuE2 GPU worker so the browser can decode video and capture the canvas."""
    return yue2_engine.unload()


@app.post("/api/video/render")
async def render_visualizer_video(request: Request, title: str = "visualizer"):
    """Convert the browser's canvas/audio capture to a shareable H.264 MP4."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise HTTPException(409, "FFmpeg is not installed")
    safe_title = slug(title)[:80] or "visualizer"
    VIDEO_RENDER_ROOT.mkdir(parents=True, exist_ok=True)
    render_id = f"{time.time_ns():x}"
    source = VIDEO_RENDER_ROOT / f"{safe_title}-{render_id}.webm"
    target = VIDEO_RENDER_ROOT / f"{safe_title}-{render_id}.mp4"
    total = 0
    try:
        with source.open("wb") as handle:
            async for chunk in request.stream():
                total += len(chunk)
                if total > 4 * 1024 * 1024 * 1024:
                    raise HTTPException(413, "Video render is limited to 4 GB")
                handle.write(chunk)
        if total == 0:
            raise HTTPException(400, "The browser did not return a video recording")
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=3600,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if completed.returncode != 0 or not target.is_file():
            target.unlink(missing_ok=True)
            raise HTTPException(500, completed.stderr.strip()[-1600:] or "FFmpeg could not encode the video")
        return FileResponse(target, filename=f"{safe_title}.mp4", media_type="video/mp4")
    finally:
        source.unlink(missing_ok=True)

@app.get("/api/status")
def status():
    ffmpeg = ffmpeg_path()
    try:
        sheetsage_status = sheetsage.status()
    except Exception:
        sheetsage_status = {"ready": False, "detail": "SheetSage2 status could not be read."}
    return {"model": yue2_engine.model_status(), "cover_art": cover_art.status(), "stems": stems_status(), "sound_effects": stable_sfx.status(), "lyrics_sync": lyrics_sync.status(), "sheetsage": sheetsage_status, "exports": {"ready": bool(ffmpeg), "detail": "MP3 and FLAC export ready" if ffmpeg else "Run Setup to install the private FFmpeg exporter"}, "service": inference_status(), "gpu": gpu_status(), "ai": ai_vault.status(), "jobs": [job.snapshot() for job in manager.list()[:30]]}


class McpActivityRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=500)
    status: str = Field(default="started", pattern="^(connected|disconnected|started|succeeded|failed)$")


@app.get("/api/mcp/activity")
def get_mcp_activity():
    with mcp_activity_lock:
        return {"items": list(reversed(mcp_activity))}


@app.post("/api/mcp/activity")
def record_mcp_activity(request: McpActivityRequest):
    entry = {"id": uuid.uuid4().hex[:12], "at": time.time(), "tool": request.tool, "summary": request.summary, "status": request.status}
    with mcp_activity_lock:
        mcp_activity.append(entry)
    log.info("MCP %s: %s", request.tool, request.summary)
    return {"ok": True, "activity": entry}


class LyricPreferencesRequest(BaseModel):
    avoid: str = Field(default="", max_length=12000)


@app.get("/api/settings/lyric-preferences")
def get_lyric_preferences():
    import lyric_preferences
    return lyric_preferences.load()


@app.put("/api/settings/lyric-preferences")
def put_lyric_preferences(request: LyricPreferencesRequest):
    import lyric_preferences
    return lyric_preferences.save(request.avoid)


@app.get("/api/settings/ai-keys")
def get_ai_keys():
    return ai_vault.public_view()


@app.put("/api/settings/ai-keys")
def put_ai_keys(request: AiKeysUpdate):
    try:
        return ai_vault.apply_update(request.model_dump())
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


def _voice_payload(request: VoiceProfilePayload) -> dict:
    payload = request.model_dump()
    payload["register"] = payload.pop("vocal_register", "")
    return payload


@app.get("/api/voices")
def get_voices(archived: bool = False):
    return {"items": voice_profiles.list_profiles(include_archived=archived)}


@app.post("/api/voices")
def create_voice(request: VoiceProfilePayload):
    try:
        return {"profile": voice_profiles.upsert(_voice_payload(request))}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.put("/api/voices/{profile_id}")
def update_voice(profile_id: str, request: VoiceProfilePayload):
    if not voice_profiles.get_profile(profile_id):
        raise HTTPException(404, "Voice profile not found")
    try:
        return {"profile": voice_profiles.upsert(_voice_payload(request), profile_id=profile_id)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/voices/{profile_id}/duplicate")
def duplicate_voice(profile_id: str):
    try:
        return {"profile": voice_profiles.duplicate(profile_id)}
    except KeyError:
        raise HTTPException(404, "Voice profile not found")


@app.delete("/api/voices/{profile_id}")
def delete_voice(profile_id: str):
    try:
        return voice_profiles.archive_or_delete(profile_id)
    except KeyError:
        raise HTTPException(404, "Voice profile not found")


@app.post("/api/voices/import")
def import_voices(request: VoiceImportRequest):
    return {"items": voice_profiles.import_profiles(request.profiles)}


@app.post("/api/voices/compile")
def compile_voices(request: VoiceCompileRequest):
    return voice_profiles.compile_for_generation(
        request.description,
        request.slots,
        request.lyrics,
        request.snapshots,
    )


@app.get("/api/voices/{profile_id}/avatar")
def get_voice_avatar(profile_id: str):
    path = voice_profiles.avatar_path(profile_id)
    if not path.is_file():
        raise HTTPException(404, "No portrait yet")
    return FileResponse(path, media_type="image/webp")


@app.post("/api/voices/{profile_id}/avatar")
async def upload_voice_avatar(profile_id: str, request: Request):
    if not voice_profiles.get_profile(profile_id):
        raise HTTPException(404, "Voice profile not found")
    body = await request.body()
    if not body:
        raise HTTPException(400, "The selected image is empty")
    if len(body) > 20 * 1024 * 1024:
        raise HTTPException(413, "Portraits are limited to 20 MB")
    suffix = Path((request.query_params.get("filename") or "portrait.png")).suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(415, "Choose a PNG, JPG, JPEG, or WebP image")
    temporary = voice_profiles.AVATARS_DIR / f"{profile_id}.upload{suffix}"
    voice_profiles.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(body)
    try:
        profile = voice_profiles.save_avatar_image(profile_id, temporary)
    except Exception as error:
        raise HTTPException(409, str(error)) from error
    finally:
        temporary.unlink(missing_ok=True)
    return {"profile": profile, "avatar_url": f"/api/voices/{profile_id}/avatar?v={profile['updated_at']}"}


@app.post("/api/voices/{profile_id}/avatar/generate")
def generate_voice_avatar(profile_id: str, request: CoverArtRequest):
    if not voice_profiles.get_profile(profile_id):
        raise HTTPException(404, "Voice profile not found")
    try:
        profile = voice_profiles.generate_avatar(profile_id, request.direction)
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error
    except KeyError:
        raise HTTPException(404, "Voice profile not found")
    return {"profile": profile, "avatar_url": f"/api/voices/{profile_id}/avatar?v={profile['updated_at']}"}


@app.get("/api/assist/caption-library")
def assist_caption_library():
    """Is the local caption reference library present, and what does it route to?"""
    return caption_library.stats()


@app.post("/api/assist/chat")
def assist_chat(request: ChatAssistRequest):
    """Easy mode: one conversational turn that also yields a music brief."""
    try:
        return ai_assist.chat(
            [message.model_dump() for message in request.messages],
            language=request.language,
            instrumental=request.instrumental,
        )
    except ai_assist.WritingBusyError as error:
        raise HTTPException(409, str(error)) from error
    except PermissionError as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(502, str(error)) from error


@app.post("/api/assist/writing")
def assist_writing(request: WritingAssistRequest):
    try:
        if request.action == "effect":
            if not request.description.strip():
                raise ValueError("Enter a sound description first.")
            return ai_assist.enhance_effect(request.description, engine=request.effect_engine)
        if request.action == "compose":
            # One line in, title + compact YuE2 style + tagged lyrics out.
            return ai_assist.compose(
                idea=request.idea or request.description,
                title=request.title,
                language=request.language,
                instrumental=request.instrumental,
            )
        if request.action == "describe":
            # Compact YuE2 style is the text that steers generation.
            return ai_assist.describe(
                description=request.description,
                title=request.title,
                lyrics=request.lyrics,
                idea=request.idea,
                language=request.language,
                instrumental=request.instrumental,
            )
        return ai_assist.write(
            request.action,
            idea=request.idea,
            random=request.random,
            title=request.title,
            description=request.description,
            lyrics=request.lyrics,
            language=request.language,
        )
    except ai_assist.WritingBusyError as error:
        raise HTTPException(409, str(error)) from error
    except PermissionError as error:
        log.warning("Writing assistant refused: %s", error)
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        log.warning("Writing assistant bad request: %s", error)
        raise HTTPException(400, str(error)) from error
    except ai_assist.WritingValidationError as error:
        log.warning("Writing draft rejected (%s): %s", request.action, error)
        raise HTTPException(502, str(error)) from error
    except RuntimeError as error:
        if str(error) == "Writing cancelled":
            log.info("Writing assistant cancelled (%s)", request.action)
            raise HTTPException(409, str(error)) from None
        log.exception("Writing assistant failed (%s): %s", request.action, error)
        raise HTTPException(502, str(error)) from error
    except Exception as error:
        log.exception("Writing assistant crashed (%s)", request.action)
        raise HTTPException(502, str(error)) from error


@app.post("/api/assist/abort")
def assist_abort():
    ai_assist.abort_writing()
    return {"ok": True}


@app.post("/api/models/refresh")
def refresh_models(): return yue2_engine.model_status()

@app.post("/api/clear-memory")
def clear_memory():
    if any(job.status in {"queued", "running"} for job in manager.list()):
        raise HTTPException(409, "Cancel active generation before clearing VRAM")
    return yue2_engine.unload()

@app.post("/api/generate")
def start_generation(request: GenerateRequest):
    state = inference_status()
    if not state["online"]: raise HTTPException(409, detail=state["detail"])
    params = request.model_dump()
    if params["seed"] is None: params["seed"] = int.from_bytes(os.urandom(4), "big") & 0x7FFFFFFF
    params["title"] = resolve_song_title(params)
    try:
        params = prepare_generation_params(params)
    except HTTPException:
        raise
    except Exception as error:
        log.exception("Could not prepare YuE2 prompt")
        raise HTTPException(500, detail=f"Could not prepare the YuE2 prompt: {error}") from error
    job = manager.submit("yue2", params, generate)
    return {"job": job.snapshot()}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.get(job_id)
    if not job: raise HTTPException(404, "Job not found")
    return {"job": job.snapshot()}

@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    target = manager.get(job_id)
    was_running = bool(target and target.status == "running")
    if not manager.cancel_job(job_id): raise HTTPException(409, "Job is already finished or missing")
    if was_running and target and target.kind == "yue2":
        yue2_engine.cancel()
        lyrics_sync.cancel()
    elif was_running and target and target.kind == "lyrics_sync":
        lyrics_sync.cancel()
    elif was_running and target and target.kind == "stable_sfx":
        stable_sfx.cancel(target)
    elif was_running and target and target.kind == "sheetsage":
        sheetsage.cancel()
    return {"status": "cancelling"}

@app.websocket("/ws/jobs/{job_id}")
async def job_socket(socket: WebSocket, job_id: str):
    await socket.accept(); subscription = manager.subscribe(job_id)
    if subscription is None: await socket.close(code=4404); return
    queue, unsubscribe = subscription
    try:
        while True:
            event = await queue.get(); await socket.send_json(event)
            if event.get("status") in {"succeeded", "failed", "cancelled"}: break
    except WebSocketDisconnect: pass
    finally: unsubscribe()

@app.get("/api/library")
def get_library(): return {"items": library()}


@app.get("/api/library/{folder:path}/timed-lyrics")
def get_timed_lyrics(folder: str):
    song_dir = resolve_song_folder(folder)
    payload = lyrics_sync.load(song_dir)
    if not payload or not payload.get("lines"):
        raise HTTPException(404, "This song does not have synchronized lyrics yet")
    try:
        metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    lyrics_sync.attach_translations(payload, str(metadata.get("english_translation") or ""))
    return payload


@app.get("/api/playlists")
def get_playlists(): return {"items": load_playlists()}


@app.post("/api/playlists")
def create_playlist(request: PlaylistCreateRequest):
    name = request.name.strip()
    if not name: raise HTTPException(422, "Playlist name cannot be blank")
    items = load_playlists()
    if any(item["name"].casefold() == name.casefold() for item in items):
        raise HTTPException(409, "A playlist with that name already exists")
    playlist = {"id": f"{slug(name)[:40]}-{time.time_ns():x}", "name": name, "song_ids": [], "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    items.append(playlist); save_playlists(items)
    return {"playlist": playlist}


@app.delete("/api/playlists/{playlist_id}")
def delete_playlist(playlist_id: str):
    items = load_playlists(); find_playlist(items, playlist_id)
    save_playlists([item for item in items if item["id"] != playlist_id])
    return {"deleted": True}


@app.post("/api/playlists/{playlist_id}/songs/{song_id}")
def add_song_to_playlist(playlist_id: str, song_id: str):
    if not any(str(song.get("id")) == song_id for song in library()):
        raise HTTPException(404, "Song not found")
    items = load_playlists(); playlist = find_playlist(items, playlist_id)
    if song_id not in playlist["song_ids"]: playlist["song_ids"].append(song_id)
    save_playlists(items)
    return {"added": True}


@app.delete("/api/playlists/{playlist_id}/songs/{song_id}")
def remove_song_from_playlist(playlist_id: str, song_id: str):
    items = load_playlists(); playlist = find_playlist(items, playlist_id)
    playlist["song_ids"] = [item for item in playlist["song_ids"] if item != song_id]
    save_playlists(items)
    return {"removed": True}


@app.get("/api/workspaces")
def get_workspaces(): return {"items": load_workspaces()}


@app.post("/api/workspaces")
def create_workspace(request: PlaylistCreateRequest):
    name = request.name.strip()
    if not name: raise HTTPException(422, "Workspace name cannot be blank")
    items = load_workspaces()
    if any(item["name"].casefold() == name.casefold() for item in items): raise HTTPException(409, "A workspace with that name already exists")
    workspace = {"id": f"{slug(name)[:40]}-{time.time_ns():x}", "name": name, "song_ids": [], "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    items.append(workspace); save_workspaces(items)
    return {"workspace": workspace}


@app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    if workspace_id == "my-workspace": raise HTTPException(409, "My Workspace cannot be deleted")
    items = load_workspaces(); workspace = find_workspace(items, workspace_id)
    default = find_workspace(items, "my-workspace")
    default["song_ids"].extend(song_id for song_id in workspace["song_ids"] if song_id not in default["song_ids"])
    save_workspaces([item for item in items if item["id"] != workspace_id])
    return {"deleted": True}


@app.post("/api/workspaces/{workspace_id}/songs/{song_id}")
def move_song_to_workspace(workspace_id: str, song_id: str):
    if not any(str(song.get("id")) == song_id for song in library()): raise HTTPException(404, "Song not found")
    items = load_workspaces(); target = find_workspace(items, workspace_id)
    for item in items: item["song_ids"] = [existing for existing in item["song_ids"] if existing != song_id]
    target["song_ids"].append(song_id); save_workspaces(items)
    return {"moved": True}


def resolve_song_folder(folder: str) -> Path:
    """Resolve one library song folder without permitting path traversal."""
    relative = Path(str(folder or ""))
    if (
        not folder
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise HTTPException(404, "Song not found")
    root = LIBRARY_ROOT.resolve()
    target = (root / relative).resolve()
    if root not in target.parents or not target.is_dir():
        raise HTTPException(404, "Song not found")
    if not (target / "song.json").is_file() and any(child.is_dir() for child in target.iterdir()):
        raise HTTPException(404, "Song not found")
    return target


# Register the specific Studio route before the catch-all song update route.
@app.patch("/api/library/{folder:path}/studio")
def save_studio_session(folder: str, request: StudioSessionRequest):
    song_dir = resolve_song_folder(folder); manifest, metadata = _studio_manifest(song_dir)
    metadata["studio"] = {"tracks": [track.model_dump() for track in request.tracks], "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"saved": True}


@app.patch("/api/library/{folder:path}/rating")
def rate_song(folder: str, request: SongRatingRequest):
    target = resolve_song_folder(folder)
    manifest = target / "song.json"
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(404, "Song details not found") from exc
    metadata["rating"] = request.rating
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"rating": request.rating}


@app.patch("/api/library/{folder:path}")
def update_song(folder: str, request: SongUpdateRequest):
    target = resolve_song_folder(folder)
    manifest = target / "song.json"
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(404, "Song details not found") from exc
    lyrics_changed = str(metadata.get("lyrics") or "") != request.lyrics
    metadata.update({
        "title": request.title.strip(),
        "artist": request.artist.strip(),
        "album": request.album.strip(),
        "genre": request.genre.strip(),
        "year": request.year.strip(),
        "track_number": request.track_number.strip(),
        "description": request.description.strip(),
        "lyrics": request.lyrics,
        "english_translation": request.english_translation,
        "lyrics_language": request.lyrics_language.strip().lower(),
    })
    timed = lyrics_sync.load(target)
    if lyrics_changed:
        shutil.rmtree(target / "lyrics_sync", ignore_errors=True)
        metadata.pop("lyrics_sync", None)
    elif timed is not None:
        lyrics_sync.attach_translations(timed, request.english_translation)
        lyrics_sync.result_path(target).write_text(json.dumps(timed, indent=2, ensure_ascii=False), encoding="utf-8")
    if not metadata["title"]:
        raise HTTPException(422, "Song title cannot be blank")
    align_audio_to_title(target, metadata, metadata["title"])
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Updated YuE2 song details: %s", target.name)
    return {"updated": True}


def regenerate_cover(job: Job) -> dict:
    request = job.params
    song_dir = resolve_song_folder(request["folder"])
    manifest = song_dir / "song.json"
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Song details could not be read") from exc
    pending = song_dir / "cover.pending.png"
    final = song_dir / "cover.png"
    folder_name = song_folder_name(song_dir)
    try:
        result = cover_art.render(
            job, str(metadata.get("title") or "Untitled Song"),
            str(metadata.get("description") or ""), str(metadata.get("lyrics") or ""), pending,
            direction=str(request.get("direction") or ""), progress_base=0.05, progress_span=0.94,
        )
        if job.cancel.is_set(): raise RuntimeError("cancelled")
        pending.replace(final)
        metadata["cover"] = final.name
        metadata["cover_error"] = None
        metadata["cover_seed"] = result.get("seed")
        metadata["cover_direction"] = str(request.get("direction") or "")
        manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Regenerated cover art: %s", final)
        return {"folder": folder_name, "cover_url": f"/api/library/{quote(folder_name, safe='')}/cover.png?v={final.stat().st_mtime_ns}", "seed": result.get("seed")}
    finally:
        pending.unlink(missing_ok=True)


@app.post("/api/library/{folder:path}/cover")
def start_cover_regeneration(folder: str, request: CoverArtRequest):
    resolve_song_folder(folder)
    if not cover_art.available():
        raise HTTPException(409, cover_art.status()["detail"])
    job = manager.submit("cover_art", {"folder": folder, "direction": request.direction.strip()}, regenerate_cover)
    return {"job": job.snapshot()}


@app.post("/api/library/{folder:path}/cover/upload")
async def upload_song_cover(folder: str, filename: str, request: Request):
    song_dir = resolve_song_folder(folder)
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(415, "Choose a PNG, JPG, JPEG, or WebP image")
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise HTTPException(409, "FFmpeg is not installed")
    temporary = song_dir / f"cover-upload-{time.time_ns()}{suffix}"
    prepared = song_dir / f"cover-prepared-{time.time_ns()}.png"
    target = song_dir / "cover.png"
    total = 0
    try:
        with temporary.open("wb") as handle:
            async for chunk in request.stream():
                total += len(chunk)
                if total > 20 * 1024 * 1024:
                    raise HTTPException(413, "Cover images are limited to 20 MB")
                handle.write(chunk)
        if total == 0:
            raise HTTPException(400, "The selected image is empty")
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(temporary), "-vf", "scale=1024:1024:force_original_aspect_ratio=decrease,pad=1024:1024:(ow-iw)/2:(oh-ih)/2:black", "-frames:v", "1", str(prepared)]
        result = subprocess.run(command, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0 or not prepared.is_file():
            raise HTTPException(409, result.stderr.strip() or "Could not prepare that cover image")
        os.replace(prepared, target)
        manifest = song_dir / "song.json"
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        metadata["cover"] = target.name
        metadata["cover_error"] = None
        manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        temporary.unlink(missing_ok=True)
        prepared.unlink(missing_ok=True)
    folder_name = song_folder_name(song_dir)
    return {"uploaded": True, "cover_url": f"/api/library/{quote(folder_name, safe='')}/cover.png?v={target.stat().st_mtime_ns}"}


def export_audio(song_dir: Path, fmt: str) -> dict:
    source = song_audio_file(song_dir)
    if not source.is_file(): raise RuntimeError("The source WAV file is missing")
    ffmpeg = ffmpeg_path()
    if not ffmpeg: raise RuntimeError("FFmpeg is not installed")
    target = song_dir / f"song.{fmt}"
    try:
        metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    created_at = str(metadata.get("created_at") or "")
    saved_year = str(metadata.get("year") or "").strip()
    inferred_year = created_at[:4] if created_at[:4].isdigit() else ""
    tags = {
        "title": str(metadata.get("title") or song_dir.name),
        "artist": str(metadata.get("artist") or ""),
        "album": str(metadata.get("album") or ""),
        "genre": str(metadata.get("genre") or ""),
        "date": saved_year or inferred_year,
        "track": str(metadata.get("track_number") or ""),
        "comment": str(metadata.get("description") or "Generated locally with YuE2 Studio"),
    }
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    cover_name = str(metadata.get("cover") or "cover.png")
    cover = song_dir / cover_name
    has_cover = cover.is_file()
    if has_cover:
        command += ["-i", str(cover), "-map", "0:a:0", "-map", "1:v:0"]
    else:
        command += ["-map", "0:a:0"]
    command += ["-map_metadata", "-1"]
    for key, value in tags.items():
        if value.strip():
            command += ["-metadata", f"{key}={value.strip()}"]
    if fmt == "mp3":
        command += ["-codec:a", "libmp3lame", "-q:a", "0", "-id3v2_version", "3"]
        if has_cover:
            command += ["-codec:v", "mjpeg", "-disposition:v:0", "attached_pic", "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        command += ["-codec:a", "flac", "-compression_level", "8"]
        if has_cover:
            command += ["-codec:v", "copy", "-disposition:v:0", "attached_pic"]
    command.append(str(target))
    result = subprocess.run(command, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode != 0 or not target.is_file(): raise RuntimeError(result.stderr.strip() or f"Could not create {fmt.upper()}")
    folder_name = song_folder_name(song_dir)
    return {"download_url": f"/api/library/{quote(folder_name, safe='')}/{quote(target.name, safe='')}", "filename": download_filename(song_dir, target.suffix)}


@app.post("/api/library/{folder:path}/export/{fmt}")
def convert_audio(folder: str, fmt: str):
    if fmt not in {"mp3", "flac"}: raise HTTPException(422, "Format must be MP3 or FLAC")
    try: return export_audio(resolve_song_folder(folder), fmt)
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc


def extract_stems(job: Job) -> dict:
    song_dir = resolve_song_folder(job.params["folder"]); source = song_audio_file(song_dir); output_root = song_dir / "stems"
    if not source.is_file(): raise RuntimeError("The source WAV file is missing")
    command = [str(yue2_engine.WORKER_PYTHON), str(Path(__file__).with_name("demucs_runner.py")), "-n", "htdemucs", "--repo", str(STEMS_ROOT), "-d", "cuda", "--segment", "7", "--overlap", "0.1", "--shifts", "1"]
    if job.params["mode"] == "2": command += ["--two-stems", "vocals"]
    command += ["-o", str(output_root), "--filename", "{stem}.{ext}", str(source)]
    environment = os.environ.copy()
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert process.stdout is not None
    job.phase, job.progress = "Separating stems on GPU", 0.08; job.emit(); started = time.monotonic()
    tail: list[str] = []
    for raw in process.stdout:
        line = raw.strip()
        if line:
            log.info("[stems] %s", line)
            tail.append(line)
            tail = tail[-8:]
        match = re.search(r"STEM_PROGRESS\s+(\d{1,3})", line)
        if match:
            fraction = min(1.0, int(match.group(1)) / 100); job.progress = 0.08 + 0.88 * fraction; job.stage_progress = fraction
            elapsed = max(0.1, time.monotonic() - started); job.eta_seconds = elapsed * (1 - fraction) / fraction if fraction else None; job.emit()
        if job.cancel.is_set(): process.kill(); process.wait(timeout=10); raise RuntimeError("cancelled")
    code = process.wait(); target_dir = output_root / "htdemucs"; files = sorted(target_dir.glob("*.wav"))
    if code != 0 or not files:
        detail = next((item for item in reversed(tail) if item and "STEM_PROGRESS" not in item), "")
        raise RuntimeError(detail or f"Stem extraction exited with code {code}")
    manifest_path = song_dir / "song.json"; metadata = json.loads(manifest_path.read_text(encoding="utf-8")); metadata["stems"] = [path.name for path in files]; manifest_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    folder_name = song_folder_name(song_dir)
    return {"folder": folder_name, "files": [{"name": path.name, "url": f"/api/library/{quote(folder_name, safe='')}/stems/{quote(path.name, safe='')}"} for path in files]}


@app.post("/api/library/{folder:path}/stems")
def start_stem_extraction(folder: str, request: StemRequest):
    resolve_song_folder(folder); state = stems_status()
    if not state["ready"]: raise HTTPException(409, state["detail"])
    job = manager.submit("stems", {"folder": folder, "mode": request.mode}, extract_stems)
    return {"job": job.snapshot()}


def _studio_manifest(song_dir: Path) -> tuple[Path, dict]:
    manifest = song_dir / "song.json"
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(404, "Song details not found") from exc
    return manifest, metadata


@app.post("/api/library/{folder:path}/studio/import")
async def import_studio_track(folder: str, filename: str, request: Request):
    song_dir = resolve_song_folder(folder); manifest, metadata = _studio_manifest(song_dir)
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}:
        raise HTTPException(415, "Choose a WAV, MP3, FLAC, M4A, AAC, or OGG audio file")
    ffmpeg = ffmpeg_path()
    if not ffmpeg: raise HTTPException(409, "FFmpeg is not installed")
    imports_dir = song_dir / "studio" / "imports"; tracks_dir = song_dir / "studio" / "tracks"
    imports_dir.mkdir(parents=True, exist_ok=True); tracks_dir.mkdir(parents=True, exist_ok=True)
    base_name = slug(Path(filename).stem)[:48] or "audio"
    stamp = f"{int(time.time() * 1000)}"
    original = imports_dir / f"{stamp}_{base_name}{suffix}"
    total = 0
    target: Path | None = None
    try:
        with original.open("wb") as handle:
            async for chunk in request.stream():
                total += len(chunk)
                if total > 512 * 1024 * 1024:
                    raise HTTPException(413, "Audio imports are limited to 512 MB")
                handle.write(chunk)
        if total == 0: raise HTTPException(400, "The selected audio file is empty")
        target = tracks_dir / f"{stamp}_{base_name}.wav"
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(original), "-vn", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(target)]
        result = subprocess.run(command, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0 or not target.is_file():
            raise HTTPException(409, result.stderr.strip() or "Could not prepare the imported audio")
    except Exception:
        if original.is_file(): original.unlink(missing_ok=True)
        if target is not None and target.is_file(): target.unlink(missing_ok=True)
        raise
    assert target is not None
    entry = {"file": target.name, "name": Path(filename).stem[:80], "original": original.name}
    metadata.setdefault("studio_imports", []).append(entry)
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    folder_name = song_folder_name(song_dir)
    return {**entry, "url": f"/api/library/{quote(folder_name, safe='')}/studio/tracks/{quote(target.name, safe='')}"}


@app.post("/api/library/{folder:path}/studio/generate-sfx")
def generate_studio_sound(folder: str, request: SoundEffectRequest):
    song_dir = resolve_song_folder(folder)
    current = stable_sfx.woosh_status() if request.engine == "woosh" else stable_sfx.status()
    if not current["ready"]:
        raise HTTPException(409, current["detail"])
    params = request.model_dump()
    if params["engine"] == "woosh":
        params["duration"] = min(5.0, params["duration"])
    if params["seed"] is None:
        params["seed"] = int.from_bytes(os.urandom(4), "big") & 0x7FFFFFFF
    job = manager.submit("stable_sfx", params, lambda active: stable_sfx.generate(active, song_dir))
    return {"job": job.snapshot()}


@app.get("/api/effects")
def effect_library():
    return {"items": stable_sfx.list_effects()}


@app.post("/api/effects/generate")
def generate_effect(request: SoundEffectRequest):
    current = stable_sfx.woosh_status() if request.engine == "woosh" else stable_sfx.status()
    if not current["ready"]:
        raise HTTPException(409, current["detail"])
    params = request.model_dump()
    if params["engine"] == "woosh":
        params["duration"] = min(5.0, params["duration"])
    if params["seed"] is None:
        params["seed"] = int.from_bytes(os.urandom(4), "big") & 0x7FFFFFFF
    job = manager.submit("stable_sfx", params, lambda active: stable_sfx.generate(active))
    return {"job": job.snapshot()}


@app.post("/api/effects/import")
async def import_effect(filename: str, request: Request, name: str = ""):
    """Accept raw local audio bytes and add the converted sound to Effects."""
    suffix = Path(filename).suffix.casefold()
    if suffix not in stable_sfx.IMPORTABLE_AUDIO_SUFFIXES:
        raise HTTPException(415, "Choose a WAV, MP3, FLAC, M4A, AAC, OGG, Opus, or WebM audio file")
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise HTTPException(409, "FFmpeg is not installed")

    stable_sfx.EFFECTS_ROOT.mkdir(parents=True, exist_ok=True)
    upload = stable_sfx.EFFECTS_ROOT / f".upload-{uuid.uuid4().hex}{suffix}"
    total = 0
    try:
        with upload.open("wb") as handle:
            async for chunk in request.stream():
                total += len(chunk)
                if total > stable_sfx.MAX_EFFECT_UPLOAD_BYTES:
                    raise HTTPException(413, "Audio imports are limited to 512 MB")
                handle.write(chunk)
        if total == 0:
            raise HTTPException(400, "The selected audio file is empty")
        item = await run_in_threadpool(stable_sfx.import_local_effect, upload, filename, name, ffmpeg)
        return item
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error
    finally:
        # Successful import moves this file into its published effect folder.
        # Every failure path removes the raw upload before responding.
        if upload.is_file():
            upload.unlink(missing_ok=True)


@app.get("/api/effects/{effect_id}/audio")
def effect_audio(effect_id: str):
    try:
        audio, _ = stable_sfx.get_effect(effect_id)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        raise HTTPException(404, "Sound effect not found")
    return FileResponse(audio, media_type="audio/wav", filename=f"{effect_id}.wav")


@app.post("/api/effects/{effect_id}/add-to-studio/{folder:path}")
def add_effect_to_studio(effect_id: str, folder: str):
    song_dir = resolve_song_folder(folder)
    try:
        entry = stable_sfx.add_to_song(effect_id, song_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        raise HTTPException(404, "Sound effect not found")
    folder_name = song_folder_name(song_dir)
    entry["url"] = f"/api/library/{quote(folder_name, safe='')}/studio/tracks/{quote(entry['file'], safe='')}"
    # Effects-page additions join the shared Effects lane immediately.  The
    # Studio can still move this sound to another effects lane afterwards.
    manifest, metadata = _studio_manifest(song_dir)
    duration = max(0.001, float(entry.get("duration") or 0.001))
    state = StudioTrackState(
        name=entry["file"], lane="Effects", gain=1.0, muted=False, solo=False,
        use_clips=True,
        clips=[StudioClip(id=uuid.uuid4().hex, start=0.0, source_in=0.0, source_out=duration)],
    )
    studio = metadata.get("studio") if isinstance(metadata.get("studio"), dict) else {}
    tracks = studio.get("tracks") if isinstance(studio.get("tracks"), list) else []
    studio["tracks"] = [*tracks, state.model_dump()]
    studio["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    metadata["studio"] = studio
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry


@app.delete("/api/effects/{effect_id}")
def remove_effect(effect_id: str):
    try:
        stable_sfx.delete_effect(effect_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Sound effect not found")
    return {"deleted": True}


def resolve_studio_clips(track: StudioTrackState) -> list[StudioClip]:
    """Return movable timeline clips, migrating the older one-block session when needed."""
    if track.use_clips:
        return [clip for clip in track.clips if clip.source_out is None or clip.source_out > clip.source_in]
    if track.clips:
        return list(track.clips)
    offset = max(0.0, track.offset)
    start = max(offset, track.trim_start)
    source_in = max(0.0, start - offset)
    source_out = None if track.trim_end is None else max(source_in + 0.001, track.trim_end - offset)
    pieces = [StudioClip(id="legacy-0", start=start, source_in=source_in, source_out=source_out, fade_in=track.fade_in, fade_out=track.fade_out)]
    for cut in track.cuts:
        split: list[StudioClip] = []
        for piece in pieces:
            unknown = piece.source_out is None
            piece_len = 1e9 if unknown else max(0.0, piece.source_out - piece.source_in)
            piece_end = piece.start + piece_len
            if cut.end <= piece.start or cut.start >= piece_end:
                split.append(piece)
                continue
            if cut.start > piece.start + 0.02:
                left_out = piece.source_in + (cut.start - piece.start)
                split.append(piece.model_copy(update={"source_out": left_out, "fade_out": 0.0}))
            if not unknown and cut.end < piece_end - 0.02:
                right_in = piece.source_in + (cut.end - piece.start)
                split.append(StudioClip(id=f"{piece.id}-r", start=cut.end, source_in=right_in, source_out=piece.source_out, fade_in=0.0, fade_out=piece.fade_out))
        pieces = split
    return pieces


def _studio_clip_chain(index: int, track: StudioTrackState, clips: list[StudioClip], filters: list[str]) -> str:
    """Place each clip on the timeline, then mix overlapping pieces from the same source."""
    labels: list[str] = []
    for clip_index, clip in enumerate(clips):
        parts: list[str] = ["aformat=channel_layouts=stereo"]
        if clip.source_in > 0 or clip.source_out is not None:
            trim = f"atrim=start={clip.source_in:.5f}"
            if clip.source_out is not None:
                trim += f":end={clip.source_out:.5f}"
            parts.append(trim)
            parts.append("asetpts=PTS-STARTPTS")
        clip_gain = max(0.0, min(4.0, track.gain * clip.gain))
        parts.append(f"volume={clip_gain:.5f}")
        left = max(0.0, min(4.0, clip.gain_left))
        right = max(0.0, min(4.0, clip.gain_right))
        if abs(left - 1.0) > 0.001 or abs(right - 1.0) > 0.001:
            parts.append(f"pan=stereo|c0={left:.5f}*c0|c1={right:.5f}*c1")
        clip_len = None if clip.source_out is None else max(0.0, clip.source_out - clip.source_in)
        if clip.fade_in > 0:
            parts.append(f"afade=t=in:st=0:d={clip.fade_in:.5f}:curve=qsin")
        if clip.fade_out > 0 and clip_len is not None:
            parts.append(f"afade=t=out:st={max(0.0, clip_len - clip.fade_out):.5f}:d={clip.fade_out:.5f}:curve=qsin")
        if clip.start > 0:
            parts.append(f"adelay={round(clip.start * 1000)}:all=1")
        label = f"clip{index}_{clip_index}"
        filters.append(f"[{index}:a]{','.join(parts)}[{label}]")
        labels.append(label)
    raw = f"rawlane{index}"
    if len(labels) == 1:
        filters.append(f"[{labels[0]}]anull[{raw}]")
    else:
        joined = "".join(f"[{label}]" for label in labels)
        filters.append(f"{joined}amix=inputs={len(labels)}:duration=longest:normalize=0[{raw}]")
    return raw


def _studio_sources(song_dir: Path, metadata: dict, request: StudioBounceRequest) -> list[tuple[Path, StudioTrackState]]:
    available = {str(name): song_dir / "stems" / "htdemucs" / str(name) for name in metadata.get("stems") or []}
    original_mix = song_dir / str(metadata.get("audio") or "song.wav")
    if original_mix.is_file(): available["song.wav"] = original_mix
    imported_names: set[str] = set()
    for item in metadata.get("studio_imports") or []:
        if isinstance(item, dict) and Path(str(item.get("file") or "")).name == str(item.get("file") or ""):
            name = str(item["file"]); available[name] = song_dir / "studio" / "tracks" / name; imported_names.add(name)
    tracks = [track for track in request.tracks if track.name in available]
    if metadata.get("stems"):
        tracks = [track for track in tracks if track.name != "song.wav"]
    if request.variant == "instrumental":
        tracks = [track for track in tracks if track.name not in {"vocals.wav", "song.wav"} and track.name not in imported_names]
    elif request.variant == "acapella":
        tracks = [track for track in tracks if track.name == "vocals.wav"]
    else:
        soloed = [track for track in tracks if track.solo and not track.muted]
        tracks = soloed or [track for track in tracks if not track.muted]
    sources = [(available[track.name], track) for track in tracks if available[track.name].is_file()]
    if not sources:
        raise HTTPException(409, "No audible stem lanes are available for this export")
    return sources


# Default ease at an effect edge. Must match SongStudio.tsx for older sessions
# that do not yet store their own fade values.
EFFECT_FADE_SECONDS = 0.18
MIN_EFFECT_FADE = 0.005


def _effect_envelope(start: float, end: float, fade_in: float, fade_out: float) -> str:
    """A selectable 0..1 envelope between `start` and `end`.

    The gate keeps the effect inside the selected region. Optional independent
    ramps let the user smooth either edge or deliberately choose a hard edge.
    """
    span = max(0.01, end - start)
    parts = [f"between(t,{start:.5f},{end:.5f})"]
    fade_in = min(span, max(0.0, fade_in))
    fade_out = min(span, max(0.0, fade_out))
    if fade_in >= MIN_EFFECT_FADE:
        parts.append(f"clip((t-{start:.5f})/{fade_in:.5f},0,1)")
    if fade_out >= MIN_EFFECT_FADE:
        parts.append(f"clip(({end:.5f}-t)/{fade_out:.5f},0,1)")
    return "*".join(parts)


def _studio_effect_filters(filters: list[str], input_label: str, lane_index: int, track: StudioTrackState, offset: float) -> str:
    """Build non-destructive region effects and return the final FFmpeg label.

    Every effect is applied as a wet/dry crossfade rather than a hard switch, so
    it eases in and out the way the live preview does.
    """
    current = input_label
    for effect_index, effect in enumerate(track.effects):
        start = max(0.0, effect.start - offset); end = max(start + 0.01, effect.end - offset)
        wet_env = _effect_envelope(start, end, effect.fade_in, effect.fade_out)
        out = f"fx{lane_index}_{effect_index}"
        amount = max(0.0, min(1.0, effect.amount))

        if effect.kind in {"gain_up", "gain_down"}:
            # Straight gain needs no split: ramp between unity and the target.
            gain = 1.0 + amount * 3.0 if effect.kind == "gain_up" else 1.0 - amount * .92
            filters.append(f"[{current}]volume='1+({gain:.5f}-1)*{wet_env}':eval=frame[{out}]")
            current = out
            continue

        # Everything else is a real processor, so crossfade a processed copy
        # against the untouched one. enable= cannot be ramped; this can.
        dry_in = f"fxdryin{lane_index}_{effect_index}"; wet_in = f"fxwetin{lane_index}_{effect_index}"
        dry = f"fxdry{lane_index}_{effect_index}"; wet = f"fxwet{lane_index}_{effect_index}"
        if effect.kind == "clarity":
            low = 1.0 + amount * 6.0; presence = 3.0 + amount * 7.0; air = 1.5 + amount * 6.0
            processor = (f"bass=g={low:.3f}:f=140,equalizer=f=2600:t=q:w=1.1:g={presence:.3f},"
                         f"treble=g={air:.3f}:f=6500")
        elif effect.kind == "auto_level":
            processor = f"dynaudnorm=f=150:g={8.0 + amount * 17.0:.3f}:p=0.95:m=10"
        elif effect.kind == "echo":
            decay = f"{0.32 + amount * .4:.3f}|{0.16 + amount * .28:.3f}"
            processor = f"aecho=0.8:{0.28 + amount * .45:.3f}:280|560:{decay}"
        elif effect.kind == "reverb":
            decay = (f"{0.32 + amount * .28:.3f}|{0.24 + amount * .22:.3f}|"
                     f"{0.18 + amount * .18:.3f}|{0.12 + amount * .14:.3f}")
            processor = f"aecho=0.8:{0.22 + amount * .4:.3f}:32|54|82|118:{decay}"
        elif effect.kind == "normalize":
            processor = "loudnorm=I=-16:TP=-1.5:LRA=11"
        elif effect.kind == "compressor":
            ratio = 2.0 + amount * 6.0; threshold = 0.25 - amount * .15
            processor = (f"acompressor=threshold={threshold:.3f}:ratio={ratio:.3f}:"
                         f"attack=15:release=180:makeup={1.0 + amount * .8:.3f}")
        elif effect.kind == "auto_pan":
            processor = f"apulsator=mode=sine:amount={amount:.3f}:hz=0.75"
        elif effect.kind == "low_pass":
            cutoff = 18000.0 * (0.09 ** amount)
            processor = f"lowpass=f={cutoff:.2f}"
        elif effect.kind == "high_pass":
            cutoff = 20.0 * (50.0 ** amount)
            processor = f"highpass=f={cutoff:.2f}"
        elif effect.kind == "telephone":
            low_cut = 20.0 + amount * 330.0; high_cut = 18000.0 - amount * 14600.0
            processor = (f"highpass=f={low_cut:.2f},lowpass=f={high_cut:.2f},"
                         f"equalizer=f=1800:t=q:w=1.2:g={amount * 7.0:.3f},"
                         f"asoftclip=type=tanh:threshold={1.0 - amount * .45:.3f}:oversample=2")
        elif effect.kind == "saturation":
            processor = f"asoftclip=type=tanh:threshold={1.0 - amount * .78:.3f}:output=0.92:oversample=2"
        elif effect.kind == "tremolo":
            processor = f"tremolo=f=4:d={amount:.3f}"
        elif effect.kind == "stereo_widen":
            processor = f"extrastereo=m={1.0 + amount:.3f}:c=1"
        elif effect.kind == "limiter":
            processor = f"alimiter=limit={0.98 - amount * .25:.3f}:attack=5:release=60:level=0"
        else:
            continue

        filters.append(f"[{current}]asplit=2[{dry_in}][{wet_in}]")
        filters.append(f"[{dry_in}]volume='1-{wet_env}':eval=frame[{dry}]")
        filters.append(f"[{wet_in}]{processor},volume='{wet_env}':eval=frame[{wet}]")
        filters.append(f"[{dry}][{wet}]amix=inputs=2:duration=longest:normalize=0[{out}]")
        current = out
    return current


def _render_studio_audio(ffmpeg: str, sources: list, request: StudioBounceRequest, target: Path):
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for source, _track in sources: command += ["-i", str(source)]
    filters = []
    for index, (_source, track) in enumerate(sources):
        clips = resolve_studio_clips(track)
        if track.use_clips or bool(track.clips):
            if not clips:
                filters.append(f"[{index}:a]volume=0,atrim=end=0.05[{f'rawlane{index}'}]")
                raw_label = f"rawlane{index}"
                offset = 0.0
            else:
                raw_label = _studio_clip_chain(index, track, clips, filters)
                offset = 0.0
        else:
            offset = max(0.0, track.offset)
            trim_start = max(0.0, track.trim_start - offset)
            trim_end = max(trim_start, track.trim_end - offset) if track.trim_end is not None else None
            chain = ["aformat=channel_layouts=stereo", f"volume={track.gain:.5f}"]
            if trim_start > 0: chain.append(f"volume=0:enable='lt(t,{trim_start:.5f})'")
            if trim_end is not None: chain.append(f"volume=0:enable='gt(t,{trim_end:.5f})'")
            for cut in track.cuts:
                start = max(0.0, cut.start - offset); end = max(start, cut.end - offset)
                chain.append(f"volume=0:enable='between(t,{start:.5f},{end:.5f})'")
            if track.fade_in > 0: chain.append(f"afade=t=in:st={trim_start:.5f}:d={track.fade_in:.5f}")
            if track.fade_out > 0 and trim_end is not None:
                chain.append(f"afade=t=out:st={max(trim_start, trim_end - track.fade_out):.5f}:d={track.fade_out:.5f}")
            if offset > 0: chain.append(f"adelay={round(offset * 1000)}:all=1")
            raw_label = f"rawlane{index}"
            filters.append(f"[{index}:a]{','.join(chain)}[{raw_label}]")
        effected = _studio_effect_filters(filters, raw_label, index, track, offset)
        if effected != f"lane{index}": filters.append(f"[{effected}]anull[lane{index}]")
    inputs = "".join(f"[lane{index}]" for index in range(len(sources)))
    if len(sources) == 1:
        filters.append(f"{inputs}alimiter=limit=0.98[out]")
    else:
        filters.append(f"{inputs}amix=inputs={len(sources)}:duration=longest:normalize=0,alimiter=limit=0.98[out]")
    if request.selection is not None:
        filters.append(f"[out]atrim=start={request.selection.start:.5f}:end={request.selection.end:.5f},asetpts=PTS-STARTPTS[selected]")
        output_label = "[selected]"
    elif request.content_end:
        filters.append(f"[out]atrim=end={request.content_end:.5f},asetpts=PTS-STARTPTS[bounded]")
        output_label = "[bounded]"
    else:
        output_label = "[out]"
    command += ["-filter_complex", ";".join(filters), "-map", output_label, "-c:a", "pcm_s16le", str(target)]
    result = subprocess.run(command, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode != 0 or not target.is_file():
        raise HTTPException(409, result.stderr.strip() or "Could not build the studio mix")


@app.post("/api/library/{folder:path}/studio/bounce")
def bounce_studio_mix(folder: str, request: StudioBounceRequest):
    song_dir = resolve_song_folder(folder); manifest, metadata = _studio_manifest(song_dir)
    ffmpeg = ffmpeg_path()
    if not ffmpeg: raise HTTPException(409, "FFmpeg is not installed")
    sources = _studio_sources(song_dir, metadata, request)
    mix_dir = song_dir / "mixes"; mix_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = mix_dir / f"{request.variant}_mix_{stamp}.wav"
    _render_studio_audio(ffmpeg, sources, request, target)
    entry = {"file": target.name, "variant": request.variant, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    payload = {
        "download_url": f"/api/library/{quote(song_folder_name(song_dir), safe='')}/studio/mixes/{quote(target.name, safe='')}",
        "filename": f"{download_filename(song_dir, '')}-{request.variant}.wav",
        "promoted": False,
    }
    if request.variant == "custom" and request.selection is None:
        # A full bounce becomes its own library entry. The take you were editing
        # stays exactly as it was.
        exported = _export_custom_mix_as_song(song_dir, metadata, target)
        entry["exported_to"] = exported["folder_name"]
        payload["exported"] = True
        payload["exported_folder"] = exported["folder_name"]
        payload["exported_title"] = exported["title"]
        payload["audio_url"] = exported["audio_url"]
    metadata.setdefault("studio_mixes", []).append(entry)
    metadata["studio"] = {"tracks": [track.model_dump() for track in request.tracks], "updated_at": entry["created_at"]}
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


@app.post("/api/library/{folder:path}/studio/combine")
def combine_studio_tracks(folder: str, request: StudioCombineRequest):
    song_dir = resolve_song_folder(folder)
    manifest, metadata = _studio_manifest(song_dir)
    chosen = set(request.files)
    imports = metadata.get("studio_imports") or []
    originals = [item for item in imports if item["file"] in chosen]
    states = [track for track in request.tracks if track.name in chosen]
    if len(chosen) != len(request.files) or len(originals) != len(chosen) or len(states) != len(chosen):
        raise HTTPException(422, "Choose at least two different imported sound tracks")
    if any(track.muted for track in states):
        raise HTTPException(422, "Unmute the selected sound tracks before combining")
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise HTTPException(409, "FFmpeg is not installed")
    # Solo is a monitoring control: combine every explicitly selected lane.
    render_states = [track.model_copy(update={"solo": False}) for track in states]
    bounce = StudioBounceRequest(tracks=render_states)
    sources = _studio_sources(song_dir, metadata, bounce)
    if len(sources) != len(chosen):
        raise HTTPException(409, "A selected sound file is missing")
    filename = f"combined-{uuid.uuid4().hex}.wav"
    target = song_dir / "studio" / "tracks" / filename
    try:
        _render_studio_audio(ffmpeg, sources, bounce, target)
        duration = yue2_engine.inspect_wav(target)["duration"]
    except Exception:
        target.unlink(missing_ok=True)
        raise
    entry = {"file": filename, "name": request.name.strip() or "Combined sounds", "duration": duration,
             "combined_sources": originals, "combined_states": [track.model_dump() for track in states]}
    shared_lane = states[0].lane if all(track.lane == states[0].lane for track in states) else None
    lane = StudioTrackState(name=filename, lane=shared_lane, use_clips=True, clips=[StudioClip(id=uuid.uuid4().hex, source_out=duration)])
    updated = [track.model_dump() for track in request.tracks if track.name not in chosen] + [lane.model_dump()]
    metadata["studio_imports"] = [item for item in imports if item["file"] not in chosen] + [entry]
    metadata["studio"] = {"tracks": updated, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"imports": [entry], "tracks": updated, "removed": list(chosen)}


@app.post("/api/library/{folder:path}/studio/uncombine/{filename}")
def uncombine_studio_tracks(folder: str, filename: str, request: StudioSessionRequest):
    song_dir = resolve_song_folder(folder)
    manifest, metadata = _studio_manifest(song_dir)
    imports = metadata.get("studio_imports") or []
    entry = next((item for item in imports if item["file"] == filename), None)
    if not entry or not entry.get("combined_sources"):
        raise HTTPException(404, "Combined track not found")
    originals = entry["combined_sources"]
    for item in originals:
        if not (song_dir / "studio" / "tracks" / item["file"]).is_file():
            raise HTTPException(409, "An original sound file is missing")
    updated = [track.model_dump() for track in request.tracks if track.name != filename] + entry["combined_states"]
    metadata["studio_imports"] = [item for item in imports if item["file"] != filename] + originals
    metadata["studio"] = {"tracks": updated, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"imports": originals, "tracks": updated, "removed": [filename]}


@app.get("/api/library/{folder:path}/studio/original-mix")
def studio_original_mix(folder: str):
    song_dir = resolve_song_folder(folder)
    target = original_mix_backup_path(song_dir).resolve()
    root = (song_dir / "studio").resolve()
    if target.parent != root or not target.is_file():
        raise HTTPException(404, "Original mix backup not found")
    return FileResponse(target, media_type="audio/wav", filename="original_mix.wav")


@app.get("/api/library/{folder:path}/studio/mixes/{filename}")
def studio_mix_file(folder: str, filename: str):
    song_dir = resolve_song_folder(folder)
    if Path(filename).name != filename: raise HTTPException(404, "Studio mix not found")
    root = (song_dir / "mixes").resolve(); target = (root / filename).resolve()
    if target.parent != root or not target.is_file(): raise HTTPException(404, "Studio mix not found")
    return FileResponse(target, media_type="audio/wav", filename=filename)


@app.get("/api/library/{folder:path}/studio/tracks/{filename}")
def studio_track_file(folder: str, filename: str):
    song_dir = resolve_song_folder(folder)
    if Path(filename).name != filename: raise HTTPException(404, "Studio track not found")
    root = (song_dir / "studio" / "tracks").resolve(); target = (root / filename).resolve()
    if target.parent != root or not target.is_file(): raise HTTPException(404, "Studio track not found")
    return FileResponse(target, media_type="audio/wav", filename=filename)


@app.delete("/api/library/{folder:path}/studio/tracks/{filename}")
def remove_studio_track(folder: str, filename: str):
    song_dir = resolve_song_folder(folder); manifest, metadata = _studio_manifest(song_dir)
    if Path(filename).name != filename: raise HTTPException(404, "Studio track not found")
    imports = metadata.get("studio_imports") or []
    entry = next((item for item in imports if isinstance(item, dict) and item.get("file") == filename), None)
    if entry is None: raise HTTPException(404, "Studio track not found")
    (song_dir / "studio" / "tracks" / filename).unlink(missing_ok=True)
    original = str(entry.get("original") or "")
    if original and Path(original).name == original: (song_dir / "studio" / "imports" / original).unlink(missing_ok=True)
    metadata["studio_imports"] = [item for item in imports if item is not entry]
    if isinstance(metadata.get("studio"), dict):
        metadata["studio"]["tracks"] = [track for track in metadata["studio"].get("tracks", []) if track.get("name") != filename]
    manifest.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"removed": True}


def synchronize_song_lyrics(job: Job) -> dict:
    song_dir = resolve_song_folder(str(job.params["folder"]))
    try:
        metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Song details could not be read") from exc
    return lyrics_sync.run(job, song_dir, metadata)


@app.post("/api/library/{folder:path}/lyrics-sync")
def start_lyrics_synchronization(folder: str):
    song_dir = resolve_song_folder(folder)
    try:
        metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(404, "Song details not found") from exc
    if metadata.get("instrumental") or not str(metadata.get("lyrics") or "").strip():
        raise HTTPException(409, "This song does not have lyrics to synchronize")
    state = lyrics_sync.status()
    if not state["ready"]:
        raise HTTPException(409, state["detail"])
    job = manager.submit("lyrics_sync", {"folder": folder}, synchronize_song_lyrics)
    return {"job": job.snapshot()}


def transcribe_cover_score(job: Job) -> dict:
    song_dir = resolve_song_folder(str(job.params["folder"]))
    melody_only = bool(job.params.get("melody_only", True))
    if job.params.get("reuse_cached"):
        cached = sheetsage.load_score(song_dir, melody_only)
        if cached:
            job.phase, job.progress = "Using saved lead sheet", 1.0
            job.emit()
            return {
                "folder": song_folder_name(song_dir),
                "abc": cached,
                "melody_only": melody_only,
                "warnings": [],
                "cached": True,
                "path": str(sheetsage.score_path(song_dir, melody_only)),
            }
    yue2_engine.unload()
    return sheetsage.run(job, song_dir, song_audio_file(song_dir), melody_only)


@app.get("/api/library/{folder:path}/score")
def song_planned_score(folder: str):
    song_dir = resolve_song_folder(folder)
    try:
        metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    abc = read_song_abc(song_dir, metadata)
    return {"abc": abc, "has_score": bool(abc)}


@app.post("/api/library/{folder:path}/cover-transcribe")
def start_cover_transcription(folder: str, request: CoverTranscribeRequest):
    state = sheetsage.status()
    if not state["ready"]:
        raise HTTPException(409, state["detail"])
    resolve_song_folder(folder)
    job = manager.submit(
        "sheetsage",
        {"folder": folder, "melody_only": request.melody_only, "reuse_cached": request.reuse_cached},
        transcribe_cover_score,
    )
    return {"job": job.snapshot()}


@app.get("/api/library/{folder:path}/stems/{filename}")
def stem_file(folder: str, filename: str):
    song_dir = resolve_song_folder(folder)
    if Path(filename).name != filename: raise HTTPException(404, "Stem not found")
    root = (song_dir / "stems" / "htdemucs").resolve(); target = (root / filename).resolve()
    if target.parent != root or not target.is_file(): raise HTTPException(404, "Stem not found")
    return FileResponse(target, media_type="audio/wav", filename=f"{slug(song_dir.name)}-{target.name}")


def _reveal_in_explorer(path: Path) -> Path:
    """Open Explorer on the file's folder, with the file selected when it exists."""
    path = path.resolve()
    if path.is_file():
        subprocess.Popen(["explorer", "/select,", str(path)], creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return path.parent
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(path)
    return path


@app.post("/api/library/{folder:path}/open")
def open_song_folder(folder: str):
    song_dir = resolve_song_folder(folder)
    try:
        metadata = json.loads((song_dir / "song.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    audio = align_audio_to_title(song_dir, metadata, str(metadata.get("title") or "song"))
    if metadata.get("audio") == audio.name:
        try:
            (song_dir / "song.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    opened = _reveal_in_explorer(audio if audio.is_file() else song_dir)
    return {"path": str(opened)}


@app.delete("/api/library/{folder:path}")
def delete_song(folder: str):
    target = resolve_song_folder(folder)
    title = target.name
    try:
        deleted_song_id = str(json.loads((target / "song.json").read_text(encoding="utf-8")).get("id") or "")
    except (OSError, json.JSONDecodeError):
        deleted_song_id = ""
    last_error: OSError | None = None
    for attempt in range(8):
        try:
            shutil.rmtree(target)
            last_error = None
            break
        except FileNotFoundError:
            last_error = None
            break
        except OSError as error:
            last_error = error
            if attempt < 7:
                time.sleep(0.15 * (attempt + 1))
    if last_error is not None:
        log.warning("Could not delete YuE2 song %s because a file is still open: %s", title, last_error)
        raise HTTPException(409, "The song is still open. Stop playback, close Studio, and try again.") from last_error
    if deleted_song_id:
        playlists = load_playlists()
        changed = False
        for playlist in playlists:
            filtered = [song_id for song_id in playlist["song_ids"] if song_id != deleted_song_id]
            changed = changed or len(filtered) != len(playlist["song_ids"])
            playlist["song_ids"] = filtered
        if changed: save_playlists(playlists)
        workspaces = load_workspaces()
        workspace_changed = False
        for workspace in workspaces:
            filtered = [song_id for song_id in workspace["song_ids"] if song_id != deleted_song_id]
            workspace_changed = workspace_changed or len(filtered) != len(workspace["song_ids"])
            workspace["song_ids"] = filtered
        if workspace_changed: save_workspaces(workspaces)
    log.info("Deleted YuE2 song: %s", title)
    return {"deleted": True}

@app.get("/api/library/{folder:path}/{filename}")
def library_file(folder: str, filename: str):
    song_dir = resolve_song_folder(folder)
    target = (song_dir / filename).resolve()
    if (not target.is_file()) and filename == "song.wav":
        alias = song_audio_file(song_dir)
        if alias.is_file():
            target = alias.resolve()
    if target.parent != song_dir.resolve() or not target.is_file(): raise HTTPException(404, "Audio not found")
    media = {".png": "image/png", ".mp3": "audio/mpeg", ".flac": "audio/flac"}.get(target.suffix.lower(), "audio/wav")
    attachment_name = download_filename(song_dir, target.suffix) if target.suffix.lower() in {".wav", ".mp3", ".flac"} else target.name
    response = FileResponse(target, media_type=media, filename=attachment_name)
    if media.startswith("audio/"):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/api/logs")
def logs(limit: int = 500, since_id: int | None = None):
    latest = ring.snapshot(limit=limit)
    reset = bool(since_id is not None and latest and latest[-1]["id"] < since_id)
    items = latest if reset else ring.snapshot(limit=limit, since_id=since_id)
    return {
        "items": items,
        "last_id": items[-1]["id"] if items else (latest[-1]["id"] if latest else -1),
        "reset": reset,
    }

@app.post("/api/logs/clear")
def clear_logs(): ring.clear(); return {"cleared": True}

@app.post("/api/open-outputs")
def open_outputs():
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    opened = _reveal_in_explorer(LIBRARY_ROOT)
    return {"path": str(opened)}


atexit.register(yue2_engine.unload)

if lan_access.DIST_ROOT.is_dir():
    app.mount("/", StaticFiles(directory=str(lan_access.DIST_ROOT), html=True), name="lan-ui")


def serve_lan():
    uvicorn.run(app, host="0.0.0.0", port=LAN_PORT, log_level="warning")


if __name__ == "__main__":
    OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=serve_lan, daemon=True, name="lan-ui").start()
    uvicorn.run(app, host=SIDECAR_HOST, port=SIDECAR_PORT, log_level="info")
