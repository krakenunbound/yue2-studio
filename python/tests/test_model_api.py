from unittest.mock import patch

from fastapi.testclient import TestClient
import main


def test_install_button_without_token_or_body():
    with patch.object(main.manager, 'list', return_value=[]), patch.object(main.yue2_engine, 'unload'), patch.object(main.model_manager, 'start', return_value={'started': True}) as start:
        response = TestClient(main.app).post('/api/models/whisper/install')
    assert response.status_code == 200
    start.assert_called_once_with('whisper', '')


def test_unknown_model_and_active_job_rejected():
    client = TestClient(main.app)
    assert client.post('/api/models/unknown/install').status_code == 404
    from types import SimpleNamespace
    with patch.object(main.manager, 'list', return_value=[SimpleNamespace(status='running')]), patch.object(main.model_manager, 'start') as start:
        assert client.post('/api/models/whisper/install').status_code == 409
        start.assert_not_called()


def test_missing_whisper_fallback_does_not_download(tmp_path):
    import pytest
    import lyrics_align_worker
    with patch.object(lyrics_align_worker, 'choose_device') as choose_device:
        with pytest.raises(RuntimeError, match='Open Models'):
            lyrics_align_worker.transcribe_with_fallback(tmp_path/'song.wav', 'en', 'auto', str(tmp_path/'missing-model'), 'lyrics')
        choose_device.assert_not_called()


def test_download_credentials_are_redacted():
    import logging
    from log_buffer import SafeFormatter
    message = 'https://cdn.example/file?Signature=signed-value&Policy=private-policy&token=secret hf_' + 'x'*30
    record = logging.LogRecord('download', logging.ERROR, '', 0, message, (), None)
    rendered = SafeFormatter().format(record)
    assert 'signed-value' not in rendered
    assert 'private-policy' not in rendered
    assert 'secret' not in rendered
    assert 'hf_' not in rendered
