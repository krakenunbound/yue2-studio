import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import log_buffer


def test_new_session_starts_fresh_and_archives_previous_exception():
    root = logging.getLogger()
    original = list(root.handlers)
    old_level = root.level
    with TemporaryDirectory() as directory:
        try:
            root.handlers = []
            with patch.object(log_buffer, "ring", log_buffer.RingHandler()):
                log_buffer.install(Path(directory))
                try:
                    raise RuntimeError("synthetic memory failure")
                except RuntimeError:
                    logging.getLogger("memory.test").exception("Synthesis failed")
                for handler in root.handlers:
                    handler.close()
                root.handlers = []
            saved = (Path(directory) / "studio.log").read_text()
            assert "Traceback (most recent call last)" in saved
            assert "RuntimeError: synthetic memory failure" in saved
            with patch.object(log_buffer, "ring", log_buffer.RingHandler()):
                log_buffer.install(Path(directory))
                history = log_buffer.ring.snapshot()
                assert history == []
                assert (Path(directory) / "studio.log").read_text() == ""
                assert next(Path(directory).glob("studio-*.log")).read_text() == saved
                logging.getLogger("memory.test").info("New session")
                # Installing twice must preserve this session and avoid duplicates.
                log_buffer.install(Path(directory))
                assert [item["message"] for item in log_buffer.ring.snapshot()] == ["New session"]
                current = (Path(directory) / "studio.log").read_text()
                assert current.count("New session") == 1
                assert "synthetic memory failure" not in current
                assert next(Path(directory).glob("studio-*.log")).read_text() == saved
        finally:
            for handler in root.handlers:
                handler.close()
            root.handlers = original
            root.setLevel(old_level)


def test_startup_archives_remain_bounded():
    root = logging.getLogger()
    original = list(root.handlers)
    old_level = root.level
    with TemporaryDirectory() as directory:
        try:
            root.handlers = []
            for session in range(5):
                with patch.object(log_buffer, "ring", log_buffer.RingHandler()):
                    log_buffer.install(Path(directory))
                    assert log_buffer.ring.snapshot() == []
                    logging.getLogger("session.test").info("Session %s", session)
                    for handler in root.handlers:
                        handler.close()
                    root.handlers = []
            archives = list(Path(directory).glob("studio-*.log"))
            assert len(archives) == 3
            assert "Session 4" in (Path(directory) / "studio.log").read_text()
            contents = "".join(p.read_text() for p in archives)
            for session in (1, 2, 3):
                assert f"Session {session}" in contents
            assert "Session 0" not in contents
        finally:
            for handler in root.handlers:
                handler.close()
            root.handlers = original
            root.setLevel(old_level)


def test_formatter_redacts_key_parameters():
    formatter = log_buffer.SafeFormatter("%(message)s")
    record = logging.LogRecord("test", logging.ERROR, "", 0,
                               "request failed ?key=fake-key-for-test&other=ok", (), None)
    assert "fake-key-for-test" not in formatter.format(record)
    assert "other=ok" in formatter.format(record)


def test_archive_timestamp_uses_previous_log_time_and_never_overwrites():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "studio.log"
        timestamp = datetime(2026, 9, 15, 22, 30, 12).timestamp()
        stamp = datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d_%H-%M-%S-%f%z")
        handler = log_buffer.SessionFileHandler(path, maxBytes=100, backupCount=3, encoding="utf-8", delay=True)
        try:
            for message in ("first", "second"):
                path.write_text(message)
                os.utime(path, (timestamp, timestamp))
                handler.doRollover()
            assert (Path(directory) / f"studio-{stamp}.log").read_text() == "first"
            assert (Path(directory) / f"studio-{stamp}-1.log").read_text() == "second"
        finally:
            handler.close()
