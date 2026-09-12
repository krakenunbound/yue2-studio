# Desktop Easy mode validation — September 9, 2026

Used the actual `YuE2 Studio.exe` Windows interface through Computer Use. Entered a request for a complete cinematic alternative rock song named **After the Rain** in Easy mode and clicked Send. No backend API was used to initiate this song.

Gemini 3.5 Flash completed chat, style and lyrics calls. The UI displayed a compact YuE2 style and 40 lyric lines. YuE2 then completed full score planning, semantic generation, all 32 acoustic steps, stereo decoding and library save without OOM. The song appeared in My songs with its cover and 4:14 duration. Clicking its Play button started the waveform display and advanced the player to 0:06; Stop reset playback. This verifies playback operation, not a listening-based musical quality assessment.

- Job: `7a592094` (prefix), seed `1303145998`.
- Settings: full score mode, 32 steps, CFG 1, temperature 1, top-k 100.
- Synthesis input: 3,229 prefix tokens and 6,355 music tokens.
- At every completed synthesis step: 7.827 GiB allocated and 10.494 GiB reserved. These samples are not peak-allocation measurements.
- Output: `outputs/library/After the Rain/After the Rain.wav`, 254.199 seconds, 48 kHz stereo. Song metadata and cover are in the same folder.
- Generation started at 22:47:45 and was saved at 23:00:53 local time.
- Exact synthesis inputs: `outputs/recovery/dab0e77e350b4840a591911337bad654`.

Closed the app through its Close button, installed the rebuilt executable, then reopened it. The Logs panel recovered the completed run's records with their original timestamps. Full tracebacks and error persistence were also covered by regression tests. Test-generated historical entries were preserved separately in `outputs/logs/initial-regression-validation.log`; new automated tests use isolated temporary logs.

The UI run exposed a blank Easy mode style summary that still expected MiniMax headings. Updated the summary to display YuE2 plain-text descriptions. After rebuilding, a second Easy mode Gemini request visibly populated the Sound preview. Cancelled this preview-only run during score planning and observed `Cancelled` in the app. Closed the app and verified no app/worker processes remained. The installed EXE SHA256 is `AA1BE0E03060DBFB72D00D1624658CAAFAB9EDE1536865D1486D8D0038EBCA0A`.

This real desktop run did not reproduce the user's previous OOM. Its old traceback was not persisted by the former logger, so its exact cause remains unconfirmed. Future runs now preserve tracebacks, allocator diagnostics and synthesis inputs for investigation.
