from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ai_assist
import lyric_preferences

class LyricPreferencesTest(TestCase):
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
            for action in ('generate','optimize'):
                ai_assist.write(action,idea='home',lyrics='A road leads home')
                self.assertIn('velvet\nSpark',complete.call_args.args[3])
