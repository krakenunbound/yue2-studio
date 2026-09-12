"""Download and verify the two YuE2 models used by this studio."""
from pathlib import Path
import hashlib
import json
from huggingface_hub import snapshot_download
ROOT = Path(__file__).resolve().parents[1]
MODELS = [('m-a-p/YuE2-3B', ROOT), ('m-a-p/YuE2-Vae', ROOT / 'models/YuE2-Vae')]
def verify(directory):
    manifest = directory / 'weights_manifest.json'
    if not manifest.is_file():
        return False
    for name, info in json.loads(manifest.read_text())['files'].items():
        path = directory / name
        if not path.is_file() or path.stat().st_size != info['bytes']:
            return False
        with path.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != info['sha256']:
                return False
    return True
def main():
    for repo, directory in MODELS:
        if not verify(directory):
            snapshot_download(repo, local_dir=directory, allow_patterns=['*.json', '*.safetensors', '*.tiktoken', '*.py', '*.whl', 'LICENSE', 'licenses/*'], force_download=True)
        if not verify(directory):
            raise RuntimeError(f'Integrity verification failed: {repo}')
        print(f'Verified {repo}: {directory}', flush=True)
if __name__ == '__main__':
    main()
