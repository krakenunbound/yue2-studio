"""Offline Sony Woosh-Flow inference in its private CUDA environment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def progress(value, phase):
    print("SFX_PROGRESS " + json.dumps({"progress": value, "phase": phase}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--steps", type=int, default=32, choices=range(1, 101))
    parser.add_argument("--cfg", type=float, default=4.5)
    parser.add_argument("--sampler", choices=("dopri5", "euler"), default="dopri5")
    args = parser.parse_args()
    root = Path(args.model_root).resolve()
    output = Path(args.output).resolve()
    if not 0.5 <= args.duration <= 5 or not 0 <= args.cfg <= 10:
        raise ValueError("Woosh supports 0.5–5 seconds and CFG 0–10 in this app.")
    os.environ["HF_HOME"] = str(root / "hf_cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.chdir(root)
    import torch
    import soundfile as sf
    from woosh.components.base import LoadConfig
    from woosh.model.ldm import LatentDiffusionModel
    from woosh.inference.flowmatching_sampler import flowmatching_integrate

    if not torch.cuda.is_available():
        raise RuntimeError("Woosh GPU runtime cannot access CUDA.")
    torch.set_num_threads(min(8, os.cpu_count() or 4))
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    progress(0.1, "Loading local Woosh-Flow")
    model = LatentDiffusionModel(LoadConfig(path="checkpoints/Woosh-Flow")).eval().to("cuda")
    with torch.inference_mode():
        noise = torch.randn(1, 128, 501, device="cuda")
        cond = model.get_cond({"audio": None, "description": [args.prompt]}, no_dropout=True, device="cuda")
        negative = model.get_cond({"audio": None, "description": [args.negative_prompt]}, no_dropout=True, device="cuda") if args.negative_prompt else None
        progress(0.35, f"Creating sound with Woosh — {args.sampler}")
        options = {"step_size": 1.0 / args.steps} if args.sampler == "euler" else {"dtype": torch.float64}
        latent = flowmatching_integrate(model, noise=noise, cond=cond, cond_neg=negative,
                                       cfg=args.cfg, device="cuda", method=args.sampler,
                                       **options)
        progress(0.85, "Decoding Woosh audio")
        rendered = model.autoencoder.inverse(latent)[0].float().cpu()[:, :round(args.duration * 48000)]
        if not torch.isfinite(rendered).all():
            raise RuntimeError("Woosh generated non-finite audio samples.")
        peak = rendered.abs().max()
        if peak > 0.95:
            rendered *= 0.95 / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, rendered.numpy().T, 48000, subtype="PCM_24")
    progress(0.98, "Saving Woosh sound effect")


if __name__ == "__main__":
    main()
