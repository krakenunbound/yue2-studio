from __future__ import annotations

import sys
import io
import json
import threading
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import yue2_engine


class YuE2ContractTests(unittest.TestCase):
    def test_worker_failure_logs_readable_traceback_at_error_level(self):
        failure = {"error": "OutOfMemoryError: test allocation", "traceback": "Traceback (most recent call last):\n  test_solver\nOutOfMemoryError: test allocation"}
        process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO("YUE2_ERROR " + json.dumps(failure) + "\n"), poll=lambda: None)
        job = SimpleNamespace(cancel=threading.Event(), emit=lambda: None)
        with patch.object(yue2_engine, "model_status", return_value={"ready": True}), \
             patch.object(yue2_engine, "runtime_status", return_value={"ready": True}), \
             patch.object(yue2_engine, "_request_payload", return_value={}), \
             patch.object(yue2_engine, "_start", return_value=process), \
             patch.object(yue2_engine, "_PROCESS", process), \
             patch.object(yue2_engine, "_stop_process") as stop, \
             self.assertLogs("yue2.engine", level="ERROR") as captured:
            with self.assertRaisesRegex(RuntimeError, "OutOfMemoryError"):
                yue2_engine.generate(job, {}, Path("unused.wav"))
        self.assertIn(failure["traceback"], captured.records[0].getMessage())
        stop.assert_called_once()

    def test_request_exposes_native_controls_and_rejects_old_duration_controls(self):
        request = main.GenerateRequest(description="warm indie folk", lyrics="[Verse]\nhello")
        self.assertEqual((request.cot_mode, request.cfg, request.steps, request.top_k, request.temperature),
                         ("full", 1.0, 32, 100, 1.0))
        self.assertNotIn("duration", main.GenerateRequest.model_fields)
        self.assertNotIn("tiled_decode", main.GenerateRequest.model_fields)

    def test_generation_payload_maps_to_native_yue2_options(self):
        request = {"description": "style", "lyrics": "words", "instrumental": False, "seed": 7,
                   "cot_mode": "melody", "abc_score": "X:1\nK:C", "cfg": 1.2, "steps": 32,
                   "temperature": 1.0, "top_k": 100}
        payload = yue2_engine._request_payload(request, Path("unused.wav"))
        self.assertEqual(payload["cot"], "melody")
        self.assertEqual(payload["abc"], "X:1\nK:C")
        self.assertEqual((payload["cfg_scale"], payload["steps"], payload["temperature"], payload["top_k"]),
                         (1.2, 32, 1.0, 100))

    def test_off_mode_uses_native_cfg_default(self):
        request = {"description": "style", "lyrics": "words", "instrumental": False, "seed": 7,
                   "cot_mode": "off", "cfg": 1.0, "steps": 32, "temperature": 1.0, "top_k": 100}
        payload = yue2_engine._request_payload(request, Path("unused.wav"))
        self.assertEqual(payload["cfg_scale"], 1.01)

    def test_flatten_style_strips_minimax_headings(self):
        style = main.flatten_style(
            "Global Metadata\nBasic Attributes: English, warm piano pop, 88 BPM.\n"
            "Global Emotional Progression: unhurried phrasing.\n\n"
            "Vocal Details\nVocal Gender & Timbre: expressive female voice.\n\n"
            "Arrangement\nInstrument Lifecycle: acoustic piano, rounded bass and light drums."
        )
        self.assertNotIn("Global Metadata", style)
        self.assertIn("warm piano pop", style)
        self.assertIn("expressive female voice", style)
        self.assertIn("acoustic piano", style)

    def test_melody_only_abc_keeps_voice_headers(self):
        abc = 'X:1\nT:\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nK:C\n"Am" A2 B2 |"G" G4|\n'
        stripped = main.melody_only_abc(abc)
        self.assertIn('name="Vocal Melody"', stripped)
        self.assertNotIn('"Am"', stripped)
        self.assertNotIn('"G"', stripped)

    def test_model_status_requires_main_model_tokenizer_and_vae(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {"model": root / "model.safetensors", "config": root / "config.json",
                     "tokenizer": root / "qwen.tiktoken", "vae": root / "vae.safetensors",
                     "vae_config": root / "vae.json"}
            files["model"].write_bytes(b"x")
            with patch.dict(yue2_engine.MODEL_FILES, files, clear=True):
                status = yue2_engine.model_status()
            self.assertFalse(status["ready"])
            self.assertEqual(status["missing"], ["config", "tokenizer", "vae", "vae_config"])

    def test_instrumental_uses_structured_nonempty_lyrics(self):
        lyrics = yue2_engine._lyrics_for_generation({"instrumental": True})
        self.assertIn("[Intro]", lyrics)
        self.assertIn("[Outro]", lyrics)
        self.assertGreaterEqual(lyrics.count("(instrumental)"), 5)

    def test_prepare_moves_performance_tags_out_of_lyrics(self):
        with patch.object(yue2_engine, "count_prompt_tokens", return_value={"tokens": 10, "maximum": 24576}):
            prepared = main.prepare_generation_params({
                "description": "English, warm piano pop, 88 BPM",
                "lyrics": "[Verse]\nFour\n[Spoken Countdown]\n4, 3, 2, 1\n[Whispered]\ncome closer",
                "instrumental": False,
                "cot_mode": "full",
                "voice_slots": {},
            })
        self.assertEqual("[Verse]\nFour\n4, 3, 2, 1\ncome closer", prepared["rendered_lyrics"])
        self.assertNotIn("[Spoken", prepared["rendered_lyrics"])
        self.assertIn("Spoken Countdown", prepared["generation_description"])
        self.assertIn("Whispered", prepared["generation_description"])
        self.assertIn("warm piano pop", prepared["generation_description"])

    def test_score_is_rejected_in_direct_generation_mode(self):
        with self.assertRaisesRegex(main.HTTPException, "ABC score"):
            main.prepare_generation_params({
                "description": "style", "lyrics": "words", "instrumental": False,
                "cot_mode": "off", "abc_score": "X:1", "voice_slots": {},
            })

    def test_windows_worker_uses_eager_backend_without_flash_attention_graphs(self):
        worker = (Path(__file__).resolve().parents[1] / "yue2_worker.py").read_text(encoding="utf-8")
        self.assertIn('backend="torch-eager"', worker)


if __name__ == "__main__":
    unittest.main()
