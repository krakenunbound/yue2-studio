"""Exercise the real FFmpeg bounce and library export with mono imports."""
import json
import sys
import tempfile
import unittest
import wave
import array
import math
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main

class MonoExportTest(unittest.TestCase):
    def test_mono_import_exports_to_both_channels(self):
        for clips in (False, True):
            with self.subTest(clips=clips), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                song = root / 'source'
                tracks = song / 'studio' / 'tracks'
                tracks.mkdir(parents=True)
                with wave.open(str(tracks / 'effect.wav'), 'wb') as out:
                    out.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                    out.writeframes(array.array('h', [int(6000 * math.sin(i * 0.04)) for i in range(4800)]).tobytes())
                (song / 'song.json').write_text(json.dumps({'title': 'Channel test', 'studio_imports': [{'file': 'effect.wav'}]}))
                track = main.StudioTrackState(name='effect.wav', use_clips=clips, clips=[main.StudioClip(id='one', source_out=.1, gain_left=.5, gain_right=.5)] if clips else [])
                with patch.object(main, 'LIBRARY_ROOT', root):
                    result = main.bounce_studio_mix('source', main.StudioBounceRequest(tracks=[track]))
                exported = root / result['exported_folder']
                metadata = json.loads((exported / 'song.json').read_text())
                with wave.open(str(exported / metadata['audio']), 'rb') as audio:
                    self.assertEqual(audio.getnchannels(), 2)
                    samples = array.array('h', audio.readframes(audio.getnframes()))
                self.assertGreater(max(abs(x) for x in samples[::2]), 100)
                self.assertEqual(samples[::2], samples[1::2])

if __name__ == '__main__':
    unittest.main()
