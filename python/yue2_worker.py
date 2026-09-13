"""Private resident inference worker for YuE2 Studio."""
from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from pathlib import Path

import gpu_profile
from yue2_memory import synthesize_bounded

_PIPE = None
_GPU_PROFILE = None


def emit(marker: str, payload: dict | None = None) -> None:
    print(marker + ((" " + json.dumps(payload, ensure_ascii=False)) if payload is not None else ""), flush=True)


def load_pipeline():
    global _PIPE, _GPU_PROFILE
    import torch
    from yue2 import YuE2Pipeline
    if not torch.cuda.is_available(): raise RuntimeError("YuE2 requires an NVIDIA CUDA GPU.")
    if not torch.cuda.is_bf16_supported(): raise RuntimeError("YuE2 requires a CUDA GPU with BF16 support.")
    if _GPU_PROFILE is None:
        _GPU_PROFILE = gpu_profile.apply_to_worker(); emit("YUE2_GPU", _GPU_PROFILE)
    if _PIPE is None:
        emit("YUE2_PROGRESS", {"progress": .02, "message": "Loading YuE2 model"})
        _PIPE = YuE2Pipeline.from_pretrained(os.environ["YUE2_MODEL_ROOT"], vae=os.environ["YUE2_VAE_ROOT"],
            # The Windows torch wheel does not expose the variable-length
            # FlashAttention kernel required by YuE2's CUDA-graph decoder.
            # Native eager SDPA remains supported by the release package.
            device="cuda", backend="torch-eager", memory_budget_gib=float(_GPU_PROFILE["budget_gb"]),
            progress=False, local_files_only=True)
    return _PIPE


def run(request: dict) -> None:
    pipe = load_pipeline()
    cancelled = lambda: False
    # The sidecar cancels by terminating this process, so the callback remains
    # available for the pipeline without adding an unreliable pipe poll loop.
    semantic_sampling = {"temperature": float(request["temperature"]), "top_k": int(request["top_k"])}
    emit("YUE2_PROGRESS", {"progress": .08, "message": "Planning score" if request["cot"] != "off" else "Preparing composition"})
    plan = pipe.plan(style=request["style"], lyrics=request["lyrics"], cot=request["cot"], abc=request.get("abc"),
                     seed=int(request["seed"]), cfg_scale=float(request["cfg_scale"]), cancelled=cancelled)
    if plan.abc:
        Path(request["output"]).with_name("score.abc").write_text(plan.abc, encoding="utf-8")
    truncated = {
        "abc": bool(getattr(plan, "truncated", False)),
        "semantic": False,
    }
    emit("YUE2_PROGRESS", {"progress": .30, "message": "Generating semantic music tokens"})
    semantic = pipe.generate_semantic(plan, sampling=semantic_sampling, cancelled=cancelled)
    truncated["semantic"] = bool(getattr(semantic, "truncated", False))
    # Keep exact inputs for a local synthesis replay if the worker fails.
    # Recovery data contains song text, never the cloud API-key vault.
    import numpy as np
    import torch
    recovery = Path(__file__).resolve().parents[1] / "outputs" / "recovery" / uuid.uuid4().hex
    plan.save(recovery)
    np.save(recovery / "semantic_tokens.npy", np.asarray(semantic.tokens, dtype=np.int32))
    (recovery / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    emit("YUE2_DIAGNOSTIC", {"recovery": str(recovery), "prefix_tokens": len(plan.prefix),
                            "music_tokens": len(semantic.tokens), "query_chunk_size": 256,
                            "allocated_gib": torch.cuda.memory_allocated() / 2**30,
                            "reserved_gib": torch.cuda.memory_reserved() / 2**30})
    emit("YUE2_PROGRESS", {"progress": .65, "message": "Synthesizing acoustic latents"})
    # YuE2's requested steps are flow-matching ODE steps, not the former MiniMax sampler steps.
    pipe.generation_config = type(pipe.generation_config)(abc=pipe.generation_config.abc,
        semantic=pipe.generation_config.semantic, ode_steps=int(request["steps"]), context=pipe.generation_config.context)
    def synthesis_progress(completed, total):
        emit("YUE2_MEMORY", {"step": completed, "total": total,
                             "allocated_gib": torch.cuda.memory_allocated() / 2**30,
                             "reserved_gib": torch.cuda.memory_reserved() / 2**30})
        emit("YUE2_PROGRESS", {"progress": .65 + .22 * completed / max(total, 1),
                              "message": f"Synthesizing audio ({completed}/{total})"})
    latents = synthesize_bounded(pipe, semantic, cancelled=cancelled, on_progress=synthesis_progress)
    emit("YUE2_PROGRESS", {"progress": .88, "message": "Decoding 48 kHz stereo audio"})
    audio = pipe.decode(latents)
    import soundfile as sf
    path = Path(request["output"]); path.parent.mkdir(parents=True, exist_ok=True)
    # inspect_wav and the export pipeline use Python's stdlib wave reader,
    # which supports PCM WAV but not IEEE float WAV.
    sf.write(path, audio, 48000, subtype="PCM_24")
    (path.with_name("result.json")).write_text(
        json.dumps({"truncated": truncated, "cot": request.get("cot"), "seed": request.get("seed")}, indent=2),
        encoding="utf-8",
    )
    ready = "Song ready"
    if truncated["abc"] or truncated["semantic"]:
        ready = "Song ready (YuE2 hit a token limit — check the ending)"
    emit("YUE2_PROGRESS", {"progress": 1., "message": ready})


def main() -> None:
    emit("YUE2_READY")
    for line in sys.stdin:
        try: run(json.loads(line)); emit("YUE2_DONE")
        except BaseException as error:
            failure = {"error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()}
            torch = sys.modules.get("torch")
            if torch is not None:
                try:
                    if torch.cuda.is_initialized():
                        failure["cuda_memory"] = torch.cuda.memory_summary()
                except Exception:
                    pass  # Preserve the original failure if CUDA itself is unavailable.
            emit("YUE2_ERROR", failure)


if __name__ == "__main__": main()
