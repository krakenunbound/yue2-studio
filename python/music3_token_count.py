"""Count MiniMax Music 3 prompt tokens without loading model weights or CUDA."""
from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path

from tokenizers import Tokenizer


def load_tokenizer_json(checkpoint: Path) -> bytes:
    """Read only the embedded tokenizer_json U8 tensor from a safetensors file."""
    with checkpoint.open("rb") as handle:
        raw_length = handle.read(8)
        if len(raw_length) != 8:
            raise RuntimeError("Music 3 text encoder has an invalid safetensors header")
        header_length = struct.unpack("<Q", raw_length)[0]
        header = json.loads(handle.read(header_length))
        entry = header.get("tokenizer_json")
        if not isinstance(entry, dict) or entry.get("dtype") != "U8":
            raise RuntimeError("Music 3 text encoder is missing tokenizer_json")
        start, end = entry.get("data_offsets", [None, None])
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise RuntimeError("Music 3 tokenizer_json has invalid offsets")
        handle.seek(8 + header_length + start)
        payload = handle.read(end - start)
    if len(payload) != end - start:
        raise RuntimeError("Music 3 tokenizer_json is truncated")
    return payload


def prompt_builder(engine_root: Path):
    source = engine_root / "comfy" / "ldm" / "minimax_music" / "prompt.py"
    spec = importlib.util.spec_from_file_location("music3_prompt_contract", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Music 3 prompt contract could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_prompt


def main() -> int:
    request = json.load(sys.stdin)
    checkpoint = Path(request["checkpoint"])
    build_prompt = prompt_builder(Path(request["engine_root"]))
    combined = build_prompt(str(request["caption"]), str(request["lyrics"]))
    # tokenizers 0.21 rejects typographic double quotes in this embedded
    # tokenizer with a misleading TextInputSequence error. The API normally
    # normalizes them first; keep this helper defensive for direct callers.
    combined = combined.translate(str.maketrans({
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
        "\u00ab": '"', "\u00bb": '"',
    }))
    tokenizer = Tokenizer.from_str(load_tokenizer_json(checkpoint).decode("utf-8"))
    tokens = len(tokenizer.encode(combined, add_special_tokens=False).ids)
    print(json.dumps({"tokens": tokens, "maximum": 5000}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
