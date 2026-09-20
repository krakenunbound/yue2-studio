# Writing-provider guidance for YuE2

Guide version 5 is defined in `python/ai_guides.py` and attached by `python/ai_assist.py`. Gemini 3.6 Flash is the cloud default for lyrics, style prompts, and the Live co-producer conversation. ChatGPT, Grok, and the other cloud writing providers use that same full guide.

Ollama is intentionally different: it keeps the local server URL and model chosen by the user (Gemma 3 4B is the recommended default) and uses a compact, local-model-specific output contract. This avoids asking a smaller local model to follow the longer conversational cloud prompt. The locked prompt format is documented in [prompt-style.md](prompt-style.md).

YuE2's official request is a compact `style` string plus a tagged lyric stream. Local `examples/tonight-awake.json` is the HF demo; GitHub `examples/song.json` is the skill canonical. Planning modes (`full` / `melody` / `off`) are app controls, not prompt text. Neither MiniMax headings nor YuE v1 space-separated tags apply.

## Style descriptions

Comma-separated. Preferred order: language, genre, vocal character, instruments, groove/tempo feel, optional BPM in the same string. Official examples are often 15–40 words; 30–80 is an editorial ceiling, not a target. Preserve explicit constraints. No headings, field checklists, MiniMax templates, or YuE v1 tag soup.

Canonical: `English, warm piano pop, expressive female voice, acoustic piano, rounded bass and light drums, lyrical memorable melody, unhurried phrasing, 88 BPM`

## Lyrics and planning

Preserve the requested language, script, story, perspective and approved text. Use familiar section labels and retain useful hook repetition. Keep production directions out of sung lines. Do not invent vocals for instrumental requests. A title may come from a distinctive hook; existing titles are preserved unless a rename is requested.

Planning mode is an app setting, not a phrase to insert into the prompt. Supplied ABC scores belong in the separate score field. The selected writing helper must not claim to have rendered or heard audio, changed settings, or guaranteed exact duration, pitch or singer identity.

The app now accepts plain style responses without requiring legacy headings and rejects empty or malformed JSON responses. Automated tests use mocked responses and do not call cloud providers or expose local credentials. Restart an already-open app to load the updated Python instructions; rebuild the desktop executable when shipping the UI changes.
