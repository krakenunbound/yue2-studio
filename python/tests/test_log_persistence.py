import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import log_buffer


def test_exception_survives_handler_close_and_reappears_in_panel():
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
                original_time = log_buffer.ring.snapshot()[0]["ts"]
                for handler in root.handlers:
                    handler.close()
                root.handlers = []
            saved = (Path(directory) / "studio.log").read_text()
            assert "Traceback (most recent call last)" in saved
            assert "RuntimeError: synthetic memory failure" in saved
            with patch.object(log_buffer, "ring", log_buffer.RingHandler()):
                log_buffer.install(Path(directory))
                history = log_buffer.ring.snapshot()
                assert any(item["level"] == "ERROR" and "Synthesis failed" in item["message"] and "RuntimeError: synthetic memory failure" in item["message"] for item in history)
                assert any("synthetic memory failure" in item["message"] for item in history)
                assert abs(history[0]["ts"] - original_time) < 0.001
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
