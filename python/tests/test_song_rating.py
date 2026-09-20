import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import log_buffer
with patch.object(log_buffer, 'install'):
    import main
from fastapi.testclient import TestClient


def test_rating_persists_without_touching_audio_or_lyrics():
    with TemporaryDirectory() as temp, patch.object(main, 'LIBRARY_ROOT', Path(temp)):
        song = Path(temp) / 'nested' / 'song'
        song.mkdir(parents=True)
        original = {'id':'test', 'title':'Test', 'audio':'Test.wav', 'lyrics':'[Verse]\nHello', 'lyrics_sync':{'status':'ready'}, 'studio':{'tracks':[]}}
        (song/'song.json').write_text(json.dumps(original), encoding='utf-8')
        (song/'Test.wav').write_bytes(b'RIFFtest-audio')
        with patch.object(main, 'align_audio_to_title', side_effect=lambda folder, data, title: folder/'Test.wav'):
            client = TestClient(main.app)
            for rating in (5, 2, 0):
                response = client.patch('/api/library/nested/song/rating', json={'rating':rating})
                assert response.status_code == 200, response.text
                assert json.loads((song/'song.json').read_text()) == {**original, 'rating':rating}
                assert main.library()[0]['rating'] == rating
                assert (song/'Test.wav').read_bytes() == b'RIFFtest-audio'


@pytest.mark.parametrize('rating', [-1, 6, 2.5, True, '5', None])
def test_invalid_ratings_rejected(rating):
    client = TestClient(main.app)
    response = client.patch('/api/library/missing/rating', json={'rating':rating})
    assert response.status_code == 422


def test_missing_song_and_traversal_rejected():
    with TemporaryDirectory() as temp, patch.object(main, 'LIBRARY_ROOT', Path(temp)):
        client = TestClient(main.app)
        for folder in ('missing', '..%2Foutside'):
            assert client.patch(f'/api/library/{folder}/rating', json={'rating':5}).status_code == 404
