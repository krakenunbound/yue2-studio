"""Windows-safe YuE2 attention: cuDNN SDPA and GraphAR without FlashAttention.

Official Linux timings assume variable-length FlashAttention. The Windows
torch wheel exposes the aten schema GraphAR uses to auto-select flash, then
crashes because USE_FLASH_ATTENTION is off. NAR ``backend="sdpa"`` can also
fall through to MATH. Force cuDNN instead; keep CUDA graphs via GraphAR.
"""
from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any, Callable


def flash_attention_usable() -> bool:
    """True only when PyTorch actually compiled FlashAttention kernels."""
    try:
        import torch
        if not torch.cuda.is_available():
            return False
        available = getattr(torch.backends.cuda, "is_flash_attention_available", None)
        if callable(available):
            return bool(available())
        # Windows wheels enable the flash SDP flag without shipping the kernel.
        return False if sys.platform == "win32" else bool(torch.backends.cuda.flash_sdp_enabled())
    except Exception:
        return False


def resolve_graph_attention(requested: str = "auto") -> str:
    """GraphAR ``auto`` picks flash from the aten schema; override on Windows."""
    if requested != "auto":
        return requested
    return "auto" if flash_attention_usable() else "cudnn"


def select_ar_backend() -> str:
    """``torch`` enables CUDA-graph decode; ``torch-eager`` skips GraphAR."""
    return "torch"


def configure_sdp() -> None:
    import torch
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    try:
        torch.set_float32_matmul_precision("high")
    except Exception:
        pass
    if flash_attention_usable():
        torch.backends.cuda.enable_flash_sdp(True)
    else:
        torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    enable_cudnn = getattr(torch.backends.cuda, "enable_cudnn_sdp", None)
    if callable(enable_cudnn):
        enable_cudnn(True)


def restore_fast_matmul() -> None:
    """Undo ``YuE2Pipeline.__init__`` disabling TF32 and forcing deterministic cuDNN."""
    import torch
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.deterministic = False
    configure_sdp()


def cudnn_attention():
    """Force CUDNN_ATTENTION around NAR / eager AR SDPA (no-op without CUDA)."""
    try:
        import torch
        from torch.nn.attention import SDPBackend, sdpa_kernel
        if not hasattr(SDPBackend, "CUDNN_ATTENTION") or not torch.cuda.is_available():
            return nullcontext()
        return sdpa_kernel(SDPBackend.CUDNN_ATTENTION)
    except Exception:
        return nullcontext()


def is_graph_fallback_error(error: BaseException) -> bool:
    if isinstance(error, (InterruptedError, KeyboardInterrupt, SystemExit)):
        return False
    name = type(error).__name__
    text = f"{name}: {error}".lower()
    if "outofmemory" in name.lower() or "out of memory" in text or "outofmemory" in text:
        return False
    return any(needle in text for needle in (
        "use_flash_attention", "flash_attention", "flash attention",
        "_flash_attention_forward", "cudnn_attention", "cudnn attention",
        "no available kernel", "cuda graph", "graph capture",
    ))


def _patch_graph_ar() -> None:
    from yue2.cuda_graph import GraphAR
    original = GraphAR.__init__
    if getattr(original, "_yue2_studio_patched", False):
        return

    def wrapped(self, model, prefixes, max_tokens, *, capture=True,
                attention_backend="auto", fuse_projections=False):
        attention_backend = resolve_graph_attention(attention_backend)
        return original(self, model, prefixes, max_tokens, capture=capture,
                        attention_backend=attention_backend, fuse_projections=fuse_projections)

    wrapped._yue2_studio_patched = True  # type: ignore[attr-defined]
    GraphAR.__init__ = wrapped


def _wrap_generate(original: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(original, "_yue2_studio_patched", False):
        return original

    def wrapped(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except BaseException as error:
            if kwargs.get("use_cuda_graph") is False or not is_graph_fallback_error(error):
                raise
            import json
            print("YUE2_SPEED " + json.dumps({
                "graphs": False, "fallback": f"{type(error).__name__}: {error}",
            }), flush=True)
            kwargs = dict(kwargs)
            kwargs["use_cuda_graph"] = False
            return original(*args, **kwargs)

    wrapped._yue2_studio_patched = True  # type: ignore[attr-defined]
    return wrapped


def _patch_generate_tokens() -> None:
    import yue2.pipeline as pipeline
    import yue2.sampling as sampling
    sampling.generate_tokens = _wrap_generate(sampling.generate_tokens)
    pipeline.generate_tokens = _wrap_generate(pipeline.generate_tokens)


def apply_speed_patches() -> None:
    _patch_graph_ar()
    _patch_generate_tokens()
