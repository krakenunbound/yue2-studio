from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lyrics_align_worker as worker
import lyrics_sync


def token(word: str, start: float, end: float) -> worker.TimedToken:
    return worker.TimedToken(token=word, start=start, end=end)


class LyricsEvidenceTests(unittest.TestCase):
    def test_blocking_alignment_reports_real_elapsed_activity(self) -> None:
        events = []
        with patch.object(worker, "emit", side_effect=lambda event, **payload: events.append((event, payload))):
            result = worker.report_while_running(
                "align",
                "Aligning recognized vocals with WhisperX",
                lambda: (time.sleep(0.04), "done")[1],
                interval_seconds=0.01,
            )
        self.assertEqual(result, "done")
        self.assertTrue(any(
            event == "progress" and "elapsed" in str(payload.get("message"))
            for event, payload in events
        ))

    def test_inline_singer_and_section_tags_preserve_sung_words(self) -> None:
        text = "[Verse A]\n[Singer A] First sung line\n[Singer B] Second sung line [Chorus]\n[Singer A & B] Our chorus [Verse B]\n[Instrumental Break]\n[Singer A & B] ♩ ♮ ♮ (4-second pause) [Chorus]"
        lines = worker.extract_lyric_lines(text, "en")
        self.assertEqual([line["text"] for line in lines], ["First sung line", "Second sung line", "Our chorus"])

    def test_empty_aligned_tokens_produces_no_invented_timings(self) -> None:
        lyric_lines = worker.extract_lyric_lines(
            "[Verse]\nRed apples on the floor\nThe night is getting cold",
            "en",
        )

        self.assertEqual(worker.align_lyric_lines(lyric_lines, [], 90.0, "en"), [])

    def test_no_recognized_words_produces_no_invented_timings(self) -> None:
        lyric_lines = worker.extract_lyric_lines(
            "[Verse]\nRed apples on the floor\nThe night is getting cold",
            "en",
        )
        aligned = [token("unrelated", 12.0, 12.4), token("noise", 12.5, 12.8)]

        self.assertEqual(worker.align_lyric_lines(lyric_lines, aligned, 90.0, "en"), [])

    def test_exact_words_after_long_intro_keep_their_late_onset(self) -> None:
        lyric_lines = worker.extract_lyric_lines(
            "[Verse]\nRed apples on the floor\nThe night is getting cold",
            "en",
        )
        aligned = [
            token("red", 61.2, 61.5), token("apples", 61.5, 62.0),
            token("on", 62.0, 62.2), token("the", 62.2, 62.4), token("floor", 62.4, 62.8),
            token("the", 64.0, 64.2), token("night", 64.2, 64.6), token("is", 64.6, 64.8),
            token("getting", 64.8, 65.3), token("cold", 65.3, 65.7),
        ]

        timed = worker.align_lyric_lines(lyric_lines, aligned, 90.0, "en")

        self.assertEqual([line["text"] for line in timed], [line["text"] for line in lyric_lines])
        self.assertGreaterEqual(timed[0]["start"], 61.0)
        self.assertGreaterEqual(timed[0]["words"][0]["start"], 61.0)
        self.assertGreaterEqual(timed[1]["start"], 64.0)

    def test_unmatched_leading_lyrics_are_not_assigned_to_the_intro(self) -> None:
        lyric_lines = worker.extract_lyric_lines(
            "[Verse]\nA phantom line was never sung\n[Chorus]\nThe actual words arrive",
            "en",
        )
        aligned = [
            token("the", 61.0, 61.2), token("actual", 61.2, 61.6),
            token("words", 61.6, 62.0), token("arrive", 62.0, 62.4),
        ]

        timed = worker.align_lyric_lines(lyric_lines, aligned, 90.0, "en")

        self.assertEqual([line["text"] for line in timed], ["The actual words arrive"])
        self.assertGreaterEqual(timed[0]["start"], 61.0)

    def test_vocal_onset_uses_recognized_words_not_the_instrumental_intro(self) -> None:
        lyric_lines = worker.extract_lyric_lines(
            "[Verse]\nRed apples on the floor\nThe night is getting cold",
            "en",
        )
        aligned = [
            token("red", 30.4, 30.7), token("apples", 30.7, 31.2),
            token("on", 31.2, 31.4), token("the", 31.4, 31.6), token("floor", 31.6, 32.0),
            token("the", 34.0, 34.2), token("night", 34.2, 34.6),
            token("is", 34.6, 34.8), token("getting", 34.8, 35.3), token("cold", 35.3, 35.7),
        ]

        start = worker.estimate_vocal_start(lyric_lines, aligned, 90.0, "en")

        self.assertGreaterEqual(start, 29.5)
        self.assertLess(start, 30.4)

    def test_faster_whisper_path_does_not_wav2vec2_align_the_full_mix(self) -> None:
        source = Path(worker.__file__).read_text(encoding="utf-8")
        faster = source.split("def transcribe_with_faster_whisper")[1].split("def transcribe_with_whisperx")[0]
        main_fn = source.split("def main()")[1]
        self.assertNotIn("whisperx.align", faster)
        self.assertIn("def force_align_known_lyrics", source)
        self.assertNotIn("force_align_known_lyrics", main_fn)
        self.assertIn("recognize_lyric_timing", main_fn)
        self.assertNotIn("Finding where the vocals start", main_fn)
        self.assertNotIn("transcribe_with_whisperx", main_fn)
        self.assertNotIn("transcribe_with_fallback", main_fn)

    def test_recognition_keeps_absolute_times_and_does_not_filter_singing(self) -> None:
        result = {"aligned": {"segments": [{"start": 23.7, "end": 27.0, "words": []}]}}
        with patch.object(worker, "transcribe_with_faster_whisper", return_value=result) as recognize:
            actual = worker.recognize_lyric_timing(Path("song.wav"), "[Verse]\nHello world", "en", "cuda", "local-model")
        self.assertFalse(recognize.call_args.kwargs["vad_filter"])
        self.assertFalse(recognize.call_args.kwargs["condition_on_previous_text"])
        self.assertEqual(actual["aligned"]["segments"][0]["start"], 23.7)
        self.assertEqual(actual["alignment_method"], "whisper-recognized-word-timestamps")

    def test_translation_keeps_original_lyric_index_when_unmatched_lines_are_omitted(self) -> None:
        payload = {"lines": [{"index": 2, "text": "The actual words arrive", "start": 61.0, "end": 62.4}]}

        lyrics_sync.attach_translations(payload, "The phantom line\nThe actual words arrive")

        self.assertEqual(payload["lines"][0]["translation"], "The actual words arrive")


if __name__ == "__main__":
    unittest.main()
