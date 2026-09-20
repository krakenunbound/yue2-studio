# Studio effects repair and shared Effects tracks — 2026-09-15

## Fixed
- Effect import route accepts nested genre/song folders and returns the correctly encoded audio URL. Previously failed with Method Not Allowed.
- Specific Studio session PATCH route is registered before the catch-all song-details PATCH route. Previously Save session could produce a 422 instead of saving.
- Native Tauri Windows dragDropEnabled is false, as required by the installed Tauri schema for HTML5 timeline drag/drop. There were no native file-drop handlers depending on the intercepted events.
- DSP buttons accept a selected track/clip without requiring a dragged range. Explicit ranges still restrict processing.
- Library/generated sounds default into one Effects track, retaining separate source audio and independently movable clips. Additional effects tracks and a move-selected-sound destination are available.
- Group mute, solo, level and lane-wide edits apply across its sources; individual clip movement stays independent. Combine preserves a common lane; restore brings back membership and offsets.
- Media elements remain mounted when visual grouping changes. Removing/combining sources disconnects old audio graphs so restoring originals reconnects them correctly.
- Generated effects retain their known duration before waveform decoding completes.

## Verification
- Browser UI on isolated localhost fixture, no user song changes: add Thunder and Coffee into one Effects track; move Coffee to 4.006 s with Thunder unchanged at 0; create Effects 2 and move Coffee there/back; group solo playback; apply Quieter only to Vocals; save/reopen; combine/restore; drag Rain from library onto Effects at ~7 s; custom export creates Studio Check (Studio Mix).
- Browser media-node identity check after playback and moving Rain to Effects 2: same audio element remains connected.
- Real FFmpeg deterministic-tone tests verify independent offsets, overlap mixing, mute, and isolation of a vocal effect from another track; combine/uncombine preserves lane and offsets.
- Frontend TypeScript/Vite and native release build succeeded. Updated workspace YuE2 Studio.exe; backup under outputs/studio-effects-qa.
- Final full suite: 284 passed, 10 subtests passed. One earlier run during concurrent UI export hit a timing-sensitive AI cancellation test and cascading lock failures; a fresh full rerun passed without source changes to those tests.
- Windows native drag configuration verified against installed Tauri documentation; drag/drop UI exercised in Chrome. Native desktop dragging was not separately automated.

Empty extra effects tracks currently exist only until the Studio closes; tracks containing sounds persist in the saved session. Existing saved ungrouped imports remain in their original layout and can be moved into Effects using the destination control.
