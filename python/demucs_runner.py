"""Run trusted local Demucs checkpoints with live, parseable progress."""
from __future__ import annotations

import sys

import torch
import tqdm
import numpy as np
from scipy.io import wavfile


_torch_load = torch.load


def trusted_load(*args, **kwargs):
    # Demucs 4 checkpoints contain their model class. PyTorch 2.6+ otherwise
    # rejects this established package format by default.
    kwargs.setdefault("weights_only", False)
    return _torch_load(*args, **kwargs)


class LineProgress(tqdm.tqdm):
    def display(self, msg=None, pos=None):
        total = float(self.total or 0)
        percent = min(100, round(100 * float(self.n) / total)) if total else 0
        print(f"STEM_PROGRESS {percent}", flush=True)


torch.load = trusted_load
tqdm.tqdm = LineProgress


def save_wav(wav, path, samplerate, clip="rescale", **_kwargs):
    """Avoid TorchCodec: write the separated float tensor as ordinary 16-bit WAV."""
    data = wav.detach().float().cpu().numpy()
    peak = float(np.abs(data).max(initial=0.0))
    if clip == "rescale" and peak > 0.99:
        data = data * (0.99 / peak)
    data = np.clip(data, -1.0, 1.0)
    wavfile.write(path, samplerate, (data.T * 32767.0).astype(np.int16))


import demucs.audio  # noqa: E402
demucs.audio.save_audio = save_wav

from demucs.separate import main  # noqa: E402


if __name__ == "__main__":
    main(sys.argv[1:])
