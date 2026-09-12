from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_profiles


class VoiceProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "voice-profiles.json"
        self.patcher = patch.object(voice_profiles, "VOICES_PATH", self.path)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.temp.cleanup()

    def test_seeds_built_in_profiles(self) -> None:
        names = {item["name"] for item in voice_profiles.list_profiles()}
        self.assertIn("Clear alto", names)
        self.assertIn("Ground baritone", names)
        self.assertIn("Warm backing stack", names)
        self.assertIn("Stevie Nicks", names)
        self.assertIn("Freddie Mercury", names)

    def test_stevie_persona_is_a_sound_description(self) -> None:
        profile = voice_profiles.get_profile("voice-gold-dust-mezzo")
        assert profile is not None
        self.assertIn("warbling vibrato", profile["expanded"])
        self.assertNotIn("Stevie", profile["expanded"])
        prompt = voice_profiles.portrait_prompt(profile)
        self.assertNotIn("Stevie", prompt)
        self.assertIn("headshot", prompt)

    def test_singer_labels_never_enter_yue2_traits(self) -> None:
        for profile_id in ("voice-gold-dust-mezzo", "voice-stadium-tenor", "voice-liquid-falsetto"):
            profile = voice_profiles.get_profile(profile_id)
            assert profile is not None
            expanded = voice_profiles.expand_profile(profile)
            self.assertNotIn(profile["name"], expanded)
            compiled = voice_profiles.compile_vocal_block({"female" if profile["role"] == "female" else "male": profile})
            assert compiled is not None
            self.assertNotIn(profile["name"], compiled["block"])

    def test_private_name_never_enters_compiled_block(self) -> None:
        profile = voice_profiles.upsert({
            "name": "Stevie",
            "role": "female",
            "expanded": "Stevie is a bright alto with close diction",
            "delivery": "melodic",
        })
        compiled = voice_profiles.compile_vocal_block(
            {"female": profile},
            "[Verse]\nHello\n[Female]\nOnly her",
        )
        assert compiled is not None
        self.assertNotIn("Stevie", compiled["block"])
        self.assertIn("Singer A (Female)", compiled["block"])
        self.assertIn("[Female]", " ".join(compiled["assignments"]))

    def test_duet_slots_compile_singer_a_and_b(self) -> None:
        female = voice_profiles.get_profile("voice-clear-alto")
        male = voice_profiles.get_profile("voice-ground-baritone")
        compiled = voice_profiles.compile_vocal_block(
            {"female": female, "male": male},
            "[Duet]\nTogether",
        )
        assert compiled is not None
        self.assertIn("Singer A (Female)", compiled["block"])
        self.assertIn("Singer B (Male)", compiled["block"])
        self.assertTrue(any("Duet" in note for note in compiled["assignments"]))

    def test_apply_replaces_vocal_details_only(self) -> None:
        description = (
            "Global Metadata\nBasic Attributes: folk.\n\n"
            "Vocal Details\nVocal Gender & Timbre: leftover template singer.\n\n"
            "Arrangement\nInstrument Lifecycle: lyre."
        )
        result = voice_profiles.apply_vocal_block(description, "Vocal Gender & Timbre: Singer A (Female), a clear alto.")
        self.assertIn("Basic Attributes: folk.", result)
        self.assertIn("Instrument Lifecycle: lyre.", result)
        self.assertIn("Singer A (Female), a clear alto.", result)
        self.assertNotIn("leftover template singer", result)

    def test_instrumental_caption_strips_singer_block(self) -> None:
        description = (
            "Global Metadata\nBasic Attributes: cyberpunk.\n\n"
            "Vocal Details\nVocal Gender & Timbre: Singer A (Female), a clear alto.\n\n"
            "Arrangement\nInstrument Lifecycle: analog synths."
        )
        result = voice_profiles.apply_instrumental_caption(description)
        self.assertIn("Fully instrumental", result)
        self.assertNotIn("Singer A (Female), a clear alto", result)
        self.assertIn("analog synths", result)

    def test_plain_genre_stays_short(self) -> None:
        result = voice_profiles.apply_instrumental_caption("Cyberpunk")
        self.assertIn("Cyberpunk", result)
        self.assertIn("Fully instrumental", result)
        self.assertNotIn("Use a natural tempo", result)
        self.assertNotIn("Global Emotional Progression", result)
        self.assertLess(len(result), 400)

    def test_compile_for_generation_is_noop_without_slots(self) -> None:
        result = voice_profiles.compile_for_generation("plain description", {})
        self.assertFalse(result["applied"])
        self.assertEqual("plain description", result["description"])

    def test_duplicate_is_not_built_in(self) -> None:
        copy = voice_profiles.duplicate("voice-clear-alto")
        self.assertFalse(copy["built_in"])
        self.assertTrue(copy["name"].endswith("copy"))
        self.assertNotEqual("voice-clear-alto", copy["id"])

    def test_prepare_generation_compiles_slots_without_rewriting_saved_description(self) -> None:
        import main
        params = {
            "title": "Test",
            "description": "Global Metadata\nBasic Attributes: folk.\n\nVocal Details\nVocal Gender & Timbre: leftover.\n\nArrangement\nInstrument Lifecycle: lyre.",
            "lyrics": "[Verse]\nHello\n[Female]\nOnly her",
            "instrumental": False,
            "cot_mode": "full",
            "voice_slots": {"female": "voice-clear-alto", "male": "", "backing": ""},
        }
        with patch.object(main.yue2_engine, "count_prompt_tokens", return_value={"tokens": 10, "maximum": 24576}):
            prepared = main.prepare_generation_params(params)
        self.assertEqual(params["description"], prepared["description"])
        self.assertEqual(params["description"], prepared["generation_description"])
        self.assertEqual("voice-clear-alto", prepared["voice_slots"]["female"])
        self.assertEqual([], prepared["voice_snapshots"])

    def test_instrumental_prepare_rewrites_vocal_details(self) -> None:
        import main
        params = {
            "title": "Untitled Song",
            "description": "Vocal Details\nVocal Gender & Timbre: Singer A (Female), a bright alto.\n\nArrangement\nSynths.",
            "lyrics": "[Verse]\nHello",
            "instrumental": True,
            "cot_mode": "full",
            "voice_slots": {"female": "voice-clear-alto", "male": "", "backing": ""},
        }
        with patch.object(main.yue2_engine, "count_prompt_tokens", return_value={"tokens": 10, "maximum": 24576}):
            prepared = main.prepare_generation_params(params)
        self.assertEqual(main.yue2_engine.INSTRUMENTAL_LYRICS, prepared["rendered_lyrics"])
        self.assertIn("[Intro]", prepared["rendered_lyrics"])
        self.assertGreaterEqual(prepared["rendered_lyrics"].count("(instrumental)"), 5)
        self.assertIn("no vocables", prepared["generation_description"])
        self.assertIn("Synths.", prepared["generation_description"])
        self.assertEqual(params["voice_slots"], prepared["voice_slots"])


if __name__ == "__main__":
    unittest.main()
