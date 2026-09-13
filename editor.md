# Native multitrack Studio

YuE2 Studio now ships one integrated editor: the native, stem-aware multitrack Studio. The former AudioMass browser bundle and `/editor` route were removed on 2026-08-13 because they duplicated a weaker, disconnected workflow.

## Current workflow

- Open **Studio** from a song's `…` menu or from its expanded Stems branch.
- Songs with Demucs stems open synchronized Bass, Drums, Other, and Vocals lanes beside the preserved original mix.
- Songs without stems can begin local four-stem extraction from inside Studio.
- Import as many local WAV, MP3, FLAC, M4A, AAC, or OGG tracks as the machine can reasonably mix.
- Drag reusable Effects-library sounds onto the timeline. A 5-second clip stays 5 seconds.
- After **Add to Studio** on the Effects page, **Open Studio** jumps straight to that song.
- Move imported tracks along the timeline, adjust lane volume, mute or solo them, and remove the project copy without touching the source file.
- Work on a 10-minute timeline canvas. Zoom with the slider or Ctrl/Cmd + wheel. Exports still stop at the last audible clip.
- Use **Move** (V) to slide clips, **Razor** (C) to cut, and **Range** (R) to select time for effects.
- **Insert space** splits at the playhead and pushes later audio to the right so a countdown or spoken line can sit in front of the song.
- Drag the yellow clip handles to create cosine fade-ins and fade-outs.
- **All lanes** slides every clip together, including the Original mix reference.
- Transport jumps to song start, clip/range start, clip/range end, or song end.
- Drag the yellow gain line on a clip to raise or lower level. **L/R split** shows separate left and right waves with independent channel lines.
- Drag a time range across the timeline, then target **This lane** or **All lanes**.
- Apply range mute (opens a gap) or any of the documented region effects below. Multiple effects can overlap; numbered per-type menus keep their instances manageable.
- Add non-destructive trim, fade-in, fade-out, and loop regions.
- Preview effect regions during playback and save the complete session into the song metadata.
- Export a custom WAV mix, a selected range, an instrumental, or an acapella into the song's local `mixes` folder.

## Region effects

Select **Range**, drag across a lane, choose **This Lane** or **All lanes**, then click an effect. Timeline chips and the inspector use matching numbered names such as **Echo 1**. Click a chip—or choose it from its effect-type menu—to adjust Amount, Fade in, and Fade out. **No fades** makes that effect begin and end immediately.

| Effect | What it does | Useful for |
| --- | --- | --- |
| Quieter / Louder | Lowers or raises level | Phrase emphasis and quick balance changes |
| Echo | Adds repeating delayed copies | Vocal throws and rhythmic tails |
| Reverb | Adds a simulated acoustic space | Depth, atmosphere, and transitions |
| Auto-pan | Moves sound between left and right at a fixed musical rate | Headphone movement and alternating lyric effects |
| Tremolo | Pulses volume four times per second | Rhythmic motion and tension |
| Low-pass | Progressively removes high frequencies | Underwater sound, muffling, and buildups |
| High-pass | Progressively removes low frequencies | Thin intros, transitions, and removing rumble |
| Telephone | Combines narrow filtering, mid presence, and light drive | Phone, radio, intercom, or lo-fi vocals |
| Saturation | Adds harmonics and soft clipping | Warmth, grit, and denser drums or vocals |
| Stereo widen | Increases left/right difference | Broader choruses, pads, and backing parts |
| Clarity EQ | Adds low definition, presence, and air | Bringing a buried part forward |
| Compressor | Reduces dynamic range and adds density | More consistent vocals, bass, or drums |
| Limiter | Catches sharp peaks | Reducing clipping risk after louder effects |
| Auto level | Smooths uneven loudness | Fast phrase-to-phrase balancing |
| Normalize | Moves audio toward a standard loudness target | Preparing a region for consistent output |

**Stereo note:** Stereo widen has little effect on a truly mono source. For deliberate placement, enable **L/R split**, select a cut clip, and use **Left only**, **Right only**, or **Swap L ↔ R**.

## Design rules

- The original generated WAV is never overwritten.
- The original-mix lane is a reference and is never doubled into stem bounces.
- All editing stays inside the MiniMax application; no browser popup or external service is required.
- Stem extraction, imported audio, edits, and rendered mixes remain local to the song library.
- The interface follows the app's deep-sea purple styling instead of embedding unrelated third-party chrome.

## Useful future additions

- Lyric-derived verse, chorus, bridge, and outro markers on the Studio ruler.
- Detailed automation curves beyond clip fade handles.
- Per-lane effect ordering, bypass, and wet/dry controls.
- Mix buses, master metering, limiter controls, and reusable effect presets.
- Section replacement or regeneration when YuE2 exposes a reliable local continuation/editing path.
