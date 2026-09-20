import sys,unittest,re
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import log_buffer
with patch.object(log_buffer,'install'):
    import main
import lyric_format as fmt
import lyrics_align_worker as worker
import lyrics_sync
import yue2_engine
import ai_assist as ai

class SingerFormatTests(unittest.TestCase):
    def test_legacy_forms_keep_words_and_move_voice_direction(self):
        for label in ('[Singer A] ', 'Singer A: ', '(Singer A) ', 'Singer A\n'):
            raw='[Verse A]\n'+label+'The kettle starts to sing\n[Chorus]\nBoth: Bring the bread home'
            cleaned,directions=main.prepare_music3_lyrics(raw)
            self.assertEqual(cleaned,'[Verse]\nThe kettle starts to sing\n[Chorus]\nBring the bread home')
            self.assertTrue(any('The kettle starts to sing' in d and 'Singer A' in d for d in directions))
            self.assertTrue(any('Both singers' in d for d in directions))
            fmt.validate_engine_lyrics(cleaned)
            self.assertEqual([x['text'] for x in worker.extract_lyric_lines(raw,'en')],['The kettle starts to sing','Bring the bread home'])
            self.assertEqual(lyrics_sync.display_lines(raw),['The kettle starts to sing','Bring the bread home'])

    def test_inline_tags_and_combined_headers(self):
        raw='[Verse 1 - Singer A]\nRed apples shine\n[Singer B] Blue berries fall [Chorus]\n[Singer A & B] Bring them home'
        cleaned,directions=main.prepare_music3_lyrics(raw)
        self.assertEqual(cleaned,'[Verse]\nRed apples shine\nBlue berries fall\n[Chorus]\nBring them home')
        self.assertTrue(any('Singer B' in x for x in directions))
        self.assertTrue(any('Singer A & B' in x for x in directions))

    def test_ordinary_sung_words_and_unicode_are_preserved(self):
        raw='[Verse]\nSinger A is my name\nBoth of us are here\n彼方へ帰ろう\nCome home, my friend'
        cleaned,_=main.prepare_music3_lyrics(raw)
        self.assertEqual(cleaned,raw)

    def test_engine_refuses_uncompiled_or_broken_labels(self):
        for raw in ('Singer A: Hello','[Singer B] Hello','[Verse\nHello','Both:\nHello'):
            with self.assertRaises(ValueError): fmt.validate_engine_lyrics(raw)
        with self.assertRaises(main.HTTPException): main.prepare_music3_lyrics('[Singer A\nHello')

    def test_generation_copy_preserves_original_metadata(self):
        raw='[Verse]\nSinger A: Red apples shine\n[Chorus]\nBoth: Bring them home'
        params={'description':'English acoustic duet, female verse, male chorus','lyrics':raw,'instrumental':False,'cot_mode':'full','seed':123,'voice_slots':{}}
        with patch.object(yue2_engine,'count_prompt_tokens',return_value={'tokens':10,'maximum':20000}):
            prepared=main.prepare_generation_params(params)
        payload=yue2_engine._request_payload(prepared,Path('unused.wav'))
        self.assertEqual(prepared['lyrics'],raw)
        self.assertEqual(params['lyrics'],raw)
        self.assertNotIn('Singer',payload['lyrics'])
        self.assertIn('Singer A',payload['style'])

    def test_writer_response_normalizes_labels_without_losing_words(self):
        result=ai._parse_writing('Title: Baker Street\n[Verse]\nSinger A: Red apples shine\nSinger B: Blue berries fall')
        cleaned,_=main.prepare_music3_lyrics(result['lyrics'])
        self.assertEqual(cleaned,'[Verse]\nRed apples shine\nBlue berries fall')

    def test_pause_notation_is_never_a_sung_line(self):
        raw='[Verse]\nSing this\n[Singer A & B] ♩ ♮ (4-second pause) [Chorus]\nSing again'
        cleaned,_=main.prepare_music3_lyrics(raw)
        self.assertEqual(cleaned,'[Verse]\nSing this\n[Chorus]\nSing again')

    def test_internal_voice_annotations_do_not_break_editor_validation(self):
        source='[Verse]\n[Singer A]\nMara turns the brass key\n[Singer B]\nTomas brings the tray\n[Chorus]\n[Both]\nBring the bread home\nWe share the work today'
        self.assertEqual(ai._lyric_problems(source), [])
        self.assertEqual(ai._rewrite_problems(source, source), [])
        cleaned,_=main.prepare_music3_lyrics(source)
        fmt.validate_engine_lyrics(cleaned)
        self.assertNotIn('[Both]',cleaned)

    def test_provider_responses_share_the_same_generation_boundary(self):
        # Parsing and engine preparation do not select a provider-specific path.
        for reply in (
            'Title: Test\n[Verse]\nSinger A: Red apples shine\n[Chorus]\nBoth: Bring them home',
            '{"title":"Test","lyrics":"[Verse]\\n[Singer B] Red apples shine\\n[Chorus]\\n[Singer A & B] Bring them home"}',
            'Title: Test\n[Verse 1 - Singer A]\nRed apples shine\n[Chorus - Both]\nBring them home',
        ):
            parsed=ai._parse_writing(reply)
            cleaned,_=main.prepare_music3_lyrics(parsed['lyrics'])
            self.assertEqual(cleaned,'[Verse]\nRed apples shine\n[Chorus]\nBring them home')
            fmt.validate_engine_lyrics(cleaned)
