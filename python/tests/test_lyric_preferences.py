from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ai_assist
import lyric_preferences
import lyrics_sync

class LyricPreferencesTest(TestCase):
    def setUp(self):
        ai_assist._session_titles.clear()

    def test_saved_list_reaches_writing_and_easy_chat_but_not_caption(self):
        with TemporaryDirectory() as temp, patch.object(lyric_preferences,'PATH',Path(temp)/'preferences.json'), patch.object(ai_assist.ai_vault,'require_enabled',return_value={'provider':'gemini','model':'test','key':'dummy'}):
            self.assertEqual(lyric_preferences.prompt(),'')
            lyric_preferences.save('neon\nechoes / echo\nWhere _____ grows')
            for guide in ('writing','chat'):
                system=ai_assist.prepare('writing',guide_name=guide)['system']
                self.assertIn('MANDATORY: NEVER USE',system)
                self.assertIn('Where _____ grows',system)
            self.assertNotIn('USER LYRIC AVOID LIST',ai_assist.prepare('writing',guide_name='caption')['system'])
            self.assertEqual(lyric_preferences.load()['avoid'],'neon\nechoes / echo\nWhere _____ grows')
            lyric_preferences.save('')
            self.assertEqual(lyric_preferences.prompt(),'')

    def test_generate_and_rewrite_send_rules_in_actual_provider_prompt(self):
        with TemporaryDirectory() as temp, patch.object(lyric_preferences,'PATH',Path(temp)/'preferences.json'), patch.object(ai_assist.ai_vault,'require_enabled',return_value={'provider':'gemini','model':'test','key':'dummy'}), patch.object(ai_assist,'_complete',return_value='Title: Test\nLyrics:\n[Verse]\nA road leads home') as complete:
            lyric_preferences.save('velvet\nSpark')
            for action in ('generate','optimize','title'):
                ai_assist._session_titles.clear()
                ai_assist.write(action,idea='home',lyrics='A road leads home',description='folk')
                self.assertIn('velvet\nSpark',complete.call_args.args[3])
                user = complete.call_args.args[4]
                self.assertTrue(user.startswith('NEVER USE these words'), user[:80])
                self.assertLess(user.find('NEVER USE'), user.find('home'))

    def test_violations_match_slash_forms_and_titles(self):
        avoid = 'neon\nechoes / echo\nWhere _____ grows'
        hits = lyric_preferences.violations('Neon Echoes', avoid)
        self.assertIn('neon', hits)
        self.assertIn('echoes', hits)
        self.assertEqual(['echo'], lyric_preferences.violations('an echo in the hall', avoid))
        self.assertIn('Where _____ grows', lyric_preferences.violations('Where silence grows', avoid))
        self.assertEqual([], lyric_preferences.violations('[Chorus]\nConcrete dawn', avoid))

    def test_whisper_ban_catches_portuguese_dodge(self):
        avoid = 'whispers\nechoes / echo'
        self.assertTrue(lyric_preferences.violations('Sombras Susurrantes', avoid))
        self.assertTrue(lyric_preferences.violations('Sombras que Sussurram', avoid))
        self.assertTrue(lyric_preferences.violations('[Verse]\nUm sussurro no café', avoid))

    def test_paragraph_lyrics_become_karaoke_lines(self):
        blob = (
            "[Verse A] [Singer A] In this city, we glow, lights in our eyes Every moment alive, so much more than we show "
            "[Singer B] In the crowd, we stand, faces like a sea of stars Lights on forever, making our dreams a promise "
            "[Chorus] [Singer A] lights, dreams, never let your hope fade"
        )
        lines = lyrics_sync.display_lines(blob)
        self.assertGreater(len(lines), 3)
        self.assertTrue(any("glow" in line for line in lines))
        self.assertTrue(any("crowd" in line for line in lines))
        self.assertFalse(any("[Singer" in line for line in lines))

    def test_session_remembers_issued_titles(self):
        ai_assist._session_titles.clear()
        ai_assist._remember_title("Static Bloom")
        taken = ai_assist._taken_titles()
        self.assertTrue(ai_assist._title_taken("Static Bloom", taken))
        self.assertTrue(ai_assist._title_taken("static bloom", taken))

    def test_near_duplicate_titles_conflict(self):
        self.assertFalse(ai_assist.titles_conflict('Sombras que Sussurram', 'Sombras Susurrantes'))
        self.assertTrue(ai_assist.titles_conflict('Conversa Mansa', 'Conversa Mansa (2)'))
        self.assertTrue(ai_assist.titles_conflict('Quiet Rain', 'quiet rain'))
        self.assertFalse(ai_assist.titles_conflict('Concrete Dawn', 'Sombras Susurrantes'))

    def test_scrub_removes_banned_bait_from_a_template_mood(self):
        avoid = 'neon\nechoes / echo\nrefrain'
        cleaned = lyric_preferences.scrub('Neon dusk, a luminous neon refrain, carefree motion', avoid)
        self.assertNotIn('neon', cleaned.casefold())
        self.assertNotIn('refrain', cleaned.casefold())
        self.assertIn('dusk', cleaned.casefold())

    def test_generate_rejects_persistent_banned_words_without_mangling_lyrics(self):
        with TemporaryDirectory() as temp, patch.object(lyric_preferences,'PATH',Path(temp)/'preferences.json'), patch.object(ai_assist.ai_vault,'require_enabled',return_value={'provider':'gemini','model':'test','key':'dummy'}), patch.object(ai_assist,'_complete',return_value='Title: Neon Echoes\n[Verse]\nNeon in the rain') as complete:
            lyric_preferences.save('neon\nechoes / echo')
            with self.assertRaisesRegex(RuntimeError, '3 attempts'):
                ai_assist.write('generate', idea='cyberpunk dusk')
            self.assertEqual(3, complete.call_count)

    def test_generate_accepts_rewrite_without_banned_words(self):
        with TemporaryDirectory() as temp, patch.object(lyric_preferences,'PATH',Path(temp)/'preferences.json'), patch.object(ai_assist.ai_vault,'require_enabled',return_value={'provider':'gemini','model':'test','key':'dummy'}), patch.object(ai_assist,'_taken_titles',return_value=['Neon Echoes']), patch.object(ai_assist,'_complete',side_effect=['Title: Neon Echoes\n[Verse]\nRain on steel', 'Title: Concrete Dawn\n[Verse]\nRain on steel']):
            lyric_preferences.save('neon\nechoes / echo')
            result = ai_assist.write('generate', idea='warehouse night')
            self.assertEqual('Concrete Dawn', result['title'])
            self.assertIn('Rain on steel', result['lyrics'])

    def test_duplicate_title_redoes_name_and_keeps_lyrics(self):
        with TemporaryDirectory() as temp, patch.object(lyric_preferences,'PATH',Path(temp)/'preferences.json'), patch.object(ai_assist.ai_vault,'require_enabled',return_value={'provider':'gemini','model':'test','key':'dummy'}), patch.object(ai_assist,'_taken_titles',return_value=['Quiet Rain']), patch.object(ai_assist,'_complete',side_effect=['Title: Quiet Rain\n[Verse]\nSteel on the dock', 'Title: Dock Lamps']) as complete:
            lyric_preferences.save('')
            result = ai_assist.write('generate', idea='night harbor')
            self.assertEqual('Dock Lamps', result['title'])
            self.assertIn('Steel on the dock', result['lyrics'])
            self.assertEqual(2, complete.call_count)
