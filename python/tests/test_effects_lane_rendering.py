from __future__ import annotations

import json
import math
import struct
import sys
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import main


SAMPLE_RATE = 44_100


def _write_tone(path: Path, frequency: float, seconds: float = 2.0, amplitude: int = 4_000) -> None:
    """Write a deterministic stereo PCM tone suitable for waveform assertions."""
    frames = bytearray()
    for index in range(round(SAMPLE_RATE * seconds)):
        value = round(amplitude * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
        frames.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames)


def _tone_level(path: Path, start: float, frequency: float, seconds: float = 0.25) -> float:
    """Return the sine-correlation level of one channel in a short output window."""
    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == SAMPLE_RATE
        handle.setpos(round(start * SAMPLE_RATE))
        frames = handle.readframes(round(seconds * SAMPLE_RATE))
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)[::2]
    return abs(2 * sum(sample * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
                       for index, sample in enumerate(samples)) / len(samples))


def _effect_song(root: Path) -> Path:
    song = root / "Dark Techno" / "Apple Signal"
    tracks = song / "studio" / "tracks"
    tracks.mkdir(parents=True)
    _write_tone(tracks / "rain.wav", 220)
    _write_tone(tracks / "thunder.wav", 440)
    stems = song / "stems" / "htdemucs"
    stems.mkdir(parents=True)
    _write_tone(stems / "vocals.wav", 880, amplitude=3_000)
    (song / "song.json").write_text(json.dumps({
        "title": "Apple Signal",
        "genre": "Dark Techno",
        "stems": ["vocals.wav"],
        "studio_imports": [
            {"file": "rain.wav", "name": "Rain"},
            {"file": "thunder.wav", "name": "Thunder"},
        ],
    }), encoding="utf-8")
    return song


def _render(root: Path, request: main.StudioBounceRequest) -> Path:
    with patch.object(main, "LIBRARY_ROOT", root):
        result = main.bounce_studio_mix("Dark Techno/Apple Signal", request)
    return root / "Dark Techno" / "Apple Signal" / "mixes" / Path(result["download_url"]).name


def test_nested_session_roundtrips_effect_lane_metadata() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        song = _effect_song(root)
        payload = {
            "tracks": [
                {"name": "rain.wav", "lane": "effects", "offset": 0.5},
                {"name": "thunder.wav", "lane": "effects", "offset": 1.0},
            ],
        }
        with patch.object(main, "LIBRARY_ROOT", root):
            response = TestClient(main.app).patch(
                "/api/library/Dark%20Techno%2FApple%20Signal/studio", json=payload,
            )
        saved = json.loads((song / "song.json").read_text(encoding="utf-8"))

    assert response.status_code == 200, response.text
    assert [(track["name"], track["lane"], track["offset"])
            for track in saved["studio"]["tracks"]] == [
        ("rain.wav", "effects", 0.5),
        ("thunder.wav", "effects", 1.0),
    ]


def test_effect_lane_keeps_imported_sounds_independent_and_mixes_overlaps() -> None:
    if not main.ffmpeg_path():
        pytest.skip("FFmpeg is not installed")
    with TemporaryDirectory() as temp:
        root = Path(temp)
        _effect_song(root)
        output = _render(root, main.StudioBounceRequest(
            selection=main.StudioRange(start=0, end=3),
            tracks=[
                main.StudioTrackState(name="rain.wav", lane="effects", offset=.5),
                main.StudioTrackState(name="thunder.wav", lane="effects", offset=1.0),
            ],
        ))
        rain_alone = _tone_level(output, .75, 220)
        rain_overlap = _tone_level(output, 1.25, 220)
        thunder_before = _tone_level(output, .75, 440)
        thunder_overlap = _tone_level(output, 1.25, 440)
        after_sounds = _tone_level(output, 2.75, 220)

    assert rain_alone > 2_500
    assert rain_overlap > 2_500
    assert thunder_before < 25
    assert thunder_overlap > 1_200
    assert after_sounds < 25


def test_muted_effect_is_absent_and_vocal_effect_does_not_process_effect_lane() -> None:
    if not main.ffmpeg_path():
        pytest.skip("FFmpeg is not installed")
    with TemporaryDirectory() as temp:
        root = Path(temp)
        _effect_song(root)
        muted = _render(root, main.StudioBounceRequest(
            selection=main.StudioRange(start=0, end=3),
            tracks=[
                main.StudioTrackState(name="rain.wav", lane="effects", offset=.5, muted=True),
                main.StudioTrackState(name="thunder.wav", lane="effects", offset=1.0),
            ],
        ))
        muted_rain = _tone_level(muted, .75, 220)
        heard_thunder = _tone_level(muted, 1.25, 440)
        baseline = _render(root, main.StudioBounceRequest(
            selection=main.StudioRange(start=0, end=2),
            tracks=[
                main.StudioTrackState(name="vocals.wav", lane="vocals"),
                main.StudioTrackState(name="rain.wav", lane="effects"),
            ],
        ))
        baseline_rain = _tone_level(baseline, 1.0, 220)
        baseline_vocals = _tone_level(baseline, 1.0, 880)
        vocal_effect = main.StudioEffectRegion(
            id="quiet-vocals", kind="gain_down", amount=1, start=.5, end=1.5,
            fade_in=0, fade_out=0,
        )
        effected = _render(root, main.StudioBounceRequest(
            selection=main.StudioRange(start=0, end=2),
            tracks=[
                main.StudioTrackState(name="vocals.wav", lane="vocals", effects=[vocal_effect]),
                main.StudioTrackState(name="rain.wav", lane="effects"),
            ],
        ))
        effected_rain = _tone_level(effected, 1.0, 220)
        effected_vocals = _tone_level(effected, 1.0, 880)

    assert muted_rain < 25
    assert heard_thunder > 1_200
    assert abs(effected_rain - baseline_rain) < 25
    assert effected_vocals < baseline_vocals * .15


def test_combine_then_uncombine_restores_shared_effect_lane_and_offsets() -> None:
    if not main.ffmpeg_path():
        pytest.skip("FFmpeg is not installed")
    with TemporaryDirectory() as temp:
        root = Path(temp)
        song = _effect_song(root)
        original_states = [
            main.StudioTrackState(name="rain.wav", lane="effects", offset=.5),
            main.StudioTrackState(name="thunder.wav", lane="effects", offset=1.0),
        ]
        combine_request = main.StudioCombineRequest(
            files=["rain.wav", "thunder.wav"], name="Storm bed", tracks=original_states,
        )
        with patch.object(main, "LIBRARY_ROOT", root):
            combined = main.combine_studio_tracks("Dark Techno/Apple Signal", combine_request)
            combined_file = combined["imports"][0]["file"]
            combined_audio_exists = (song / "studio" / "tracks" / combined_file).is_file()
            restored = main.uncombine_studio_tracks(
                "Dark Techno/Apple Signal", combined_file,
                main.StudioSessionRequest(tracks=[
                    main.StudioTrackState.model_validate(track) for track in combined["tracks"]
                ]),
            )
        metadata = json.loads((song / "song.json").read_text(encoding="utf-8"))

    assert combined_audio_exists
    assert [(track["name"], track["lane"], track["offset"])
            for track in restored["tracks"]] == [
        ("rain.wav", "effects", .5),
        ("thunder.wav", "effects", 1.0),
    ]
    assert [(track["name"], track["lane"], track["offset"])
            for track in metadata["studio"]["tracks"]] == [
        ("rain.wav", "effects", .5),
        ("thunder.wav", "effects", 1.0),
    ]


def test_tauri_disables_native_drag_drop_for_html5_timeline_dragging() -> None:
    """Tauri's Windows HTML5 drag/drop guidance requires this to remain disabled."""
    config = json.loads((PYTHON_ROOT.parent / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["app"]["windows"][0]["dragDropEnabled"] is False
