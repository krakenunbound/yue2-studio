"""Local API-key vault. Keys never appear in GET responses or logs."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from config import OUTPUTS_ROOT
import ai_guides

log = logging.getLogger("yue2.vault")
VAULT_PATH = OUTPUTS_ROOT / "settings" / "api-keys.json"
_LOCK = threading.RLock()

PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {"label": "Google Gemini", "jobs": ("writing", "images")},
    "xai": {"label": "xAI Grok", "jobs": ("writing", "images", "video")},
    "groq": {"label": "Groq", "jobs": ("writing",)},
    "openai": {"label": "OpenAI", "jobs": ("writing", "images")},
    "anthropic": {"label": "Anthropic", "jobs": ("writing",)},
    "nvidia": {"label": "NVIDIA NIM", "jobs": ("writing",)},
    "kling": {"label": "Kling", "jobs": ("video",)},
    "seedance": {"label": "Seedance", "jobs": ("video",)},
}

CAPABILITIES: dict[str, dict[str, Any]] = {
    "writing": {
        "label": "Writing",
        "blurb": "Titles, lyrics, and style prompts for YuE2. The local YuE2 model generates the audio.",
        "providers": ("gemini", "xai", "groq", "openai", "anthropic", "nvidia"),
        "default_provider": "gemini",
        "default_model": "gemini-3.5-flash",
        "local_ok": False,
    },
    "images": {
        "label": "Still images",
        "blurb": "Covers and thumbnails only. Always 1:1 square. Default stays local SD 1.5.",
        "providers": ("local", "xai", "gemini", "openai"),
        "default_provider": "local",
        "default_model": "sd15",
        "local_ok": True,
    },
    "video": {
        "label": "Motion / video",
        "blurb": "Companion video. Horizontal 16:9 or vertical 9:16. Default stays local Video Studio.",
        "providers": ("local", "kling", "seedance", "xai"),
        "default_provider": "local",
        "default_model": "visualizer",
        "local_ok": True,
    },
}

LOCAL_MODELS = {"images": "sd15", "video": "visualizer"}


def _blank() -> dict[str, Any]:
    return {
        "version": 1,
        "providers": {},
        "capabilities": {
            key: {
                "enabled": False,
                "provider": spec["default_provider"],
                "model": spec["default_model"],
            }
            for key, spec in CAPABILITIES.items()
        },
    }


def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = _blank()
    if not isinstance(raw, dict):
        return data
    for name, entry in (raw.get("providers") or {}).items():
        if name not in PROVIDERS or not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if not key:
            continue
        data["providers"][name] = {
            "label": PROVIDERS[name]["label"],
            "key": key,
            "updated_at": str(entry.get("updated_at") or ""),
        }
    for name, spec in CAPABILITIES.items():
        incoming = (raw.get("capabilities") or {}).get(name) or {}
        provider = str(incoming.get("provider") or spec["default_provider"])
        allowed = spec["providers"]
        if provider not in allowed:
            provider = spec["default_provider"]
        model = str(incoming.get("model") or spec["default_model"]).strip() or spec["default_model"]
        if name == "writing" and provider == "gemini" and model in {"gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"}:
            model = spec["default_model"]
        enabled = bool(incoming.get("enabled"))
        if enabled and not _can_enable(data, name, provider):
            enabled = False
        data["capabilities"][name] = {"enabled": enabled, "provider": provider, "model": model}
    return data


def _can_enable(data: dict[str, Any], capability: str, provider: str) -> bool:
    spec = CAPABILITIES[capability]
    if provider == "local":
        return False
    return provider in spec["providers"] and bool((data.get("providers") or {}).get(provider, {}).get("key"))


def _load_unlocked() -> dict[str, Any]:
    if not VAULT_PATH.is_file():
        return _blank()
    try:
        return _normalize(json.loads(VAULT_PATH.read_text(encoding="utf-8")))
    except Exception as error:
        log.warning("API key vault unreadable; using empty vault (%s)", error)
        return _blank()


def _save_unlocked(data: dict[str, Any]) -> None:
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_normalize(data), indent=2)
    tmp = VAULT_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(VAULT_PATH)
    try:
        os.chmod(VAULT_PATH, 0o600)
    except OSError:
        pass


def load() -> dict[str, Any]:
    with _LOCK:
        return _load_unlocked()


def _last4(key: str) -> str:
    clean = key.strip()
    return clean[-4:] if len(clean) >= 4 else "••••"


def public_view() -> dict[str, Any]:
    data = load()
    return {
        "version": 1,
        "catalog": {
            "providers": {name: {"label": spec["label"], "jobs": list(spec["jobs"])} for name, spec in PROVIDERS.items()},
            "capabilities": {
                name: {
                    "label": spec["label"],
                    "blurb": spec["blurb"],
                    "providers": list(spec["providers"]),
                    "local_ok": spec["local_ok"],
                    "how": ai_guides.catalog()[name],
                }
                for name, spec in CAPABILITIES.items()
            },
        },
        "providers": {
            name: {
                "label": spec["label"],
                "configured": name in data["providers"],
                "last4": _last4(data["providers"][name]["key"]) if name in data["providers"] else None,
                "updated_at": (data["providers"].get(name) or {}).get("updated_at") or None,
            }
            for name, spec in PROVIDERS.items()
        },
        "capabilities": data["capabilities"],
    }


def status() -> dict[str, Any]:
    data = load()
    out: dict[str, Any] = {}
    for name, cap in data["capabilities"].items():
        provider = cap["provider"]
        configured = provider == "local" or bool((data["providers"].get(provider) or {}).get("key"))
        if name == "writing":
            configured = any((data["providers"].get(item) or {}).get("key") for item in CAPABILITIES["writing"]["providers"])
        out[name] = {
            "configured": bool(configured),
            "enabled": bool(cap["enabled"]),
            "provider": provider,
        }
    return out


def apply_update(body: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _load_unlocked()
        for name, entry in (body.get("providers") or {}).items():
            if name not in PROVIDERS or not isinstance(entry, dict):
                continue
            if entry.get("clear"):
                data["providers"].pop(name, None)
                continue
            key = entry.get("key")
            if not isinstance(key, str):
                continue
            key = key.strip()
            if not key or set(key) <= {"•", "*"}:
                continue
            data["providers"][name] = {
                "label": PROVIDERS[name]["label"],
                "key": key,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        for name, entry in (body.get("capabilities") or {}).items():
            if name not in CAPABILITIES or not isinstance(entry, dict):
                continue
            current = data["capabilities"][name]
            provider = str(entry.get("provider") or current["provider"])
            if provider not in CAPABILITIES[name]["providers"]:
                raise ValueError(f"{CAPABILITIES[name]['label']} cannot use {provider}")
            model = str(entry.get("model") if entry.get("model") is not None else current["model"]).strip()
            if provider == "local":
                model = LOCAL_MODELS.get(name, model)
            enabled = current["enabled"] if entry.get("enabled") is None else bool(entry.get("enabled"))
            if enabled and not _can_enable(data, name, provider):
                raise ValueError(f"Pick a cloud provider and save its key before enabling {CAPABILITIES[name]['label']}")
            current["provider"] = provider
            current["model"] = model or CAPABILITIES[name]["default_model"]
            current["enabled"] = enabled
        for name, cap in data["capabilities"].items():
            if cap["enabled"] and not _can_enable(data, name, cap["provider"]):
                cap["enabled"] = False
        _save_unlocked(data)
    return public_view()


def require_enabled(capability: str) -> dict[str, Any]:
    """Phase B+ entry point. Refuses unless the user checked Enable and a key exists."""
    data = load()
    cap = data["capabilities"].get(capability)
    if not cap or not cap.get("enabled"):
        raise PermissionError(f"{capability} cloud assist is off")
    provider = cap["provider"]
    if provider == "local":
        raise PermissionError(f"{capability} is set to the local engine")
    key = (data["providers"].get(provider) or {}).get("key")
    if not key:
        raise PermissionError(f"No API key saved for {provider}")
    return {"provider": provider, "model": cap["model"], "key": key}


def secret_for(provider: str) -> str | None:
    return ((load().get("providers") or {}).get(provider) or {}).get("key")
