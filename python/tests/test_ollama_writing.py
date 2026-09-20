from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_assist
import ai_vault


class OllamaWritingTests(unittest.TestCase):
    def test_cancel_and_shutdown_keep_model_loaded(self):
        for shutdown in (False, True):
            with self.subTest(shutdown=shutdown), \
                    patch.object(ai_assist, "_cancel") as cancel, \
                    patch.object(ai_assist, "_shutdown") as closing, \
                    patch.object(ai_assist, "_active_http") as connection, \
                    patch.object(ai_assist.urllib.request, "urlopen") as opened:
                ai_assist.abort_writing(shutdown=shutdown)
                cancel.set.assert_called_once()
                connection.cancel.assert_called_once()
                opened.assert_not_called()
                self.assertEqual(closing.set.call_count, int(shutdown))

    def test_normalize_lan_url_adds_v1(self):
        self.assertEqual(ai_vault.normalize_ollama_url("http://192.168.1.115:11434"), "http://192.168.1.115:11434/v1")
        self.assertEqual(ai_vault.normalize_ollama_url("http://192.168.1.115:11434/v1/"), "http://192.168.1.115:11434/v1")

    def test_default_ollama_endpoint_is_localhost(self):
        self.assertEqual(ai_vault.OLLAMA_DEFAULT_URL, "http://127.0.0.1:11434/v1")

    def test_older_gemini_flash_choice_migrates_to_the_working_default(self):
        with TemporaryDirectory() as temp, patch.object(ai_vault, "VAULT_PATH", Path(temp) / "api-keys.json"):
            view = ai_vault.apply_update({
                "providers": {"gemini": {"key": "test-only"}},
                "capabilities": {"writing": {"enabled": True, "provider": "gemini", "model": "gemini-2.5-flash"}},
            })
        self.assertEqual(view["capabilities"]["writing"]["model"], "gemini-3.6-flash")

    def test_normalize_rejects_public_hosts(self):
        with self.assertRaises(ValueError):
            ai_vault.normalize_ollama_url("https://api.openai.com/v1")

    def test_enable_ollama_with_url_and_no_cloud_key(self):
        with TemporaryDirectory() as temp, patch.object(ai_vault, "VAULT_PATH", Path(temp) / "api-keys.json"):
            view = ai_vault.apply_update({
                "providers": {"ollama": {"base_url": "http://192.168.1.115:11434/v1", "key": "ollama"}},
                "capabilities": {"writing": {"enabled": True, "provider": "ollama", "model": "songwriter"}},
            })
            self.assertTrue(view["capabilities"]["writing"]["enabled"])
            self.assertEqual(view["capabilities"]["writing"]["provider"], "ollama")
            self.assertEqual(view["providers"]["ollama"]["base_url"], "http://192.168.1.115:11434/v1")
            access = ai_vault.require_enabled("writing")
            self.assertEqual(access["provider"], "ollama")
            self.assertEqual(access["model"], "songwriter")
            self.assertEqual(access["base_url"], "http://192.168.1.115:11434/v1")
            self.assertIn("192.168.1.115", ai_vault.VAULT_PATH.read_text(encoding="utf-8"))

    def test_complete_streams_native_ollama_chat(self):
        captured: dict[str, str] = {}

        class Fake:
            def readline(self):
                if getattr(self, "done", False):
                    return b""
                self.done = True
                return json.dumps({"message": {"content": "Title: Silent Rain\n[Verse]\nRain"}, "done": True}).encode() + b"\n"

            def close(self):
                return None

        def fake_open(request, timeout=90):
            captured["url"] = request.full_url
            captured["timeout"] = str(timeout)
            captured["body"] = request.data.decode("utf-8")
            return Fake()

        with patch.object(ai_assist.urllib.request, "urlopen", fake_open):
            text = ai_assist._complete(
                "ollama", "gemma3:4b", "ollama", "sys", "user",
                base_url="http://192.168.1.115:11434/v1", timeout=45, label="test",
            )
        self.assertEqual(text, "Title: Silent Rain\n[Verse]\nRain")
        self.assertEqual(captured["url"], "http://192.168.1.115:11434/api/chat")
        payload = json.loads(captured["body"])
        self.assertTrue(payload.get("stream"))
        self.assertEqual(payload["options"]["presence_penalty"], 0.15)


if __name__ == "__main__":
    unittest.main()
