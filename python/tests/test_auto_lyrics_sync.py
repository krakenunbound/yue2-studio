import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import lyrics_sync
from jobs import Job


class AutomaticLyricsSyncTests(unittest.TestCase):
    def run_generation(self, *, instrumental=False, ready=True, cover_failure=False, sync_failure=False, cancel_sync=False):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            folder = Path(temp) / "song"
            folder.mkdir()
            events = []
            params = dict(title="Apples", description="dark techno", lyrics="[Verse]\nRed apples on the floor", instrumental=instrumental, seed=12, cot_mode="off", steps=32, cfg=1.2)
            job = Job("qa", "yue2", params)
            def music(job, request, output):
                events.append("song")
                output.write_bytes(b"test audio")
                return {"duration": 20, "sample_rate": 48000}
            def cover(*args, **kwargs):
                events.append("thumbnail")
                if cover_failure: raise RuntimeError("cover failed")
                (folder / "cover.png").write_bytes(b"test cover")
            def sync(job, song_dir, metadata, **kwargs):
                events.append("sync")
                saved = json.loads((folder / "song.json").read_text())
                self.assertEqual(saved["cover"], None if cover_failure else "cover.png")
                self.assertEqual(kwargs, {"progress_base": .96, "progress_span": .035})
                if cancel_sync:
                    job.cancel.set()
                    raise RuntimeError("cancelled")
                if sync_failure: raise RuntimeError("alignment failed")
                metadata["lyrics_sync"] = {"status": "ready", "line_count": 1}
                return {"timed_lyrics": {"lines": [{"text": "Red apples on the floor"}]}}
            replacements = [
                (main.ai_assist, "ensure_unique_title", lambda title, **kw: title),
                (main, "create_song_directory", lambda *args: folder),
                (main.yue2_engine, "generate", music),
                (main.yue2_engine, "cancel", lambda: events.append("release-yue2")),
                (main, "align_audio_to_title", lambda *args: folder / "song.wav"),
                (main, "song_folder_name", lambda *args: "song"),
                (main, "song_audio_url", lambda *args: "/audio"),
                (main.cover_art, "available", lambda: True),
                (main.cover_art, "render", cover),
                (main.generation_timing, "predict", lambda *args: SimpleNamespace(cover_seconds=1)),
                (main.lyrics_sync, "status", lambda: {"ready": ready, "detail": "not installed"}),
                (main.lyrics_sync, "run", sync),
            ]
            for obj, name, replacement in replacements: stack.enter_context(patch.object(obj, name, replacement))
            if cancel_sync:
                with self.assertRaisesRegex(RuntimeError, "cancelled"): main.generate(job)
                self.assertTrue((folder / "song.wav").exists())
                return
            result = main.generate(job)
            saved = json.loads((folder / "song.json").read_text())
            self.assertEqual(saved["needs_lyric_sync"], result["needs_lyric_sync"])
            return events, result

    def test_sync_runs_after_thumbnail_before_song_completes(self):
        events, result = self.run_generation()
        self.assertEqual(events, ["song", "thumbnail", "release-yue2", "sync"])
        self.assertFalse(result["needs_lyric_sync"])
        self.assertEqual(result["lyrics_sync"]["status"], "ready")

    def test_thumbnail_failure_still_syncs_saved_audio(self):
        events, result = self.run_generation(cover_failure=True)
        self.assertEqual(events[-1], "sync")
        self.assertEqual(result["cover_error"], "cover failed")

    def test_sync_failure_preserves_song_and_retry_flag(self):
        _, result = self.run_generation(sync_failure=True)
        self.assertTrue(result["needs_lyric_sync"])
        self.assertEqual(result["lyrics_sync_error"], "alignment failed")

    def test_instrumental_skips_sync(self):
        events, result = self.run_generation(instrumental=True)
        self.assertEqual(events, ["song", "thumbnail"])
        self.assertFalse(result["needs_lyric_sync"])

    def test_missing_runtime_is_recorded_without_failing_song(self):
        events, result = self.run_generation(ready=False)
        self.assertEqual(events, ["song", "thumbnail"])
        self.assertEqual(result["lyrics_sync_error"], "not installed")

    def test_cancel_during_sync_preserves_saved_song(self):
        self.run_generation(cancel_sync=True)

    def test_silent_worker_can_be_cancelled_without_waiting_for_output(self):
        class SilentStream:
            def __init__(self):
                self.reading = threading.Event()
                self.release = threading.Event()

            def __iter__(self):
                self.reading.set()
                self.release.wait(5)
                return iter(())

        class SilentProcess:
            def __init__(self):
                self.stdout = SilentStream()
                self.stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def wait(self, timeout=None):
                return 0

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "song"
            folder.mkdir()
            (folder / "song.wav").write_bytes(b"audio")
            process = SilentProcess()
            job = Job("qa", "lyrics_sync", {})

            def stop(target=None):
                process.stopped = True
                process.stdout.release.set()

            def request_cancel():
                self.assertTrue(process.stdout.reading.wait(1))
                job.cancel.set()

            canceller = threading.Thread(target=request_cancel, daemon=True)
            canceller.start()
            started = time.monotonic()
            with patch.object(lyrics_sync, "status", return_value={"ready": True}), \
                 patch.object(lyrics_sync.subprocess, "Popen", return_value=process), \
                 patch.object(lyrics_sync, "_stop_process", side_effect=stop):
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    lyrics_sync.run(job, folder, {"lyrics": "words", "audio": "song.wav"})
            self.assertLess(time.monotonic() - started, 2)

    def test_hung_worker_times_out_then_retries_cpu(self):
        class HangStream:
            def __init__(self):
                self.release = threading.Event()

            def __iter__(self):
                self.release.wait(5)
                return iter(())

        class HangProcess:
            def __init__(self):
                self.stdout = HangStream()
                self.stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def wait(self, timeout=None):
                return 0

        processes: list[HangProcess] = []

        def popen(*args, **kwargs):
            process = HangProcess()
            processes.append(process)
            return process

        def stop(target=None):
            process = target or processes[-1]
            process.stopped = True
            process.stdout.release.set()

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "song"
            folder.mkdir()
            (folder / "song.wav").write_bytes(b"audio")
            job = Job("qa", "lyrics_sync", {})
            started = time.monotonic()
            with patch.object(lyrics_sync, "WORKER_TIMEOUT_SECONDS", 0.4), \
                 patch.object(lyrics_sync, "status", return_value={"ready": True}), \
                 patch.object(lyrics_sync.subprocess, "Popen", side_effect=popen), \
                 patch.object(lyrics_sync, "_stop_process", side_effect=stop):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    lyrics_sync.run(job, folder, {"lyrics": "words", "audio": "song.wav"})
            self.assertEqual(len(processes), 2)
            self.assertLess(time.monotonic() - started, 3)

    def test_result_event_finishes_even_if_worker_never_exits(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "song"
            folder.mkdir()
            (folder / "song.wav").write_bytes(b"audio")
            sync = folder / "lyrics_sync"
            sync.mkdir()
            payload = {"language": "en", "line_count": 1, "word_count": 2, "alignment_method": "whisperx-forced-known-lyrics", "created_at": "now", "lines": [{"text": "hi", "start": 1, "end": 2}]}
            result_file = sync / "timed_lyrics.json"
            result_file.write_text(json.dumps(payload), encoding="utf-8")
            result_line = json.dumps({"event": "result", "json_path": str(result_file)}) + "\n"
            progress_line = json.dumps({"event": "progress", "phase": "write", "message": "Writing JSON, LRC, and ASS karaoke files."}) + "\n"

            class ResultThenHang:
                def __init__(self):
                    self.stdout = iter([progress_line, result_line])
                    self.stopped = False

                def poll(self):
                    return 0 if self.stopped else None

                def wait(self, timeout=None):
                    raise subprocess.TimeoutExpired(cmd="lyrics", timeout=timeout)

                def close(self):
                    return None

            process = ResultThenHang()

            def stop(target=None):
                process.stopped = True

            job = Job("qa", "lyrics_sync", {})
            started = time.monotonic()
            with patch.object(lyrics_sync, "status", return_value={"ready": True}), \
                 patch.object(lyrics_sync.subprocess, "Popen", return_value=process), \
                 patch.object(lyrics_sync, "_stop_process", side_effect=stop):
                result = lyrics_sync.run(job, folder, {"lyrics": "words", "audio": "song.wav", "title": "Hi"})
            self.assertEqual(result["status"], "ready")
            self.assertFalse(job.cancel.is_set())
            self.assertLess(time.monotonic() - started, 2)
