"""The VRAM policy is what keeps Windows responsive while a song renders."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import gpu_profile

GB = 1024 ** 3


class GpuProfileTests(TestCase):
    def test_display_gpu_keeps_real_headroom(self):
        """A 24 GB display card must not be handed 21 GB.

        ComfyUI's stock Windows reserve is 600 MB, which let the worker climb to
        21.2 GB of 24 GB. Anything else wanting VRAM then forced Windows to evict
        display surfaces, freezing the desktop for 15-20 seconds.
        """
        profile = gpu_profile.describe(24 * GB, name="RTX 3090", display=True)
        # Comfortably above ComfyUI's 600 MB, but not so much that the model
        # loses resident layers and the song takes minutes longer.
        self.assertGreaterEqual(profile["reserved_bytes"], 2 * GB)
        self.assertLessEqual(profile["reserved_bytes"], 3 * GB)
        self.assertGreater(profile["budget_bytes"], 20 * GB)

    def test_small_cards_still_get_a_workable_budget(self):
        profile = gpu_profile.describe(8 * GB, name="RTX 3070", display=True)
        self.assertGreaterEqual(profile["reserved_bytes"], gpu_profile.MIN_RESERVE_BYTES)
        self.assertGreater(profile["budget_bytes"], 5 * GB)

    def test_headless_card_is_not_penalised(self):
        profile = gpu_profile.describe(24 * GB, name="A5000", display=False)
        self.assertEqual(profile["reserved_bytes"], gpu_profile.HEADLESS_RESERVE_BYTES)
        self.assertGreater(profile["budget_bytes"], 22 * GB)

    def test_reserve_scales_but_is_clamped_at_both_ends(self):
        """The desktop's needs are roughly fixed; a huge card should not lose 10 GB."""
        self.assertEqual(gpu_profile.describe(8 * GB, display=True)["reserved_bytes"], gpu_profile.MIN_RESERVE_BYTES)
        self.assertLess(
            gpu_profile.describe(12 * GB, display=True)["reserved_bytes"],
            gpu_profile.describe(24 * GB, display=True)["reserved_bytes"],
        )
        self.assertEqual(
            gpu_profile.describe(80 * GB, display=True)["reserved_bytes"],
            gpu_profile.MAX_DISPLAY_RESERVE_BYTES,
        )

    def test_env_override_is_honoured_but_capped(self):
        with patch.dict("os.environ", {gpu_profile.OVERRIDE_ENV: "1.5"}):
            profile = gpu_profile.describe(24 * GB, display=True)
            self.assertEqual(profile["reserved_bytes"], int(1.5 * GB))
            self.assertTrue(profile["overridden"])
        # A nonsense override must never starve the model of the whole card.
        with patch.dict("os.environ", {gpu_profile.OVERRIDE_ENV: "999"}):
            self.assertEqual(gpu_profile.describe(24 * GB, display=True)["reserved_bytes"], 12 * GB)
        with patch.dict("os.environ", {gpu_profile.OVERRIDE_ENV: "not a number"}):
            self.assertFalse(gpu_profile.describe(24 * GB, display=True)["overridden"])

    def test_unknown_display_state_is_treated_as_a_display_gpu(self):
        """Reserving too much costs a little speed. Too little freezes the machine."""
        with patch.object(gpu_profile, "_smi", return_value=[]):
            self.assertTrue(gpu_profile._drives_display(24 * GB))
