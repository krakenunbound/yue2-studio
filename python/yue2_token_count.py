"""Validate YuE2's native prompt context without loading weights or CUDA."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from yue2.protocol import CONTEXT, SongRequest, token_prefixes
from yue2.tokenization_yue2 import YuE2TextTokenizer

request = json.loads(sys.stdin.read())
song = SongRequest(style=str(request["style"]), lyrics=str(request["lyrics"]), cot=str(request["cot"]), abc=request.get("abc"))
tokenizer = YuE2TextTokenizer(Path(request["model_root"]) / "qwen.tiktoken")
print(json.dumps({"tokens": len(token_prefixes(song, tokenizer)), "maximum": CONTEXT - 3}))
