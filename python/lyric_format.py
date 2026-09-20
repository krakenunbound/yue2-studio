"""Provider-independent boundaries between lyric words and control annotations."""
import re

SPEAKER = r"(?:Singer\s+[A-Z0-9](?:\s*(?:&|and|/)\s*(?:Singer\s+)?[A-Z0-9])?|Female|Male|Woman|Man|Both|Duet|Backing vocals)"
_PREFIX = re.compile(rf"^\s*({SPEAKER})\s*:\s*", re.I)
_ALONE = re.compile(rf"^\s*({SPEAKER})\s*$", re.I)
_PAREN = re.compile(rf"^\s*\(({SPEAKER})\)\s*", re.I)

WRITER_FORMAT_RULE = (
    "YuE2 lyric format: only sung words and section headers such as [Verse 1], "
    "[Verse 2], [Chorus], on separate lines. Voice assignments belong in the separate "
    "style description, not in lyric text. For duets, use section order for the two "
    "parts and a shared chorus. Even if the brief requests singer labels, do not output "
    "Singer A:, Singer B:, Both:, [Singer A], names as speaker labels, musical notation, "
    "or performance instructions. These are not verified YuE2 speaker-control tokens. "
    "For editing or translation, preserve existing bracketed speaker annotations "
    "as app metadata, along with section order and sung words; do not add new labels "
    "or turn existing control tags into sung words. The app removes those annotations "
    "from the final YuE2 lyric input."
)


def control_lines(text: str) -> list[str]:
    """Canonicalize explicit labels, retaining all adjacent sung text and order."""
    result = []
    for raw in str(text or "").splitlines():
        if not raw.strip():
            result.append("")
            continue
        for chunk in re.split(r"(\[[^\[\]\n]+\])", raw):
            line = chunk.strip()
            combined = re.fullmatch(rf"\[(Intro|Verse|Pre-Chorus|Chorus|Post-Chorus|Bridge|Outro)(\s+[0-9A-Z]+)?\s+[-–—]\s+({SPEAKER})\]", line, re.I)
            if combined:
                result.extend([f"[{combined[1]}{combined[2] or ''}]", f"[{combined[3]}]"])
                continue
            match = _PREFIX.match(line) or _PAREN.match(line) or _ALONE.fullmatch(line)
            if match:
                result.append(f"[{match[1]}]")
                line = line[match.end():].strip()
            if line:
                result.append(line)
    return result


def validate_engine_lyrics(text: str) -> None:
    """Fail closed if an uncompiled request reaches the engine boundary."""
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        if "[" in line or "]" in line:
            if not re.fullmatch(r"\s*\[(?:Intro|Verse|Pre-Chorus|Chorus|Post-Chorus|Bridge|Interlude|Instrumental|Solo|Hook|Outro)(?:\s+[0-9A-Z]+)?\]\s*", line, re.I):
                raise ValueError("Uncompiled lyric annotation: keep voice directions in style, not sung words.")
        elif _PREFIX.match(line) or _PAREN.match(line) or _ALONE.fullmatch(line):
            raise ValueError("A singer label reached the sung lyrics. Compile the voice directions before generating.")


def sung_lines(text: str) -> list[str]:
    result = []
    for line in control_lines(text):
        if re.fullmatch(r"\[[^\]]+\]", line):
            continue
        if re.fullmatch(r"\([^)]*\)", line):
            continue
        line = re.sub(r"\(\s*\d+(?:\.\d+)?[- ]seconds?\s+pause\s*\)", "", line, flags=re.I).strip()
        if re.search(r"[^\W_]", line, re.UNICODE):
            result.append(line)
    return result
