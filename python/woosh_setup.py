"""Pinned Woosh installation, sharing the model manager's progress and cancellation."""
from pathlib import Path
import json
import os
import shutil
import sys
import zipfile


def manifest():
    return json.loads(Path(__file__).with_name('woosh_downloads.json').read_text(encoding='utf-8'))


def unpack(manager, archive, destination, strip_root=False):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            manager._check_cancel()
            parts = Path(item.filename).parts
            relative = Path(*parts[1:]) if strip_root else Path(*parts)
            target = (destination / relative).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('Archive contains an unsafe path')
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.extracting')
            with bundle.open(item) as source, temporary.open('wb') as output:
                while block := source.read(1024 * 1024):
                    manager._check_cancel()
                    output.write(block)
            temporary.replace(target)


def install(manager):
    key = 'woosh'; spec = manifest()
    root = manager.ROOT / 'models/sound_effects/woosh'
    entries = manager.CATALOG[key]
    for index, archive in enumerate(spec['archives']):
        name = Path(archive['path']).stem
        required = [entry for entry in entries if f'/checkpoints/{name}/' in entry['path']]
        if not all(manager._verified(entry, manager.target(entry)) for entry in required):
            manager._download(key, archive, '', index, 4)
            manager._update(key, phase=f'Unpacking {name}')
            unpack(manager, manager.target(archive), root)
    for index, entry in enumerate(entries):
        if 'url' in entry or 'text' in entry:
            manager._download(key, entry, '', index, len(entries))
    vendor = manager.ROOT / 'python/vendor/Woosh'
    # Install the pinned upstream code without requiring Git on the user's PC.
    manager._download(key, spec['source'], '', 3, 4)
    unpack(manager, manager.target(spec['source']), vendor, strip_root=True)
    runtime = manager.runtime_python(key)
    try:
        manager._run(key, [str(runtime), '-c', 'import woosh, torch, torchaudio, transformers, soundfile'], 'Checking Woosh runtime')
    except (RuntimeError, OSError):
        tools = manager.ROOT / 'python/model_install_tools'
        tool_python = tools / 'Scripts/python.exe'
        if not tool_python.is_file():
            manager._run(key, [sys.executable, '-m', 'venv', str(tools)], 'Preparing Woosh installer')
        manager._run(key, [str(tool_python), '-m', 'pip', 'install', 'uv==0.9.24'], 'Installing Python setup tools')
        manager._run(key, [str(tool_python), '-m', 'uv', 'sync', '--project', str(vendor), '--python', '3.12', '--extra', 'cuda', '--no-default-groups', '--group', 'audioio'], 'Installing Woosh GPU runtime and Python 3.12', extra_env={'UV_PROJECT_ENVIRONMENT':str(runtime.parent.parent), 'UV_PYTHON_INSTALL_DIR':str(manager.ROOT/'python/managed'), 'UV_CACHE_DIR':str(manager.OUTPUTS_ROOT/'downloads/uv-cache')})
        manager._run(key, [str(runtime), '-c', 'import woosh, torch, torchaudio, transformers, soundfile'], 'Verifying Woosh runtime')
    for license_file in vendor.glob('LICENSE*'):
        shutil.copy2(license_file, root / license_file.name)
