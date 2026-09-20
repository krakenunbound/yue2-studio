"""Exercise cleanup with a real pipe whose reader is blocked inside readline."""
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lyrics_sync
from jobs import Job


class LyricsWorkerCleanupTests(unittest.TestCase):
    def run_blocked_worker(self, mode):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            worker = folder / "worker.py"
            worker.write_text(
                "import json, pathlib, sys, time\n"
                "folder = pathlib.Path(sys.argv[sys.argv.index('--output-dir') + 1])\n"
                "folder.mkdir(exist_ok=True)\n"
                "result = folder / 'timed_lyrics.json'\n"
                "result.write_text(json.dumps({'lines': [{'text': 'Hello', 'start': 0, 'end': 1}]}))\n"
                "print(json.dumps({'event': 'progress', 'phase': 'align'}), flush=True)\n"
                + ("print(json.dumps({'event': 'result', 'json_path': str(result)}), flush=True)\n" if mode == "result" else "")
                + "time.sleep(30)\n",
                encoding="utf-8",
            )
            job = Job("pipe-test", "lyrics_sync", {})
            processes = []
            outcomes = []
            real_popen = subprocess.Popen

            def launch(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process

            def run():
                try:
                    outcomes.append(lyrics_sync._run_worker(
                        job, folder, {"lyrics": "Hello"}, folder / "lyrics.txt", "en", "cpu",
                        progress_base=.96, progress_span=.035,
                    ))
                except Exception as error:
                    outcomes.append(error)

            with patch.object(lyrics_sync, "WORKER", worker), \
                 patch.object(lyrics_sync, "RUNTIME_PYTHON", Path(sys._base_executable)), \
                 patch.object(lyrics_sync, "WORKER_TIMEOUT_SECONDS", .4 if mode == "timeout" else 10), \
                 patch.object(lyrics_sync.subprocess, "Popen", side_effect=launch):
                runner = threading.Thread(target=run, daemon=True)
                runner.start()
                if mode == "cancel":
                    deadline = time.monotonic() + 2
                    while job.progress < .97 and runner.is_alive() and time.monotonic() < deadline:
                        time.sleep(.01)
                    job.cancel.set()
                runner.join(3)
                completed = not runner.is_alive()
                children_exited = all(process.poll() is not None for process in processes)
                readers_exited = not any(thread.name == "yue2-lyrics-output" for thread in threading.enumerate())
                # Always release the child, including when the negative control deadlocks.
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                runner.join(3)
            self.assertTrue(completed, f"{mode}: cleanup blocked on the live stdout reader")
            self.assertTrue(children_exited, "cleanup left a running child process")
            self.assertTrue(readers_exited, "cleanup left a blocked output reader")
            self.assertFalse(runner.is_alive())
            self.assertIsNone(lyrics_sync._PROCESS)
            self.assertTrue(outcomes)
            if mode == "result":
                self.assertIsInstance(outcomes[0], dict)
                self.assertEqual(outcomes[0]["status"], "ready")
            else:
                self.assertIsInstance(outcomes[0], RuntimeError)
                self.assertIn("cancelled" if mode == "cancel" else "timed out", str(outcomes[0]))

    def test_completed_worker_with_open_pipe_does_not_block(self):
        self.run_blocked_worker("result")

    def test_cancellation_with_open_pipe_does_not_block(self):
        self.run_blocked_worker("cancel")

    def test_timeout_with_open_pipe_does_not_block(self):
        self.run_blocked_worker("timeout")


if __name__ == "__main__":
    unittest.main()
