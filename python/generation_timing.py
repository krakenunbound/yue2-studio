"""Phase-aware, locally learned generation timing for Music 3.

The autoregressive Music 3 counter is a maximum, not a promise that every song
will consume every frame.  Extrapolating that counter therefore badly
overstates early ETAs for songs which end naturally.  This module starts with a
measured RTX 3090 profile and replaces it with medians from successful local
runs as the Studio gathers them.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from config import OUTPUTS_ROOT

HISTORY_PATH = OUTPUTS_ROOT / "generation-timing.json"
_LOCK = threading.RLock()
_MAX_SAMPLES = 24


@dataclass(frozen=True)
class TimingProfile:
    compose_seconds: float
    refine_seconds: float
    cover_seconds: float
    samples: int = 0

    @property
    def audio_seconds(self) -> float:
        return self.compose_seconds + self.refine_seconds

    @property
    def total_seconds(self) -> float:
        return self.audio_seconds + self.cover_seconds


def _duration_factor(request: dict) -> float:
    # Auto mode deliberately gives Music 3 the full five-minute ceiling.  A
    # natural-ending song usually stops well before that, so do not scale the
    # prediction as though all 300 seconds must be generated.
    if bool(request.get("auto_duration")):
        return 1.0
    duration = max(1.0, min(300.0, float(request.get("duration") or 240.0)))
    return max(0.38, min(1.25, duration / 240.0))


def default_profile(request: dict) -> TimingProfile:
    factor = _duration_factor(request)
    # Measured locally on the target RTX 3090: 2:19 compose, 0:41 refine and
    # decode, then 0:16 for the 512px SD 1.5 thumbnail.
    return TimingProfile(139.0 * factor, 41.0 * factor, 16.0, 0)


def _read(path: Path = HISTORY_PATH) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def predict(request: dict, path: Path = HISTORY_PATH) -> TimingProfile:
    fallback = default_profile(request)
    auto = bool(request.get("auto_duration"))
    requested = float(request.get("duration") or 240.0)
    with _LOCK:
        compatible = [item for item in _read(path) if bool(item.get("auto_duration")) == auto]
    if not compatible:
        return fallback
    # Manual durations have a meaningful target. Prefer nearby runs. Auto
    # duration is a five-minute ceiling, so recent natural-ending runs are the
    # most useful comparison.
    if not auto:
        compatible.sort(key=lambda item: abs(float(item.get("requested_duration") or 240.0) - requested))
    compatible = compatible[-8:] if auto else compatible[:8]

    def median(name: str, default: float) -> float:
        values = [float(item[name]) for item in compatible if float(item.get(name) or 0.0) > 0.0]
        return statistics.median(values) if values else default

    return TimingProfile(
        median("compose_seconds", fallback.compose_seconds),
        median("refine_seconds", fallback.refine_seconds),
        median("cover_seconds", fallback.cover_seconds),
        len(compatible),
    )


def remaining(
    profile: TimingProfile,
    phase: str,
    phase_elapsed: float,
    live_eta: float | None = None,
) -> float:
    """Return a stable whole-job ETA for the current phase."""
    elapsed = max(0.0, phase_elapsed)
    if phase == "compose":
        # The AR total is a ceiling and may stop early. Historical phase time is
        # substantially more honest than extrapolating its maximum frame count.
        return max(0.0, profile.compose_seconds - elapsed) + profile.refine_seconds + profile.cover_seconds
    if phase == "refine":
        baseline = max(0.0, profile.refine_seconds - elapsed)
        if live_eta is not None:
            # Refinement has a fixed step count, so its measured ETA is useful;
            # clamp only startup outliers from the first CUDA step.
            ceiling = max(12.0, profile.refine_seconds * 1.75)
            baseline = min(ceiling, max(0.0, float(live_eta)))
        return baseline + profile.cover_seconds
    if phase == "decode":
        return max(2.0, profile.refine_seconds - elapsed) + profile.cover_seconds
    if phase == "thumbnail":
        return max(0.0, profile.cover_seconds - elapsed)
    return max(0.0, profile.total_seconds - elapsed)


def record(
    request: dict,
    compose_seconds: float,
    refine_seconds: float,
    cover_seconds: float | None,
    path: Path = HISTORY_PATH,
) -> None:
    sample = {
        "auto_duration": bool(request.get("auto_duration")),
        "requested_duration": float(request.get("duration") or 240.0),
        "compose_seconds": round(max(0.0, compose_seconds), 3),
        "refine_seconds": round(max(0.0, refine_seconds), 3),
        "cover_seconds": round(max(0.0, cover_seconds), 3) if cover_seconds is not None else None,
        "recorded_at": time.time(),
    }
    with _LOCK:
        items = _read(path)
        items.append(sample)
        items = items[-_MAX_SAMPLES:]
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(items, indent=2), encoding="utf-8")
        temporary.replace(path)


def profile_payload(profile: TimingProfile) -> dict:
    return {**asdict(profile), "total_seconds": profile.total_seconds}
