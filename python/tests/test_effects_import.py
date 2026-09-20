from __future__ import annotations

import io
import json
import subprocess
import sys
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import main
import stable_sfx


def _wav_bytes(seconds: float = .1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


def _ffmpeg() -> str:
    path = main.ffmpeg_path()
    assert path, "Tests require the app's local FFmpeg exporter"
    return path


def test_imported_wav_and_compressed_sound_are_playable_and_add_to_nested_studio_song() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        effects = root / "effects"
        song = root / "Dark Techno" / "Apple Signal"
        song.mkdir(parents=True)
        (song / "song.json").write_text("{}", encoding="utf-8")
        wav = root / "input.wav"
        wav.write_bytes(_wav_bytes(.2))
        mp3 = root / "input.mp3"
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), str(mp3)], check=True)

        with patch.object(main, "LIBRARY_ROOT", root), patch.object(stable_sfx, "EFFECTS_ROOT", effects):
            client = TestClient(main.app)
            first = client.post("/api/effects/import?filename=hand-clap.wav&name=Hand%20Clap", content=wav.read_bytes())
            second = client.post("/api/effects/import?filename=recording.mp3", content=mp3.read_bytes())
            assert first.status_code == 200, first.text
            assert second.status_code == 200, second.text
            imported, compressed = first.json(), second.json()
            listed = client.get("/api/effects").json()["items"]
            audio = client.get(imported["url"])
            added = client.post(f"/api/effects/{compressed['id']}/add-to-studio/Dark%20Techno/Apple%20Signal")

        assert imported["source"] == "local-upload"
        assert imported["seed"] is None
        assert imported["name"] == "Hand Clap"
        assert imported["duration"] > .15
        assert imported["sample_rate"] == 44100
        assert imported["channels"] == 2
        assert {item["id"] for item in listed} == {imported["id"], compressed["id"]}
        assert audio.status_code == 200 and audio.headers["content-type"].startswith("audio/wav")
        assert (effects / imported["id"] / "source.wav").is_file()
        assert (effects / compressed["id"] / "source.mp3").is_file()
        assert (effects / imported["id"] / "source.wav").read_bytes() == wav.read_bytes()
        assert (effects / compressed["id"] / "source.mp3").read_bytes() == mp3.read_bytes()
        assert added.status_code == 200, added.text
        studio_entry = added.json()
        assert (song / "studio" / "tracks" / studio_entry["file"]).is_file()
        saved = json.loads((song / "song.json").read_text(encoding="utf-8"))
        assert saved["studio_imports"][0]["source"] == "local-upload"


def test_invalid_or_empty_effect_imports_are_not_published_or_left_as_partial_files() -> None:
    with TemporaryDirectory() as temp:
        effects = Path(temp) / "effects"
        with patch.object(stable_sfx, "EFFECTS_ROOT", effects):
            client = TestClient(main.app)
            empty = client.post("/api/effects/import?filename=empty.wav", content=b"")
            invalid = client.post("/api/effects/import?filename=bad.ogg", content=b"not audio")
            unsupported = client.post("/api/effects/import?filename=bad.txt", content=b"text")

        assert empty.status_code == 400
        assert invalid.status_code == 409
        assert unsupported.status_code == 415
        assert not effects.exists() or not list(effects.iterdir())


def test_duplicate_import_names_have_distinct_effect_ids_and_preserve_each_original() -> None:
    with TemporaryDirectory() as temp:
        effects = Path(temp) / "effects"
        with patch.object(stable_sfx, "EFFECTS_ROOT", effects):
            client = TestClient(main.app)
            one = client.post("/api/effects/import?filename=first.wav&name=My%20Sound", content=_wav_bytes()).json()
            two = client.post("/api/effects/import?filename=second.wav&name=My%20Sound", content=_wav_bytes()).json()

        assert one["id"] != two["id"]
        assert (effects / one["id"] / "source.wav").is_file()
        assert (effects / two["id"] / "source.wav").is_file()


def test_effect_import_staging_folders_are_hidden_and_oversize_uploads_are_cleaned_up() -> None:
    with TemporaryDirectory() as temp:
        effects = Path(temp) / "effects"
        staging = effects / ".half-import.partial"
        staging.mkdir(parents=True)
        (staging / "effect.wav").write_bytes(_wav_bytes())
        (staging / "effect.json").write_text(json.dumps({"name": "Should stay hidden"}), encoding="utf-8")
        with patch.object(stable_sfx, "EFFECTS_ROOT", effects), patch.object(stable_sfx, "MAX_EFFECT_UPLOAD_BYTES", 32):
            client = TestClient(main.app)
            assert client.get("/api/effects").json()["items"] == []
            response = client.post("/api/effects/import?filename=too-big.wav", content=b"x" * 33)

        assert response.status_code == 413
        assert list(effects.iterdir()) == [staging]
