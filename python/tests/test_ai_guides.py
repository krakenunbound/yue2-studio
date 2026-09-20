from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import ai_assist
import ai_guides
import ai_vault


class AiGuideTests(TestCase):
    def test_images_are_square(self):
        pack = ai_guides.pack("images")
        self.assertEqual(pack["constraints"]["aspect"], "1:1")
        self.assertIn("1:1", pack["system"])

    def test_video_orientation(self):
        wide = ai_guides.pack("video", orientation="landscape")
        tall = ai_guides.pack("video", orientation="portrait")
        self.assertEqual(wide["constraints"]["aspect"], "16:9")
        self.assertEqual(tall["constraints"]["aspect"], "9:16")
        self.assertIn("16:9", wide["system"])
        self.assertIn("9:16", tall["system"])

    def test_shared_preamble_names_the_engine_and_both_inputs(self):
        system = ai_guides.writing_system()
        self.assertIn("YuE2", system)
        self.assertIn("style prompt, lyrics, and optional symbolic planning", system)

    def test_non_english_language_codes_expand_to_native_script_instructions(self):
        self.assertIn("Japanese", ai_assist.language_instruction("ja"))
        self.assertIn("native script", ai_assist.language_instruction("ja"))
        self.assertIn("Sung language: English.", ai_assist.language_instruction("en"))
        user = ai_assist._writing_user("generate", idea="J-pop", language="ja")
        self.assertIn("Japanese", user)
        self.assertIn("native script", user)
        self.assertNotIn("Language: ja", user)
        chat = ai_assist._chat_user([{"role": "user", "content": "J-pop"}], language="ja", instrumental=False)
        self.assertIn("Japanese", chat)

    def test_translate_action_asks_for_english_display_copy(self):
        user = ai_assist._writing_user("translate", lyrics="[Verse]\n夜が明ける")
        self.assertIn("Translate the sung lyrics into English", user)
        self.assertIn("never sung", user)
        self.assertIn("夜が明ける", user)
        with self.assertRaises(ValueError):
            ai_assist.write("translate", lyrics="[Verse]\n")

    def test_lyric_prompt_preserves_language_and_supported_example_sections(self):
        system = ai_guides.lyrics_system()
        self.assertIn("[Interlude]", system)
        self.assertIn("Preserve Unicode", system)
        self.assertIn("Keep useful chorus repetition", system)
        self.assertNotIn("official section tags", system.lower())

    def test_style_prompt_is_compact_and_keeps_planning_separate(self):
        system = ai_guides.caption_system()
        self.assertIn("30-80", system)
        self.assertIn("comma-separated", system)
        self.assertIn("sung language", system)
        self.assertTrue(ai_guides.STYLE_EXAMPLE.startswith("English,"))
        self.assertIn("optional ABC score separately", system)
        self.assertIn("instrumental/no vocals", system)
        self.assertNotIn("250-450", system)
        self.assertNotIn("Global Metadata", system)
        self.assertNotIn("inspiring female uplifting pop", system)

    def test_describe_instrumental_forbids_a_singer(self):
        user = ai_assist._caption_user(
            brief="Lo-fi study beats", title="", lyrics="", language="en", references="", instrumental=True,
        )
        self.assertIn("INSTRUMENTAL", user)
        self.assertIn("no vocals", user.casefold())

    def test_describe_accepts_native_style_without_legacy_template_injection(self):
        from unittest.mock import patch
        prompt = "Intimate acoustic folk, warm alto, fingerpicked guitar, gentle bass, restrained chorus."
        access = {"provider": "gemini", "model": "test", "key": "test-only", "system": ai_guides.caption_system()}
        with patch.object(ai_assist, "prepare", return_value=access), \
             patch.object(ai_assist, "_complete", return_value=prompt) as complete, \
             patch.object(ai_assist.caption_library, "reference_block") as legacy:
            result = ai_assist.describe(idea="Acoustic folk, no drums", lyrics="[Verse]\nStay with me\n[Interlude]", language="en")
        self.assertEqual(prompt, result["description"])
        self.assertEqual("", result["references"])
        legacy.assert_not_called()
        user = complete.call_args.args[4]
        self.assertIn("no drums", user)
        self.assertIn("[Interlude]", user)
        self.assertNotIn("official sub-fields", user)

    def test_describe_rejects_empty_or_json_reply(self):
        from unittest.mock import patch
        access = {"provider": "gemini", "model": "test", "key": "test-only", "system": "style"}
        for output in ("", "{"):
            with self.subTest(output=output), patch.object(ai_assist, "prepare", return_value=access), \
                 patch.object(ai_assist, "_complete", return_value=output):
                with self.assertRaises(RuntimeError):
                    ai_assist.describe(idea="Acoustic folk")

    def test_writing_and_caption_packs_are_not_the_same_prompt(self):
        """Regression guard.

        write() once built the writing pack and then threw it away, sending the
        lyric prompt for every job -- so nothing could ever produce a caption.
        Each capability must resolve to its own system prompt.
        """
        lyric_pack = ai_guides.pack("writing")
        caption_pack = ai_guides.pack("caption")
        chat_pack = ai_guides.pack("chat")
        self.assertEqual(lyric_pack["system"], ai_guides.lyrics_system())
        self.assertEqual(caption_pack["system"], ai_guides.caption_system())
        self.assertEqual(chat_pack["system"], ai_guides.chat_system())
        self.assertNotEqual(lyric_pack["system"], caption_pack["system"])
        self.assertEqual(caption_pack["constraints"]["shape"], "style-prompt")

    def test_chat_prompt_demands_the_brief_marker(self):
        system = ai_guides.chat_system()
        self.assertIn(ai_guides.BRIEF_MARKER, system)
        self.assertIn("one or two sentences", system)

    def test_cloud_chat_keeps_the_conversational_co_producer_prompt(self):
        from unittest.mock import patch
        access = {"provider": "gemini", "model": "gemini-2.5-flash", "key": "test-only", "system": ai_guides.chat_system()}
        response = "A slow-burning city-pop confession will let the neon and rain carry the ache.\n---BRIEF---\nJapanese city pop with warm keys and a patient night-drive pulse."
        with patch.object(ai_assist, "prepare", return_value=access), patch.object(ai_assist, "_complete", return_value=response) as complete:
            ai_assist.chat([{"role": "user", "content": "Japanese city pop about rain"}])
        self.assertEqual(complete.call_args.args[3], ai_guides.chat_system())
        self.assertIn("co-producer", complete.call_args.args[3])

    def test_ollama_chat_uses_the_compact_local_prompt(self):
        from unittest.mock import patch
        access = {"provider": "ollama", "model": "gemma3:4b", "key": "ollama", "base_url": "http://127.0.0.1:11434/v1", "system": ai_guides.chat_system()}
        response = "I will shape that into a bright, close-miked song.\n---BRIEF---\nEnglish indie pop with guitar and a gentle lift."
        with patch.object(ai_assist, "prepare", return_value=access), patch.object(ai_assist, "_complete", return_value=response) as complete:
            ai_assist.chat([{"role": "user", "content": "Bright indie pop about meeting someone"}])
        system = complete.call_args.args[3]
        self.assertIn("You help plan a song", system)
        self.assertNotIn("co-producer inside YuE2 Studio", system)

    def test_chat_reply_splits_off_the_hidden_brief(self):
        reply, brief = ai_assist._split_brief(
            "That is a great shape for a song.\n"
            f"{ai_guides.BRIEF_MARKER}\n"
            "Dark techno, 140 bpm, male vocal, driving four-on-the-floor."
        )
        self.assertEqual("That is a great shape for a song.", reply)
        self.assertIn("Dark techno", brief)
        self.assertNotIn(ai_guides.BRIEF_MARKER, reply)
        # No marker at all means the model asked a question instead.
        only_reply, no_brief = ai_assist._split_brief("What mood are you after?")
        self.assertEqual("What mood are you after?", only_reply)
        self.assertEqual("", no_brief)
        loose_reply, loose_brief = ai_assist._split_brief(
            "That sounds evocative.\n\n---\n\nBRIEF - Soft, hazy lo-fi track with gentle piano and strings."
        )
        self.assertIn("evocative", loose_reply)
        self.assertIn("lo-fi", loose_brief)
        self.assertNotIn("BRIEF", loose_brief)

    def test_chat_turn_stays_ready_when_the_user_already_gave_a_song_idea(self):
        reply, brief, ready = ai_assist._finalize_chat_turn(
            "That sounds evocative. Soft piano, hazy strings, wistful mood.",
            "A lo-fi song about the star to go out.",
        )
        self.assertTrue(ready)
        self.assertIn("piano", brief.lower() + reply.lower())
        q_reply, q_brief, q_ready = ai_assist._finalize_chat_turn("What mood are you after?", "hi")
        self.assertFalse(q_ready)
        self.assertEqual("", q_brief)
        self.assertIn("mood", q_reply.lower())

    def test_assist_refuses_when_disabled(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        with TemporaryDirectory() as temp, patch.object(ai_vault, "VAULT_PATH", Path(temp) / "api-keys.json"):
            with self.assertRaises(PermissionError):
                ai_assist.prepare("writing")

    def test_title_action_accepts_plain_title_line(self):
        parsed = ai_assist._parse_writing("Neon Rain")
        recovered = ai_assist._first_title_line(parsed["lyrics"] or "Neon Rain")
        self.assertEqual("Neon Rain", recovered)
        self.assertEqual("Night Drive", ai_assist._first_title_line("Title: Night Drive"))

    def test_parse_json_fenced_block(self):
        parsed = ai_assist._parse_writing('```json\n{"lyrics":"[Verse]\\nHello","title":"Hello"}\n```')
        self.assertEqual("[Verse]\nHello", parsed["lyrics"])
        self.assertEqual("Hello", parsed["title"])

    def test_parse_plain_lyrics_and_reject_brace(self):
        parsed = ai_assist._parse_writing("Title: Event Horizon\n\n[Verse]\nI fall through the dark")
        self.assertEqual("Event Horizon", parsed["title"])
        self.assertIn("[Verse]", parsed["lyrics"])
        self.assertTrue(ai_assist._looks_like_json_junk("{"))
        self.assertFalse(ai_assist._looks_like_json_junk("[Verse]\nhello"))

    def test_split_caption_out_of_lyrics(self):
        raw = "Global Metadata\nBasic Attributes: space rock.\n\nVocal Details\nSinger A.\n\nArrangement\nSparse drums.\n\n[Intro]\n\n[Verse]\nThe stars begin to stretch"
        parsed = ai_assist._parse_writing(raw)
        self.assertIn("[Verse]", parsed["lyrics"])
        self.assertNotIn("Global Metadata", parsed["lyrics"])
        self.assertIn("Global Metadata", parsed["description"])
        self.assertIn("space rock", parsed["description"])

    def test_parse_broken_gemini_json_blob(self):
        raw = (
            '  "title": "Singularity",\n'
            '  "lyrics": "[Intro]\\n\\n[Verse]\\nThe stars begin to stretch and fade\\n'
            'A silent curve that we have made\\n[Chorus]\\nFalling deep into the gravity\\n'
            'Singularity\\nSet me free"\n'
            "}\n}"
        )
        parsed = ai_assist._parse_writing(raw)
        self.assertEqual("Singularity", parsed["title"])
        self.assertIn("[Intro]", parsed["lyrics"])
        self.assertIn("Falling deep into the gravity", parsed["lyrics"])
        self.assertNotIn('"lyrics"', parsed["lyrics"])
        self.assertFalse(ai_assist._looks_like_json_junk(parsed["lyrics"]))
