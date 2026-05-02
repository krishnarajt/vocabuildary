import os
import unittest
from unittest.mock import patch

import httpx

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from app.adapters.llm_gateway import LLMGatewayAdapter
from app.services.reminder_content_service import _extract_content


class FakeResponse:
    def __init__(self, data=None, status_code=200, text="OK"):
        self._data = data or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code < 400:
            return

        request = httpx.Request("POST", "https://gateway.test/api/chat")
        response = httpx.Response(self.status_code, request=request, text=self.text)
        raise httpx.HTTPStatusError("request failed", request=request, response=response)


class FakeClient:
    def __init__(self, timeout, response, calls):
        self.timeout = timeout
        self.response = response
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json, headers):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": self.timeout,
            }
        )
        return self.response


class LLMGatewayAdapterTests(unittest.TestCase):
    def test_chat_uses_gateway_contract(self):
        calls = []
        response = FakeResponse({"content": '{"paragraph":"ok","history":"ok","etymology":"ok"}'})

        def client_factory(timeout):
            return FakeClient(timeout, response, calls)

        adapter = LLMGatewayAdapter(
            base_url="https://gateway.test",
            api_key="gw-test-key",
            default_model="gemini-flash-latest",
            chat_path="/api/chat",
        )

        with patch("app.adapters.llm_gateway.httpx.Client", side_effect=client_factory):
            result = adapter.chat(
                messages=[
                    {"role": "system", "content": "Return JSON."},
                    {"role": "user", "content": "Word: ephemeral"},
                ],
                temperature=0.4,
                max_tokens=256,
                response_format={"type": "json_object"},
            )

        self.assertEqual(result, response.json())
        self.assertEqual(len(calls), 1)

        call = calls[0]
        self.assertEqual(call["url"], "https://gateway.test/api/chat")
        self.assertEqual(
            call["headers"],
            {"Content-Type": "application/json", "X-API-Key": "gw-test-key"},
        )
        self.assertEqual(
            call["json"],
            {
                "system_prompt": "Return JSON.",
                "user_prompt": "Word: ephemeral",
                "config": {
                    "model": "gemini-flash-latest",
                    "temperature": 0.4,
                    "max_output_tokens": 256,
                    "extra": {"response_format": {"type": "json_object"}},
                },
            },
        )

    def test_chat_requires_gateway_api_key(self):
        adapter = LLMGatewayAdapter(
            base_url="https://gateway.test",
            api_key="",
            default_model="gemini-flash-latest",
            chat_path="/api/chat",
        )

        with self.assertRaisesRegex(RuntimeError, "LLM_GATEWAY_API_KEY"):
            adapter.chat(messages=[{"role": "user", "content": "Hello"}])


class ReminderContentResponseTests(unittest.TestCase):
    def test_extract_content_accepts_gateway_response(self):
        self.assertEqual(_extract_content({"content": "  hello  "}), "hello")

    def test_extract_content_keeps_openai_response_fallback(self):
        self.assertEqual(
            _extract_content({"choices": [{"message": {"content": "  hello  "}}]}),
            "hello",
        )


if __name__ == "__main__":
    unittest.main()
