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
        self.assertIn("Mariah Carey", names)
        self.assertIn("Kurt Cobain", names)
        self.assertIn("Robert Plant", names)
        self.assertIn("Frank Sinatra", names)

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
        self.assertIn("female vocal", compiled["block"])
        self.assertNotIn("not a generic", compiled["block"].casefold())
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

    def test_apply_appends_compact_voice_phrase(self) -> None:
        description = (
            "Global Metadata\nBasic Attributes: folk.\n\n"
            "Vocal Details\nVocal Gender & Timbre: leftover template singer.\n\n"
            "Arrangement\nInstrument Lifecycle: lyre."
        )
        result = voice_profiles.apply_vocal_block(description, "Singer A (Female), a clear alto")
        self.assertIn("folk", result)
        self.assertIn("lyre", result)
        self.assertIn("Singer A (Female), a clear alto", result)
        self.assertNotIn("leftover template singer", result)
        self.assertNotIn("Vocal Details", result)
        self.assertNotIn("Global Metadata", result)

    def test_compile_preview_is_compact_yue2_style(self) -> None:
        female = voice_profiles.get_profile("voice-clear-alto")
        assert female is not None
        result = voice_profiles.compile_for_generation(
            "Global Metadata\nBasic Attributes: English, cinematic alternative rock.\n\nVocal Details\nleftover.\n\nArrangement\nInstrument Lifecycle: live guitars.",
            {"female": female["id"], "male": "", "backing": ""},
        )
        self.assertTrue(result["applied"])
        self.assertNotIn("Vocal Gender & Timbre", result["preview"])
        self.assertNotIn("Vocal Details", result["preview"])
        self.assertNotIn("Global Metadata", result["preview"])
        self.assertIn("Singer A (Female)", result["preview"])
        self.assertIn("cinematic alternative rock", result["preview"])
        self.assertIn("live guitars", result["preview"])

    def test_instrumental_caption_strips_singer_block(self) -> None:
        description = (
            "Global Metadata\nBasic Attributes: cyberpunk.\n\n"
            "Vocal Details\nVocal Gender & Timbre: Singer A (Female), a clear alto.\n\n"
            "Arrangement\nInstrument Lifecycle: analog synths."
        )
        result = voice_profiles.apply_instrumental_caption(description)
        self.assertIn("instrumental", result.casefold())
        self.assertIn("no vocals", result.casefold())
        self.assertNotIn("Singer A (Female), a clear alto", result)
        self.assertIn("analog synths", result)
        self.assertNotIn("Vocal Details", result)

    def test_plain_genre_stays_short(self) -> None:
        result = voice_profiles.apply_instrumental_caption("Cyberpunk")
        self.assertIn("Cyberpunk", result)
        self.assertIn("instrumental", result.casefold())
        self.assertNotIn("Use a natural tempo", result)
        self.assertNotIn("Global Emotional Progression", result)
        self.assertLess(len(result), 400)

    def test_compile_for_generation_is_noop_without_slots(self) -> None:
        result = voice_profiles.compile_for_generation("plain description", {})
        self.assertFalse(result["applied"])
        self.assertEqual("plain description", result["description"])

    def test_strip_template_singers_drops_flat_live_voice(self) -> None:
        text = (
            "Japanese, 1980s city pop, upbeat and danceable, groovy bass, "
            "Singer A (Female), a warm clear mezzo with joyful Japanese phrasing, "
            "easy upper register and unhurried city-night cool, Fully melodic, danceable verses"
        )
        stripped = voice_profiles.strip_template_singers(text)
        self.assertIn("city pop", stripped)
        self.assertIn("Fully melodic", stripped)
        self.assertNotIn("Singer A", stripped)
        self.assertNotIn("warm clear mezzo", stripped)

    def test_assigned_male_character_replaces_template_female_singer(self) -> None:
        description = (
            "Japanese, 1980s city pop, upbeat and danceable, groovy bass, electric guitar, "
            "bright synths, joyful neon-city night rather than modern J-pop or disco parody, "
            "Singer A (Female), a warm clear mezzo with joyful Japanese phrasing, easy upper "
            "register and unhurried city-night cool, Fully melodic, danceable verses, a memorable chorus"
        )
        result = voice_profiles.compile_for_generation(
            description,
            {"female": "", "male": "voice-liquid-falsetto", "backing": ""},
        )
        self.assertTrue(result["applied"])
        preview = result["preview"]
        self.assertIn("Singer A (Male)", preview)
        self.assertIn("male vocal", preview)
        self.assertIn("liquid falsetto", preview)
        self.assertIn("city pop", preview)
        self.assertIn("Fully melodic", preview)
        self.assertNotIn("Singer A (Female)", preview)
        self.assertNotIn("warm clear mezzo", preview)
        self.assertNotIn("Prince", preview)

    def test_duet_characters_replace_template_hair_band_tenor(self) -> None:
        description = (
            "English, 1980s glam metal hair-band rock with twin leads, "
            "Singer A (Male), a high raspy glam-metal tenor with open vowels, a screaming-sung belt "
            "and a memorable gang-ready hook, Sung verses with attitude"
        )
        result = voice_profiles.compile_for_generation(
            description,
            {"female": "voice-whisper-close", "male": "voice-croon-baritone", "backing": ""},
        )
        self.assertTrue(result["applied"])
        preview = result["preview"]
        self.assertIn("Singer A (Female)", preview)
        self.assertIn("Singer B (Male)", preview)
        self.assertIn("whisper-mezzo", preview)
        self.assertIn("crooner baritone", preview)
        self.assertNotIn("glam-metal tenor", preview)
        self.assertNotIn("Billie", preview)
        self.assertNotIn("Sinatra", preview)

    def test_dark_techno_keeps_arrangement_and_replaces_generic_voice(self):
        result = voice_profiles.compile_for_generation(
            'English, dark techno, 130 BPM, distorted kick, industrial bass, detached female vocals, no choir',
            {'female': 'voice-gold-dust-mezzo'})
        text = result['description']
        for expected in ('dark techno', '130 BPM', 'distorted kick', 'industrial bass', 'no choir', 'husky', 'grainy chest', 'slow, wide, and slightly uneven vibrato'):
            self.assertIn(expected, text)
        for unwanted in ('detached female', '70s rock', 'folk-rock', 'Mandatory vocal identity', 'generic model voice'):
            self.assertNotIn(unwanted, text)
        self.assertEqual(text.count('grainy chest'), 1)

    def test_embedded_singer_preserves_other_instruments(self):
        self.assertEqual(voice_profiles.strip_competing_vocals('dark techno with detached female vocals and pounding drums'), 'dark techno and pounding drums')
        self.assertEqual(voice_profiles.strip_competing_vocals('industrial bass, vocal chops, no choir'), 'industrial bass, vocal chops, no choir')

    def test_freeform_only_profile_keeps_traits(self):
        phrase = voice_profiles.yue2_voice_phrase({'expanded': 'breathy alto with clipped diction'}, singer_label='Singer A')
        self.assertIn('breathy alto', phrase)

    def test_lowercase_arrangement_survives_template_singer_cleanup(self):
        result = voice_profiles.strip_template_singers('indie folk, Singer A (Female), warm alto, acoustic guitar, brushed drums, gentle tempo')
        self.assertEqual(result, 'indie folk, acoustic guitar, brushed drums, gentle tempo')

    def test_instrument_registers_are_not_singers(self):
        self.assertEqual(voice_profiles.strip_competing_vocals('jazz, tenor saxophone, alto flute, baritone guitar, brushed drums'), 'jazz, tenor saxophone, alto flute, baritone guitar, brushed drums')

    def test_backing_profile_does_not_request_a_lead(self):
        profile = voice_profiles.get_profile('voice-warm-backing')
        if profile is None:
            profile = next(p for p in voice_profiles.list_profiles() if p['role'] == 'backing')
        phrase = voice_profiles.yue2_voice_phrase(profile, singer_label='Backing vocals')
        self.assertIn('backing vocal', phrase)
        self.assertNotIn('lead vocal', phrase)

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
        self.assertNotIn("Global Metadata", prepared["generation_description"])
        self.assertIn("folk", prepared["generation_description"])
        self.assertEqual("[Verse]\nHello\nOnly her", prepared["rendered_lyrics"])
        self.assertIn("Singer A (Female)", prepared["generation_description"])
        self.assertNotIn("Vocal Gender & Timbre", prepared["generation_description"])
        self.assertEqual("voice-clear-alto", prepared["voice_slots"]["female"])
        self.assertEqual("voice-clear-alto", prepared["voice_snapshots"][0]["id"])

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
        self.assertIn("Synths", prepared["generation_description"])
        self.assertNotIn("Singer A (Female)", prepared["generation_description"])
        self.assertNotIn("Vocal Details", prepared["generation_description"])
        self.assertEqual(params["voice_slots"], prepared["voice_slots"])


if __name__ == "__main__":
    unittest.main()
