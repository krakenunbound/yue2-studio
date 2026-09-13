"""Reusable prompt voices. Private names stay local; YuE2 only sees traits."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from config import OUTPUTS_ROOT, ROOT, WORKER_PYTHON

log = logging.getLogger("yue2.voices")
VOICES_PATH = OUTPUTS_ROOT / "settings" / "voice-profiles.json"
AVATARS_DIR = OUTPUTS_ROOT / "settings" / "voice-avatars"
_LOCK = threading.RLock()
_RENDERER = ROOT / "python" / "cover_art_renderer.py"

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
    # Local labels may recall public singers. Traits sent to YuE2 must stay acoustic.
    {
        "id": "voice-gold-dust-mezzo",
        "name": "Stevie Nicks",
        "role": "female",
        "register": "husky fluttering rock-mezzo",
        "timbre": "grainy chest, airy head mix, throaty edges, a shawl of breath around the tone",
        "delivery": "behind-the-beat folk-rock phrasing, circling the pitch, story-first verses, a wide open chorus",
        "accent": "California American English",
        "vibrato": "slow, wide, and slightly uneven",
        "dynamics": "intimate and smoky, then suddenly stadium-open",
        "harmony": "one ghostly high double on the refrain only",
        "effects": "close room, plate tails, no glossy pop stack",
        "tag": "70s folk-rock · husky",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "70s rock, folk-rock, husky raspy female vocals, smoky contralto, gravelly chest voice, distinctive warbling vibrato, raw emotional power mixed with vulnerability, dark warm tone, analog warmth",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-temple-tenor",
        "name": "Chris Cornell",
        "role": "male",
        "register": "dark high baritone that opens into a ringing tenor",
        "timbre": "bronze chest, huge head voice, controlled grit, long sustained belts with a human crack at the top",
        "delivery": "intimate tense verses, then a soaring open-throated chorus; fully sung, not screamed as the default",
        "accent": "Pacific Northwest American English",
        "vibrato": "controlled, widening on long belts",
        "dynamics": "quiet menace into cathedral-scale release",
        "harmony": "none except a low octave ghost on the last refrain",
        "effects": "dry band mix, long hall only on the biggest notes",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a dark high baritone that opens into a ringing tenor, bronze chest, huge head voice, controlled grit and long human belts rather than constant screaming",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-stadium-tenor",
        "name": "Freddie Mercury",
        "role": "male",
        "register": "bright theatrical tenor with a piercing upper register",
        "timbre": "clear cutting vowels, sudden piano-to-forte leaps, camp-to-operatic color without losing rock bite",
        "delivery": "dramatic contour, precise consonants, call-to-the-back-row choruses, playful verse asides",
        "accent": "British theatrical English",
        "vibrato": "present and proud on sustained high notes",
        "dynamics": "whisper to arena in one phrase",
        "harmony": "stacked gang answers on selected hook words only",
        "effects": "piano-front stadium space, no auto-tune",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a bright theatrical tenor with a piercing upper register, precise consonants, sudden dynamic leaps and camp-to-operatic rock phrasing",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-soul-chest",
        "name": "Adele",
        "role": "female",
        "register": "smoky British contralto-mezzo",
        "timbre": "thick chest, broken-heart diction, sudden clean belt, audible catch in the throat",
        "delivery": "piano-ballad verses spoken-sung, then a huge tuneful chorus with held climactic notes",
        "accent": "London British English",
        "vibrato": "late, emotional, not constant",
        "dynamics": "close confession into a belted refrain",
        "harmony": "one low double on the last chorus",
        "effects": "dry piano-room vocal, long hall only at the peak",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a smoky British contralto-mezzo with thick chest, broken-heart diction, a sudden clean belt and piano-ballad space",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-gospel-peak",
        "name": "Whitney Houston",
        "role": "female",
        "register": "gleaming gospel-pop soprano",
        "timbre": "bright focused vowels, church-trained breath, effortless high belts, tasteful melisma at cadences",
        "delivery": "clearly pitched verses, a rising pre-chorus, a soaring memorable refrain with controlled runs",
        "accent": "American English with gospel inflections",
        "vibrato": "fast and shining on long notes",
        "dynamics": "composed verses, then a huge open peak",
        "harmony": "small gospel answers only on the final hook",
        "effects": "polished 80s-90s pop space, present centered vocal",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a gleaming gospel-pop soprano with church-trained breath, effortless high belts and tasteful melisma only at cadences",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-jazz-smoke",
        "name": "Amy Winehouse",
        "role": "female",
        "register": "dry jazz-soul alto",
        "timbre": "smoky-nasal mix, vintage close-mic grain, small-combo intimacy, never a modern pop stack",
        "delivery": "behind-the-beat phrasing, pub-soul asides, a tuneful hook with conversational swing",
        "accent": "North London English",
        "vibrato": "short and vintage",
        "dynamics": "intimate and slightly weary, then a proud chorus",
        "harmony": "none, or one dusty unison",
        "effects": "dry mono-leaning vocal, tape warmth",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a dry jazz-soul alto with smoky-nasal mix, vintage close-mic grain, behind-the-beat phrasing and small-combo intimacy",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-whisper-close",
        "name": "Billie Eilish",
        "role": "female",
        "register": "extremely close whisper-mezzo",
        "timbre": "air-forward, almost spoken, sudden chest punches, dry and intimate",
        "delivery": "ASMR-quiet verses, compact tuneful hooks, no belting choir",
        "accent": "contemporary Californian English",
        "vibrato": "almost none",
        "dynamics": "whisper to a close chest hit, never arena",
        "harmony": "ghostly self-unison, very low in the mix",
        "effects": "dry close mic, sub-bass bed, no glossy stack",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "an extremely close whisper-mezzo with air-forward tone, sudden chest punches, almost no vibrato and dry intimate presence",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-country-bright",
        "name": "Dolly Parton",
        "role": "female",
        "register": "bright country soprano",
        "timbre": "smiling vowels, Appalachian lilt, light sparkle, story-first clarity",
        "delivery": "plainspoken verses, a memorable communal refrain, no pop belt",
        "accent": "East Tennessee American English",
        "vibrato": "light and cheerful",
        "dynamics": "porch-warm, then a lifted chorus",
        "harmony": "high country thirds in the refrain only",
        "effects": "honest acoustic-country room",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a bright country soprano with smiling vowels, Appalachian lilt, story-first phrasing and light country-third harmony on the refrain",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-railroad-baritone",
        "name": "Johnny Cash",
        "role": "male",
        "register": "deep dry baritone",
        "timbre": "almost spoken melody, railroad-straight tone, little sweetness, gravely dignity",
        "delivery": "story-first, on the beat, boom-chicka gravity, no crooner polish",
        "accent": "Southern American English",
        "vibrato": "minimal",
        "dynamics": "level and stern, a slight lift on the last line",
        "harmony": "none",
        "effects": "dry slapback, centered, no choir",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a deep dry baritone with almost spoken melody, railroad-straight tone, Southern diction and boom-chicka gravity",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-art-baritone",
        "name": "David Bowie",
        "role": "male",
        "register": "chameleon British baritone with sudden falsetto color",
        "timbre": "theatrical consonants, cool and slightly alien, art-rock intimacy",
        "delivery": "precise phrasing, characterful verse, a soaring unusual chorus interval",
        "accent": "British art-rock English",
        "vibrato": "controlled, sometimes withheld",
        "dynamics": "detached cool into a sudden open cry",
        "harmony": "one odd high color, never a pop choir",
        "effects": "dry-to-spacey, no generic crooner plate",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a chameleon British baritone with theatrical consonants, sudden falsetto color, art-rock cool and precise unusual phrasing",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-liquid-falsetto",
        "name": "Prince",
        "role": "male",
        "register": "agile high tenor with liquid falsetto",
        "timbre": "tight, sensual, clipped and rhythmic, Minneapolis funk-pop bite",
        "delivery": "short rhythmic phrases, sudden falsetto leaps, a memorable hook sung on the groove",
        "accent": "American English",
        "vibrato": "quick and stylish when used",
        "dynamics": "whispered verse, athletic chorus",
        "harmony": "tight stacked answers on the hook only",
        "effects": "dry funk vocal, slap delay, no choir",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "an agile high tenor with liquid falsetto, tight rhythmic phrasing, sensual clipped phrases and funk-pop bite",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-gospel-soul",
        "name": "Aretha Franklin",
        "role": "female",
        "register": "gospel-soul mezzo",
        "timbre": "piano-driven fire, shout-to-silk, human grain, Detroit church authority",
        "delivery": "improvisatory soul phrasing, conversational verses, a climactic gospel refrain",
        "accent": "American English with gospel inflections",
        "vibrato": "rich and late",
        "dynamics": "talk-sing into a holy shout, then silk",
        "harmony": "small church answers, never a pop choir stack",
        "effects": "live-room piano and voice, audible air",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a gospel-soul mezzo with piano-driven fire, shout-to-silk dynamics, human grain and improvisatory church-trained phrasing",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-light-pop-tenor",
        "name": "Michael Jackson",
        "role": "male",
        "register": "light agile tenor",
        "timbre": "boyish upper mix, razor rhythm, hiccup ornaments, dry precise consonants",
        "delivery": "dance-pop phrasing locked to the groove, compact tuneful hooks, no cartoon impersonation",
        "accent": "American English",
        "vibrato": "short ornamental hiccups rather than wide opera vibrato",
        "dynamics": "tight and rhythmic, then a bright chorus",
        "harmony": "tight unison doubles, no choir",
        "effects": "dry gated 80s-pop space",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a light agile tenor with boyish upper mix, razor rhythm, short hiccup ornaments and dry dance-pop phrasing",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-cool-silk",
        "name": "Sade",
        "role": "female",
        "register": "cool silky alto",
        "timbre": "almost spoken smoothness, late-night sophistication, little grain, international hush",
        "delivery": "behind-the-beat, unforced, a simple memorable refrain",
        "accent": "British-international English",
        "vibrato": "almost none",
        "dynamics": "level, intimate, never belted",
        "harmony": "none",
        "effects": "warm close jazz-soul space",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a cool silky alto with almost spoken smoothness, little vibrato, behind-the-beat phrasing and late-night sophistication",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-showman-baritone",
        "name": "Elvis Presley",
        "role": "male",
        "register": "warm Southern baritone",
        "timbre": "croon-to-rockabilly snap, gospel-tinged vowels, intimate then showman",
        "delivery": "hiccup ornaments, behind-then-on the beat, a tuneful refrain with physical swing",
        "accent": "Southern American English",
        "vibrato": "present on held notes",
        "dynamics": "close croon into a rocking chorus",
        "harmony": "gospel answers only if the arrangement asks",
        "effects": "slapback echo, dry band",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "a warm Southern baritone with croon-to-rockabilly snap, gospel-tinged vowels, hiccup ornaments and slapback intimacy",
        "built_in": True,
        "archived": False,
    },
    {
        "id": "voice-athletic-mezzo",
        "name": "Beyoncé",
        "role": "female",
        "register": "agile contemporary R&B mezzo",
        "timbre": "laser pitch, athletic belts, precise diction, retained human grain under polish",
        "delivery": "tight rhythmic verses, a soaring hook, stacked self-harmony only on the chorus",
        "accent": "American English with Southern color",
        "vibrato": "controlled, used as punctuation",
        "dynamics": "quiet command into a stadium belt",
        "harmony": "tight self-stacks on the hook, never an anonymous choir",
        "effects": "modern vocal-forward pop mix, dry verses, wide chorus",
        "audition_notes": "Local label only. YuE2 receives the acoustic traits, not the name.",
        "expanded": "an agile contemporary R&B mezzo with laser pitch, athletic belts, precise diction and tight self-harmony only on the hook",
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
        "tag": "",
        "avatar": "",
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
    for key in (*TRAIT_KEYS, "audition_notes", "expanded", "tag"):
        profile[key] = str(profile.get(key) or "").strip()[:800]
    profile["tag"] = profile["tag"][:80]
    profile["avatar"] = "custom" if str(profile.get("avatar") or "").strip() == "custom" else ""
    if not profile["tag"] and profile.get("register"):
        profile["tag"] = str(profile["register"])[:40]
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
        if not str(existing.get("tag") or "").strip():
            existing["tag"] = seed.get("tag") or existing.get("tag") or ""
        old_stevie = "a husky fluttering rock-mezzo"
        if seed["id"] == "voice-gold-dust-mezzo" and old_stevie in str(existing.get("expanded") or ""):
            existing["expanded"] = seed["expanded"]
            existing["tag"] = seed.get("tag") or existing.get("tag") or ""
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


def avatar_path(profile_id: str) -> Path:
    return AVATARS_DIR / f"{profile_id}.webp"


def mark_custom_avatar(profile_id: str) -> dict[str, Any]:
    profile = get_profile(profile_id)
    if not profile:
        raise KeyError(profile_id)
    profile["avatar"] = "custom"
    profile["updated_at"] = _now()
    return upsert(profile, profile_id=profile_id)


def save_avatar_image(profile_id: str, source: Path) -> dict[str, Any]:
    if not get_profile(profile_id):
        raise KeyError(profile_id)
    from PIL import Image
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    image = Image.open(source).convert("RGB")
    image.resize((512, 512), Image.Resampling.LANCZOS).save(avatar_path(profile_id), "WEBP", quality=86, method=6)
    return mark_custom_avatar(profile_id)


def portrait_prompt(profile: dict[str, Any]) -> str:
    role = str(profile.get("role") or "any")
    gender = "woman" if role == "female" else "man" if role == "male" else "person"
    sound = expand_profile(profile)
    vibe = str(profile.get("tag") or "").strip()
    pieces = [
        f"square cinematic studio headshot of an original fictional {gender} singer",
        vibe,
        sound,
        "album-character portrait, no text, no logo, not a likeness of any real celebrity",
    ]
    return ", ".join(piece for piece in pieces if piece)[:420]


def generate_avatar(profile_id: str, direction: str = "") -> dict[str, Any]:
    import cover_art
    profile = get_profile(profile_id)
    if not profile:
        raise KeyError(profile_id)
    if not cover_art.available():
        raise RuntimeError("Install Cover art in Models to generate a portrait, or upload an image.")
    prompt = portrait_prompt(profile)
    if direction.strip():
        prompt = f"{prompt}, {direction.strip()}"[:420]
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    png = AVATARS_DIR / f"{profile_id}.png"
    command = [str(WORKER_PYTHON), str(_RENDERER), "--prompt", prompt, "--output", str(png)]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags, timeout=180)
    if completed.returncode != 0 or not png.is_file():
        detail = (completed.stdout or completed.stderr or "Portrait generation failed").strip()
        raise RuntimeError(detail[-400:])
    result = save_avatar_image(profile_id, png)
    png.unlink(missing_ok=True)
    return result


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
    """Compact YuE2 style fragment. No MiniMax Vocal Details headings."""
    if not assigned:
        return None
    female = assigned.get("female")
    male = assigned.get("male")
    backing = assigned.get("backing")
    parts: list[str] = []
    if female:
        parts.append(f"Singer A (Female), {expand_profile(female)}")
    if male:
        label = "Singer B (Male)" if female else "Singer A (Male)"
        parts.append(f"{label}, {expand_profile(male)}")
    if not parts:
        parts.append("a clearly identified lead vocalist whose timbre suits the requested genre")
    if backing:
        parts.append(f"backing vocals, {expand_profile(backing)}")
    elif female and male:
        parts.append("keep the two leads distinct, no choir blend")
    assignments = lyric_assignments(lyrics, assigned)
    parts.extend(assignments)
    block = ", ".join(part.strip(" .,") for part in parts if str(part).strip())
    snapshots = []
    for slot, profile in assigned.items():
        snap = {key: profile.get(key, "") for key in _blank_profile()}
        snap["slot"] = slot
        snapshots.append(snap)
    return {"block": block, "assignments": assignments, "snapshots": snapshots}


INSTRUMENTAL_BAN = (
    "instrumental, no vocals, no humming, no vocables, no oohs, no aahs, "
    "no choir, no rap, no vocal chops, lead instrument only"
)


def _compact_style(text: str, *, keep_vocal_fields: bool = True) -> str:
    try:
        from main import flatten_style
        return flatten_style(text, keep_vocal_fields=keep_vocal_fields)
    except Exception:
        return re.sub(r"\s+", " ", text or "").strip()


def apply_instrumental_caption(description: str) -> str:
    """Prefix the official instrumental lock. Drop leftover MiniMax singer blocks."""
    style = re.sub(r"(?i)\bSinger [AB]\s*(?:\([^)]+\))?,?\s*", "", _compact_style(description)).strip(" ,")
    if "instrumental" in style.casefold() and "no vocals" in style.casefold():
        return style
    return f"{INSTRUMENTAL_BAN}. {style}".strip(" .") if style else INSTRUMENTAL_BAN


def apply_vocal_block(description: str, block: str) -> str:
    """Append a compact voice phrase to a YuE2 style line."""
    style = _compact_style(description, keep_vocal_fields=False).rstrip(" ,")
    phrase = (block or "").strip().rstrip(" ,")
    if not phrase:
        return style
    if phrase.casefold() in style.casefold():
        return style
    if not style:
        return phrase
    return f"{style}, {phrase}"


def compile_for_generation(
    description: str,
    slots: Any,
    lyrics: str = "",
    snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized = normalize_slots(slots)
    assigned = resolve_assigned(normalized, snapshots)
    compiled = compile_vocal_block(assigned, lyrics)
    style = _compact_style(description, keep_vocal_fields=not bool(compiled))
    if not compiled:
        return {
            "applied": False,
            "description": style,
            "slots": normalized,
            "snapshots": [],
            "preview": style,
        }
    preview = apply_vocal_block(style, compiled["block"])
    return {
        "applied": True,
        "description": preview,
        "slots": normalized,
        "snapshots": compiled["snapshots"],
        "preview": preview,
        "assignments": compiled["assignments"],
    }
