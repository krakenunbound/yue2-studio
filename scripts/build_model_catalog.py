"""Maintainer tool: freeze upstream model identities; never run by the app."""
import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
files = {key: [] for key in ('yue2', 'whisper', 'cover_art', 'stems', 'sound_effects')}

def repo(key, name, destination, select):
    response = httpx.get(f'https://huggingface.co/api/models/{name}', params={'blobs': 'true'}, follow_redirects=True, timeout=30)
    response.raise_for_status()
    data = response.json()
    for entry in data['siblings']:
        filename = entry['rfilename']
        if not select(filename):
            continue
        files[key].append({'path': str(Path(destination) / filename).replace('\\', '/'),
            'url': f"https://huggingface.co/{data['id']}/resolve/{data['sha']}/{filename}",
            'bytes': entry['size'], 'sha256': entry.get('lfs', {}).get('sha256'),
            'git_sha1': None if entry.get('lfs') else entry['blobId']})

repo('yue2', 'm-a-p/YuE2-3B', '.', lambda n: n in {'config.json','generation_config.json','model.safetensors','qwen.tiktoken','weights_manifest.json','yue2_generation_config.json','yue2_infer-0.1.5-py3-none-any.whl','LICENSE'})
repo('yue2', 'm-a-p/YuE2-Vae', 'models/YuE2-Vae', lambda n: n in {'config.json','model.safetensors','weights_manifest.json','LICENSE'})
repo('whisper', 'dropbox-dash/faster-whisper-large-v3-turbo', 'models/lyrics/whisper-large-v3-turbo', lambda n: n.endswith(('.bin','.json')))
repo('sound_effects', 'stabilityai/stable-audio-3-small-sfx', 'models/sound_effects/stable-audio-3-small-sfx', lambda n: n.endswith(('.safetensors','.json','.model')) or n in {'LICENSE.md','LICENSE_GEMMA.md','NOTICE'})
repo('cover_art', 'stable-diffusion-v1-5/stable-diffusion-v1-5', 'models/cover_art/sd15-config', lambda n: n.endswith('.json') or n=='tokenizer/merges.txt')

def local_identity(key, path, url):
    source = ROOT / path
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    files[key].append({'path':path, 'url':url, 'bytes':source.stat().st_size, 'sha256':digest})

local_identity('cover_art', 'models/cover_art/juggernaut_aftermath.safetensors', 'https://civitai.com/api/download/models/127207?fileId=91987')
config_text = (ROOT/'python/cover_art/sd15-v1-inference.yaml').read_text(encoding='utf-8')
files['cover_art'].append({'path':'python/cover_art/sd15-v1-inference.yaml','text':config_text,'bytes':len(config_text.encode()),'sha256':hashlib.sha256(config_text.encode()).hexdigest()})
local_identity('whisper', 'models/lyrics/torch/hub/checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth', 'https://download.pytorch.org/torchaudio/models/wav2vec2_fairseq_base_ls960_asr_ls960.pth')
local_identity('stems', 'models/stems/955717e8-8726e21a.th', 'https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th')
# The tiny local-repository descriptor is generated, not fetched from mutable upstream.
body = "models: ['955717e8']\n"
files['stems'].append({'path':'models/stems/htdemucs.yaml','text':body,'bytes':len(body),'sha256':hashlib.sha256(body.encode()).hexdigest()})
# Woosh's archive-backed manifest is pinned separately from HF repositories.
files['woosh'] = json.loads((ROOT/'python/model_catalog.json').read_text(encoding='utf-8'))['woosh']
(ROOT/'python/model_catalog.json').write_text(json.dumps(files, indent=2)+'\n', encoding='utf-8')
print('Frozen catalog:', {key: len(value) for key,value in files.items()})
