import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import model_manager as mm


@pytest.fixture
def installer(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, 'ROOT', tmp_path)
    monkeypatch.setattr(mm, 'OUTPUTS_ROOT', tmp_path/'outputs')
    monkeypatch.setattr(mm, 'STATE_FILE', tmp_path/'outputs/state.json')
    monkeypatch.setattr(mm, '_states', {})
    monkeypatch.setattr(mm, '_thread', None)
    mm._cancel.clear()
    yield tmp_path
    mm._cancel.clear()


def entry(data=b'correct model'):
    return {'path':'models/test.bin','url':'https://huggingface.co/example/resolve/revision/test.bin',
            'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def response(data, status=200, headers=None):
    return nullcontext(httpx.Response(status, content=data, headers=headers,
        request=httpx.Request('GET','https://huggingface.co/example')))


def test_verified_download_is_installed_atomically(installer):
    item = entry()
    with patch.object(mm.httpx,'stream',return_value=response(b'correct model')):
        mm._download('yue2',item,'',0,1)
    assert mm.target(item).read_bytes() == b'correct model'
    assert not mm.target(item).with_suffix('.bin.part').exists()


def test_corrupt_download_preserves_existing_file(installer):
    item = entry()
    path = mm.target(item)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'old working model')
    with patch.object(mm.httpx,'stream',return_value=response(b'incorrect!!!!')):
        with pytest.raises(RuntimeError,match='integrity'):
            mm._download('yue2',item,'',0,1)
    assert path.read_bytes() == b'old working model'


def test_resume_range_and_ignored_range(installer):
    item = entry()
    path = mm.target(item)
    path.parent.mkdir(parents=True)
    partial = path.with_suffix('.bin.part')
    partial.write_bytes(b'correct ')
    with patch.object(mm.httpx,'stream',return_value=response(b'model',206,{'content-range':'bytes 8-12/13'})) as request:
        mm._download('yue2',item,'',0,1)
    assert request.call_args.kwargs['headers']['Range'] == 'bytes=8-'
    assert path.read_bytes() == b'correct model'
    path.unlink()
    partial.write_bytes(b'correct ')
    with patch.object(mm.httpx,'stream',return_value=response(b'correct model')):
        mm._download('yue2',item,'',0,1)
    assert path.read_bytes() == b'correct model'


def test_git_blob_identity_verifies_small_config(installer):
    data = b'{}\n'
    item = entry(data)
    item.pop('sha256')
    item['git_sha1'] = hashlib.sha1(b'blob 3\0'+data).hexdigest()
    path = mm.target(item)
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    assert mm._verified(item,path)


def test_git_text_with_windows_line_endings_is_present_and_not_redownloaded(installer):
    lf = b'{\n  "model": "YuE2"\n}\n'
    item = {
        'path': 'config.json', 'url': 'https://huggingface.co/example/resolve/revision/config.json',
        'bytes': len(lf), 'git_sha1': hashlib.sha1(b'blob ' + str(len(lf)).encode() + b'\0' + lf).hexdigest(),
    }
    path = mm.target(item)
    path.write_bytes(lf.replace(b'\n', b'\r\n'))

    assert mm._has_file(item)
    assert mm._verified(item, path)
    assert mm._remaining(item) == 0
    with patch.object(mm.httpx, 'stream') as request:
        mm._download('yue2', item, '', 0, 1)
    request.assert_not_called()


def test_git_identity_does_not_normalize_binary_entries(installer):
    lf = b'left\nright\n'
    item = {
        'path': 'binary.dat', 'url': 'https://huggingface.co/example/resolve/revision/binary.dat',
        'bytes': len(lf), 'git_sha1': hashlib.sha1(b'blob ' + str(len(lf)).encode() + b'\0' + lf).hexdigest(),
    }
    path = mm.target(item)
    path.write_bytes(b'left\r\n\0right\r\n')
    assert not mm._has_file(item)
    assert not mm._verified(item, path)


def test_git_identity_keeps_exact_binary_entries(installer):
    data = b'wheel\0payload\r\n'
    item = {
        'path': 'package.whl', 'url': 'https://huggingface.co/example/resolve/revision/package.whl',
        'bytes': len(data), 'git_sha1': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
    }
    path = mm.target(item)
    path.write_bytes(data)
    assert mm._has_file(item)
    assert mm._verified(item, path)


def test_space_enforced_before_network(installer):
    with patch.object(mm.shutil,'disk_usage',return_value=SimpleNamespace(free=0)), patch.object(mm.httpx,'stream') as request:
        with pytest.raises(RuntimeError,match='free disk space'):
            mm._download('yue2',entry(),' ',0,1)
        request.assert_not_called()


def test_gated_download_has_actionable_message_and_no_file(installer):
    with patch.object(mm.httpx,'stream',return_value=response(b'denied',403)):
        with pytest.raises(RuntimeError,match='accept its terms'):
            mm._download('sound_effects',entry(),'test-token',0,1)
    assert not mm.target(entry()).exists()


def test_cancel_does_not_promote_partial(installer):
    mm._cancel.set()
    with patch.object(mm.httpx,'stream',return_value=response(b'correct model')):
        with pytest.raises(InterruptedError):
            mm._download('yue2',entry(),'',0,1)
    assert not mm.target(entry()).exists()


def test_catalog_cannot_escape_workspace(installer):
    with pytest.raises(ValueError,match='outside'):
        mm.target({'path':'../outside.bin'})


def test_failed_install_never_persists_token(installer):
    with patch.object(mm,'_download',side_effect=RuntimeError('denied test-secret-token')):
        mm._install('sound_effects','test-secret-token')
    saved = mm.STATE_FILE.read_text()
    assert 'test-secret-token' not in saved
    assert '[REDACTED]' in saved
    assert mm._states['sound_effects']['status'] == 'failed'


def test_start_rejects_concurrent_install_and_unknown_id(installer):
    with pytest.raises(KeyError):
        mm.start('unknown')
    with patch.object(mm,'_thread',SimpleNamespace(is_alive=lambda:True)):
        with pytest.raises(RuntimeError,match='Another'):
            mm.start('yue2')


def test_cancel_reports_false_when_that_model_is_not_installing(installer):
    assert mm.cancel('yue2') == {'cancelled': False}
    mm._states['yue2'] = {'status': 'running'}
    with patch.object(mm, '_stop_process') as stop:
        assert mm.cancel('yue2') == {'cancelled': True}
    stop.assert_called_once()


def test_restart_marks_interrupted_install_cancelled(installer):
    mm.STATE_FILE.parent.mkdir(parents=True)
    mm.STATE_FILE.write_text(json.dumps({'yue2':{'status':'running','progress':.5}}))
    mm._load_states()
    assert mm._states['yue2']['status'] == 'cancelled'


def test_active_install_prevents_job_submission(installer):
    import jobs
    with patch.object(mm,'busy',return_value=True):
        with pytest.raises(mm.InstallationBusyError):
            jobs.manager.submit('yue2',{},lambda job: {})
