# Changelog

All notable changes to YuE2 Studio are documented here. The same notes are used for GitHub releases.

## [0.6.2] — 2026-09-13

### Changed
- Windows generation uses cuDNN attention and CUDA graphs instead of math SDPA. On an RTX 3090, a 4:22 song generated in 3:09 (was ~15 minutes). FlashAttention is still Linux-only on this torch wheel; GraphAR auto-flash is forced to cuDNN, with eager decode if graph capture fails. 24 GB cards use a 1024 NAR tile. Clear VRAM or restart so the worker reloads.

### Added
- **Radio** in the top modes: play the library as a station from the desktop or a LAN browser.
- Optional **LAN sharing** on port **6969** (System on/off, no password). Desktop sidecar stays on 7794.

### Notes
- Official “faster than playback” Linux numbers assume FlashAttention. This Windows build uses cuDNN + CUDA graphs instead.
- Do not expose LAN sharing to the public internet.

## [0.6.1] — 2026-09-13

### Fixed
- SheetSage2 install rewrites `config.json` so the model uses the local MERT folder. Verification treated that rewrite as a missing file, so install always ended with “required files are still missing” and a 2 KB remaining download. Config is now marked mutable. Weights already on disk are reused.
- After a song finishes, the library banner no longer keeps a red elapsed clock running. Library playback uses the native audio element (Web Audio was muting cross-origin tracks in the desktop WebView).

## [0.6.0] — 2026-09-13

### Added
- **Remix this song** in the library menu: generate a new recording from the saved YuE2 score. Keep the melody, or keep melody and chords.
- **Cover from audio** with optional SheetSage2: transcribe a recording to an editable ABC lead sheet, then re-sing it with YuE2. Install SheetSage2 from Models (CC-BY-NC).
- Video Studio scene tiles (black, white, grayscale, chroma green/blue/magenta, plus washes). Scene color is backdrop only.
- New visualizer presets: Analog, Equalizer, Cascade, Stereo, Silk, Dots, plus reworked Sunburst, Mesh, and Peak.
- `/api/video/prepare` unloads the YuE2 GPU worker before a canvas capture.

### Changed
- Generation style is a compact official YuE2 line, not MiniMax structured captions. Performance tags such as `[Spoken]` move out of lyrics into style.
- Off-mode semantic CFG uses the official **1.01** default when the form is left at 1.0.
- Voice-profile compiled prompt is compact YuE2 style and is applied on generate.
- Native ABC placeholder uses Vocal/Ins voices. Remix melody mode strips chord quotes from music lines only.
- Peak, Bars, Wave, Grid, and Equalizer sit on the bottom edge in both 16:9 and 9:16. Lyrics stay above Peak.
- Video Studio capture: looping background video is not seeked every clock tick; note particles use cached sprites; photo/video backgrounds skip extra glow passes; draw rate is capped during render; FFmpeg uses `-preset veryfast`.

### Fixed
- Library and Video Studio playback no longer restart on status polls.
- Library listing no longer renames audio files on GET (that could yank a playing wav).
- Particles draw with visualizers on every scene, including black.

### Removed
- Weak or duplicate Video Studio presets: Aurora, Skyline, Flow, Rings, Spiral, Helix, Vista, Contour, Disc, Ribbon.
- Primary/Secondary color pickers in Video Studio.

### Notes
- Remix uses the saved score (`score.abc`). Cover from audio needs SheetSage2 installed.
- Covers are a new performance of the transcribed tune, not a mix of the original vocal take.
- Model weights, private runtimes, API keys, and personal media are not in this source tree.

## [0.5.1] — 2026-09-12

- Video Studio visualizers: derived multi-color palettes, full-spectrum Peak and Disc, cinematic atmosphere, richer Orbit depth, corrected Bars/Skyline.

## [0.5.0] — 2026-09-11

- Sony Woosh-Flow in Effects (CC-BY-NC), optional Models installer, mono playback through both ears, Combine sound tracks, Gemini prompt help for effects.
