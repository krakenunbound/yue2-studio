# Gemma writing recovery — 2026-09-15

The recent Live logs showed generated drafts rejected after three attempts for banned wording and a missing opening section tag. Normal user/test cancellation also appeared as an error traceback.

## Changes

- Restore a missing opening `[Verse]` in generated lyrics only when there are at least two sung lines and the candidate passes formatting checks and is not a recognizable production-instruction dump. Preserve every existing sung line and section. Other validation still runs.
- For local generated drafts whose only remaining problem is banned wording, ask Gemma to repair just the offending title/lines. Supply the exact rejected terms, use lower sampling temperature, and reuse one replacement for repeated chorus lines.
- Keep valid titles/lines unchanged. Ignore unsolicited response fields; reject missing keys, empty/non-string values, line breaks and section-tag insertions. Revalidate the complete result, including all user bans, language and formatting.
- Preserve the three-attempt limit. Focused repair must fit the existing local prompt budget; otherwise use the normal bounded retry. Never truncate the avoid list or accept a still-invalid draft.
- Log intermediate repairs and requested stops at INFO. Exhausted draft validation is a WARNING without a crash traceback. Explicit cancellation returns HTTP 409. Genuine transport/runtime failures remain errors.

## Verification

- 78 tests pass across writing recovery, quality, lyric preferences, Ollama writing/transport, and AI guides.
- Existing quality tests now isolate title lookup from the real library so the cancellation test cannot miss its deadline while scanning hundreds of songs.
- The configured `gemma3:4b` produced three fresh valid songs using the user's real avoid list (robot bakery, missed ferry, raccoon mayor). No audio generation or library writes were performed.
- Injected a draft containing a missing initial tag, banned title `Trace`, and repeated `whisper` chorus. The first real Gemma repair introduced another banned phrase; validation rejected it. The next correction passed. Final recovery took 3.73 seconds, preserved both original valid lines and repeated chorus structure, and ignored an unsolicited replacement for the already-valid title.
- Real-call evidence is in `outputs/gemma-recovery-qa/results.json` (initial checks) and `repair-results.json` (final targeted recovery).

These changes improve bounded recovery; they cannot guarantee every model response is valid. Persistently invalid drafts still fail clearly instead of weakening the user's preferences.
