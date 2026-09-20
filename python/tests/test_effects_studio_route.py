from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import main
import stable_sfx


def test_add_effect_to_nested_studio_song_persists_and_serves_track() -> None:
    """An effect can be added to a genre/title library folder, then played in Studio."""
    with TemporaryDirectory() as temp:
        root = Path(temp)
        song = root / "Dark Techno" / "Apple Signal"
        effect = root / "effects" / "thunder-1"
        song.mkdir(parents=True)
        effect.mkdir(parents=True)
        (song / "song.json").write_text(json.dumps({"studio": {"tracks": [{"name": "vocals.wav", "gain": .8}]}}), encoding="utf-8")
        effect_audio = b"RIFF" + b"effect-audio" * 64
        (effect / "effect.wav").write_bytes(effect_audio)
        (effect / "effect.json").write_text(json.dumps({
            "id": "thunder-1",
            "name": "Heavy Thunderstorm",
            "prompt": "A heavy thunderstorm",
            "duration": 30.0,
            "seed": 77,
        }), encoding="utf-8")

        with patch.object(main, "LIBRARY_ROOT", root), patch.object(stable_sfx, "EFFECTS_ROOT", root / "effects"):
            client = TestClient(main.app)
            response = client.post("/api/effects/thunder-1/add-to-studio/Dark%20Techno/Apple%20Signal")
            assert response.status_code == 200, response.text
            imported = response.json()
            audio = client.get(imported["url"])

        manifest = json.loads((song / "song.json").read_text(encoding="utf-8"))

        assert audio.status_code == 200
        assert audio.content == effect_audio
        assert imported["url"].startswith("/api/library/Dark%20Techno%2FApple%20Signal/studio/tracks/")
        assert (song / "studio" / "tracks" / imported["file"]).is_file()
        assert manifest["studio"]["tracks"][0] == {"name": "vocals.wav", "gain": .8}
        added_track = manifest["studio"]["tracks"][1]
        assert added_track["name"] == imported["file"]
        assert added_track["lane"] == "Effects"
        assert added_track["gain"] == 1.0
        assert added_track["muted"] is False and added_track["solo"] is False
        assert added_track["use_clips"] is True
        assert added_track["clips"][0]["start"] == 0.0
        assert added_track["clips"][0]["source_out"] == 30.0
        assert manifest["studio_imports"] == [{
            "file": imported["file"],
            "name": "Heavy Thunderstorm",
            "source": "stable-audio-3-small-sfx",
            "effect_id": "thunder-1",
            "prompt": "A heavy thunderstorm",
            "negative_prompt": "",
            "duration": 30.0,
            "seed": 77,
            "created_at": manifest["studio_imports"][0]["created_at"],
        }]
