"""Keep regression-test logging separate from real desktop sessions."""
import sys
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

_test_logs = tempfile.TemporaryDirectory(prefix="yue2-test-logs-")
config.LOGS_ROOT = Path(_test_logs.name)


def pytest_sessionfinish(session, exitstatus):
    logging.shutdown()
    _test_logs.cleanup()
