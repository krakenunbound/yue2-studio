from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def progress(value: float, phase: str, stage_progress: float | None = None) -> None:
    payload = {"progress": value, "phase": phase}
    if stage_progress is not None:
        payload["stage_progress"] = stage_progress
    print("SFX_PROGRESS " + json.dumps(payload), flush=True)


def localize_model_config(model_config: dict, model_root: Path) -> dict:
    """Point every gated prompt conditioner at the checked local snapshot."""
    for conditioning in model_config["model"]["conditioning"]["configs"]:
        if conditioning.get("type") != "t5gemma":
            continue
        conditioner_config = conditioning.setdefault("config", {})
        conditioner_config.pop("repo_id", None)
        conditioner_config.pop("subfolder", None)
        conditioner_config["model_path"] = str(model_root / "t5gemma-b-b-ul2")
    return model_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    # The Studio is intentionally offline at generation time. The gated model
    # and its prompt encoder must both live inside the app's model folder.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    # Leave enough CPU available for playback and the Studio interface.
    import torch
    import soundfile as sf
    from stable_audio_3.loading_utils import load_diffusion_cond
    from stable_audio_3.model import StableAudioModel

    torch.set_num_threads(max(2, min(12, (os.cpu_count() or 8) // 2)))
    model_root = Path(args.model_root)
    config_path = model_root / "model_config.json"
    checkpoint_path = model_root / "model.safetensors"
    output = Path(args.output)

    progress(0.12, "Loading local sound-effects model")
    model_config = localize_model_config(
        json.loads(config_path.read_text(encoding="utf-8")),
        model_root,
    )
    raw_model = load_diffusion_cond(
        model_config,
        checkpoint_path,
        device="cpu",
        model_half=False,
    )
    model = StableAudioModel(raw_model, model_config, "cpu", False)
    progress(0.38, "Creating sound effect", 0.0)
    audio = model.generate(
        prompt=args.prompt,
        negative_prompt=args.negative_prompt or None,
        duration=args.duration,
        seed=args.seed,
        steps=8,
        cfg_scale=1.0,
        sampler_type="pingpong",
        chunked_decode=True,
    )
    progress(0.90, "Saving generated sound", 1.0)
    rendered = audio[0].detach().to(torch.float32).cpu()
    peak = rendered.abs().max()
    if peak > 1e-8:
        rendered = (rendered / peak * 0.95).clamp(-1, 1)
    data = rendered.numpy().T
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, data, int(model_config["sample_rate"]), subtype="PCM_16")
    progress(0.98, "Adding sound to Studio", 1.0)


if __name__ == "__main__":
    main()
