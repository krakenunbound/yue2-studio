from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sheetsage
import main


def test_prepare_local_parent_points_at_downloaded_mert(tmp_path, monkeypatch):
    model = tmp_path / "sheetsage2"
    mert = model / "mert"
    mert.mkdir(parents=True)
    (model / "config.json").write_text(json.dumps({"base_model_name_or_path": "m-a-p/MERT-v2-FullSong"}), encoding="utf-8")
    monkeypatch.setattr(sheetsage, "MODEL_ROOT", model)
    monkeypatch.setattr(sheetsage, "MERT_ROOT", mert)
    sheetsage.prepare_local_parent()
    config = json.loads((model / "config.json").read_text(encoding="utf-8"))
    assert config["base_model_name_or_path"] == str(mert.resolve())


def test_cached_cover_transcription_skips_the_worker(tmp_path, monkeypatch):
    song = tmp_path / "night-drive"
    song.mkdir()
    (song / "sheetsage").mkdir()
    (song / "sheetsage" / "melody.abc").write_text("X:1\nK:C\nCDEF|\n", encoding="utf-8")
    monkeypatch.setattr(main, "resolve_song_folder", lambda _folder: song)
    monkeypatch.setattr(main.sheetsage, "load_score", sheetsage.load_score)
    monkeypatch.setattr(main.sheetsage, "score_path", sheetsage.score_path)
    job = SimpleNamespace(params={"folder": "night-drive", "melody_only": True, "reuse_cached": True}, phase="", progress=0, emit=lambda: None)
    with patch.object(main.yue2_engine, "unload") as unload, patch.object(main.sheetsage, "run") as run:
        result = main.transcribe_cover_score(job)
    assert result["cached"] is True
    assert "X:1" in result["abc"]
    unload.assert_not_called()
    run.assert_not_called()


def test_cover_transcribe_requires_installed_model():
    from fastapi.testclient import TestClient
    with patch.object(main.sheetsage, "status", return_value={"ready": False, "detail": "Open Models to install SheetSage2 cover-from-audio."}):
        response = TestClient(main.app).post("/api/library/song-one/cover-transcribe", json={"melody_only": True})
    assert response.status_code == 409
