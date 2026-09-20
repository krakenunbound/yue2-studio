# Automatic lyric sync and instrumental-intro repair

- Normal creation and Live now use the same backend order: audio, thumbnail attempt, Whisper vocal recognition plus WhisperX alignment, completion.
- Instrumentals skip lyric sync. Thumbnail/sync errors preserve the song. Sync errors keep the retry flag.
- Removed whole-recording forced alignment of supplied lyrics. It could place unsung text over instrumental passages.
- Recognition uses no lyric prompt, no previous-text conditioning, and no speech-only VAD (that VAD discarded all singing in the reproduced song).
- Only confidently matched saved lyric lines receive timestamps. Unrecognized lines are omitted, not distributed over music. Translations retain original line indices.

## Real audio verification (2026-09-15)

- Chromatic Drift: previous first lyric 0.480 s; repaired first lyric 30.461 s. All 16 saved lines matched. Original metadata and subtitles backed up in outputs/sync-qa/chromatic-original.
- Repeated sync on the original audio produced the same 30.461 s onset.
- Added 60 s of the actual instrumental opening ahead of the full audio: first lyric 90.461 s; all 16 lines retained. 15 line starts shifted exactly 60 s; one differed by 0.28 s due to recognition/alignment variability.
- Instrumental-only first 20 s: no saved lyrics matched, worker returned a clear failure and produced no fabricated timed-lyrics file.
- Shared generation smoke test reused existing music output, then ran actual thumbnail generation and actual WhisperX in sequence. Saved cover existed before sync began; final song metadata had ready timing and no pending-sync flag. Evidence: outputs/sync-qa/auto-events.json. The music model itself was not rerun for this postprocessing test.
- Native application rebuilt and installed as YuE2 Studio.exe. Previous executable backed up in outputs/sync-qa.

These checks verify the reported timing failure and postprocessing order; they are not a guarantee of perfect word timing on every vocal style or language. Unrecognized lyrics remain in song metadata but are not animated as if recognized.
