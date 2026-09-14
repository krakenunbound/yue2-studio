"""Bound acoustic attention workspace using the pinned YuE2 0.1.5 API."""
from __future__ import annotations

QUERY_CHUNK_SIZE = 256


def query_chunk_size(budget_gb: float | None = None) -> int:
    """Tile NAR attention. 256 is the Windows-safe default; 24GB cards can take 1024."""
    if budget_gb is not None and budget_gb >= 18:
        return 1024
    return QUERY_CHUNK_SIZE


def synthesize_bounded(pipe, semantic, *, cancelled=None, on_progress=None, budget_gb=None):
    # Keep the release pipeline's validation and solver settings. Its public
    # wrapper doesn't expose query_chunk_size, but the underlying solver does.
    from yue2.pipeline import SemanticResult
    from yue2.protocol import token_prefixes
    from yue2.nar import synthesize

    if pipe.backend not in {"torch", "torch-eager"} or pipe.quantization != "none":
        raise ValueError("Bounded synthesis requires the unquantized PyTorch pipeline")
    if not isinstance(semantic, SemanticResult):
        raise TypeError("Expected the SemanticResult returned by generate_semantic")
    if token_prefixes(semantic.plan.request, pipe.tokenizer, semantic.plan.abc_ids) != semantic.plan.prefix:
        raise ValueError("Semantic result does not retain the request's exact prefix")
    from yue2_speed import cudnn_attention

    model = pipe._load_model(for_nar=True)
    with cudnn_attention():
        result = synthesize(
            model, semantic.plan.prefix, semantic.tokens, semantic.plan.request.seed,
            steps=pipe.generation_config.ode_steps, context=pipe.generation_config.context,
            offload_ar=pipe.offload_ar, cancelled=cancelled, on_progress=on_progress,
            query_chunk_size=query_chunk_size(budget_gb),
        )
    return result.detach().float().cpu().numpy()
