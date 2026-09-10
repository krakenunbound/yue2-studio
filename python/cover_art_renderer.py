"""One-shot direct SD 1.5 cover renderer owned by YuE2 Studio."""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "cover_art" / "juggernaut_aftermath.safetensors"
CONFIG = ROOT / "python" / "cover_art" / "sd15-v1-inference.yaml"
LOCAL_CONFIG = ROOT / "models" / "cover_art" / "sd15-config"
NEGATIVE = (
    "(three legs, extra leg, missing leg, extra limbs, missing limbs:1.5), "
    "(deformed limbs, fused limbs, malformed anatomy, bad anatomy:1.4), "
    "extra appendages, extra arms, extra hands, extra feet, extra fingers, extra toes, "
    "fused fingers, disfigured, duplicate person, text, letters, logo, watermark, blurry"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=-1)
    args = parser.parse_args()
    if not MODEL.is_file() or not CONFIG.is_file():
        raise FileNotFoundError("The local SD 1.5 cover model or configuration is missing.")

    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionPipeline
    from PIL.PngImagePlugin import PngInfo

    seed = args.seed if args.seed >= 0 else secrets.randbelow(2**31 - 1)
    print("COVER_PROGRESS " + json.dumps({"step": 0, "total": 30, "message": "Loading thumbnail model"}), flush=True)
    pipe = StableDiffusionPipeline.from_single_file(
        str(MODEL), original_config=str(CONFIG), local_files_only=True,
        **({"config": str(LOCAL_CONFIG)} if (LOCAL_CONFIG / "model_index.json").is_file() else {}),
        torch_dtype=torch.float16, safety_checker=None, requires_safety_checker=False,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, algorithm_type="dpmsolver++", solver_order=2, use_karras_sigmas=True,
    )
    pipe.to("cuda")

    def progress(_pipeline, step: int, _timestep, callback_kwargs):
        print("COVER_PROGRESS " + json.dumps({"step": step + 1, "total": 30, "message": f"Generating thumbnail {step + 1}/30"}), flush=True)
        return callback_kwargs

    image = pipe(
        prompt=args.prompt, negative_prompt=NEGATIVE, width=512, height=512,
        num_inference_steps=30, guidance_scale=5.5,
        generator=torch.Generator(device="cuda").manual_seed(seed),
        callback_on_step_end=progress,
    ).images[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngInfo(); metadata.add_text("provider", "Juggernaut Aftermath / SD 1.5")
    metadata.add_text("seed", str(seed)); metadata.add_text("prompt", args.prompt); metadata.add_text("negative_prompt", NEGATIVE)
    image.save(args.output, pnginfo=metadata)
    print("COVER_DONE " + json.dumps({"output": str(args.output), "seed": seed}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("COVER_ERROR " + json.dumps({"error": f"{type(error).__name__}: {error}"}), flush=True)
        raise SystemExit(1)
