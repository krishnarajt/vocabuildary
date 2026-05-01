"""
LLM Gateway adapter.

This is a client for the LLM Gateway service hosted at
`llmgateway.krishnarajthadesar.in` (or the in-cluster svc DNS, configured
via LLM_GATEWAY_URL). It is intentionally NOT used anywhere in v1.5 —
the business logic still comes straight out of the words table — but
it's wired up so v2 can start making real generation calls without
further plumbing.

Assumes an OpenAI-compatible chat-completions payload. If the gateway
grows a bespoke route, only `LLM_GATEWAY_CHAT_PATH` / `chat()` need to
change.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.common import constants

logger = logging.getLogger(__name__)


class LLMGatewayAdapter:
    """HTTP client for Krishnaraj's personal LLM Gateway."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        chat_path: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or constants.LLM_GATEWAY_URL).rstrip("/")
        self.api_key = api_key or constants.LLM_GATEWAY_API_KEY
        self.default_model = default_model or constants.LLM_GATEWAY_DEFAULT_MODEL
        self.chat_path = chat_path or constants.LLM_GATEWAY_CHAT_PATH
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # The gateway may accept either Bearer or x-api-key. Send Bearer
        # by default and let v2 adjust if the gateway expects otherwise.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Fire a chat-completions request at the gateway.

        `messages` follows the OpenAI shape:
            [{"role": "system", "content": "..."},
             {"role": "user",   "content": "..."}]

        Extra kwargs (temperature, max_tokens, response_format, ...) are
        forwarded verbatim to the gateway body.
        """
        url = f"{self.base_url}{self.chat_path}"
        payload: Dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
        }
        payload.update(kwargs)

        logger.debug(f"POST {url} model={payload['model']}")
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()

    def health(self) -> bool:
        """Cheap liveness probe against the gateway root."""
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{self.base_url}/health", headers=self._headers())
            return r.status_code == 200
        except Exception as e:
            logger.warning(f"LLM Gateway health check failed: {e}")
            return False
