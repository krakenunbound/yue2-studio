"""Detect the GPU and choose a safe VRAM policy for YuE2 Studio.

YuE2 runs on the same card that draws the user's desktop. Reserving a little
VRAM prevents Windows from evicting display surfaces during generation.

Nothing here changes a number the model computes. It only decides how much of
the card we are willing to occupy, and it is deliberately conservative when the
GPU is also the display adapter.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger("yue2.gpu")

# What Windows needs to keep compositing is roughly FIXED -- the desktop does
# not want more VRAM just because the card is bigger. So the reserve is a small
# share, clamped at both ends: enough headroom on a modest card, and never so
# much on a large one that the model is starved of resident layers.
#
MIN_RESERVE_BYTES = 1536 * 1024 ** 2       # 1.5 GB
MAX_DISPLAY_RESERVE_BYTES = 3 * 1024 ** 3
DISPLAY_RESERVE_SHARE = 0.10
# A headless compute card only needs enough to avoid driver-level churn.
HEADLESS_RESERVE_BYTES = 768 * 1024 ** 2
OVERRIDE_ENV = "YUE2_RESERVE_VRAM_GB"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _override_bytes() -> int | None:
    raw = (os.environ.get(OVERRIDE_ENV) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        log.warning("Ignoring unparseable %s=%r", OVERRIDE_ENV, raw)
        return None
    if value <= 0:
        return None
    return int(value * 1024 ** 3)


def _smi(fields: str) -> list[str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    first = (result.stdout or "").strip().splitlines()
    return [part.strip() for part in first[0].split(",")] if first else []


def _drives_display(total_bytes: int) -> bool:
    """True when this GPU is also painting the desktop.

    Windows always has *something* resident on the display adapter, so a
    non-trivial baseline with no compute process of ours is the tell. When we
    cannot tell, assume it does: reserving too much only costs a little speed,
    reserving too little freezes the machine.
    """
    if sys.platform != "win32":
        return True
    fields = _smi("memory.used,display_active")
    if len(fields) >= 2 and fields[1] in {"Enabled", "Disabled"}:
        return fields[1] == "Enabled"
    if fields:
        try:
            return int(fields[0]) * 1024 ** 2 > 0.01 * total_bytes
        except ValueError:
            pass
    return True


def reserve_bytes(total_bytes: int, display: bool) -> int:
    override = _override_bytes()
    if override is not None:
        return min(override, int(total_bytes * 0.5))
    if not display:
        return HEADLESS_RESERVE_BYTES
    scaled = int(total_bytes * DISPLAY_RESERVE_SHARE)
    return max(MIN_RESERVE_BYTES, min(scaled, MAX_DISPLAY_RESERVE_BYTES))


def describe(total_bytes: int, name: str = "", display: bool | None = None) -> dict:
    if display is None:
        display = _drives_display(total_bytes)
    reserved = reserve_bytes(total_bytes, display)
    budget = max(1024 ** 3, total_bytes - reserved)
    return {
        "name": name,
        "total_bytes": total_bytes,
        "total_gb": round(total_bytes / 1024 ** 3, 1),
        "drives_display": display,
        "reserved_bytes": reserved,
        "reserved_gb": round(reserved / 1024 ** 3, 1),
        "budget_bytes": budget,
        "budget_gb": round(budget / 1024 ** 3, 1),
        "memory_fraction": round(min(0.95, budget / total_bytes), 3),
        "override_env": OVERRIDE_ENV,
        "overridden": _override_bytes() is not None,
    }


def probe() -> dict:
    """Describe the GPU without importing torch. Safe to call from the sidecar."""
    fields = _smi("name,memory.total")
    if len(fields) < 2:
        return {"available": False, "reason": "nvidia-smi did not report a GPU"}
    try:
        total = int(fields[1]) * 1024 ** 2
    except ValueError:
        return {"available": False, "reason": "Could not read total VRAM"}
    return {"available": True, **describe(total, name=fields[0])}


def apply_to_worker() -> dict:
    """Called inside the YuE2 worker after torch is importable."""
    import torch

    index = torch.cuda.current_device()
    properties = torch.cuda.get_device_properties(index)
    profile = describe(int(properties.total_memory), name=properties.name)

    torch.cuda.set_per_process_memory_fraction(profile["memory_fraction"], index)
    profile["engine_reserve_applied"] = True
    log.info(
        "GPU %s: %.1f GB total, reserving %.1f GB for the desktop, budget %.1f GB",
        profile["name"], profile["total_gb"], profile["reserved_gb"], profile["budget_gb"],
    )
    return profile
