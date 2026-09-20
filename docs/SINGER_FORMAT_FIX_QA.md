# Singer formatting fix — verified 2026-09-16

Implemented shared control parsing for legacy standalone, inline, colon and parenthesized singer labels, combined section/singer headers, and labels around real lyric text. Sung words and Unicode remain intact. Timed-pause notation does not become lyrics.

Generation moves voice directions into style, with passage anchors, and preserves the original supplied lyric metadata. The final engine payload rejects leftover singer labels and malformed/unknown lyric annotations. Instrumental behavior remains unchanged. Karaoke alignment and translated display use the shared extraction logic.

All writer providers receive a shared formatting instruction. New lyric requests are told to use section-based parts with vocal instructions outside sung text. Existing singer tags are retained as app metadata during edits and translations, and removed at generation/display boundaries. The app does not treat singer annotations as official hard-control YuE2 tokens.

Validation:
- 199 writing, formatting, voice, karaoke, cleanup and Studio tests passed.
- 68 additional YuE2 contract, Studio contract and speed tests passed.
- Actual configured gemma3:4b: fresh duet and legacy lyric edit passed through writer validation and the engine-input check. Initial trials exposed editor-validation bugs; those were repaired before the successful rerun. Evidence in outputs/singer-format-fix-qa/writer-results.json.
- Actual YuE2 full-mode generation: 52.119-second stereo WAV, 48kHz, 32 synthesis steps, seed73016. Input includes three legacy singer-label formats; compiled lyrics contain only section tags and sung words.
- Independent no-prompt transcription contains the intended verses/chorus, with no Singer A/B labels detected. Recognition is not a listening guarantee of exact singer identity or voice switching. The test audio is outputs/singer-format-fix-qa/duet.wav.
- Production build passed. No library songs were altered. Test inference worker was unloaded and no test Python processes remain.

Limit: Prompted voice switching remains probabilistic. This change prevents recognized control labels from being submitted as sung text, but cannot guarantee a particular performance from the music model. Existing recordings that sang labels require regeneration to remove those sounds.
