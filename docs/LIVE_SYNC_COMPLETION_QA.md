# Live lyric-sync completion regression — 2026-09-15

## Reproduced in the native application

Launched `F:\YuE2-3B\YuE2 Studio.exe` and used Live → Start live with the normal five-song buffer. No generation or alignment calls were mocked.

- Live generated **Circuit Horizon** (Techno, vocal duet).
- Job `e4ca4548b0cc4dd7868de1f8b184311e` finished with `status=succeeded`, `progress=1`, `phase=Song ready`, lyric sync `ready`, 24 timed lines, and `needs_lyric_sync=false`.
- The native Live banner remained **98% — Aligning saved lyrics with WhisperX**, and the generated song was not added to its playback queue.
- The executable was built at 19:50:50, before the existing `src/LivePage.tsx` completion fix saved at 19:56:56. That fix keeps the refresh callback in a ref so a parent refresh cannot invalidate the completion poll before it publishes success and releases the next generation.
- The old executable is backed up under `outputs/live-sync-fix-qa/YuE2-Studio-before.exe`; the completed backend snapshot is in `outputs/live-sync-fix-qa/before-job.json`.

## Additional cleanup defect fixed

`python/lyrics_sync.py` closed a worker's stdout from the job thread while its reader thread could be blocked waiting for output with the pipe buffer lock held. This could block completion, cancellation, and the timeout fallback before termination was attempted.

The reader now owns closing stdout. Cleanup terminates the worker first, uses bounded process waits, and joins the reader with a timeout. Process termination does not hold the global process lock.

## Regression checks

- New real-subprocess tests reproduced all three cleanup failures before the patch; all three pass after it. They verify completion, cancellation, timeout, child termination, and reader-thread cleanup.
- All nine automatic lyric-sync tests pass, including error recovery, thumbnail ordering, cancellation, and CPU timeout fallback.
- All eight vocal-timing evidence tests pass. Alignment and lyric matching behavior were not changed by this fix.
- `node scripts/tests/live-completion.mjs` passes, including the negative control that reproduces the old 98% freeze and the Stop guard against late completions.
- `npm run tauri build` succeeds (TypeScript, Vite, and Rust release build).

## Native retest

The rebuilt executable was copied to `F:\YuE2-3B\YuE2 Studio.exe` and relaunched. Used Live → Start live again, with the existing local Gemma writer and five-song buffer:

1. **Chromatic Descent** — instrumental; job `912864bf78db45e1892c5d82485c3c25` succeeded at 100%. Live added it to the queue and automatically generated the next song.
2. **Prism Shift** — vocal; job `f45bb188cc704ef6af6d51a322f20204` succeeded at 100%, with lyric sync `ready` and 20 timed lines. Live's queue grew to seven songs and it advanced to writing an East Coast boom bap vocal duet. No 98% stall and no remaining WhisperX process.

Stopped Live after these consecutive completions. Backend snapshots are saved in `outputs/live-sync-fix-qa/after-jobs.json`.

The user then took over the rebuilt app and opened Prism Shift in Radio. Left that user-controlled app session open; the test generation jobs were complete and no WhisperX workers remained.

Deployed executable SHA-256: `FAC4EB6EA5009EF1741302B73D94208E60D6C2A49D995C6A7F3A2AB5774B3B97`.

These checks verify generation completion and continuation, not an overnight soak or the auditory accuracy of every saved subtitle. During the retest, the user reported early highlighting in the existing **Through the Grid** track. Its timing file was saved on September 14 at 05:44:29, with the first lyric at 1.54 seconds. Existing song timings were not rewritten. A read-only review list of early starts and missing timings is saved in `outputs/live-sync-fix-qa/library-timing-review.md`; early starts are candidates to review, not proof of incorrect timing.
