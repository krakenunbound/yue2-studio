"""Reusable prompt voices. Private names stay local; YuE2 only sees traits."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from copy import deepcopy
from typing import Any

from config import OUTPUTS_ROOT

log = logging.getLogger("yue2.voices")
VOICES_PATH = OUTPUTS_ROOT / "settings" / "voice-profiles.json"
_LOCK = threading.RLock()

ROLES = ("female", "male", "backing", "any")
TRAIT_KEYS = (
    "register",
    "timbre",
    "delivery",
    "accent",
    "vibrato",
    "dynamics",
    "harmony",
    "effects",
)
SLOT_KEYS = ("female", "male", "backing")

_VOCAL_HEADING = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?Vocal Details\s*:?\s*$")
_ARRANGEMENT_HEADING = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?Arrangement\s*:?\s*$")

_DEFAULTS: list[dict[str, Any]] = [
    {
        "id": "voice-clear-alto",
        "name": "Clear alto",
        "role": "female",
        "register": "clear natural alto",
        "timbre": "warm chest resonance, conversational diction, a trace of rasp only on emotional sustained notes",
        "delivery": "restrained intimate verses and a memorable open-throated chorus; preserve natural phrasing and audible breath",
        "accent": "",
        "vibrato": "minimal, controlled",
        "dynamics": "close and conversational, then open on the refrain",
        "harmony": "one low harmony and occasional octave support only at the largest refrain",
        "effects": "close-miked, no glossy pop stack",
        "audition_notes": "Default lead for cinematic alt-rock templates.",
        "expanded": "a clear natural alto with warm chest resonance, conversational diction, controlled breath and a trace of rasp only on emotional sustained notes",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-smoky-mezzo",
        "name": "Smoky mezzo",
        "role": "female",
        "register": "low smoky mezzo",
        "timbre": "dry close-mic intimacy, precise consonants, cool self-possessed center",
        "delivery": "nearly whispered low verses, a concise rising pre-chorus, a tuneful chorus",
        "accent": "",
        "vibrato": "restrained",
        "dynamics": "internal rather than belted",
        "harmony": "one soft octave double",
        "effects": "dry and close",
        "audition_notes": "Default lead for dark synth-pop.",
        "expanded": "a low smoky mezzo with dry close-mic intimacy, precise consonants, restrained vibrato and a cool self-possessed center",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-weathered-tenor",
        "name": "Weathered tenor",
        "role": "male",
        "register": "weathered high baritone to tenor",
        "timbre": "intelligible clean tone with controlled false-cord grit and a distinct human break between the two colors",
        "delivery": "tense pitched verses with short grit accents; chorus fully sung and memorable, not shouted",
        "accent": "",
        "vibrato": "controlled",
        "dynamics": "contained menace into a defiant refrain",
        "harmony": "gang support on no more than two climactic words",
        "effects": "dry band mix, no choir",
        "audition_notes": "Default lead for modern metal.",
        "expanded": "a weathered high baritone to tenor with intelligible clean tone, controlled false-cord grit and a distinct human break between the two colors",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-soft-androgynous",
        "name": "Soft midrange",
        "role": "any",
        "register": "androgynous soft midrange",
        "timbre": "intimate lower-register verses, clean open vowels, quietly confident upper register",
        "delivery": "fully melodic with a compact verse contour and a broad memorable chorus",
        "accent": "",
        "vibrato": "light",
        "dynamics": "night-drive intimacy",
        "harmony": "subtle unison doubles and one floating high harmony in the final refrain",
        "effects": "no spoken narration or exaggerated retro affect",
        "audition_notes": "Default lead for synthwave.",
        "expanded": "an androgynous soft midrange voice with intimate lower-register verses, clean open vowels and a quietly confident upper register",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-ground-baritone",
        "name": "Ground baritone",
        "role": "male",
        "register": "deep resonant bass-baritone",
        "timbre": "earthy subharmonic edge, clearly separate from the lead",
        "delivery": "answers selected phrases and supplies low open-vowel drones beneath choruses",
        "accent": "",
        "vibrato": "minimal",
        "dynamics": "ground register, never steals the principal melody",
        "harmony": "low drones and selected answering phrases only",
        "effects": "distinct rather than blended into a choir",
        "audition_notes": "Use in the Male slot under a female lead.",
        "expanded": "a deep resonant bass-baritone with an earthy subharmonic edge who answers selected phrases, supplies low open-vowel drones beneath choruses, and takes only the lyric lines explicitly assigned to him",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-warm-backing",
        "name": "Warm backing stack",
        "role": "backing",
        "register": "small supporting ensemble",
        "timbre": "brief warm responses, tightly phrased around the lead",
        "delivery": "enters only in the refrain or tagged call-and-response lines",
        "accent": "",
        "vibrato": "blended and short",
        "dynamics": "under the lead, never a pop choir",
        "harmony": "high and low support only where the arrangement asks",
        "effects": "no generic choir stack",
        "audition_notes": "Backing slot only.",
        "expanded": "a small group of supporting voices that provide brief warm responses without becoming a pop choir",
        "built_in": True,
        "archived": False,
    },
]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _blank_profile() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "role": "any",
        "register": "",
        "timbre": "",
        "delivery": "",
        "accent": "",
        "vibrato": "",
        "dynamics": "",
        "harmony": "",
        "effects": "",
        "audition_notes": "",
        "expanded": "",
        "built_in": False,
        "archived": False,
        "created_at": "",
        "updated_at": "",
    }


def _normalize_profile(raw: dict[str, Any] | None, *, built_in: bool = False) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    profile = _blank_profile()
    profile.update({key: raw[key] for key in profile if key in raw})
    profile["id"] = str(profile.get("id") or "").strip() or f"voice-{uuid.uuid4().hex[:10]}"
    profile["name"] = re.sub(r"\s+", " ", str(profile.get("name") or "").strip())[:80]
    if not profile["name"]:
        return None
    role = str(profile.get("role") or "any").strip().casefold()
    profile["role"] = role if role in ROLES else "any"
    for key in (*TRAIT_KEYS, "audition_notes", "expanded"):
        profile[key] = str(profile.get(key) or "").strip()[:800]
    profile["built_in"] = bool(built_in or raw.get("built_in"))
    profile["archived"] = bool(raw.get("archived"))
    profile["created_at"] = str(raw.get("created_at") or _now())
    profile["updated_at"] = str(raw.get("updated_at") or profile["created_at"])
    return profile


def _seeded() -> dict[str, Any]:
    stamped = []
    for item in _DEFAULTS:
        profile = _normalize_profile(item, built_in=True)
        if profile:
            stamped.append(profile)
    return {"version": 1, "profiles": stamped}


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    known = {item["id"]: item for item in data.get("profiles") or [] if isinstance(item, dict) and item.get("id")}
    for seed in _seeded()["profiles"]:
        existing = known.get(seed["id"])
        if existing is None:
            known[seed["id"]] = seed
            continue
        # Keep user edits; only restore the built-in flag and missing ids.
        existing["built_in"] = True
    data["version"] = 1
    data["profiles"] = list(known.values())
    return data


def load() -> dict[str, Any]:
    with _LOCK:
        try:
            raw = json.loads(VOICES_PATH.read_text(encoding="utf-8"))
            data = raw if isinstance(raw, dict) else _seeded()
        except (OSError, json.JSONDecodeError):
            data = _seeded()
        return _merge_defaults(data)


def save(data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        payload = _merge_defaults(data)
        VOICES_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = VOICES_PATH.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, VOICES_PATH)
        return payload


def list_profiles(*, include_archived: bool = False) -> list[dict[str, Any]]:
    items = [_normalize_profile(item) for item in load()["profiles"]]
    profiles = [item for item in items if item]
    if not include_archived:
        profiles = [item for item in profiles if not item["archived"]]
    return sorted(profiles, key=lambda item: (item["archived"], item["role"], item["name"].casefold()))


def get_profile(profile_id: str) -> dict[str, Any] | None:
    needle = (profile_id or "").strip()
    for item in load()["profiles"]:
        if item.get("id") == needle:
            return _normalize_profile(item)
    return None


def upsert(payload: dict[str, Any], *, profile_id: str | None = None) -> dict[str, Any]:
    data = load()
    incoming = dict(payload)
    if profile_id:
        incoming["id"] = profile_id
    existing = next((item for item in data["profiles"] if item.get("id") == incoming.get("id")), None)
    if existing:
        incoming["built_in"] = bool(existing.get("built_in"))
        incoming["created_at"] = existing.get("created_at") or _now()
    incoming["updated_at"] = _now()
    profile = _normalize_profile(incoming, built_in=bool(incoming.get("built_in")))
    if not profile:
        raise ValueError("Voice profile needs a name")
    data["profiles"] = [item for item in data["profiles"] if item.get("id") != profile["id"]] + [profile]
    save(data)
    return profile


def duplicate(profile_id: str) -> dict[str, Any]:
    source = get_profile(profile_id)
    if not source:
        raise KeyError(profile_id)
    copy = deepcopy(source)
    copy["id"] = f"voice-{uuid.uuid4().hex[:10]}"
    copy["name"] = f"{source['name']} copy"[:80]
    copy["built_in"] = False
    copy["archived"] = False
    copy["created_at"] = _now()
    copy["updated_at"] = copy["created_at"]
    return upsert(copy)


def archive_or_delete(profile_id: str) -> dict[str, Any]:
    data = load()
    target = next((item for item in data["profiles"] if item.get("id") == profile_id), None)
    if not target:
        raise KeyError(profile_id)
    if target.get("built_in"):
        target["archived"] = True
        target["updated_at"] = _now()
        save(data)
        return {"id": profile_id, "archived": True, "deleted": False}
    data["profiles"] = [item for item in data["profiles"] if item.get("id") != profile_id]
    save(data)
    return {"id": profile_id, "archived": False, "deleted": True}


def import_profiles(raw_items: list[Any]) -> list[dict[str, Any]]:
    imported: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        payload["built_in"] = False
        payload["id"] = f"voice-{uuid.uuid4().hex[:10]}"
        payload["created_at"] = _now()
        imported.append(upsert(payload))
    return imported


def export_profiles() -> dict[str, Any]:
    return {"version": 1, "profiles": list_profiles(include_archived=True)}


def _strip_private_name(text: str, name: str) -> str:
    clean = text.strip()
    label = (name or "").strip()
    if label and label.casefold() not in {"singer a", "singer b", "singer c"}:
        clean = re.sub(rf"\b{re.escape(label)}\b", "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", clean).strip(" ,;")


def expand_profile(profile: dict[str, Any]) -> str:
    """Public trait sentence. Never includes the private profile name."""
    expanded = _strip_private_name(str(profile.get("expanded") or ""), str(profile.get("name") or ""))
    if expanded:
        return expanded
    parts: list[str] = []
    for key in TRAIT_KEYS:
        value = str(profile.get(key) or "").strip()
        if value:
            parts.append(_strip_private_name(value, str(profile.get("name") or "")))
    return "; ".join(part for part in parts if part) or "a clearly identified human singer whose timbre suits the arrangement"


def normalize_slots(raw: Any) -> dict[str, str]:
    slots = {key: "" for key in SLOT_KEYS}
    if not isinstance(raw, dict):
        return slots
    for key in SLOT_KEYS:
        slots[key] = str(raw.get(key) or "").strip()
    return slots


def resolve_assigned(slots: dict[str, str], snapshots: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    catalog = {item["id"]: item for item in list_profiles(include_archived=True)}
    for item in snapshots or []:
        profile = _normalize_profile(item)
        if profile:
            catalog[profile["id"]] = profile
    assigned: dict[str, dict[str, Any]] = {}
    for key in SLOT_KEYS:
        profile_id = slots.get(key) or ""
        if profile_id and profile_id in catalog:
            assigned[key] = catalog[profile_id]
    return assigned


def lyric_assignments(lyrics: str, assigned: dict[str, dict[str, Any]]) -> list[str]:
    text = lyrics or ""
    notes: list[str] = []
    has_female = "female" in assigned
    has_male = "male" in assigned
    if has_female and re.search(r"\[(?:Female|Woman|Singer A)\]", text, re.IGNORECASE):
        notes.append("Lines tagged [Female] or [Singer A] are performed only by Singer A (Female)")
    if has_male and re.search(r"\[(?:Male|Man|Singer B)\]", text, re.IGNORECASE):
        notes.append("Lines tagged [Male] or [Singer B] are performed only by Singer B (Male)")
    if has_female and has_male and re.search(r"\[(?:Duet|Call and Response|Call-and-Response)\]", text, re.IGNORECASE):
        notes.append("Lines tagged [Duet] or [Call and Response] are shared: Singer A leads, Singer B answers or joins")
    return notes


def compile_vocal_block(assigned: dict[str, dict[str, Any]], lyrics: str = "") -> dict[str, Any] | None:
    if not assigned:
        return None
    female = assigned.get("female")
    male = assigned.get("male")
    backing = assigned.get("backing")
    singers: list[str] = []
    if female:
        singers.append(f"Singer A (Female), {expand_profile(female)}")
    if male:
        label = "Singer B (Male)" if female else "Singer A (Male)"
        singers.append(f"{label}, {expand_profile(male)}")
    if not singers:
        # Backing-only still needs an identified lead placeholder.
        singers.append("Singer A, an explicitly identified lead vocalist whose timbre suits the requested genre")
    deliveries = [expand_profile(item) for key, item in assigned.items() if key != "backing" and item.get("delivery")]
    if not deliveries:
        deliveries = [str((female or male or {}).get("delivery") or "clearly pitched melodic singing")]
    backing_text = (
        expand_profile(backing)
        if backing
        else "Keep every named singer sonically distinct. Supporting voices enter only in the sections described, and never replace the principal melody unless explicitly requested."
    )
    effects = [str(item.get("effects") or "").strip() for item in assigned.values() if str(item.get("effects") or "").strip()]
    fx_text = "; ".join(effects) if effects else "Keep effects subordinate to diction and performance"
    assignments = lyric_assignments(lyrics, assigned)
    assignment_line = ""
    if assignments:
        assignment_line = "Section Performance and Singer Assignments: " + "; ".join(assignments) + "."
    block = "\n".join(
        [
            f"Vocal Gender & Timbre: {' '.join(sentence + ('' if sentence.endswith('.') else '.') for sentence in singers)}",
            f"Vocal Style: {deliveries[0].rstrip('.')}.",
            f"Harmony/Backing Vocals: {backing_text.rstrip('.')}.",
            f"Vocal FX: {fx_text.rstrip('.')}.",
            *([assignment_line] if assignment_line else []),
        ]
    )
    snapshots = []
    for slot, profile in assigned.items():
        snap = {key: profile.get(key, "") for key in _blank_profile()}
        snap["slot"] = slot
        snapshots.append(snap)
    return {"block": block, "assignments": assignments, "snapshots": snapshots}


INSTRUMENTAL_VOCAL_BLOCK = (
    "Vocal Gender & Timbre: Instrumental composition; no sung, spoken, chanted, sampled, hummed, or vocal-chop human voice. "
    "The principal melodic instrument named in the arrangement occupies the lead role.\n"
    "Vocal Style: Not applicable; keep the music fully instrumental.\n"
    "Harmony/Backing Vocals: None.\n"
    "Vocal FX: None."
)
INSTRUMENTAL_BAN = (
    "Fully instrumental. No singing, speech, humming, choir, or vocal chops. "
    "Write a complete track with a beginning, development, and ending, about 2 to 4 minutes — not a sting, loop, or short intro."
)


def apply_instrumental_caption(description: str) -> str:
    """Keep the user's description. Only rewrite Vocal Details when a structured caption already exists."""
    text = (description or "").strip()
    structured = bool(_VOCAL_HEADING.search(text) or _ARRANGEMENT_HEADING.search(text))
    if structured:
        text = apply_vocal_block(text, INSTRUMENTAL_VOCAL_BLOCK)
    if INSTRUMENTAL_BAN not in text:
        text = f"{INSTRUMENTAL_BAN}\n\n{text}" if text else INSTRUMENTAL_BAN
    return text


def apply_vocal_block(description: str, block: str) -> str:
    """Replace or insert the Vocal Details body. Leaves the rest of the caption alone."""
    text = (description or "").strip()
    if not text:
        return f"Vocal Details\n{block}"
    vocal = _VOCAL_HEADING.search(text)
    arrangement = _ARRANGEMENT_HEADING.search(text)
    if vocal:
        start = vocal.end()
        end = arrangement.start() if arrangement and arrangement.start() > start else len(text)
        return f"{text[:start].rstrip()}\n{block}\n\n{text[end:].lstrip()}".strip()
    if arrangement:
        return f"{text[:arrangement.start()].rstrip()}\n\nVocal Details\n{block}\n\n{text[arrangement.start():].lstrip()}".strip()
    return f"{text}\n\nVocal Details\n{block}"


def compile_for_generation(
    description: str,
    slots: Any,
    lyrics: str = "",
    snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized = normalize_slots(slots)
    assigned = resolve_assigned(normalized, snapshots)
    compiled = compile_vocal_block(assigned, lyrics)
    if not compiled:
        return {
            "applied": False,
            "description": description,
            "slots": normalized,
            "snapshots": [],
            "preview": description,
        }
    preview = apply_vocal_block(description, compiled["block"])
    return {
        "applied": True,
        "description": preview,
        "slots": normalized,
        "snapshots": compiled["snapshots"],
        "preview": preview,
        "assignments": compiled["assignments"],
    }
