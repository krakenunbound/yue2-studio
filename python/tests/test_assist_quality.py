import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_assist as ai
import lyric_preferences


class AssistQualityTests(unittest.TestCase):
    def setUp(self):
        ai._cancel.clear()
        ai._shutdown.clear()
        ai._session_titles.clear()
        self.access = patch.object(ai, 'prepare', return_value={'provider':'ollama', 'model':'gemma3:4b', 'key':'ollama', 'system':'test', 'base_url':'http://test/v1'})
        self.access.start()
        self.prefs = patch.object(lyric_preferences, 'load', return_value={'avoid':''})
        self.prefs.start()
        self.titles = patch.object(ai, '_taken_titles', side_effect=lambda include_session=True: list(ai._session_titles) if include_session else [])
        self.titles.start()
        self.addCleanup(self.titles.stop)
        self.addCleanup(self.access.stop)
        self.addCleanup(self.prefs.stop)
        self.addCleanup(ai._cancel.clear)
        self.addCleanup(ai._session_titles.clear)

    def test_source_is_present_for_optimize_and_translate(self):
        for action in ('optimize', 'translate'):
            self.assertIn('Mara keeps a kettle', ai._writing_user(action, lyrics='[Verse]\nMara keeps a kettle'))

    def test_translation_does_not_request_original_language_or_new_verse(self):
        prompt = ai._writing_user('translate', lyrics='[Bridge]\n夜', language='ja')
        self.assertNotIn('Sung language: Japanese', prompt)
        self.assertNotIn('starting with [Verse]', prompt)

    def test_same_line_section_is_not_swallowed_by_title(self):
        result = ai._parse_writing('Title: Rolling Wheat — [Verse 1]\nWarm bread\n[Chorus]\nTake it home')
        self.assertEqual(ai._clean_title(result['title']), 'Rolling Wheat')
        self.assertTrue(result['lyrics'].startswith('[Verse 1]'))

    def test_title_only_parser(self):
        self.assertEqual(ai._parse_writing('Title: Copper Kettle')['title'], 'Copper Kettle')
        self.assertEqual(ai._parse_writing('Title: Copper Kettle')['lyrics'], '')

    def test_clean_title_removes_dangling_dash_and_romanization(self):
        self.assertEqual(ai._clean_title('Harbor Lantern —'), 'Harbor Lantern')
        self.assertEqual(ai._clean_title('雨の駅 (Ame no Eki)'), '雨の駅')

    def test_japanese_phonetic_duplicate_lines_require_repair(self):
        self.assertTrue(ai._language_problems('[Verse]\n雨の駅\nあめのえき\n猫が眠る\nねこがねむる', 'ja'))
        self.assertEqual(ai._language_problems('[Verse]\n雨の駅\n猫が眠る', 'ja'), [])
        self.assertTrue(ai._language_problems('[Verse]\nWasureられたmenkige mitsumeteru', 'ja'))

    def test_parallel_romanization_removed_without_dropping_native_lyrics(self):
        lyrics = '[Verse]\n雨の駅\nAme no eki\n猫が眠る\nNeko ga nemuru'
        self.assertEqual(ai._remove_parallel_romanization(lyrics, 'ja'), '[Verse]\n雨の駅\n猫が眠る')
        self.assertTrue(ai._language_problems('[Verse]\nOnly English', 'ja'))

    def test_edit_discards_extra_sections_only_after_matching_source(self):
        source = '[Verse]\nKettle\n[Chorus]\nCome home'
        draft = '[Verse 1]\nWarm kettle\n[Chorus]\nCome home\n[Verse 2]\nInvented'
        self.assertEqual(ai._fit_rewrite_sections(draft, source), '[Verse 1]\nWarm kettle\n[Chorus]\nCome home')
        unrelated = '[Bridge]\nNew\n[Chorus]\nOld'
        self.assertEqual(ai._fit_rewrite_sections(unrelated, source), unrelated)

    def test_native_unspaced_bans(self):
        self.assertTrue(lyric_preferences.violations('今夜は長い', '夜'))
        self.assertFalse(lyric_preferences.violations('bread', 'red'))

    def test_ban_aliases_and_invisible_characters(self):
        for value in ('N\u200beon', 'Ｎｅｏｎ', 'Neón'):
            self.assertTrue(lyric_preferences.violations(value, 'neon'))
        self.assertTrue(lyric_preferences.violations('Ecos no cais', 'echo'))
        self.assertTrue(ai._lyric_problems('[Verse]\nSafe line\n[Neon]'))

    def test_generate_rejects_prose_and_then_accepts_repair(self):
        with patch.object(ai, '_complete', side_effect=['Here is your song!', 'Title: Copper Kettle\n[Verse]\nMara keeps the kettle warm']) as complete:
            result = ai.write('generate', idea='a kettle')
        self.assertEqual(complete.call_count, 2)
        self.assertTrue(result['lyrics'].startswith('[Verse]'))
        self.assertIn('Previous draft to correct', complete.call_args_list[1].args[4])
        self.assertEqual(complete.call_args_list[1].kwargs['temperature'], 0.25)

    def test_generate_keeps_a_valid_song_when_local_model_adds_annotations(self):
        raw = ('Title: Harbor Lantern\nHere is your song:\n[Whispered]\n'
               '[Verse 1]\nMara keeps the kettle warm\n[Chorus]\nBring me home')
        with patch.object(ai, '_complete', return_value=raw):
            result = ai.write('generate', idea='a kettle')
        self.assertEqual(result['lyrics'], '[Verse 1]\nMara keeps the kettle warm\n[Chorus]\nBring me home')
        self.assertEqual(ai._lyric_problems(result['lyrics']), [])

    def test_generate_drops_unknown_bracket_label(self):
        raw = 'Title: Harbor Lantern\n[Softly]\n[Verse]\nA kettle warms the rain'
        with patch.object(ai, '_complete', return_value=raw):
            result = ai.write('generate', idea='a kettle')
        self.assertNotIn('[Softly]', result['lyrics'])

    def test_generate_preserves_singer_routing_tag_after_a_section(self):
        raw = 'Title: Harbor Lantern\n[Verse]\n[Singer A]\nMara keeps the kettle warm'
        with patch.object(ai, '_complete', return_value=raw):
            result = ai.write('generate', idea='a kettle')
        self.assertIn('[Singer A]', result['lyrics'])
        self.assertEqual(ai._lyric_problems(result['lyrics']), [])

    def test_sanitizer_does_not_discard_an_untagged_opening_verse(self):
        malformed = 'Mara keeps the kettle warm\n[Chorus]\nBring me home'
        cleaned = ai._sanitize_generated_lyrics(malformed)
        self.assertEqual(cleaned, '[Verse]\n' + malformed)
        self.assertEqual(ai._lyric_problems(cleaned), [])

    def test_preserve_supplied_title(self):
        with patch.object(ai, '_complete', return_value='Title: Wrong Name\n[Verse]\nMara keeps a kettle'):
            result = ai.write('optimize', title='Chosen Name', lyrics='[Verse]\nMara keeps a kettle')
        self.assertEqual(result['title'], 'Chosen Name')
        self.assertTrue(ai._title_taken('Chosen Name', ai._taken_titles()))

    def test_duplicate_title_cannot_hide_behind_edition_suffix(self):
        for title in ('Copper Kettle (Live)', 'Copper Kettle - Acoustic', 'Copper Kettle (2)'):
            self.assertTrue(ai.titles_conflict('Copper Kettle', title))
        self.assertFalse(ai.titles_conflict('Copper Kettle', 'Copper River'))

    def test_no_numbered_title_fallback(self):
        with patch.object(ai, '_taken_titles', return_value=['Copper Kettle']), patch.object(ai, '_complete', return_value='Title: Copper Kettle'):
            with self.assertRaisesRegex(RuntimeError, 'No duplicate'):
                ai.ensure_unique_title('Copper Kettle')

    def test_submitting_issued_title_does_not_rename_or_reserve_failed_job(self):
        ai._remember_title('Copper Kettle QA')
        self.assertEqual(ai.ensure_unique_title('Copper Kettle QA', for_generation=True), 'Copper Kettle QA')
        self.assertEqual(ai.ensure_unique_title('Copper Kettle QA', for_generation=True), 'Copper Kettle QA')

    def test_title_response_never_overwrites_lyrics(self):
        with patch.object(ai, '_complete', return_value='Title: A Baker at Sea\n[Verse]\nUnwanted words'):
            self.assertEqual(ai.write('title', lyrics='original')['lyrics'], '')

    def test_translation_retries_wrong_line_count(self):
        with patch.object(ai, '_complete', side_effect=['[Verse]\nThe cat sleeps', '[Verse]\nThe cat sleeps\nRain taps the roof']) as complete:
            result = ai.write('translate', lyrics='[Verse]\n猫が眠る\n雨が降る', language='ja')
        self.assertEqual(complete.call_count, 2)
        self.assertEqual(len(result['lyrics'].splitlines()), 3)

    def test_greeting_never_starts_generation(self):
        with patch.object(ai, '_complete') as complete:
            self.assertFalse(ai.chat([{'role':'user','content':'Hello'}])['ready'])
        complete.assert_not_called()

    def test_cancel_cannot_be_cleared_by_another_request(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(2)
            return 'Title: River Boats\n[Verse]\nThe tide rolls in'
        def run():
            try: ai.write('generate', idea='boats')
            except RuntimeError as error: errors.append(str(error))
        with patch.object(ai, '_complete', side_effect=blocked):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(entered.wait(1))
            ai.abort_writing()
            try:
                with self.assertRaises(ai.WritingBusyError): ai.describe(idea='piano')
                self.assertTrue(ai.writing_cancelled())
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any('cancelled' in e for e in errors))

    def test_chat_and_effect_recover_after_abort(self):
        for fn in (lambda: ai.chat([{'role':'user','content':'A piano song about fishing'}]), lambda: ai.enhance_effect('door')):
            ai.abort_writing()
            with patch.object(ai, '_complete', return_value='A deep wooden impact in a stone room.'):
                self.assertTrue(fn())

    def test_clean_effect_wrapper(self):
        with patch.object(ai.ai_vault, 'require_enabled', return_value={'provider':'ollama','model':'test','key':'test'}), patch.object(ai, '_complete', return_value='```json\n{"prompt":"A deep wooden slam in a quiet room."}\n```'):
            self.assertEqual(ai.enhance_effect('door')['description'], 'A deep wooden slam in a quiet room.')

    def test_optimize_preserves_sung_quantities(self):
        source = '[Verse]\nSeven cups and room for one more'
        self.assertTrue(ai._rewrite_problems(source, '[Verse 1]\nSix mugs and room for one more'))
        self.assertEqual(ai._rewrite_problems(source, '[Verse 1]\nSeven cups and room for one more'), [])

    def test_scrub_preserves_line_boundaries(self):
        self.assertEqual(lyric_preferences.scrub('[Verse]\n\nNeon rain\nDry road', 'Neon'), '[Verse]\n\n rain\nDry road')


if __name__ == '__main__':
    unittest.main()
