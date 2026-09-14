from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yue2_speed


class Yue2SpeedTests(unittest.TestCase):
    def test_windows_graph_attention_is_cudnn_when_flash_is_missing(self):
        with patch.object(yue2_speed, "flash_attention_usable", return_value=False):
            self.assertEqual(yue2_speed.resolve_graph_attention("auto"), "cudnn")
            self.assertEqual(yue2_speed.resolve_graph_attention("flash"), "flash")
        with patch.object(yue2_speed, "flash_attention_usable", return_value=True):
            self.assertEqual(yue2_speed.resolve_graph_attention("auto"), "auto")

    def test_ar_backend_requests_cuda_graphs(self):
        self.assertEqual(yue2_speed.select_ar_backend(), "torch")

    def test_worker_emits_phase_timings(self):
        worker = (Path(__file__).resolve().parents[1] / "yue2_worker.py").read_text(encoding="utf-8")
        self.assertIn('emit("YUE2_TIMING"', worker)
        self.assertIn('"phase": "semantic"', worker)
        self.assertIn('"phase": "synthesize"', worker)
        self.assertIn("audio_seconds", worker)

    def test_graph_fallback_skips_oom_and_cancel(self):
        self.assertFalse(yue2_speed.is_graph_fallback_error(InterruptedError("Cancelled")))
        self.assertFalse(yue2_speed.is_graph_fallback_error(RuntimeError("OutOfMemoryError: CUDA")))
        oom = type("OutOfMemoryError", (RuntimeError,), {})("tried to allocate")
        self.assertFalse(yue2_speed.is_graph_fallback_error(oom))
        self.assertTrue(yue2_speed.is_graph_fallback_error(
            RuntimeError("USE_FLASH_ATTENTION not enabled")))
        self.assertTrue(yue2_speed.is_graph_fallback_error(
            RuntimeError("No available kernel for cudnn attention")))

    def test_generate_tokens_retries_eager_after_flash_crash(self):
        calls = []

        def fake(*, use_cuda_graph=True):
            calls.append(use_cuda_graph)
            if use_cuda_graph:
                raise RuntimeError("USE_FLASH_ATTENTION not enabled")
            return ("ok", {}, False)

        wrapped = yue2_speed._wrap_generate(fake)
        self.assertEqual(wrapped(use_cuda_graph=True), ("ok", {}, False))
        self.assertEqual(calls, [True, False])

    def test_generate_tokens_does_not_retry_when_already_eager(self):
        def fake(*, use_cuda_graph=True):
            raise RuntimeError("USE_FLASH_ATTENTION not enabled")

        wrapped = yue2_speed._wrap_generate(fake)
        with self.assertRaisesRegex(RuntimeError, "USE_FLASH_ATTENTION"):
            wrapped(use_cuda_graph=False)

    def test_synthesize_bounded_still_forwards_solver_kwargs(self):
        runtime = Path(__file__).resolve().parents[1] / "runtime" / "Lib" / "site-packages"
        if str(runtime) not in sys.path:
            sys.path.insert(0, str(runtime))
        try:
            import torch
            from yue2.pipeline import SymbolicPlan, SemanticResult
            from yue2.protocol import SongRequest, GenerationConfig, token_prefixes
        except ImportError:
            self.skipTest("yue2 runtime is not importable")
        from unittest.mock import patch as mock_patch
        from yue2_memory import synthesize_bounded

        tokenizer = SimpleNamespace(encode=lambda text: [11, 12])
        request = SongRequest(style="folk", lyrics="hello", cot="off", seed=12)
        plan = SymbolicPlan(request, None, [], token_prefixes(request, tokenizer, []))
        semantic = SemanticResult(plan, list(range(9000)), {}, False)
        pipe = SimpleNamespace(
            backend="torch", quantization="none", tokenizer=tokenizer,
            generation_config=GenerationConfig(ode_steps=32), offload_ar=False,
            _load_model=lambda **kw: object(),
        )
        with mock_patch("yue2.nar.synthesize", return_value=torch.zeros(9000, 64)) as solver:
            synthesize_bounded(pipe, semantic, budget_gb=21.6)
        self.assertEqual(solver.call_args.kwargs["query_chunk_size"], 1024)
        self.assertEqual(solver.call_args.kwargs["steps"], 32)


if __name__ == "__main__":
    unittest.main()
