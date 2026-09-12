# YuE2 prompt and style (locked)

This studio talks to **YuE2-3B**, not YuE v1. Sources: [YuE `main`](https://github.com/multimodal-art-projection/YuE), [generation.md](https://github.com/multimodal-art-projection/YuE/blob/main/docs/generation.md), [yue2-music skill](https://github.com/multimodal-art-projection/YuE/blob/main/skills/yue2-music/SKILL.md), [HF YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B). YuE v1 lives on the [`YuE-v1` branch](https://github.com/multimodal-art-projection/YuE/tree/YuE-v1) and uses a different prompt. Do not mix the two.

## Request fields the model actually takes

| Field | Use |
| --- | --- |
| `style` | Genre, language, voice, instruments, feel, optional BPM. `tags` is an alias; both must agree if set. |
| `lyrics` | Section tags + sung words only. |
| `cot` | App control: `full` (default), `melody` (covers), `off`. Never paste these words into `style`. |
| `abc` | Optional score. Melody-only ABC (no chords) with `cot=melody` for covers. |
| `seed` | Comparison aid, not bit-identical across machines. |

There is **no** `reference_audio`, `phonemes`, `bpm`, `negative_prompt`, edit-interval, or cloned-singer field. Tempo belongs in `style` (and in ABC when you supply a score).

## Style string

One comma-separated line. Preferred order:

1. Sung language (`English`, `Mandarin`, …) when it is not obvious
2. Genre or a compatible blend
3. Vocal character (timbre, register, delivery — not a named identity)
4. Core instruments
5. Groove / phrasing / mood
6. Optional BPM as plain text in the same string
7. Exclusions (`no guitar`) when they matter

Canonical (GitHub `examples/song.json` / skill `assets/prompt.json`):

```text
English, warm piano pop, expressive female voice, acoustic piano, rounded bass and light drums, lyrical memorable melody, unhurried phrasing, 88 BPM
```

Other published shapes that still fit:

```text
City Pop, upbeat, danceable, groovy bass, electric guitar, synth, energetic, joyful, neon city night
Jazz-funk, warm lead vocal, Rhodes piano, electric bass, tight drums
Jazz, expressive lead vocal, piano, tenor saxophone, upright bass, brushed drums, no guitar, spacious modern harmony
```

Keep it short. Official examples are often **15–40 words**. Do not write MiniMax-style headings (`Global Metadata` / `Vocal Details` / `Arrangement`). Do not write YuE v1 tag soup (`inspiring female uplifting pop airy vocal electronic bright vocal vocal`).

## Lyrics

TitleCase tags on their own lines, then the words to sing. Official examples use `[Verse]` and `[Chorus]`, not YuE v1 `[verse]`.

```text
[Verse]
Neon fades along the lane
Footsteps keep the time of rain

[Chorus]
Let the day come into view
Every road begins with you
```

Useful extra tags in this app: `[Intro]`, `[Pre-Chorus]`, `[Interlude]`, `[Bridge]`, `[Outro]`. Keep production notes, timestamps, ABC, and singer essays out of the lyric stream. Put whispered / spoken / rapped delivery in `style` unless you are inserting a known direction for the lyric field.

Instrumental: no sung words. Say `instrumental/no vocals` in `style`.

## Planning vs prompt

| Mode | When |
| --- | --- |
| `full` | New songs; melody + chords; default |
| `melody` | Covers; free accompaniment; strip chords from ABC first |
| `off` | Direct audio; no editable ABC |

Change style, lyrics, or ABC → generate a new recording. Cached latents only reuse a decoder, not a musical edit.

## YuE v1 (do not use here)

YuE v1 wanted five space-separated buckets (genre, instrument, mood, gender, timbre), lowercase `[verse]` / `[chorus]` sessions, optional 30s ICL audio, and `genre.txt` + `lyrics.txt`. That interface is not YuE2.
