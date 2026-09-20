"""Bounded, cancellable native Ollama chat transport.

This module deliberately uses Ollama's streaming endpoint.  Closing the active
response stops an in-progress generation but ``keep_alive: -1`` leaves the
model resident on the server for the next request.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any


# A 4k context is intentionally conservative for the RX 580's 8 GB VRAM.  It
# still allows a compact prompt plus the 1,500-token completion cap below.
NUM_CTX = 4096
NUM_PREDICT = 1500
NUM_BATCH = 64
MAX_INPUT_BYTES = 6 * 1024
MAX_REPLY_BYTES = 48 * 1024
MAX_EVENT_BYTES = 64 * 1024


class ActiveRequest:
    """A request handle that can interrupt a blocking stream read.

    ``cancel`` is safe to call from the web request that received Stop.  It
    first shuts down the underlying socket, then closes the HTTP response;
    either operation may already have happened and is therefore best-effort.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._response: Any | None = None
        self._cancelled = threading.Event()
        self._timed_out = threading.Event()

    @property
    def timed_out(self) -> bool:
        return self._timed_out.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def attach(self, response: Any) -> None:
        with self._lock:
            self._response = response
            already_cancelled = self._cancelled.is_set()
        if already_cancelled:
            self._close(response)

    def detach(self, response: Any) -> None:
        with self._lock:
            if self._response is response:
                self._response = None

    def timeout(self) -> None:
        self._timed_out.set()
        self.cancel()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            response = self._response
        if response is not None:
            self._close(response)

    @staticmethod
    def _close(response: Any) -> None:
        # urllib's response shape differs between Python builds.  Walk the
        # common wrappers to find a raw socket and use shutdown to wake a
        # thread blocked in readline before closing the response object.
        seen: set[int] = set()
        candidates = [response]
        while candidates:
            current = candidates.pop()
            if current is None or id(current) in seen:
                continue
            seen.add(id(current))
            raw_socket = getattr(current, "_sock", None)
            if raw_socket is not None and hasattr(raw_socket, "shutdown"):
                try:
                    raw_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            for name in ("fp", "raw"):
                child = getattr(current, name, None)
                if child is not None:
                    candidates.append(child)
        try:
            response.close()
        except Exception:
            pass


def _check_cancel(active: ActiveRequest, cancelled: Callable[[], bool]) -> None:
    if active.timed_out:
        raise RuntimeError("Local LLM timed out")
    if active.cancelled or cancelled():
        raise RuntimeError("Writing cancelled")


def _bounded_text(value: str, name: str) -> str:
    text = str(value or "")
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(f"Local LLM {name} is too long; shorten it and try again")
    return text


def _origin(base_url: str) -> str:
    origin = str(base_url or "").strip().rstrip("/")
    if origin.endswith("/v1"):
        origin = origin[:-3]
    if not origin:
        raise RuntimeError("Local LLM server URL is missing")
    return origin


def _payload(model: str, system: str, user: str, temperature: float, think: bool | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model or "gemma3:4b",
        "stream": True,
        "keep_alive": -1,
        "options": {
            "temperature": temperature,
            "top_p": 0.95,
            "top_k": 40,
            "repeat_penalty": 1.05,
            "presence_penalty": 0.15,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "num_batch": NUM_BATCH,
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if think is False:
        payload["think"] = False
    return payload


def chat(
    model: str,
    system: str,
    user: str,
    *,
    temperature: float,
    timeout: float,
    base_url: str,
    think: bool | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    register: Callable[[ActiveRequest | None], None] | None = None,
) -> str:
    """Send one native Ollama chat request and return its completed text.

    ``register`` receives an ``ActiveRequest`` before connecting and ``None``
    during cleanup.  Store that handle per API request and call ``cancel`` from
    the corresponding abort path.  The total deadline covers connection and
    streaming time, rather than resetting after every received chunk.
    """
    if timeout <= 0:
        raise ValueError("Local LLM timeout must be positive")
    system = _bounded_text(system, "instruction")
    user = _bounded_text(user, "prompt")
    if len(system.encode("utf-8")) + len(user.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Local LLM prompt is too long; shorten it and try again")

    active = ActiveRequest()
    if register is not None:
        register(active)
    deadline = time.monotonic() + timeout
    timer = threading.Timer(timeout, active.timeout)
    timer.daemon = True
    timer.start()
    response: Any | None = None
    try:
        _check_cancel(active, cancelled)
        request = urllib.request.Request(
            f"{_origin(base_url)}/api/chat",
            data=json.dumps(_payload(model, system, user, temperature, think)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Local LLM timed out")
        try:
            response = urllib.request.urlopen(request, timeout=remaining)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Local LLM HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            _check_cancel(active, cancelled)
            reason = error.reason
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise RuntimeError("Local LLM timed out") from error
            raise RuntimeError(f"Could not reach the Local LLM ({reason})") from error
        except TimeoutError as error:
            raise RuntimeError("Local LLM timed out") from error

        active.attach(response)
        _check_cancel(active, cancelled)
        parts: list[str] = []
        reply_bytes = 0
        finished = False
        while not finished:
            _check_cancel(active, cancelled)
            try:
                line = response.readline()
            except (OSError, ValueError) as error:
                _check_cancel(active, cancelled)
                raise RuntimeError("Local LLM stream failed") from error
            # A deadline/cancel can fire while readline is blocked.  Check
            # again before treating the wake-up EOF as a server-side failure.
            _check_cancel(active, cancelled)
            if not line:
                raise RuntimeError("Local LLM stream ended before completion")
            if len(line) > MAX_EVENT_BYTES:
                raise RuntimeError("Local LLM returned an oversized stream event")
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError("Local LLM returned malformed stream data") from error
            if not isinstance(event, dict):
                raise RuntimeError("Local LLM returned malformed stream data")
            if event.get("error"):
                raise RuntimeError(f"Local LLM error: {str(event['error'])[:400]}")
            message = event.get("message") or {}
            if not isinstance(message, dict):
                raise RuntimeError("Local LLM returned malformed stream data")
            content = message.get("content") or ""
            if not isinstance(content, str):
                raise RuntimeError("Local LLM returned malformed stream data")
            if content:
                reply_bytes += len(content.encode("utf-8"))
                if reply_bytes > MAX_REPLY_BYTES:
                    raise RuntimeError("Local LLM reply exceeded the safe size limit")
                parts.append(content)
            if event.get("done") is True:
                if str(event.get("done_reason") or "").lower() == "length":
                    raise RuntimeError("Local LLM reply hit the output limit; shorten the prompt and try again")
                finished = True
        reply = "".join(parts).strip()
        if not reply:
            raise RuntimeError("Local LLM returned an empty reply")
        return reply
    finally:
        timer.cancel()
        if response is not None:
            active.detach(response)
            ActiveRequest._close(response)
        if register is not None:
            register(None)
