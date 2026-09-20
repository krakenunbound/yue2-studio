"""Local API-key vault. Keys never appear in GET responses or logs."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import threading
import time
import urllib.parse
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
    "ollama": {"label": "Local LLM", "jobs": ("writing",)},
    "kling": {"label": "Kling", "jobs": ("video",)},
    "seedance": {"label": "Seedance", "jobs": ("video",)},
}

CAPABILITIES: dict[str, dict[str, Any]] = {
    "writing": {
        "label": "Writing",
        "blurb": "Titles, lyrics, and style prompts for YuE2. The local YuE2 model generates the audio.",
        "providers": ("ollama", "gemini", "xai", "groq", "openai", "anthropic", "nvidia"),
        "default_provider": "gemini",
        "default_model": "gemini-3.6-flash",
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
# A portable default. Users can enter a private LAN IP and port for a server
# running elsewhere; never ship a workstation-specific address in the app.
OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434/v1"
OLLAMA_DEFAULT_MODEL = "gemma3:4b"


def normalize_ollama_url(raw: str) -> str:
    """Accept a LAN OpenAI-compatible root such as http://192.168.1.115:11434/v1."""
    text = (raw or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Local LLM URL must look like http://127.0.0.1:11434/v1")
    host = (parsed.hostname or "").lower()
    if not _lan_host(host):
        raise ValueError("Local LLM URL must be this computer or a private network address. Do not port-forward it.")
    path = (parsed.path or "").rstrip("/")
    if path in {"", "/api"}:
        path = "/v1"
    elif not path.endswith("/v1"):
        path = f"{path}/v1"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _lan_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(".local")
    return bool(address.is_private or address.is_loopback)


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
        base_url = str(entry.get("base_url") or "").strip()
        if name == "ollama":
            try:
                base_url = normalize_ollama_url(base_url) if base_url else ""
            except ValueError:
                base_url = ""
            if not base_url:
                continue
            data["providers"][name] = {
                "label": PROVIDERS[name]["label"],
                "key": key or "ollama",
                "base_url": base_url,
                "updated_at": str(entry.get("updated_at") or ""),
            }
            continue
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
        # Gemini 2.5 Flash and the earlier 3.5 default are unavailable to this
        # API project. Migrate them rather than leaving saved writer settings
        # failing until the user happens to edit them again.
        if name == "writing" and provider == "gemini" and model in {"gemini-2.5-flash", "gemini-3.5-flash"}:
            model = spec["default_model"]
        if name == "writing" and provider == "ollama" and not model:
            model = OLLAMA_DEFAULT_MODEL
        enabled = bool(incoming.get("enabled"))
        if enabled and not _can_enable(data, name, provider):
            enabled = False
        data["capabilities"][name] = {"enabled": enabled, "provider": provider, "model": model}
    return data


def _can_enable(data: dict[str, Any], capability: str, provider: str) -> bool:
    spec = CAPABILITIES[capability]
    if provider == "local":
        return False
    if provider == "ollama":
        return bool((data.get("providers") or {}).get("ollama", {}).get("base_url"))
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
                "configured": name in data["providers"] and (
                    bool(data["providers"][name].get("base_url")) if name == "ollama" else True
                ),
                "last4": _last4(data["providers"][name]["key"]) if name in data["providers"] else None,
                "updated_at": (data["providers"].get(name) or {}).get("updated_at") or None,
                **({"base_url": data["providers"][name].get("base_url") or ""} if name == "ollama" and name in data["providers"] else {}),
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
            configured = any(
                (data["providers"].get(item) or {}).get("base_url") if item == "ollama"
                else (data["providers"].get(item) or {}).get("key")
                for item in CAPABILITIES["writing"]["providers"]
            )
        out[name] = {
            "configured": bool(configured),
            "enabled": bool(cap["enabled"]),
            "provider": provider,
            "model": cap.get("model") or "",
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
            current = dict(data["providers"].get(name) or {})
            key = entry.get("key")
            if isinstance(key, str):
                key = key.strip()
                if key and set(key) <= {"•", "*"}:
                    key = ""
            else:
                key = ""
            if name == "ollama":
                raw_url = entry.get("base_url")
                base_url = current.get("base_url") or ""
                if isinstance(raw_url, str) and raw_url.strip():
                    base_url = normalize_ollama_url(raw_url)
                if not base_url:
                    continue
                data["providers"][name] = {
                    "label": PROVIDERS[name]["label"],
                    "key": key or current.get("key") or "ollama",
                    "base_url": base_url,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                continue
            if not key:
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
            if provider == "ollama" and not model:
                model = OLLAMA_DEFAULT_MODEL
            enabled = current["enabled"] if entry.get("enabled") is None else bool(entry.get("enabled"))
            if enabled and not _can_enable(data, name, provider):
                raise ValueError(
                    "Save the Local LLM server URL first" if provider == "ollama"
                    else f"Pick a cloud provider and save its key before enabling {CAPABILITIES[name]['label']}"
                )
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
    entry = data["providers"].get(provider) or {}
    if provider == "ollama":
        base_url = str(entry.get("base_url") or "")
        if not base_url:
            raise PermissionError("No Local LLM server URL saved")
        return {
            "provider": provider,
            "model": cap["model"] or OLLAMA_DEFAULT_MODEL,
            "key": str(entry.get("key") or "ollama"),
            "base_url": base_url,
        }
    key = entry.get("key")
    if not key:
        raise PermissionError(f"No API key saved for {provider}")
    return {"provider": provider, "model": cap["model"], "key": key}


def secret_for(provider: str) -> str | None:
    return ((load().get("providers") or {}).get(provider) or {}).get("key")
