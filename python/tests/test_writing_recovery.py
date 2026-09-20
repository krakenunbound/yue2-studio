import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_assist as ai
import lyric_preferences
import main
import ollama_transport
from fastapi import HTTPException


class WritingRecoveryTests(unittest.TestCase):
    def setUp(self):
        ai._cancel.clear()
        ai._shutdown.clear()
        ai._session_titles.clear()
        for target, name, value in (
            (ai, 'prepare', {'provider':'ollama','model':'gemma3:4b','key':'ollama','system':'test','base_url':'http://test/v1'}),
            (ai, '_taken_titles', []),
            (lyric_preferences, 'load', {'avoid':'whisper\necho\nTrace'}),
        ):
            stub = patch.object(target, name, return_value=value)
            stub.start()
            self.addCleanup(stub.stop)
        self.addCleanup(ai._cancel.clear)
        self.addCleanup(ai._session_titles.clear)

    def test_missing_opening_tag_keeps_all_sung_lines_without_a_retry(self):
        raw = 'Title: Copper Kettle\nMara warms the kettle\nRain taps the roof\n[Chorus]\nBring me home'
        with patch.object(ai, '_complete', return_value=raw) as complete:
            result = ai.write('generate', idea='a kettle')
        self.assertEqual(result['lyrics'], '[Verse]\n' + raw.split('\n', 1)[1])
        self.assertEqual(complete.call_count, 1)

    def test_prose_or_style_dump_is_not_disguised_as_a_verse(self):
        for text in ('Here is your song!\nEnjoy these lyrics', 'Drum machines at 120 BPM\nFour-on-the-floor warehouse electronics'):
            self.assertFalse(ai._sanitize_generated_lyrics(text).startswith('[Verse]'))

    def test_focused_repair_preserves_good_lines_and_repeated_chorus(self):
        draft = 'Title: Trace\n[Verse]\nMara warms the kettle\n[Chorus]\nA whispered promise\n[Verse]\nRain taps the roof\n[Chorus]\nA whispered promise'
        with patch.object(ai, '_complete', side_effect=[draft, '{"0":"A promise in your hand","title":"Copper Kettle"}']) as complete:
            result = ai.write('generate', idea='a kettle')
        self.assertEqual(result['title'], 'Copper Kettle')
        self.assertEqual(result['lyrics'], draft.split('\n',1)[1].replace('A whispered promise', 'A promise in your hand'))
        self.assertEqual(result['lyrics'].count('A promise in your hand'), 2)
        self.assertFalse(lyric_preferences.violations(result['title']+'\n'+result['lyrics']))
        self.assertEqual(complete.call_count, 2)
        repair_prompt = complete.call_args_list[1].args[4]
        self.assertEqual(json.loads(repair_prompt.split('Values to repair:\n')[1]), {'0':'A whispered promise','title':'Trace'})

    def test_failed_patch_never_drops_lines_or_bypasses_bans(self):
        draft = 'Title: Copper Kettle\n[Verse]\nMara warms the kettle\n[Chorus]\nA whispered promise'
        for invalid in ('{}', '{"0":""}', '{"0":"[Verse]"}', '{"0":"A whispered promise"}', '{"0":42}'):
            with self.subTest(invalid=invalid), patch.object(ai, '_complete', side_effect=[draft, invalid, invalid]) as complete:
                with self.assertRaises(ai.WritingValidationError):
                    ai.write('generate', idea='a kettle')
                self.assertEqual(complete.call_count, 3)
                self.assertNotIn('Copper Kettle', ai._session_titles)

    def test_unrequested_patch_fields_never_replace_valid_content(self):
        draft = 'Title: Copper Kettle\n[Verse]\nMara warms the kettle\n[Chorus]\nA whispered promise'
        with patch.object(ai, '_complete', side_effect=[draft, '{"0":"A promise in your hand","title":"Unrequested Name","extra":"echo"}']):
            result = ai.write('generate', idea='a kettle')
        self.assertEqual(result['title'], 'Copper Kettle')
        self.assertEqual(result['lyrics'], draft.split('\n',1)[1].replace('A whispered promise','A promise in your hand'))

    def test_large_draft_still_receives_a_small_focused_repair(self):
        draft = 'Title: Copper Kettle\n[Verse]\n' + 'Mara warms the copper kettle by the window\n' * 160 + '[Chorus]\nA whispered promise'
        with patch.object(ai, '_complete', side_effect=[draft, '{"0":"A promise in your hand"}']) as complete:
            result = ai.write('generate', idea='a kettle')
        call = complete.call_args_list[1]
        self.assertLess(len((call.args[3]+call.args[4]).encode('utf8')), ollama_transport.MAX_INPUT_BYTES)
        self.assertEqual(result['lyrics'].count('Mara warms the copper kettle by the window'), 160)

    def test_oversized_patch_falls_back_to_normal_retry(self):
        draft = 'Title: Copper Kettle\n[Verse]\nA whispered promise'
        with patch.object(ollama_transport, 'MAX_INPUT_BYTES', 5), patch.object(ai, '_complete', side_effect=[draft, 'Title: Copper Kettle\n[Verse]\nA promise in your hand']) as complete:
            result = ai.write('generate', idea='a kettle')
        self.assertEqual(complete.call_count, 2)
        self.assertIn('Previous reply failed validation', complete.call_args_list[1].args[4])
        self.assertIn('A promise in your hand', result['lyrics'])

    def test_cancel_between_draft_and_repair_sends_no_more_requests(self):
        def draft(*args, **kwargs):
            ai._cancel.set()
            return 'Title: Copper Kettle\n[Verse]\nA whispered promise'
        with patch.object(ai, '_complete', side_effect=draft) as complete:
            with self.assertRaisesRegex(RuntimeError, 'Writing cancelled'):
                ai.write('generate', idea='a kettle')
        self.assertEqual(complete.call_count, 1)

    def test_endpoint_distinguishes_cancel_rejection_and_transport_failure(self):
        for error, status, method in ((RuntimeError('Writing cancelled'),409,'info'), (ai.WritingValidationError('Invalid after 3 attempts'),502,'warning'), (RuntimeError('Local LLM stream failed'),502,'exception')):
            with self.subTest(error=error), patch.object(main.ai_assist,'write',side_effect=error), patch.object(main,'log') as log:
                with self.assertRaises(HTTPException) as raised:
                    main.assist_writing(main.WritingAssistRequest(action='generate',idea='boats'))
                self.assertEqual(raised.exception.status_code,status)
                getattr(log,method).assert_called_once()
                if method != 'exception':
                    log.exception.assert_not_called()


if __name__ == '__main__':
    unittest.main()
