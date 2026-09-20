from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ollama_transport


class _Stream:
    def __init__(self, events: list[bytes]) -> None:
        self.events = iter(events)
        self.closed = False

    def readline(self) -> bytes:
        return next(self.events, b"")

    def close(self) -> None:
        self.closed = True


def _event(content: str = "", **extra: object) -> bytes:
    data = {"message": {"content": content}}
    data.update(extra)
    return json.dumps(data).encode("utf-8") + b"\n"


class OllamaTransportTests(unittest.TestCase):
    def call(self, stream: _Stream, **kwargs: object) -> str:
        with patch.object(ollama_transport.urllib.request, "urlopen", return_value=stream):
            return ollama_transport.chat(
                "songwriter", "system", "user", temperature=0.7,
                timeout=1, base_url="http://192.168.1.115:11434/v1", **kwargs,
            )

    def test_native_stream_payload_keeps_model_loaded_and_caps_work(self) -> None:
        stream = _Stream([_event("hello", done=True, done_reason="stop")])
        with patch.object(ollama_transport.urllib.request, "urlopen", return_value=stream) as opened:
            self.assertEqual("hello", ollama_transport.chat(
                "songwriter", "sys", "user", temperature=0.7, timeout=1,
                base_url="http://host:11434/v1", think=False,
            ))
        request = opened.call_args.args[0]
        self.assertEqual("http://host:11434/api/chat", request.full_url)
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(-1, payload["keep_alive"])
        self.assertFalse(payload["think"])
        self.assertEqual(4096, payload["options"]["num_ctx"])
        self.assertEqual(1500, payload["options"]["num_predict"])
        self.assertEqual(64, payload["options"]["num_batch"])

    def test_rejects_malformed_premature_and_length_streams(self) -> None:
        cases = [
            ([_event("hello")], "ended before completion"),
            ([b"not json\n"], "malformed stream"),
            ([_event("partial", done=True, done_reason="length")], "output limit"),
            ([_event("", done=True, done_reason="stop")], "empty reply"),
        ]
        for events, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, message):
                    self.call(_Stream(events))

    def test_rejects_server_error_and_reply_overflow(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "out of memory"):
            self.call(_Stream([json.dumps({"error": "out of memory"}).encode() + b"\n"]))
        huge = "x" * (ollama_transport.MAX_REPLY_BYTES + 1)
        with self.assertRaisesRegex(RuntimeError, "safe size"):
            self.call(_Stream([_event(huge, done=True, done_reason="stop")]))

    def test_rejects_oversized_inputs_before_opening_a_socket(self) -> None:
        with patch.object(ollama_transport.urllib.request, "urlopen") as opened:
            with self.assertRaisesRegex(ValueError, "too long"):
                ollama_transport.chat(
                    "m", "s", "x" * (ollama_transport.MAX_INPUT_BYTES + 1),
                    temperature=0.7, timeout=1, base_url="http://host:11434",
                )
        opened.assert_not_called()

    def test_registered_handle_cancels_blocking_read(self) -> None:
        attached = threading.Event()
        released = threading.Event()
        holder: list[ollama_transport.ActiveRequest | None] = []

        class Blocking:
            def readline(self) -> bytes:
                released.wait(1)
                return b""

            def close(self) -> None:
                released.set()

        def register(handle: ollama_transport.ActiveRequest | None) -> None:
            holder.append(handle)
            if handle is not None:
                attached.set()

        result: list[Exception] = []
        with patch.object(ollama_transport.urllib.request, "urlopen", return_value=Blocking()):
            thread = threading.Thread(target=lambda: self._capture(result, register), daemon=True)
            thread.start()
            self.assertTrue(attached.wait(0.5))
            self.assertIsNotNone(holder[-1])
            holder[-1].cancel()  # type: ignore[union-attr]
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual("Writing cancelled", str(result[0]))
        self.assertIsNone(holder[-1])

    def _capture(self, result: list[Exception], register: object) -> None:
        try:
            ollama_transport.chat(
                "m", "s", "u", temperature=0.7, timeout=1,
                base_url="http://host:11434", register=register,  # type: ignore[arg-type]
            )
        except Exception as error:
            result.append(error)

    def test_total_deadline_interrupts_a_stalled_stream(self) -> None:
        released = threading.Event()

        class Blocking:
            def readline(self) -> bytes:
                released.wait(1)
                return b""

            def close(self) -> None:
                released.set()

        started = time.monotonic()
        with patch.object(ollama_transport.urllib.request, "urlopen", return_value=Blocking()):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                ollama_transport.chat("m", "s", "u", temperature=0.7, timeout=0.05, base_url="http://host:11434")
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
