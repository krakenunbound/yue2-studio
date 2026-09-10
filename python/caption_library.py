"""Local retrieval over MiniMax's official caption template library.

MiniMax ships a `music-caption-rewriter` agent skill: a genre router, 19 family
indexes, and 1000 complete structured captions. Upstream expects an LLM agent to
walk that library file by file. We cannot afford that round trip inside the app,
so this module does the same job locally in Python: score every index card
against the user's music description, pick up to three references with distinct
roles, and read only those template files off disk.

Nothing here calls the network. See caption_library/PROVENANCE.md.
"""
from __future__ import annotations

import functools
import logging
import re
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("music3.captions")

LIBRARY_ROOT = Path(__file__).resolve().parent / "caption_library"
REFERENCES_DIR = LIBRARY_ROOT / "references"
TEMPLATES_DIR = LIBRARY_ROOT / "templates"
ROUTER_PATH = REFERENCES_DIR / "genre-router.md"

MAX_REFERENCES = 3
MAX_TEMPLATE_CHARS = 6000

# Router aliases, normalised toward the vocabulary the index cards actually use.
ALIASES: dict[str, str] = {
    "r&b": "rnb",
    "r'n'b": "rnb",
    "r and b": "rnb",
    "rhythm and blues": "rnb",
    "hip hop": "hiphop",
    "hip-hop": "hiphop",
    "lo fi": "lofi",
    "lo-fi": "lofi",
    "drum and bass": "dnb",
    "drum & bass": "dnb",
    "singer songwriter": "singer-songwriter",
    "华语流行": "mandopop",
    "国语流行": "mandopop",
    "粤语流行": "cantopop",
    "国风流行": "guofeng mandopop",
    "氛围": "atmospheric",
    "朋克流行": "pop punk",
    "电影感": "cinematic",
    "史诗感": "epic",
}

# Everyday words for music that MiniMax's router does not list. Each one is
# EXPANDED (the original is kept and the router's own vocabulary is added), so
# "a cyberpunk song about juggling zebras" can reach the synth family instead of
# scraping a spurious arena-rock card.
EXPANSIONS: dict[str, str] = {
    "cyberpunk": "darkwave retrowave synthwave industrial electronic synth pop nocturnal",
    "synthwave": "retrowave darkwave synth pop electronic",
    "vaporwave": "downtempo synth pop ambient electronic",
    "chillwave": "dream pop ambient pop downtempo electronic",
    "phonk": "trap hiphop lofi dark",
    "witch house": "darkwave industrial electronic",
    "dungeon synth": "ambient orchestral cinematic",
    "chiptune": "electropop synth pop electronic",
    "8 bit": "electropop synth pop electronic",
    "shoegaze": "dream pop alternative rock indie rock",
    "emo": "alternative rock pop punk indie rock",
    "screamo": "post hardcore metalcore",
    "math rock": "indie rock alternative rock progressive",
    "post rock": "alternative rock cinematic instrumental",
    "sea shanty": "traditional folk maritime celtic",
    "anime opening": "jrock anime rock pop rock",
    "anime": "jrock jpop anime rock",
    "kpop": "korean dance pop electropop",
    "k pop": "korean dance pop electropop",
    "jpop": "japanese pop electropop",
    "j pop": "japanese pop electropop",
    "citypop": "japanese pop funk pop disco",
    "city pop": "japanese pop funk pop disco",
    "afrobeats": "global folk fusion dance pop groove",
    "amapiano": "house dance electronic groove",
    "reggaeton": "dance pop latin hip hop groove",
    "latin pop": "dance pop global",
    "bossa": "bossa nova jazz lounge jazz",
    "ska": "reggae punk horns upbeat",
    "dub": "reggae downtempo bass",
    "drill": "trap hiphop dark",
    "boom bap": "hip hop rap",
    "jersey club": "house dance electronic club",
    "hyperpop": "electropop synth pop dance pop",
    "breakcore": "breakbeat electronic club",
    "dnb": "breakbeat electronic club drum and bass",
    "psytrance": "trance electronic club festival",
    "gospel choir": "gospel worship soul",
    "spaghetti western": "americana country cinematic orchestral",
    "lullaby": "folk acoustic ballad gentle",
    "christmas": "holiday traditional pop easy listening",
    "video game": "cinematic orchestral electronic",
    "trailer": "cinematic orchestral epic choral",
    "horror": "darkwave industrial cinematic orchestral",
    "western": "country americana",
    "medieval": "traditional folk celtic",
    "viking": "traditional folk nordic ritual",
    "norse": "traditional folk nordic ritual",
    "celtic": "traditional folk celtic",
}

# Words that carry no routing signal.
STOPWORDS = frozenset("""
a an the and or of with for from into about that this these those it its is are was were be been being
song track piece music musical sound sounds sounding style styles vibe vibes feel feels feeling like
very really quite some more most much many make makes making want wants need needs please
i you he she we they me my your our their his her
in on at to by as but if then than so such over under out up down
one two three four five
influences influence elements element inspired flavour flavor fusion touches hints
""".split())

# Tokens that describe energy or mood only. The router is explicit that these are
# modifiers, never genre evidence on their own.
MODIFIER_ONLY = frozenset({
    "emotional", "epic", "dark", "modern", "cinematic", "ballad", "intense",
    "powerful", "soft", "hard", "big", "small", "beautiful", "sad", "happy",
})

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_CARD_RE = re.compile(r"^\|(?!\s*-)(.+)\|\s*$")
_BPM_RE = re.compile(r"(\d{2,3})\s*bpm", re.I)
_TICK_RE = re.compile(r"`([^`]+)`")


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #

def _normalise(text: str) -> str:
    lowered = (text or "").lower()
    for source, target in ALIASES.items():
        lowered = lowered.replace(source, target)
    lowered = lowered.replace("&", " and ")
    return lowered


def _tokens(text: str) -> set[str]:
    return {word for word in _TOKEN_RE.findall(_normalise(text)) if word not in STOPWORDS and len(word) > 2}


def _phrases(text: str) -> str:
    """A hyphen-flattened haystack for substring checks."""
    flat = _normalise(text).replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", flat)


# --------------------------------------------------------------------------- #
# library loading (cached for the life of the process)
# --------------------------------------------------------------------------- #

def available() -> bool:
    return ROUTER_PATH.is_file() and TEMPLATES_DIR.is_dir()


@functools.lru_cache(maxsize=1)
def _families() -> dict[str, dict[str, Any]]:
    """Parse the genre router's family map into cue lists."""
    families: dict[str, dict[str, Any]] = {}
    if not ROUTER_PATH.is_file():
        return families
    for line in ROUTER_PATH.read_text(encoding="utf-8").splitlines():
        match = _CARD_RE.match(line.strip())
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(1).split("|")]
        if len(cells) < 4:
            continue
        route = _TICK_RE.search(cells[0])
        index_link = re.search(r"\((index-[^)]+\.md)\)", cells[3])
        if not route or not index_link:
            continue
        cues = [cue.strip() for cue in re.split(r"[,;]", cells[1]) if len(cue.strip()) > 2]
        families[route.group(1)] = {
            "index": index_link.group(1),
            "cues": [_phrases(cue) for cue in cues],
        }
    return families


@functools.lru_cache(maxsize=1)
def _cards() -> list[dict[str, Any]]:
    """Flatten every family index into scoreable cards."""
    cards: list[dict[str, Any]] = []
    for family, meta in _families().items():
        path = REFERENCES_DIR / meta["index"]
        if not path.is_file():
            log.warning("Caption family index missing: %s", path.name)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _CARD_RE.match(line.strip())
            if not match:
                continue
            cells = [cell.strip() for cell in match.group(1).split("|")]
            if len(cells) < 8 or not cells[0].startswith("`"):
                continue
            identifier = _TICK_RE.search(cells[0])
            template = _TICK_RE.search(cells[7])
            if not identifier or not template:
                continue
            bpm_match = _BPM_RE.search(cells[3])
            secondary = [item.strip() for item in re.split(r"[,;]", cells[2]) if item.strip() not in {"", "—", "-"}]
            style = cells[1]
            blob = " ".join(cells[1:7])
            cards.append({
                "id": identifier.group(1),
                "family": family,
                "style": style,
                "style_phrase": _phrases(style),
                "style_tokens": _tokens(style),
                "secondary": secondary,
                "bpm": int(bpm_match.group(1)) if bpm_match else None,
                "tempo_key": cells[3],
                "mood": cells[4],
                "vocal": cells[5],
                "vocal_phrase": _phrases(cells[5]),
                "palette": cells[6],
                "template": template.group(1),
                "blob_tokens": _tokens(blob),
            })
    if not cards:
        log.warning("Caption library produced no cards; falling back to prompt-only captions.")
    return cards


# --------------------------------------------------------------------------- #
# brief analysis
# --------------------------------------------------------------------------- #

def _expand(brief: str) -> str:
    """Append router vocabulary for everyday terms the router never lists."""
    flat = _phrases(brief)
    extra = [words for cue, words in EXPANSIONS.items() if cue in flat]
    return brief + ("\n" + " ".join(extra) if extra else "")


def _analyse(raw_brief: str) -> dict[str, Any]:
    brief = _expand(raw_brief)
    phrase = _phrases(brief)
    tokens = _tokens(brief)
    bpm_match = _BPM_RE.search(raw_brief or "")
    wants_female = bool(re.search(r"\bfemale\b|\bwoman\b|\bher voice\b|\bsoprano\b|\balto\b", phrase))
    wants_male = bool(re.search(r"\bmale\b|\bman\b|\bhis voice\b|\btenor\b|\bbaritone\b|\bbass voice\b", phrase))
    if wants_female and wants_male:
        wants_female = wants_male = False  # a duet request constrains nothing
    return {
        "phrase": phrase,
        "tokens": tokens,
        "genre_tokens": tokens - MODIFIER_ONLY,
        "bpm": int(bpm_match.group(1)) if bpm_match else None,
        "instrumental": bool(re.search(r"\binstrumental\b|\bno vocals?\b|\bwithout vocals?\b", phrase)),
        "female": wants_female,
        "male": wants_male,
    }


def _family_scores(brief: dict[str, Any]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for family, meta in _families().items():
        score = 0
        for cue in meta["cues"]:
            if len(cue) > 3 and cue in brief["phrase"]:
                score += 9
        scores[family] = score
    return scores


def _score(card: dict[str, Any], brief: dict[str, Any], family_scores: dict[str, int]) -> int:
    score = family_scores.get(card["family"], 0)

    # Whole style name present in the description is the strongest signal there is.
    for part in re.split(r"\s*/\s*", card["style_phrase"]):
        part = part.strip()
        if len(part) > 3 and part in brief["phrase"]:
            score += 14

    genre_hits = card["style_tokens"] & brief["genre_tokens"]
    score += 6 * len(genre_hits)

    # Penalise a card that drags in extra genres the user never asked for, so a
    # pure "Nu-Metal / Rap Rock" beats "Rap Rock with Traditional Chinese elements".
    strays = card["style_tokens"] - brief["tokens"] - MODIFIER_ONLY
    score -= 3 * min(4, len(strays))

    for family in card["secondary"]:
        if family_scores.get(family, 0) > 0:
            score += 4

    # Instruments, production words and mood language shared with the card.
    score += min(6, len(card["blob_tokens"] & brief["tokens"]))

    # Vocal configuration: never contradict an explicit request.
    has_female = "female" in card["vocal_phrase"]
    has_male = "male" in card["vocal_phrase"] and "female" not in card["vocal_phrase"]
    sung = any(word in card["vocal_phrase"] for word in
               ("singer", "vocalist", "vocal", "voices", "choir", "cappella", "rapper"))
    if brief["instrumental"]:
        score += -14 if sung else 8
    elif brief["female"]:
        score += 6 if has_female else -7
    elif brief["male"]:
        score += 6 if has_male else -7

    # Tempo, including plausible half-time / double-time relationships.
    if brief["bpm"] and card["bpm"]:
        gap = abs(brief["bpm"] - card["bpm"])
        halved = min(abs(brief["bpm"] - card["bpm"] * 2), abs(brief["bpm"] * 2 - card["bpm"]))
        if gap <= 12:
            score += 6
        elif gap <= 25:
            score += 2
        elif halved <= 12:
            score += 2
        elif gap > 45:
            score -= 3

    return score


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #

ROLES = ("Foundation", "Modifier", "Arrangement")


def select(description: str, lyrics: str = "", title: str = "", limit: int = MAX_REFERENCES) -> list[dict[str, Any]]:
    """Pick up to `limit` reference cards with distinct roles.

    Lyrics only ever contribute broad emotional context, never quoted content,
    so we feed the caller's lyric text in as weak signal and nothing more.
    """
    cards = _cards()
    if not cards:
        return []
    brief = _analyse(" ".join(part for part in (description, title, lyrics[:600]) if part))
    family_scores = _family_scores(brief)
    ranked = sorted(
        ((_score(card, brief, family_scores), card) for card in cards),
        key=lambda pair: (-pair[0], pair[1]["id"]),
    )
    MIN_CONFIDENT_SCORE = 8
    if not ranked or ranked[0][0] < MIN_CONFIDENT_SCORE:
        # No musical evidence at all: fall back to the general pop and ballad family.
        ranked = sorted(
            ((_score(card, brief, family_scores), card) for card in cards if card["family"] == "general-pop-ballad"),
            key=lambda pair: (-pair[0], pair[1]["id"]),
        )
        if not ranked:
            return []

    chosen: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for score, card in ranked:
        if len(chosen) >= limit:
            break
        # Foundation takes the best card outright; later roles prefer a new family
        # so the three references cover different responsibilities.
        if chosen and card["family"] in seen_families and len(seen_families) < len(_families()):
            continue
        chosen.append({**card, "score": score, "role": ROLES[len(chosen)] if len(chosen) < len(ROLES) else "Reference"})
        seen_families.add(card["family"])

    # A single strong family is better than padding with weak cross-family cards.
    return [card for card in chosen if card["score"] > 0] or chosen[:1]


def read_template(card: dict[str, Any]) -> str:
    path = LIBRARY_ROOT / card["template"]
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()[:MAX_TEMPLATE_CHARS]


def reference_block(description: str, lyrics: str = "", title: str = "", limit: int = MAX_REFERENCES) -> str:
    """Render the chosen templates as a prompt fragment, or '' when unavailable."""
    if not available():
        return ""
    try:
        chosen = select(description, lyrics=lyrics, title=title, limit=limit)
    except Exception:  # a broken library must never break generation
        log.exception("Caption reference selection failed")
        return ""
    blocks: list[str] = []
    for card in chosen:
        body = read_template(card)
        if not body:
            continue
        blocks.append(f"--- REFERENCE ({card['role']} — {card['style']}) ---\n{body}")
    if not blocks:
        return ""
    return (
        "Reference captions from the official MiniMax library. Study their level of "
        "detail, their sub-field names, and how the Arrangement reads as a timeline. "
        "Use the Foundation for overall musical identity, the Modifier only for the "
        "dimension it was chosen for, and the Arrangement only for timeline logic. "
        "Do not copy their sentences, key, BPM, instruments, or section order — the "
        "user's own brief always wins.\n\n" + "\n\n".join(blocks)
    )


def diagnostics(description: str, lyrics: str = "", title: str = "") -> list[dict[str, Any]]:
    """Scoring detail for debugging. Not used on the generation path."""
    return [
        {"role": card["role"], "id": card["id"], "family": card["family"], "style": card["style"], "score": card["score"]}
        for card in select(description, lyrics=lyrics, title=title)
    ]


def stats() -> dict[str, Any]:
    return {
        "available": available(),
        "families": len(_families()),
        "cards": len(_cards()),
        "templates": len(list(TEMPLATES_DIR.glob("*.txt"))) if TEMPLATES_DIR.is_dir() else 0,
    }


def _iter_all_ids() -> Iterable[str]:
    return (card["id"] for card in _cards())
