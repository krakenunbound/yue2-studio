import array
import json
import math
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main

class CombineTest(unittest.TestCase):
    def test_combine_and_restore_preserve_timing_edits_and_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); song=root/'source'; tracks=song/'studio'/'tracks'; tracks.mkdir(parents=True)
            originals=[]
            for name in ('a.wav','b.wav'):
                with wave.open(str(tracks/name),'wb') as f:
                    f.setparams((1,2,48000,0,'NONE','not compressed'))
                    f.writeframes(array.array('h',[int(4000*math.sin(i*.04)) for i in range(4800)]).tobytes())
                originals.append({'file':name,'name':name,'duration':.1})
            (song/'song.json').write_text(json.dumps({'title':'Test','studio_imports':originals}))
            states=[main.StudioTrackState(name='a.wav',gain=.5,use_clips=True,clips=[main.StudioClip(id='a',start=.2,source_out=.1,fade_in=.02)]),main.StudioTrackState(name='b.wav',solo=True,use_clips=True,clips=[main.StudioClip(id='b',start=.5,source_out=.1,gain_left=.5,gain_right=.5)])]
            with patch.object(main,'LIBRARY_ROOT',root):
                result=main.combine_studio_tracks('source',main.StudioCombineRequest(tracks=states,files=['a.wav','b.wav']))
                entry=result['imports'][0]
                with wave.open(str(tracks/entry['file']),'rb') as f:
                    self.assertEqual(f.getnchannels(),2); samples=array.array('h',f.readframes(f.getnframes()))
                left=samples[::2];self.assertEqual(left,samples[1::2])
                self.assertEqual(max(abs(x) for x in left[:9000]),0)
                self.assertGreater(max(abs(x) for x in left[10000:14000]),100)
                self.assertGreater(max(abs(x) for x in left[24500:28000]),100)
                self.assertEqual(len(json.loads((song/'song.json').read_text())['studio_imports']),1)
                self.assertTrue(all((tracks/item['file']).is_file() for item in originals))
                restored=main.uncombine_studio_tracks('source',entry['file'],main.StudioSessionRequest(tracks=[main.StudioTrackState(**t) for t in result['tracks']]))
                self.assertEqual(restored['imports'],originals)
                self.assertEqual(restored['tracks'],[t.model_dump() for t in states])

if __name__=='__main__': unittest.main()
