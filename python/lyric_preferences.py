"""Local, user-owned lyric preferences, independent of provider credentials."""
import json
import threading
from config import OUTPUTS_ROOT

PATH = OUTPUTS_ROOT / 'settings' / 'lyric-preferences.json'
_lock = threading.RLock()


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


def prompt():
    avoid = load()['avoid'].strip()
    if not avoid:
        return ''
    return ('\n\nUSER LYRIC AVOID LIST\n'
            'Apply these user preferences whenever drafting or rewriting lyrics. Entries can be words, phrases, imagery or writing habits. '
            'MANDATORY: NEVER USE these words, phrases, or patterns in generated or rewritten lyrics. Match words without regard to case; slash-separated alternatives ban both forms, and blanks or ellipses describe phrase patterns to avoid. Replace violations naturally during rewrites. '
            'Keep the intended meaning and useful chorus repetition; do not replace banned wording with equally formulaic filler. '
            'Before returning lyrics, check the draft against this list and revise violations. '
            'These preferences concern lyric content only; preserve the required output format.\n'
            + avoid + '\nEND USER LYRIC AVOID LIST\n')
