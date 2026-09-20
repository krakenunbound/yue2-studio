"""Local, user-owned lyric preferences, independent of provider credentials."""
import json
import re
import threading
import unicodedata
from config import OUTPUTS_ROOT

PATH = OUTPUTS_ROOT / 'settings' / 'lyric-preferences.json'
_lock = threading.RLock()
_WILDCARD = re.compile(r'(_{3,}|\.{3}|…)')

# English ban roots plus the usual dodge translations. Live titles were slipping
# through as "sussurro" / "eco" instead of whisper / echo.
_ALIASES = {
    "whisper": ["whispers", "whispered", "whispering", "sussurro", "sussurros", "sussurrar", "sussurram", "sussurrante", "sussurrantes", "susurro", "susurros", "susurrar", "susurrante", "susurrantes"],
    "echo": ["echoes", "echoing", "echoed", "écho", "échos", "eco", "ecos"],
    "neon": ["néon", "neón"],
}


def load():
    with _lock:
        if not PATH.exists():
            return {'avoid': ''}
        value = json.loads(PATH.read_text(encoding='utf-8'))
        return {'avoid': str(value.get('avoid', ''))}


def save(avoid):
    if len(avoid) > 12000:
        raise ValueError('Keep the list under 12,000 characters')
    with _lock:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = PATH.with_suffix('.tmp')
        value = {'avoid': avoid.strip()}
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(PATH)
        return value


def preamble():
    """Short ban line to put at the top of the writing request, before the song idea."""
    words = [term for term in terms() if term and not _WILDCARD.search(term)]
    if not words:
        return ''
    listed = ", ".join(words[:80])
    return (
        f"NEVER USE these words in the title or any sung line: {listed}. "
        "This is a ban list. Do not include them, do not translate them, do not hint them.\n\n"
    )


def prompt():
    avoid = load()['avoid'].strip()
    if not avoid:
        return ''
    return ('\n\nUSER LYRIC AVOID LIST\n'
            'Apply these user preferences whenever drafting or rewriting the song title and lyrics. '
            'MANDATORY: NEVER USE these words, phrases, or patterns in the title or in any sung line. '
            'This is a ban list, not a list of words to include. Do not translate a banned word into another language to dodge it. '
            'Match without regard to case; slash-separated alternatives ban both forms, and blanks or ellipses describe phrase patterns to avoid. '
            'Replace violations with different concrete imagery. Do not swap in equally formulaic filler. '
            'Before returning, check the title and every sung line against this list and revise violations. '
            'These preferences concern title and lyric content only; preserve the required output format.\n'
            + avoid + '\nEND USER LYRIC AVOID LIST\n')


def _expand_aliases(entry: str) -> list[str]:
    folded = entry.casefold()
    extras: list[str] = []
    for root, aliases in _ALIASES.items():
        family = {root, *aliases}
        if folded == root or folded in {item.casefold() for item in aliases}:
            extras.extend(item for item in family if item.casefold() != folded)
    return extras


def terms(avoid=None):
    raw = (load()['avoid'] if avoid is None else avoid) or ''
    items = []
    seen = set()
    for line in str(raw).splitlines():
        line = line.strip()
        if not line:
            continue
        for part in re.split(r'\s*/\s*', line):
            part = part.strip()
            if not part:
                continue
            for item in (part, *_expand_aliases(part)):
                key = item.casefold()
                if key not in seen:
                    seen.add(key)
                    items.append(item)
    return items


def _pattern(entry: str):
    text = (entry or '').strip()
    if not text:
        return None
    if _WILDCARD.search(text):
        pieces = []
        index = 0
        for match in _WILDCARD.finditer(text):
            pieces.append(re.escape(text[index:match.start()]))
            pieces.append(r'.{1,40}')
            index = match.end()
        pieces.append(re.escape(text[index:]))
        return re.compile(''.join(pieces), re.IGNORECASE)
    words = [re.escape(word) for word in re.split(r'\s+', text) if word]
    if not words:
        return None
    # CJK and Thai lyrics do not reliably separate words with spaces.
    boundary = '' if re.search(r'[\u3040-\u30ff\u3400-\u9fff\u0e00-\u0e7f]', text) else r'\b'
    return re.compile(boundary + r'\s+'.join(words) + boundary, re.IGNORECASE)


def violations(text: str, avoid=None) -> list[str]:
    hay = unicodedata.normalize('NFKC', text or '')
    hay = ''.join(char for char in hay if unicodedata.category(char) != 'Cf')
    hay = re.sub(r'\[[^\]]*\]', ' ', hay)
    found = []
    seen = set()
    for entry in terms(avoid):
        pattern = _pattern(entry)
        key = entry.casefold()
        if pattern and key not in seen and pattern.search(hay):
            seen.add(key)
            found.append(entry)
    return found


def scrub(text: str, avoid=None) -> str:
    out = text or ''
    ranked = sorted((entry for entry in terms(avoid) if entry), key=len, reverse=True)
    for entry in ranked:
        pattern = _pattern(entry)
        if pattern:
            out = pattern.sub('', out)
    out = re.sub(r'\s+,', ',', out)
    out = re.sub(r'[^\S\n\r]{2,}', ' ', out)
    return out.strip(' ,')
