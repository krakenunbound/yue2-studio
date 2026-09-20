from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import re
import threading
from collections import deque
from datetime import datetime
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


class SessionFileHandler(RotatingFileHandler):
    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        source = Path(self.baseFilename)
        if source.exists() and source.stat().st_size:
            # Use the last write time, including the local UTC offset, so old
            # sessions retain their actual date when archived on the next launch.
            stamp = datetime.fromtimestamp(source.stat().st_mtime).astimezone().strftime("%Y-%m-%d_%H-%M-%S-%f%z")
            archive = source.with_name(f"studio-{stamp}.log")
            counter = 1
            while archive.exists():
                archive = source.with_name(f"studio-{stamp}-{counter}.log")
                counter += 1
            source.rename(archive)
            archives = sorted(
                (p for p in source.parent.glob("studio-*.log")
                 if re.fullmatch(r"studio-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}[+-]\d{4}(?:-\d+)?\.log", p.name)),
                key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True,
            )
            for old in archives[self.backupCount:]:
                old.unlink()
        if not self.delay:
            self.stream = self._open()


def install(log_root: Path) -> None:
    log_root.mkdir(parents=True, exist_ok=True)
    ring.setFormatter(SafeFormatter("%(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    path = str((log_root / "studio.log").resolve())
    if ring not in root.handlers:
        ring.clear()
        root.addHandler(ring)
    if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == path for h in root.handlers):
        handler = SessionFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        # Begin each process with a fresh file while retaining bounded history.
        # Repeated installation in the same process must not discard its log.
        if Path(path).stat().st_size:
            handler.doRollover()
        handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
