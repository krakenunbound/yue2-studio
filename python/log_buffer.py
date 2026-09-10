from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import re
import threading
from datetime import datetime
from collections import deque
from pathlib import Path


class RingHandler(logging.Handler):
    def __init__(self, capacity: int = 3000) -> None:
        super().__init__()
        self._items: deque[dict] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._next_id = 0

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._items.append({
                "id": self._next_id,
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            })
            self._next_id += 1

    def snapshot(self, *, limit: int = 500, since_id: int | None = None) -> list[dict]:
        with self._lock:
            items = list(self._items)
        if since_id is not None:
            items = [item for item in items if item["id"] > since_id]
        return items[-max(1, min(limit, 2000)):]

    def clear(self) -> None:
        with self._lock: self._items.clear()


ring = RingHandler()


class SafeFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        text = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", text)
        text = re.sub(r"hf_[0-9A-Za-z]{20,}", "[REDACTED]", text)
        return re.sub(r"(?i)([?&](?:key|api_key|token|signature|policy|x-amz-signature|x-amz-credential|x-amz-security-token)=)[^\s&\"']+", r"\1[REDACTED]", text)


def install(log_root: Path) -> None:
    log_root.mkdir(parents=True, exist_ok=True)
    ring.setFormatter(SafeFormatter("%(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    path = str((log_root / "studio.log").resolve())
    if ring not in root.handlers:
        # Reopen the last saved log in the panel, not only in a disk file.
        try:
            with open(path, encoding="utf-8") as saved:
                previous = deque(saved, maxlen=1000)
            pending = None
            for line in previous:
                match = re.match(r"^\S+ \S+ (DEBUG|INFO|WARNING|ERROR|CRITICAL) ([^:]+): (.*)", line.rstrip())
                if match:
                    if pending is not None:
                        ring.emit(pending)
                    pending = logging.LogRecord(match[2], getattr(logging, match[1]), "", 0, match[3], (), None)
                    try:
                        pending.created = datetime.fromisoformat(line[:23].replace(",", ".")).timestamp()
                    except ValueError:
                        pass
                elif pending is not None:
                    pending.msg += "\n" + line.rstrip()
                else:
                    pending = logging.LogRecord("previous.session", logging.INFO, "", 0, line.rstrip(), (), None)
            if pending is not None:
                ring.emit(pending)
        except FileNotFoundError:
            pass
        root.addHandler(ring)
    if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == path for h in root.handlers):
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
