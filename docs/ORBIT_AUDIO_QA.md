# Live audio response verification � 2026-09-15

## Follow-up correction after user reported unrelated jiggle

The initial patch did not sufficiently preserve loudness differences or make the visible outer rings respond promptly. Replaced logarithmic byte-level ring drive with waveform RMS amplitude, split into bass/mid/high using FFT power. Quiet sounds now stay proportionally quiet; bass has the strongest displacement. Attack/release smoothing uses elapsed audio time. Removed autonomous camera tilt, scene rotation, and idle animation from this visual so silence settles to a stationary scene.

With the real 437-song catalog (76 rings), the old outer-ring propagation was over four seconds. The complete scene now caps outward travel at 0.8 seconds. Outer rings retain 45% of the drive instead of falling to zero. Pausing, changing songs, suspended audio, and long frame gaps clear stale history.

## Actual player + rendered scene test

An isolated browser page mounted the real SongVisualizer and OrbitGalaxy with the same analyser and the full catalog. A WAV contained an 80 Hz hit at 2 seconds and a ten-times-louder hit at 4 seconds, followed by silence. Scene render callbacks measured actual mesh positions, not a mocked analyser.

- 697 rendered samples; 76 rings.
- Quiet hit: first ring peak at 2.060 s, lift 0.18110; outer ring peak 2.860 s.
- Loud hit: first ring peak at 4.060 s, lift 1.80897; outer ring peak 4.860 s.
- Measured loud/quiet response: approximately 10:1.
- In the silent tail all ring lifts returned to effectively zero (5.34e-35).
- Repeated the full playback at Volume 0: 666 rendered samples, every measured ring lift zero throughout both hit windows and tail.

`node scripts/tests/orbit-audio.mjs` also passes linear amplitude, frequency isolation, silence despite stale FFT, 30/120 FPS response, pause, song switch, frame-gap reset, propagation, and outer-ring checks. Production build passed and installed executable hash matches release. Running user app preserved; restart loads the replacement.

## Sync check

A fresh real WhisperX run on an isolated copy of Dusky Hour completed in 10.12 seconds, status ready, 20 timed lines, method whisperx-recognized-vocals. This independently checks sync; the user's subsequent screenshot was a separate writing/lyric-format validation failure, investigated in the same task.

## Writing regression repair

Generated lyrics now remove unsupported standalone bracket annotations and narrowly recognized model boilerplate before validation. Official sections and Singer A/B routing remain intact. Untagged sung openings are preserved for repair, never silently truncated. Ban and duplicate-title checks remain enforced. Initial local-writer temperature is 0.75, repair temperature remains 0.65. Two actual Ollama requests passed with distinct titles and no banned terms.

Full Python suite after the changes: 294 passed plus 10 subtests. Existing source-contract tests were updated to expect the higher-resolution analyser and absence of autonomous orbital movement.

## Real complete generation run

Used the second actual writer result, Departing Horizon, with Live settings (melody mode, 32 steps), isolated output folder, and the actual YuE2/thumbnail/WhisperX engines. No engine stages were mocked. Completed in 156.55 seconds: 199.44-second stereo song, cover.png present with no cover error, automatic sync after thumbnail, status ready with 16 lines / 88 timed words, needs_lyric_sync=false, no sync error. Proof and generated artifacts are under outputs/orbit-audio-qa/pipeline-library and pipeline-result.json. All helper workers exited; user app preserved.

## Ambient orbit restored

User clarified that continuous ring rotation and camera orbit must remain. Restored camera auto-orbit, steady scene rotations, and gentle independent ring turning. They are separate from amplitude-driven vertical ripples. The invented sinusoidal camera tilt remains removed. Regression checks now require steady rotation during silence while vertical audio lift stays zero; amplitude, propagation, and mute behavior are preserved.

## Full three-dimensional orbit rates
Restored exact original Orbitwave camera speed (0.25) and three-axis scene rates (0.018, 0.006, 0.009 radians/second). Previous restoration mistakenly retained slower YuE2 rates, making turnover difficult to see. Tests compare rates against the original source and verify front/edge/underside viewing directions across the orbit. Audio-response tests and 50 studio contract checks pass.
