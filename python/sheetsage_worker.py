"""Private SheetSage2 worker. Loads only from the app model folder."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def emit(event: str, **payload) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--mert-root", required=True)
    parser.add_argument("--output-dir", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--melody-only", action="store_true")
    mode.add_argument("--full", action="store_true")
    args = parser.parse_args()
    melody_only = not args.full

    emit("progress", progress=0.08, message="Loading SheetSage2")
    import torch
    from transformers import AutoModel

    if not torch.cuda.is_available():
        raise RuntimeError("SheetSage2 requires an NVIDIA CUDA GPU.")
    model_root = Path(args.model_root)
    mert_root = Path(args.mert_root)
    model = AutoModel.from_pretrained(
        str(model_root),
        trust_remote_code=True,
        local_files_only=True,
        base_model_path=str(mert_root),
        attn_implementation="sdpa",
        device_map={"": "cuda"},
        torch_dtype=torch.float32,
    ).eval()
    emit("progress", progress=0.35, message="Transcribing melody")
    result = model.transcribe(
        args.audio,
        output_dir=str(Path(args.output_dir) / ("melody" if melody_only else "full")),
        melody_only=melody_only,
    )
    abc = str(result.get("abc") or "").strip()
    if not abc:
        raise RuntimeError(str(result.get("abc_error") or "Transcription did not produce ABC"))
    warnings = result.get("warnings") or []
    emit("progress", progress=0.95, message="Score ready")
    emit("result", abc=abc, warnings=list(warnings), melody_only=melody_only)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit("error", message=f"{type(error).__name__}: {error}")
        print(f"{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
