"""Live Gemini check. Never prints the API key. Run from python/: python tests/live_writing_check.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ai_assist
import ai_vault


def fail(label: str, detail: str) -> int:
    print(f"FAIL {label}: {detail}")
    return 1


def main() -> int:
    view = ai_vault.public_view()
    gemini = view["providers"].get("gemini") or {}
    if not gemini.get("configured"):
        return fail("vault", "no Gemini key saved")
    try:
        ai_vault.apply_update({"capabilities": {"writing": {"enabled": True, "provider": "gemini"}}})
    except ValueError as error:
        return fail("enable", str(error))

    mixed = (
        "Global Metadata\n- Basic Attributes: Cinematic Alternative Rock\n\n"
        "Vocal Details\n- Singer A: Male lead\n\nArrangement\n- Intro: pads\n\n"
        "[Intro]\n\n[Verse]\nThe warning lights are fading out to blue\n"
    )
    split = ai_assist._parse_writing(mixed)
    if "Global Metadata" in split["lyrics"]:
        return fail("split", "caption still in lyrics")
    if "warning lights" not in split["lyrics"]:
        return fail("split", "lost the verse")
    print("OK split: caption stripped, verse kept")

    result = ai_assist.write(
        "generate",
        idea="falling through a black hole",
        title="",
        description="Cinematic alternative rock, intimate opening, live drums, wide chorus.",
        lyrics="",
        language="en",
    )
    lyrics = result["lyrics"]
    print("title:", result["title"] or "(none)")
    print("description_extracted:", "yes" if result.get("description") else "no")
    print("lyrics_lines:", len(lyrics.splitlines()))
    print("lyrics_head:")
    print("\n".join(lyrics.splitlines()[:8]))
    print("---")
    checks = []
    if lyrics.lstrip().startswith("{") or '"lyrics"' in lyrics[:80]:
        checks.append("json_wrapper")
    if "Global Metadata" in lyrics or "Vocal Details" in lyrics or "Sonics & Production" in lyrics:
        checks.append("caption_leak")
    if not ai_assist.SECTION_LINE.search(lyrics):
        checks.append("no_section_tag")
    if len(lyrics) < 80:
        checks.append("too_short")
    if checks:
        return fail("generate", ", ".join(checks))
    print("OK generate: lyrics-only with section tags")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
