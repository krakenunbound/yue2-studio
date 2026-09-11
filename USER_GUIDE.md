# YuE2 Studio user guide

For version 0.5.0. Start with the quick start, then use the section for the task you want to do. The README gallery uses older screenshots; some controls have changed.

## Contents

- [Quick start](#quick-start)
- [Installation, updates and models](#installation-updates-and-models)
- [Create: writing and generating songs](#create-writing-and-generating-songs)
- [Library: organizing finished work](#library-organizing-finished-work)
- [Effects: generating sounds](#effects-generating-sounds)
- [Studio: arranging and mixing](#studio-arranging-and-mixing)
- [Lyrics synchronization and karaoke](#lyrics-synchronization-and-karaoke)
- [Cover art and video](#cover-art-and-video)
- [Keys, System, Jobs and Logs](#keys-system-jobs-and-logs)
- [Troubleshooting](#troubleshooting)
- [Files, backups and sharing](#files-backups-and-sharing)

## Quick start

1. Install the Windows release in a folder you can write to. Launch YuE2 Studio from its shortcut or executable.
2. Open **Models**. Install **YuE2 music generation** if you want songs. Install only the optional features you need. Wait for setup to finish before generating.
3. In **Create**, start with a short, straightforward idea and a supplied style/template. Review the description and lyrics before generating. Use instrumental mode for music without vocals.
4. Watch the job's phase and elapsed time. The stages have different speeds; 70% does not necessarily mean 70% of the time has passed.
5. Play the completed result in **Library**. Keep a result you like before experimenting further.
6. For sound effects, install Woosh or Stable Audio, then open **Effects**. For Woosh, try `pouring a cup of coffee` with default settings and no prompt enhancement first.
7. To arrange sounds with a song, choose **Send effects to**, click **Add to Studio**, and open that song in **Studio**. Move the sound clip to the desired time, save the session, and export a custom mix.

Gemini is optional. Local generation does not require a Gemini key. Cloud writing/enhancement actions require your own configured provider and may incur provider charges.

## Installation, updates and models

The installer includes the desktop app, its backend Python, and FFmpeg. Large models and their separate runtimes are downloaded only when you choose Install in **Models**. A fresh installation therefore does not mean every generator is ready immediately.

Close the app before installing an update. Back up your work first. The installer is designed to preserve your outputs and downloaded models; do not manually delete the app folder during an update, because it also contains your data.

### Choosing downloads

| Models option | What it enables | What to expect |
| --- | --- | --- |
| YuE2 music generation | Songs from musical descriptions and lyrics | NVIDIA GPU with BF16 support; installs the music model, audio decoder and GPU runtime. |
| Whisper lyrics and karaoke | Word/line timing for lyrics, with transcription fallback | Includes WhisperX, Whisper large-v3-turbo and English alignment. Other alignment languages may download on first use. |
| Cover art — Stable Diffusion 1.5 | Local song artwork | Installs Juggernaut Aftermath, an SD 1.5 checkpoint, plus its configuration/runtime. Uses an NVIDIA GPU. |
| Separate vocals and instruments | Vocals, drums, bass and other stems | Installs Demucs/htdemucs for Studio. Separation is approximate; bleed and artifacts can remain. |
| Sound effects — Stable Audio 3 | Text-driven sound effects | Small SFX model in its own CPU runtime; leaves the GPU free but can be slow. Publisher access terms may be required. |
| Sound effects — Sony Woosh-Flow | Short text-driven effects on GPU | Up to five seconds; installs all three model components, tokenizer, pinned source and a private Python 3.12/CUDA runtime. Weights are CC-BY-NC, for non-commercial use. |

**Already installed features are hidden.** A missing button can mean the feature is already ready. Use **Refresh and check space**, then check its working page. A partial installation should appear as needing setup.

Each card shows its destination, estimated download and available/required disk space. Runtime sizes are estimates. Installation needs room for both archives and extracted files, not just final weights. Cancel keeps completed downloads for another attempt; failed or corrupt files are verified before use. An interruption may require clicking Install again.

For gated Stable Audio downloads, open the publisher's terms, obtain access with your own Hugging Face account, and supply a read token with that access. The app's installation token field is not a Gemini key. No publisher access is granted by installing this app.

This app has been used on an RTX 3090 with 24 GB VRAM. File size is not the same as peak working memory: duration, decoder work and other GPU applications matter. Smaller cards are not guaranteed by this guide. Start small and avoid simultaneous GPU workloads.

## Create: writing and generating songs

**Easy mode** offers a simpler starting point. **Custom mode** gives more direct control over the model description, lyrics and generation settings. Templates provide structured examples; they are starting points rather than promises of a particular sound.

### A useful music description

Describe genre, tempo/feel, mood, voice, instruments and how the arrangement changes. Keep them consistent. For example:

> Intimate late-night jazz, relaxed brushed drums, upright bass and warm piano. A restrained alto vocal, a short instrumental opening, gentle verses and a slightly fuller chorus. Close, natural room sound.

Start with one coherent style. Change one major instruction at a time when comparing results. Contradictory descriptions, many unrelated styles, or demands for several different arrangements make evaluation harder.

### Lyrics and vocal directions

Use the lyrics field for words to be sung and song-section tags such as `[Verse]` and `[Chorus]`. **Prepare pasted lyrics** formats pasted material for YuE2; review the result. The app moves performance directions into the music description rather than leaving arbitrary directions in the sung text.

**Generate Lyrics** writes new text with the optional writing helper. **Optimize** rewrites existing lyrics. Neither is Whisper transcription or timing. Check the words before accepting a rewrite.

Choose the lyrics language correctly. An **English translation** is display-only: it is saved for review/karaoke, not sent to YuE2 to be sung. Keep translated lines aligned with the sung lines.

Voice profiles describe desired vocal traits. They are prompt guidance, not a guarantee of a fixed singer identity. Instrumental mode does not need written lyrics.

Keep the first test short. Save settings and a seed when offered if you want a more controlled comparison. Identical settings are useful for comparisons, although different hardware or software versions can still change a result.

## Library: organizing finished work

Library is the main list of songs and exported Studio mixes. Play a result and use its **More actions** menu for editing details, reusing it as a new song, opening Studio, artwork, video, stems, lyrics tools and downloads where available.

- **Edit song details** changes the saved description, title or lyrics. Changing text does not regenerate the recording.
- **Reuse as new song** starts another generation from saved information; it does not replace the original audio.
- **Playlists** collect songs for listening. **Workspaces** help organize separate bodies of work.
- **Studio Projects** provides access to saved editing work.
- **Open song folder** exposes the actual files for backup or use elsewhere.

Use descriptive song and effect names. Names are easier to recognize than the opening words of a long prompt. Before deleting a song, make sure it is not your only copy of a take or arrangement you want.

## Effects: generating sounds

Effects has its own library. Generating a sound does not automatically alter a song. Choose an engine first, then enter a name, sound description, length and optional seed.

### Woosh: begin simply

Try one source and one action:

- `pouring a cup of coffee`
- `a wooden door closing`
- `footsteps on gravel`
- `a distant thunder rumble`

Generate with defaults before adding detail. Add only the missing detail you can actually hear, such as distance or surface. Long sequences of events and elaborate recording directions can make results worse. The optional **Enhance prompt** helper can over-expand a good short prompt; enhancement is not a quality guarantee. Review its suggestion, or keep your original wording.

Woosh produces roughly five seconds per generation. The app can trim shorter, but the duration slider cannot produce a supported longer generation. Longer ambience would need a separate editing/looping approach. There is no automatic seamless-loop guarantee.

| Woosh control | How to use it |
| --- | --- |
| Avoid / negative prompt | Optional unwanted sounds. Try a short list only when needed. It cannot guarantee removal of hiss or artifacts. |
| CFG | Default 4.5; stronger guidance can change adherence and sound quality. Higher is not automatically better. Compare one adjustment at a time. |
| DOPRI5 | Recommended default sampler. Chooses its own integration steps, so the Steps control shows auto. |
| Euler | Experimental fixed-step comparison. Enables the 1–100 Steps slider. More steps take longer and do not guarantee better sound. |
| Seed | Keep it unchanged while comparing prompting or settings; change it to try another variation. |

Woosh uses the GPU and unloads YuE2 before generation. It outputs mono audio, played equally through both ears. That is centered mono, not a recording with different left and right information. Studio preserves both-ear playback and exports to stereo channels.

### Stable Audio 3 Small SFX

Start at **8 steps** and **Ping-pong**. Eight is the default, not the slider maximum. Other samplers are experimental and more steps may not help. **Decode in chunks** reduces memory requirements; disable it only to compare full decoding.

This post-trained Small SFX checkpoint does not support useful CFG adjustments or negative prompting in this integration. A disabled CFG control is intentional. Use positive descriptions of what you want, and do not expect an Avoid instruction to repair a noisy result.

### Moving a sound into a song

Choose the destination under **Send effects to**, then click **Add to Studio**. This copies the sound into that song's Studio tracks. Select the correct destination before adding. In Studio, place it at the desired point and adjust its level. Exporting a custom mix is what creates the finished song containing those changes.

For Woosh, generate on the **Effects** page and then add it to Studio. Studio's internal **Generate a sound** dialog currently uses Stable Audio.

## Studio: arranging and mixing

Studio combines the original mix, separated stems and imported sounds on a timeline. Extract stems if you need to work separately with vocals, drums, bass and other instruments. With stems present, the original mix is a reference rather than an additional copy to play over them.

### Navigation and editing

- **Play / Pause / Stop** control the arrangement. Stop returns to the beginning.
- Click or seek along the timeline to choose a position. **Fit** and the zoom controls change the visible scale, not the audio.
- **Move** slides clips. **Razor** splits them. **Range** selects a span for range operations.
- **This Lane** limits an edit to the chosen lane. **All lanes** can affect the whole arrangement. Check this before moving, inserting space or removing a range.
- Clip edges, fades and level controls shape when a sound begins/ends and how loudly it plays. The lane volume affects the lane; clip level affects a particular clip.
- **M** mutes and **S** solos. A muted lane will not contribute to a normal mix; solo can exclude other lanes.
- **Undo / Redo** handles ordinary timeline edits. Save the session before closing.

**Mono wave / Stereo wave** changes the waveform display. It does not itself turn a sound into stereo. Left/right gain and placement controls change channel levels; a zero right level intentionally produces left-only sound.

### Region effects

Select a time range, then choose a region effect. Available tools include level changes, echo, reverb, filters, compression/limiting, saturation, tremolo, auto-pan and stereo widening. Their amount and fade controls let you ease an effect in and out. Start subtly; stacking many strong processors can make a mix louder, muddy or distorted.

Select an existing effect region to edit or remove it. Monitor both channels after changing stereo placement. Mono routed equally to both ears is usually the correct starting point for an imported single-source effect.

### Combine sound tracks

1. Select an imported sound lane and choose **Combine sound tracks…** in the right panel.
2. Check two or more imported tracks and give the combined track a name. Unmute a track first if you want to combine it.
3. Click **Combine selected tracks**. The selected lanes become one rendered audio lane, preserving their timing, overlap, levels, fades and region effects. Other lanes remain separate.
4. The session is saved. Select the combined lane and use **Restore original tracks** to return to the pre-combine tracks.

This is a rendered combination, not cross-lane dragging of independently editable source clips. Silence between events remains part of the combined audio. Individual effects/fades are baked into it. Restoring originals discards edits made to the combined lane; it restores the saved pre-combine settings. Normal undo history is cleared at this structural operation. Original audio files are retained.

### Saving versus exporting

**Save session** saves the arrangement and editing settings. It does not replace the Library song's audio.

**Export custom mix** renders the audible arrangement and adds a new Studio Mix song to the main Library. The original song is preserved. The rendered result includes imported sound effects and processing, and mono imports are placed into both stereo channels unless you deliberately change channel levels.

A range export creates only the selected span. Quick **Instrumental** and **Acapella** exports use their corresponding stems; they do not include imported sound-effect lanes. Use **Export custom mix** for your complete arrangement with added sounds.

After exporting, play the new Library entry from start to finish before making a video or sharing it. For a video of the edited arrangement, select the exported Studio Mix rather than the original take.

## Lyrics synchronization and karaoke

Install **Whisper lyrics and karaoke** in Models. Use the Library song's lyrics-sync action when it is available. This analyzes existing audio and aligns lyrics for timed display; it does not compose lyrics or change the sung performance. The app can use transcription as a fallback.

Set the correct language and review the saved lyrics first. Instrumental songs, unclear vocals, background singing and a written lyric that differs from the actual performance can cause poor alignment. Other languages may need an additional alignment download on first use. Review playback and timing before using karaoke in a finished video.

## Cover art and video

Use **Generate cover art** from the song menu after installing the artwork model. The app uses saved song details and any optional visual direction. A successful regeneration replaces that song's cover. Describe visual subjects and composition, not sound-production settings.

Use **Make video** to open the visualizer/video tools. Choose a layout and supported visual options, review the preview, then render. Use timed lyrics if you want synchronized words and the selected layout supports them. Video rendering can take time and needs disk space for its output.

For a mixed song, first export it from Studio and select the new Library entry. Editing a Studio session alone does not change the original song used by other tools.

## Keys, System, Jobs and Logs

**Keys** configures optional cloud helpers. Save your own provider key in the appropriate category and enable that helper. Writing actions and Effects prompt enhancement use the Writing configuration. A stored key alone does not mean every helper is enabled. Review generated suggestions before applying them.

Cloud actions send the relevant request text to the configured provider and can use paid credits. Local models use your own computer. Do not include private information in a prompt unless you intend that provider to receive it.

**System** reports hardware/runtime information. Idle free VRAM is not a promise that an entire generation will fit in memory.

**Job** shows the current task, phase, progress and cancellation. Elapsed time remains visible; a remaining-time estimate is shown only when one is available. A phase can take time without the percentage moving smoothly.

**Logs** is the place to inspect installation or generation failures. When reporting a problem, include the app version, selected model, relevant settings, task phase and a short error excerpt. Review logs for private paths or prompt text before sharing. Never attach your API-key vault.

## Troubleshooting

| Symptom | First checks |
| --- | --- |
| No install button for a model | Installed models are hidden. Refresh Models and check the relevant feature's ready status. |
| Missing model files or unavailable generator | Use Models to install the complete feature/runtime. Do not copy an unrelated checkpoint into its folder. |
| Download fails with access denied | For gated Stable Audio, confirm publisher access and the correct Hugging Face read token. For public models, check the connection and retry. |
| Not enough disk space | Free space on the app's drive. Downloads and extraction need more room than the final weights alone. |
| GPU out of memory | Stop other GPU work, try a shorter/smaller job and restart the app after a failed task. Read the logged error. Model file size alone is not the memory requirement. |
| Sound effect is noisy or distorted | Try a simple prompt, default sampler/settings and a new seed. Compare one variable at a time. Check levels and processing in Studio. Prompt enhancement or extra steps can make results worse. |
| Woosh Steps slider is disabled | DOPRI5 is adaptive. Select Euler only if you want to experiment with a fixed step count. |
| Effect only in one ear | Use 0.5.0 or later, restart after updating, and check clip left/right gains and placement. Imported mono audio should be centered without a special effect. |
| Edits missing in Library playback | Save the Studio session, then Export custom mix. Play the new Studio Mix entry. |
| Added sounds missing from export | Use custom mix, check mute/solo, timeline placement and export range. Quick stem exports omit imported sounds. |
| Lyrics are absent or mistimed | Check the lyric text/language, install Whisper and run sync. A text rewrite cannot change what was actually sung. |
| Gemini helper unavailable | Check Writing provider, model, saved key and enable state. Read the error for quota or provider problems. |
| Old controls still visible | Close the running app and launch the updated executable/installation. An already open window does not load a rebuilt frontend. |

## Files, backups and sharing

The app stores data beside its application files:

| Folder | Contents |
| --- | --- |
| `outputs/library` | Songs, their metadata, Studio tracks and mixes. |
| `outputs/effects` | Generated sound effects and their settings. |
| `outputs/settings` | Local settings, including the private API-key vault. |
| `outputs/logs` | Diagnostic logs. |
| `outputs/downloads` | Download archives, partial transfers and setup caches. |
| `models` | Optional model components. |
| `python` | App backend and private feature runtimes. |

Back up `outputs` while the app is closed, and treat that backup as private because it includes settings and keys. For a shareable audio file, export/download the recording instead of sending the entire app directory. Retain the full song folder if you need to keep an editable Studio session.

The GitHub source and Windows installer intentionally omit your media, keys, downloaded models and private runtimes. Use the Models page for downloads on each installation. Each model has its own license; Woosh's released weights are non-commercial. Check the relevant publisher's terms before using model-dependent output commercially.
