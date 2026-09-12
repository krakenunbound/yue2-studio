"""Private resident inference worker for MiniMax Music 3 Studio."""
from __future__ import annotations

import gc
import json
import sys
import time
import traceback
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "python" / "vendor" / "ComfyUI"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gpu_profile

_GPU_PROFILE: dict | None = None

_CLIP = None
_MODEL = None
_VAE = None
_MODEL_FINGERPRINT = None


def emit(marker: str, payload: dict | None = None) -> None:
    print(marker + ((" " + json.dumps(payload, ensure_ascii=False)) if payload is not None else ""), flush=True)


def save_wav(path: Path, waveform, sample_rate: int) -> None:
    samples = waveform.detach().float().cpu().squeeze(0).clamp(-1, 1).numpy()
    if samples.ndim == 1:
        samples = np.stack([samples, samples])
    pcm = (samples.T * 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(int(pcm.shape[1]))
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def load_models(paths: dict):
    global _CLIP, _MODEL, _VAE, _MODEL_FINGERPRINT
    import comfy.sd
    import comfy.utils

    fingerprint = tuple(str(Path(paths[key]).resolve()) for key in ("text_encoder", "diffusion", "decoder"))
    if _MODEL_FINGERPRINT == fingerprint and _CLIP is not None and _MODEL is not None and _VAE is not None:
        emit("MUSIC3_PROGRESS", {"progress": 0.02, "message": "Reusing warm Music 3 models"})
        return _CLIP, _MODEL, _VAE
    emit("MUSIC3_PROGRESS", {"progress": 0.02, "message": "Loading optimized Music 3 models"})
    _CLIP = comfy.sd.load_clip([paths["text_encoder"]], clip_type=comfy.sd.CLIPType.MINIMAX)
    _MODEL = comfy.sd.load_diffusion_model(paths["diffusion"], model_options={})
    decoder_state, decoder_metadata = comfy.utils.load_torch_file(paths["decoder"], return_metadata=True)
    _VAE = comfy.sd.VAE(sd=decoder_state, metadata=decoder_metadata)
    _MODEL_FINGERPRINT = fingerprint
    return _CLIP, _MODEL, _VAE


def run(request: dict) -> None:
    import torch
    import comfy.model_management
    import comfy.sample
    import comfy.sd
    import comfy.utils
    from comfy.ldm.minimax_music.ar import AUDIO_FRAMES_PER_SECOND, MAX_AUDIO_FRAMES
    from comfy.ldm.minimax_music.dit import latent_length
    from comfy.ldm.minimax_music.prompt import build_prompt

    global _GPU_PROFILE
    if not torch.cuda.is_available():
        raise RuntimeError("MiniMax Music 3 requires an NVIDIA CUDA GPU.")
    # Hand the desktop back real headroom before anything allocates. A hardcoded
    # 0.92 on a 24 GB display GPU leaves Windows ~1.4 GB, and the moment another
    # app wants VRAM the compositor gets evicted and the machine stalls.
    if _GPU_PROFILE is None:
        _GPU_PROFILE = gpu_profile.apply_to_worker()
        emit("MUSIC3_GPU", _GPU_PROFILE)
    models = request["models"]
    clip, model, vae = load_models(models)

    duration = max(1.0, min(300.0, float(request["duration"])))
    max_frames = min(MAX_AUDIO_FRAMES, max(1, round(duration * AUDIO_FRAMES_PER_SECOND)))
    seed = int(request["seed"])
    emit("MUSIC3_PROGRESS", {"progress": 0.05, "message": "Composing song structure and vocals"})

    stage = {"name": "ar"}
    ar_started = time.monotonic()
    def progress(value, total, _preview=None, node_id=None):
        # AR can account for thousands of frame updates. Map all engine work
        # into a stable UI range without presenting fake time estimates.
        fraction = (value / total) if total else 0.0
        if stage["name"] == "ar":
            value_out, message = 0.06 + 0.76 * fraction, "Composing song structure and vocals"
        elif stage["name"] == "decode":
            value_out, message = 0.88 + 0.02 * fraction, "Decoding stereo audio"
        else:
            return
        elapsed = max(0.001, time.monotonic() - ar_started)
        rate = value / elapsed if value else 0.0
        # Include a small measured allowance for diffusion, audio decode and
        # the automatic SD 1.5 thumbnail so this is a whole-job ETA.
        eta = (((total - value) / rate) + 30.0) if rate > 0 and total else None
        emit("MUSIC3_PROGRESS", {"progress": value_out, "message": message, "eta_seconds": eta})

    comfy.utils.set_progress_bar_global_hook(progress)
    caption, lyrics = request["caption"], request["lyrics"]
    if not isinstance(caption, str) or not isinstance(lyrics, str):
        raise TypeError(f"Music 3 worker expected text caption and lyrics, got {type(caption).__name__} and {type(lyrics).__name__}")
    combined_prompt = str(build_prompt(str(caption), str(lyrics)))
    if not isinstance(combined_prompt, str):
        raise TypeError(f"Music 3 combined prompt must be text, got {type(combined_prompt).__name__}")
    token_ids = clip.tokenizer.tokenizer.encode(combined_prompt, add_special_tokens=False).ids
    tokens = {
        "minimax_music3": [[(token, 1.0) for token in token_ids]],
        "seed": seed,
        "max_audio_frames": max_frames,
        "cfg_scale": float(request["cfg"]),
        "top_k": int(request.get("top_k", 50)),
    }
    conditioning = clip.encode_from_tokens_scheduled(tokens)
    for cond in conditioning:
        hidden = cond[0]
        cond[1]["conditioning_scale"] = torch.ones((hidden.shape[0], 1, 1), device=hidden.device, dtype=hidden.dtype)
    seconds = conditioning[0][0].shape[1] / AUDIO_FRAMES_PER_SECOND
    negative = []
    for tensor, metadata in conditioning:
        meta = metadata.copy()
        meta["conditioning_scale"] = torch.zeros_like(meta["conditioning_scale"])
        negative.append([torch.zeros_like(tensor), meta])
    latent_frames = latent_length(min(MAX_AUDIO_FRAMES, max(1, round(seconds * AUDIO_FRAMES_PER_SECOND))))
    latent = torch.zeros((1, 128, latent_frames), device=comfy.model_management.intermediate_device(), dtype=comfy.model_management.intermediate_dtype())
    noise = comfy.sample.prepare_noise(latent, seed)
    steps = int(request["steps"])
    stage["name"] = "diffusion"
    diffusion_started = time.monotonic()
    def sample_progress(step, _x0, _x, total_steps):
        completed = step + 1
        elapsed = max(0.001, time.monotonic() - diffusion_started)
        eta = max(0.0, (total_steps - completed) * (elapsed / completed) + 18.0)
        emit("MUSIC3_PROGRESS", {
            "progress": 0.83 + 0.04 * (completed / max(1, total_steps)),
            "message": f"Refining audio {completed}/{total_steps}",
            "eta_seconds": eta,
        })
    samples = comfy.sample.sample(
        model, noise, steps, float(request["cfg"]), "euler", "simple",
        conditioning, negative, latent, denoise=1.0, callback=sample_progress, seed=seed,
    )
    emit("MUSIC3_PROGRESS", {"progress": 0.88, "message": "Decoding stereo audio", "eta_seconds": None})
    stage["name"] = "decode"
    if request["tiled_decode"]:
        audio = vae.decode_tiled(samples, tile_x=1536, tile_y=64, overlap=64).movedim(-1, 1)
    else:
        audio = vae.decode(samples).movedim(-1, 1)
    std = torch.std(audio, dim=[1, 2], keepdim=True) * 5.0
    std[std < 1.0] = 1.0
    audio /= std
    save_wav(Path(request["output"]), audio, int(getattr(vae, "audio_sample_rate", 44100)))
    emit("MUSIC3_PROGRESS", {"progress": 1.0, "message": "Song ready"})
    # Preserve warm CPU model objects for the next task while giving Windows
    # back GPU memory between stages/jobs. Dynamic loading repopulates only
    # the layers needed for the next request.
    comfy.model_management.unload_all_models()
    comfy.model_management.soft_empty_cache()


def main() -> int:
    import torch
    emit("MUSIC3_READY")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            with torch.inference_mode():
                run(json.loads(line))
            emit("MUSIC3_DONE")
        except BaseException as error:
            traceback.print_exc()
            emit("MUSIC3_ERROR", {"error": f"{type(error).__name__}: {error}"})
            # Retire after an error; the parent starts a clean process. This
            # avoids reusing a partially loaded CUDA graph or interrupted KV cache.
            return 1
        finally:
            gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
