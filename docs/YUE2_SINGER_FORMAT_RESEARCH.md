# YuE2 singer-label research — 2026-09-15

## Official evidence
- https://github.com/multimodal-art-projection/YuE/blob/main/skills/yue2-music/SKILL.md : vocal character belongs in style; section tags and sung words belong in lyrics.
- https://github.com/multimodal-art-projection/YuE/blob/main/skills/yue2-music/assets/prompt.json : official example uses [Verse]/[Chorus] and a female-voice description in style.
- https://github.com/multimodal-art-projection/YuE/blob/main/skills/yue2-music/references/generation-and-covers.md : supported request fields include style and lyrics; no dedicated reference-singer field.
- https://huggingface.co/m-a-p/YuE2-3B/blob/main/README.md : published interface and examples.

No documented dedicated [Singer A]/[Singer B] switching contract was found in these sources. This does not establish that the model cannot respond to textual duet cues; it means such cues are not verified hard controls. Section-based duet directions in style require actual generation/listening to establish adherence.

## App findings
- voice_profiles.py defines local Singer A/B conventions and adds text descriptions to style.
- main.prepare_music3_lyrics removes standalone bracket singer labels. Inline [Singer A] text and plain Singer A: pass through to generation (reproduced in generation-cleanup.json).
- ai_assist.py local system says no singer labels, but contradictory briefs can override that in model output.
- Shared cloud guide discourages singer descriptions in sung lines but does not enforce a formal output boundary.

## Direct local model probes
Configured gemma3:4b was called directly, with no song generation, no cloud requests, and no library writes. Raw results are outputs/singer-format-research/results.json.
- Current local system + explicit singer-label request: labels returned.
- Current shared system + same request: literal Singer A:, Singer B:, Both: returned.
- Explicit separation system + contradictory label request, two trials: labels returned both times.
- Explicit separation system + consistent section-based duet request, two trials: see saved results.
These small probes demonstrate a failure mode, not a model-wide reliability estimate or evidence of Gemini's historical response.

## Recommended next implementation
1. Keep singer/voice assignments as structured app metadata. Compile section-level duet direction into style; retain only supported section headers and sung words in generation lyrics.
2. Use one consistent formatting contract across providers. Do not simultaneously request speaker labels and forbid them.
3. Validate the final model-bound lyrics regardless of source. Normalize recognized leading singer labels without deleting sung content; require review/repair for ambiguous notation rather than inventing model controls.
4. Keep karaoke display separate from generation direction. Preserve user-authored originals.
5. Regression cases: standalone, inline, colon labels, two tags around lyric text, repeated chorus, both singers, plain words that resemble names, translation/optimization and manual edits.
6. Render short controlled duet comparisons before promising reliable singer switching. No audio generation or production code changes were made in this research pass.
