"""User-initiated, verified model installation into this application's folders."""
from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import httpx
from config import ROOT, OUTPUTS_ROOT

log = logging.getLogger('yue2.models')
GIB = 1024 ** 3
CATALOG = json.loads(Path(__file__).with_name('model_catalog.json').read_text(encoding='utf-8'))
DEFINITIONS = {
    'woosh': ('Sound effects — Sony Woosh-Flow', 'Creates short sound effects from simple text prompts on your NVIDIA GPU.', 'Installs Woosh-Flow, its audio decoder and text encoder, tokenizer, and a private Python 3.12 GPU runtime. Generates up to 5 seconds. Weights are for non-commercial use (CC-BY-NC).', True, 'models/sound_effects/woosh', 'woosh', ('torch','torchaudio','transformers','soundfile.py'), 5, 18, 'https://github.com/SonyResearch/Woosh'),
    'yue2': ('YuE2 music generation', 'Creates complete songs from your prompts and lyrics.', 'Installs YuE2-3B, its audio decoder, tokenizer and GPU runtime.', False, '.', 'main', ('yue2','torch','torchaudio'), 5, 25, 'https://huggingface.co/m-a-p/YuE2-3B'),
    'whisper': ('Whisper lyrics and karaoke', 'Matches lyrics to the vocals so words can follow playback.', 'Installs WhisperX, the English alignment model and Whisper large-v3-turbo for transcription fallback. Other alignment languages may download on first use.', True, 'models/lyrics', 'lyrics', ('whisperx','faster_whisper','torch'), 5, 22, 'https://github.com/m-bain/whisperX'),
    'cover_art': ('Cover art — Stable Diffusion 1.5', 'Creates square artwork for your songs on your NVIDIA GPU.', 'Installs Juggernaut Aftermath (an SD 1.5 model), its local configuration and image-generation runtime.', True, 'models/cover_art', 'main', ('diffusers','transformers','accelerate','torch'), 5, 25, 'https://civitai.com/models/46422/juggernaut?modelVersionId=127207'),
    'stems': ('Separate vocals and instruments', 'Splits a song into vocals, drums, bass and other instruments.', 'Installs Demucs and its htdemucs separation model for the Studio.', True, 'models/stems', 'main', ('demucs','torch','torchaudio'), 5, 25, 'https://github.com/facebookresearch/demucs'),
    'sound_effects': ('Sound effects — Stable Audio 3', 'Creates effects such as footsteps, impacts and ambience from text.', 'Installs the sound model, its text encoder and a separate CPU runtime. CPU generation can be slow, but leaves the GPU free.', True, 'models/sound_effects/stable-audio-3-small-sfx', 'sfx', ('stable_audio_3','torch','torchaudio'), 2, 10, 'https://huggingface.co/stabilityai/stable-audio-3-small-sfx'),
    'sheetsage': ('SheetSage2 cover from audio', 'Turns a recording into an editable lead sheet so YuE2 can cover it.', 'Installs SheetSage2, its MERT-v2 encoder, and a private GPU runtime. Weights are for non-commercial use (CC-BY-NC). Uses the GPU; YuE2 waits while it transcribes.', True, 'models/sheetsage2', 'sheetsage', ('transformers','torch','torchaudio'), 6, 16, 'https://huggingface.co/m-a-p/SheetSage2'),
}
RUNTIME_DIRS = {'woosh':'python/woosh_runtime','main':'python/runtime', 'lyrics':'python/lyrics_runtime', 'sfx':'python/sfx_runtime', 'sheetsage':'python/sheetsage_runtime'}
STATE_FILE = OUTPUTS_ROOT / 'settings' / 'model-installations.json'
_lock = threading.RLock()
activity_lock = threading.RLock()
_states: dict = {}
_cancel = threading.Event()
_thread: threading.Thread | None = None
_process: subprocess.Popen | None = None


class InstallationBusyError(RuntimeError):
    pass


def target(entry):
    result = (ROOT / entry['path']).resolve()
    if not result.is_relative_to(ROOT.resolve()):
        raise ValueError('Model destination is outside this app')
    return result


def runtime_python(key):
    return ROOT / RUNTIME_DIRS[DEFINITIONS[key][5]] / 'Scripts/python.exe'


def runtime_ready(key):
    runtime = runtime_python(key)
    packages = runtime.parent.parent / 'Lib/site-packages'
    if key == 'woosh' and not (ROOT/'python/vendor/Woosh/woosh').is_dir():
        return False
    return runtime.is_file() and all((packages/name).exists() for name in DEFINITIONS[key][6])


def _has_file(entry):
    path = target(entry)
    if not path.is_file():
        return False
    # Rewritten after download (SheetSage2 local MERT path). Presence is enough.
    if entry.get('mutable'):
        return path.stat().st_size > 0
    # Hugging Face records Git blob IDs over LF content.  A Windows checkout
    # with core.autocrlf enabled has the same text content, but a larger file.
    # Only catalogued Git text files use this normalization; weight files keep
    # their exact byte-size check below.
    if entry.get('git_sha1'):
        return _git_blob_matches(entry, path)
    return path.stat().st_size == entry['bytes']


def _remaining(entry):
    if _has_file(entry):
        return 0
    partial = target(entry).with_name(target(entry).name + '.part')
    size = partial.stat().st_size if partial.is_file() else 0
    return entry['bytes'] - size if 0 <= size < entry['bytes'] else entry['bytes']


def _load_states():
    try:
        states = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        for key, state in states.items():
            if key not in DEFINITIONS or not isinstance(state, dict):
                continue
            if state.get('status') == 'running':
                state = {'status':'cancelled', 'phase':'Installation was interrupted. Click Install to continue.', 'progress':0}
            _states[key] = state
    except (OSError, ValueError):
        pass


def _update(key, **values):
    with _lock:
        _states.setdefault(key, {}).update(values)
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps(_states, indent=2), encoding='utf-8')
        temporary.replace(STATE_FILE)


def list_models():
    free = shutil.disk_usage(ROOT).free
    items = []
    with _lock:
        for key, definition in DEFINITIONS.items():
            name, description, does, optional, folder, _, _, download_gib, disk_gib, source = definition
            models_ok = all(_has_file(entry) for entry in CATALOG[key])
            runtime_ok = runtime_ready(key)
            remaining = sum(_remaining(entry) for entry in CATALOG[key])
            if key == 'woosh' and not models_ok:
                # Archives coexist with extracted weights while installing.
                import woosh_setup
                archive_bytes = sum(entry['bytes'] for entry in woosh_setup.manifest()['archives'])
                remaining += archive_bytes
            installed = models_ok and runtime_ok
            items.append({'id':key, 'name':name, 'description':description, 'does':does,
                'optional':optional, 'ready':installed, 'model_ready':models_ok, 'runtime_ready':runtime_ok,
                'download_bytes':remaining + (0 if runtime_ok else download_gib * GIB),
                'required_free_bytes':remaining + (0 if runtime_ok else disk_gib * GIB) + 2 * GIB,
                'free_bytes':free, 'folder':str((ROOT/folder).resolve()),
                'detail': 'Installed · Repair verifies all files.' if installed else 'Missing model files or runtime. Install handles both; sizes include an estimate for runtime downloads.',
                'gated':key == 'sound_effects', 'source_url':source,
                'install':dict(_states.get(key, {'status':'idle','phase':'','progress':0}))})
    return {'items':items}


def _check_cancel():
    if _cancel.is_set():
        raise InterruptedError('Installation cancelled. Completed files are kept for the next attempt.')


def _git_blob_matches(entry, path):
    """Match a Git text blob after the LF-to-CRLF checkout conversion."""
    data = path.read_bytes()
    def blob_sha1(content):
        digest = hashlib.sha1(f"blob {len(content)}\0".encode())
        digest.update(content)
        return digest.hexdigest()

    # A few small distributable artifacts use Git blob IDs too.  Their raw
    # identity is always accepted; only a failed text identity can use the
    # Windows checkout normalization below.
    if len(data) == entry['bytes'] and blob_sha1(data) == entry['git_sha1']:
        return True
    # Git does not perform text conversion on NUL-containing blobs.  Do not
    # weaken identity checks for a binary entry which happens to use git_sha1.
    if b'\0' in data:
        return False
    normalized = data.replace(b'\r\n', b'\n')
    if len(normalized) != entry['bytes']:
        return False
    return blob_sha1(normalized) == entry['git_sha1']


def _verified(entry, path):
    if not path.is_file():
        return False
    if entry.get('mutable'):
        return path.stat().st_size > 0
    if entry.get('git_sha1'):
        return _git_blob_matches(entry, path)
    if path.stat().st_size != entry['bytes']:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            _check_cancel()
            digest.update(block)
    return digest.hexdigest() == entry['sha256']


def _download(key, entry, token, index, count):
    path = target(entry)
    _update(key, phase=f"Checking {path.name}", progress=.7 * index/count)
    if _verified(entry, path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + '.part')
    if part.is_symlink():
        raise RuntimeError('The partial download path must not be a symbolic link.')
    if 'text' in entry:
        part.write_bytes(entry['text'].encode())
    else:
        offset = part.stat().st_size if part.exists() else 0
        if offset >= entry['bytes']:
            if _verified(entry, part):
                part.replace(path)
                return
            offset = 0
        # Reserve space again immediately before transfer; other apps may have used it.
        if shutil.disk_usage(path.parent).free < entry['bytes'] - offset + GIB:
            raise RuntimeError('Not enough free disk space to complete this download.')
        headers = {'Range':f'bytes={offset}-'} if offset else {}
        if token and urlparse(entry['url']).hostname == 'huggingface.co':
            headers['Authorization'] = 'Bearer ' + token
        last_update = 0.0
        with httpx.stream('GET', entry['url'], headers=headers, follow_redirects=True,
                          timeout=httpx.Timeout(30, read=15)) as response:
            if response.status_code in (401,403):
                raise RuntimeError('Publisher access required. Open the model page, accept its terms, and supply a Hugging Face read token with access to this model.' if key == 'sound_effects' else 'The publisher denied this download. Check the model page for access requirements and try again.')
            response.raise_for_status()
            if response.status_code == 206:
                content_range = response.headers.get('content-range','')
                if not content_range.startswith(f'bytes {offset}-') or not content_range.endswith(f"/{entry['bytes']}"):
                    raise RuntimeError('The server returned an unexpected download range. Retry installation.')
            else:
                offset = 0  # Server ignored Range: restart instead of appending duplicate bytes.
            received = offset
            with part.open('ab' if offset else 'wb') as stream:
                for block in response.iter_bytes(1024 * 1024):
                    _check_cancel()
                    received += len(block)
                    if received > entry['bytes']:
                        raise RuntimeError(f'{path.name}: downloaded file is larger than expected')
                    stream.write(block)
                    now = time.monotonic()
                    if now - last_update > .5:
                        _update(key, phase=f"Downloading {path.name} · {received/1024**2:.0f} / {entry['bytes']/1024**2:.0f} MB",
                                progress=.7 * (index + received / entry['bytes']) / count)
                        last_update = now
    _update(key, phase=f'Verifying {path.name}')
    if not _verified(entry, part):
        # A complete but corrupt partial must not be reused on the next attempt.
        if part.exists() and part.stat().st_size >= entry['bytes']:
            part.unlink()
        raise RuntimeError(f'{path.name}: integrity check failed. Retry to download a verified copy.')
    _check_cancel()
    part.replace(path)
    log.info('Installed verified model file: %s', path)


def _stop_process(process):
    if process and process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), check=False)
        else:
            process.terminate()


def _run(key, command, phase, extra_env=None):
    global _process
    _check_cancel()
    _update(key, phase=phase)
    env = os.environ.copy()
    env.update(extra_env or {})
    scratch = OUTPUTS_ROOT/'downloads/tmp'
    scratch.mkdir(parents=True, exist_ok=True)
    env.update({'TMP':str(scratch), 'TEMP':str(scratch), 'PIP_CACHE_DIR':str(OUTPUTS_ROOT/'downloads/pip-cache'),
                'PYTHONUNBUFFERED':'1', 'PIP_DISABLE_PIP_VERSION_CHECK':'1'})
    with _lock:
        _check_cancel()
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        _process = process
    tail = []
    try:
        for line in process.stdout:
            _check_cancel()
            line = line.rstrip()
            if line:
                log.info('[install %s] %s',key,line)
                tail = (tail + [line])[-6:]
        code = process.wait()
        _check_cancel()
        if code:
            raise RuntimeError(phase + ' failed. ' + '\n'.join(tail))
    finally:
        _stop_process(process)
        process.wait(timeout=15)
        with _lock:
            if _process is process:
                _process = None


def _install_runtime(key):
    runtime = runtime_python(key)
    if not runtime.is_file():
        _run(key,[sys.executable,'-m','venv',str(runtime.parent.parent)],'Creating private runtime')
    # Repair is deliberately an import probe followed by installation, not a path-only check.
    modules = DEFINITIONS[key][6]
    try:
        _run(key,[str(runtime),'-c','; '.join('import '+name for name in modules)],'Checking runtime')
        return
    except RuntimeError:
        pass
    version, index = ('2.8.0','cu128') if key in {'whisper', 'sheetsage'} else (('2.7.1','cpu') if key == 'sound_effects' else ('2.10.0','cu128'))
    _run(key,[str(runtime),'-m','pip','install',f'torch=={version}',f'torchaudio=={version}','--index-url',f'https://download.pytorch.org/whl/{index}'], 'Installing runtime — this can take several minutes')
    packages = {
        'yue2':[str(ROOT/'yue2_infer-0.1.5-py3-none-any.whl'),'-r',str(ROOT/'python/engine-requirements.txt')],
        'whisper':['whisperx==3.8.4'],
        'cover_art':['diffusers==0.37.0','transformers==4.57.6','accelerate==1.13.0','pillow','omegaconf'],
        'stems':['demucs==4.0.1'],
        'sound_effects':['https://github.com/Stability-AI/stable-audio-3/archive/a0b57f5483c4588f827f3552b7d5c6ca2a9687be.zip'],
        'sheetsage':['transformers==4.45.2','huggingface-hub==0.36.0','safetensors==0.5.3','pretty_midi==0.2.10','mido==1.3.3','scipy'],
    }[key]
    _run(key,[str(runtime),'-m','pip','install',*packages], 'Installing feature support')
    _run(key,[str(runtime),'-c','; '.join('import '+name for name in modules)],'Verifying installed runtime')


def _install(key, token):
    try:
        entries = CATALOG[key]
        if key == 'woosh':
            import woosh_setup
            woosh_setup.install(sys.modules[__name__])
        else:
            for index, entry in enumerate(entries):
                _check_cancel()
                _download(key, entry, token, index, len(entries))
        token = ''
        _update(key, progress=.75)
        if key != 'woosh':
            _install_runtime(key)
        if key == 'sheetsage':
            import sheetsage
            sheetsage.prepare_local_parent()
        _check_cancel()
        missing = [entry['path'] for entry in entries if not _has_file(entry)]
        if not runtime_ready(key) or missing:
            detail = ', '.join(missing[:8]) if missing else 'private runtime'
            raise RuntimeError(f'Installation finished but required files are still missing: {detail}')
        _update(key,status='succeeded',phase='Installed and verified',progress=1,error=None)
        log.info('Model installation complete: %s', key)
    except InterruptedError as error:
        _update(key,status='cancelled',phase=str(error),error=None)
        log.info('Model installation cancelled: %s', key)
    except Exception as error:
        # Do not persist credentials or signed redirect URLs in UI state.
        message = str(error)
        if isinstance(error,httpx.HTTPError):
            message = 'Download failed. Check your connection and retry; partial downloads are retained.'
        if token:
            message = message.replace(token,'[REDACTED]')
        _update(key,status='failed',phase='Installation failed',error=message)
        log.error('Model installation failed (%s): %s',key,message)


def start(key, token=''):
    global _thread
    if key not in DEFINITIONS:
        raise KeyError(key)
    with _lock:
        if _thread and _thread.is_alive():
            raise RuntimeError('Another model installation is running. Wait or cancel it first.')
        item = next(item for item in list_models()['items'] if item['id'] == key)
        if item['free_bytes'] < item['required_free_bytes']:
            raise RuntimeError('Not enough free space on the app drive. Free some space and retry.')
        _cancel.clear()
        _update(key,status='running',phase='Preparing installation',progress=0,error=None)
        token = token.strip() or os.environ.get('HF_TOKEN','').strip()
        _thread = threading.Thread(target=_install,args=(key,token),name='model-installer',daemon=True)
        _thread.start()
    return {'started':True}


def cancel(key):
    if key not in DEFINITIONS:
        raise KeyError(key)
    with _lock:
        if _states.get(key,{}).get('status') != 'running':
            return {'cancelled':False}
        _cancel.set()
        process = _process
    _stop_process(process)
    return {'cancelled':True}


def busy():
    return bool(_thread and _thread.is_alive())


def shutdown():
    _cancel.set()
    _stop_process(_process)
    if _thread and _thread.is_alive():
        _thread.join(timeout=16)


_load_states()
atexit.register(shutdown)
