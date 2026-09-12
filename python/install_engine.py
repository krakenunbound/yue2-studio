"""Manually repair the YuE2 runtime after the Models page downloaded core YuE2.

Normal installs are driven by the in-app Models page. This utility is retained
for source developers who need to repair only the core runtime; it never
downloads model files itself.
"""
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'python/runtime/Scripts/python.exe'
def main():
    wheel = ROOT / 'yue2_infer-0.1.5-py3-none-any.whl'
    if not wheel.is_file():
        raise RuntimeError(
            'The YuE2 inference package is missing. Launch YuE2 Studio, open '
            'Models, and install or repair YuE2-3B before running this utility.'
        )
    if not RUNTIME.is_file():
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / 'python/runtime')], check=True)
    subprocess.run([str(RUNTIME), '-m', 'pip', 'install', 'torch==2.10.0', 'torchaudio==2.10.0', '--index-url', 'https://download.pytorch.org/whl/cu128'], check=True)
    subprocess.run([str(RUNTIME), '-m', 'pip', 'install', str(wheel), '-r', str(ROOT / 'python/engine-requirements.txt')], check=True)
if __name__ == '__main__':
    main()
