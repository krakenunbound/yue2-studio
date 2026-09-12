from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import generation_timing


class GenerationTimingTest(TestCase):
    def test_auto_duration_opens_near_measured_whole_job_time(self) -> None:
        profile = generation_timing.default_profile({"auto_duration": True, "duration": 300})
        self.assertEqual(196.0, profile.total_seconds)
        self.assertEqual(196.0, generation_timing.remaining(profile, "compose", 0.0))

    def test_early_ar_progress_does_not_extrapolate_the_maximum_counter(self) -> None:
        profile = generation_timing.default_profile({"auto_duration": True, "duration": 300})
        # Even if the worker's raw early estimate says eight minutes, compose
        # uses the calibrated natural-ending history instead.
        eta = generation_timing.remaining(profile, "compose", 12.0, 480.0)
        self.assertEqual(184.0, eta)

    def test_successful_local_runs_teach_future_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "timing.json"
            request = {"auto_duration": True, "duration": 300}
            generation_timing.record(request, 120.0, 36.0, 14.0, path)
            generation_timing.record(request, 126.0, 40.0, 18.0, path)
            profile = generation_timing.predict(request, path)
            self.assertEqual(123.0, profile.compose_seconds)
            self.assertEqual(38.0, profile.refine_seconds)
            self.assertEqual(16.0, profile.cover_seconds)
            self.assertEqual(2, profile.samples)

    def test_manual_short_songs_start_with_a_shorter_prediction(self) -> None:
        short = generation_timing.default_profile({"auto_duration": False, "duration": 90})
        full = generation_timing.default_profile({"auto_duration": False, "duration": 240})
        self.assertLess(short.total_seconds, full.total_seconds)
