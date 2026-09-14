"""Optional LAN web access. Localhost (the desktop app) is unchanged and never gated."""
from __future__ import annotations

import json
import socket

from fastapi import Request
from fastapi.responses import JSONResponse

from config import LAN_PORT, OUTPUTS_ROOT, ROOT

SETTINGS = OUTPUTS_ROOT / "settings" / "lan.json"
DIST_ROOT = ROOT / "dist"
PUBLIC_PREFIXES = (
    "/health",
    "/api/lan/status",
    "/assets/",
    "/favicon",
    "/video-studio-static/",
)


def _load() -> dict:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save(data: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_local(request: Request) -> bool:
    client = (request.client.host if request.client else "") or ""
    return client in {"127.0.0.1", "::1", "localhost"}


def advertised_urls(port: int = LAN_PORT) -> list[str]:
    urls = [f"http://127.0.0.1:{port}"]
    seen = {"127.0.0.1"}
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        if ip and ip not in seen:
            seen.add(ip)
            urls.append(f"http://{ip}:{port}")
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and ip not in seen and not ip.startswith("127."):
                seen.add(ip)
                urls.append(f"http://{ip}:{port}")
    except OSError:
        pass
    return urls


def status(request: Request | None = None) -> dict:
    state = _load()
    enabled = bool(state.get("enabled"))
    local = is_local(request) if request is not None else True
    return {
        "enabled": enabled,
        "ui_ready": DIST_ROOT.is_dir() and (DIST_ROOT / "index.html").is_file(),
        "urls": advertised_urls() if enabled else [f"http://127.0.0.1:{LAN_PORT}"],
        "local": local,
        "needs_login": False,
        "port": LAN_PORT,
    }


def update(*, enabled: bool | None = None) -> dict:
    state = _load()
    if enabled is not None:
        state["enabled"] = bool(enabled)
    _save(state)
    return status()


def gate(request: Request):
    if is_local(request):
        return None
    path = request.url.path
    if path == "/" or path == "/index.html" or path.startswith("/assets/"):
        return None
    if any(path == prefix or path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return None
    if request.method == "OPTIONS":
        return None
    if not _load().get("enabled"):
        return JSONResponse({"detail": "LAN access is off. Enable it in System on the studio PC."}, status_code=403)
    return None
