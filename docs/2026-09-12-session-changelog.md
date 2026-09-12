# Session changelog — 12 September 2026

Work in this session was on **YuE2 Studio**: Easy-mode creation, Video Studio visualizers, karaoke, lyric sync, and stems. Japanese J-pop (`カラフル・ランデヴー`) exposed several Windows Unicode bugs that English titles never hit.

**How to pick up the work**

- **Desktop UI** (Easy templates, Cancel, send-arrow pulse, Translate to English, stem-job wiring): relaunch `YuE2 Studio.exe` in the repo root. That file was rebuilt during the session.
- **Video Studio, lyric sync, stems, Demucs**: these run from the Python sidecar (`python/video_studio/`, `python/lyrics_sync.py`, `python/demucs_runner.py`). Fully quit the app so the sidecar restarts. Close and reopen Video Studio after that so it does not keep a cached page.

---

## Bugs found and fixed

### 1. Spectrum and Bars were the same visualizer

**Where:** Video Studio presets.

Spectrum was a centered copy of Bars. Bars already sat on the floor. Spectrum overlapped the cover.

**Fix:** Removed Spectrum. Kept Bars. Also dropped Ring (clone of Orbit) and Mirror (clone of Wave). FFT bands are now **log-spaced** so the display is not a bass-left ramp. Pulse no longer secretly drew Orbit on top of itself. Wave and Grid sat through the cover; they now sit low. Tunnel/Pulse used wall-clock time; they now follow song time.

### 2. Sync Lyrics from Video Studio looked stuck on “Queued / Syncing…”

**Where:** Video Studio lyrics overlay vs main library.

Main-page sync uses Tauri `sidecar_http`. Video Studio is an iframe and polled `/api/jobs/...` with `fetch`. The job often **did start**, but this page never showed progress. The preview player can also keep the WAV open on Windows, which can stall Whisper.

**Fix:** The main window pushes live job snapshots into Video Studio. Sync releases the audio file while Whisper runs, then restores it. Polling uses timeouts and retries.

### 3. “Queued” was real, but the UI made it look frozen

The studio runs **one job at a time**. Lyric sync waits behind song generation, stems, or cover art. Video Studio showed **Queued** plus a **Syncing…** button with no explanation. The main job drawer already made that obvious.

**Fix:** Button reads **Queued...** while waiting and names the job ahead of it, e.g. “Queued behind song generation.” Preview keeps playing until Whisper actually starts. Polling no longer gives up on a known job id.

### 4. Easy templates fired generation immediately; J-pop lyrics came out in English

**Where:** Create → Easy.

Clicking J-pop called `sendChat()` at once, so there was no chance to add notes. Gemini was always told `Language: en`. The template saying “Japanese diction” never overrode that. Typing “Japanese language J-Pop” in **What’s the vibe?** still sent `en`.

**Fix:** Clicking a template **fills the vibe box and waits**. Send with the arrow. J-pop / City pop / anime opening default to Japanese; K-pop to Korean; Brazilian phonk to Portuguese; Opera to Italian. Free text like “Japanese language…” is inferred. Gemini is told to write **all sung lines in native script**, not English or romaji-only. `startGeneration` now receives the language in the same turn (React state had not flushed yet).

### 5. Cancel on Easy did not return to the start page

Cancel stopped the job in the backend but left the chat thread up, with elapsed time still moving.

**Fix:** Cancel returns to the Easy template page, clears the timer, and ignores late job polls.

### 6. Template clicks appended instead of replacing

Choosing another template kept or appended the previous prompt.

**Fix:** Each template click clears the box and inserts only that template.

### 7. Lyric sync crashed on Japanese lyrics (`charmap`)

```
UnicodeEncodeError: 'charmap' codec can't encode character ...
```

The Whisper worker printed UTF-8 JSON (`ensure_ascii=False`) into a Windows `cp1252` pipe.

**Fix:** Worker env `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`. Stdio forced to UTF-8. Progress JSON is ASCII-safe.

### 8. Stem split “failed” / did not auto-start

Studio showed **This song has not been separated yet** with **Split into 4 stems**. Auto-split often *had* started, then the UI lost the job because another utility job (lyric sync) occupied `utilityJob`. The empty prompt looked like a crash.

**Fix:** Stem progress is taken from `status.jobs`, not only `utilityJob`. Studio retries auto-split once per song. Failed jobs show the real error.

### 9. Stem extraction exited with code 1 on Japanese titles

Logs:

```
print(f"Separated tracks will be stored in {out.resolve()}")
UnicodeEncodeError: 'charmap' codec can't encode characters ...
```

Demucs printed `カラフル・ランデヴー` to stdout and died **before** separating. English folder names never hit this.

**Fix:** Same UTF-8 pipe treatment as lyric sync, in `demucs_runner.py` and the stem subprocess env. Errors now surface the last useful log line instead of only “exited with code 1”.

### 10. Dual-language toggle did not appear after a full app restart

The English translation **was** on the song and on `timed_lyrics.json`. Video Studio hid **Both languages** until JS saw `line.translation`, and `/video-studio` HTML could stay cached.

**Fix:** GET `/api/library/{folder}/timed-lyrics` always stamps `english_translation` from `song.json` onto timed lines. Video Studio pages are `Cache-Control: no-store`. The dual row is visible in the HTML.

### 11. Cover **None** still left a circular hole in Orbit / Sunburst

First pass only shrank the hub (`span * 0.05`). That is still a disk over the face.

**Fix:** With Cover off, Orbit / Halo / Sunburst / Arc / Pulse start at the **center** (inner radius 0). Bars, Wave, Grid, Aurora were already floor/field looks.

---

## Features added

### Easy Create

- Template click no longer generates. Prompt box expands, the page scrolls to it, caret at the end, send arrow pulses cyan.
- **More templates** sits in the grid under the last thumbnail (replaces header **View all 25**).
- **Translate to English** on the Easy lyrics card, Custom translation field, and Edit song. Sung lyrics stay Japanese; English is display-only (karaoke / review), never sent to YuE2.

| Want | Sung | Overlay |
|---|---|---|
| Japanese only | Japanese lyrics | Japanese |
| English only | Lyrics language = English | English |
| Both | Keep Japanese lyrics | Japanese + English underneath |

### Video Studio — lyrics

- **Both languages / Sung only** under Lyrics Overlay when a translation exists. Default **Both**: Japanese word-highlight on top, English as a smaller line under it, in preview and MP4.
- Word-level English highlighting was **rejected on purpose**. Whisper times sung Japanese syllables. English is a whole-line translation with different word order (`駆け出すキミの隣で` vs “Right beside you as you start to run”). Fake English word timing would light the wrong word.

### Video Studio — visualizers

Presets now include the reference looks (Motion Array / oscilloscope / skyline / split title card), not only the original ten:

| Preset | Role |
|---|---|
| Orbit, Pulse, Halo, Sunburst, Tunnel, Arc, Disc, Rings, Spiral | Circular / radial |
| Bars | Floor EQ with glow, gradient, reflection |
| Split | Mirrored side bars, **lyrics in the center** |
| Skyline | City bars + floor reflection, **lyrics in the center** |
| Peak | Rainbow mountains + mirror, **lyrics in the center** |
| Wave, Scope | Waveform / oscilloscope |
| Flow, Mesh, Aurora | Layered / Motion Array waves |
| Grid | LED matrix |

Cover **on**: circular presets wrap the round thumbnail. Cover **off** or a full-bleed background: they fill the frame instead of leaving a fake hole.

### Video Studio — cinematic visualizer pass

- Added a shared cinematic atmosphere layer: slowly drifting primary/secondary color blooms, a soft horizon light, and a restrained edge vignette.
- Reworked canvas color handling so the two selected template colors generate a continuous derived hue route, including a third midpoint color instead of alternating only the two inputs.
- Added a template-anchored full color-wheel sweep for rainbow-oriented **Peak** and **Disc** looks.
- Tiered up **Orbit** with layered neon rings, log-spaced audio bars, an audio-reactive inner ribbon, orbiting nodes, and a rotating detail ring.
- Tiered up **Bars**, **Wave**, **Tunnel**, and **Peak** with floor bloom, peak caps, layered trails, perspective depth, chromatic structure, and spectrum-edge highlights.
- Kept the existing preset controls, lyric layout, cover behavior, and MP4 render path unchanged. No new EXE is required for this sidecar-only pass.

### Video Studio — Bars / Skyline regression

The palette pass briefly made Bars and Skyline appear empty because their gradient helpers still expected hex colors after the presets began receiving generated `hsla(...)` colors. The shared color helper now accepts both formats. Live preview confirms both presets render their reactive columns and reflections without console errors.

### Video Studio — particles

- **Rain:** thin vertical streaks, nearer drops longer and faster, slight wind. No glowing sausages.
- **Stars:** shooting stars only fall from the top on a downward diagonal (no horizontal streaks from the sides).
- **Bubbles:** glass rim, highlight, slight squash — not neon circles.
- **Confetti:** removed.

---

## Why this batch happened together

The J-pop path (Japanese lyrics, Japanese folder name, Video Studio karaoke, stems, dual-language overlay) was the first full non-English song through these tools. Several subsystems assumed ASCII: Windows console encoding, `Language: en` on Easy, stem UI bound to a single `utilityJob`, visualizers built around a circular cover.

---

## Files touched (high level)

| Area | Paths |
|---|---|
| Easy Create / language | `src/App.tsx`, `src/App.css`, `python/ai_assist.py`, `python/ai_guides.py` |
| Translate to English | `src/App.tsx`, `src/api.ts`, `python/ai_assist.py`, `python/main.py` |
| Video Studio UI + viz + particles | `python/video_studio/index.html`, `video_studio.js`, `video_studio.css` |
| Lyric sync Unicode | `python/lyrics_sync.py`, `python/lyrics_align_worker.py` |
| Stems Unicode + errors | `python/main.py`, `python/demucs_runner.py` |
| Timed lyrics + translation stamp | `python/main.py` (`get_timed_lyrics`) |
| Contracts | `python/tests/test_studio.py`, `python/tests/test_studio_contract.py`, `python/tests/test_ai_guides.py` |

---

## Not done / declined

- Word-synced English karaoke (see above).
- Auto-translate during Easy generation (button only; extra Gemini call before YuE2 was out of scope).
- New EXE is **not** required for Video Studio JS/Python sidecar fixes; it **is** required for Easy-mode React changes already baked into `YuE2 Studio.exe`.
