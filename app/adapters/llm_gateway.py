"""
LLM Gateway adapter.

This is a client for the LLM Gateway service hosted at
`llmgateway.krishnarajthadesar.in` (or the in-cluster svc DNS, configured
via LLM_GATEWAY_URL). Reminder generation uses it to enrich each word
with an example paragraph, historical context, and etymology.

The gateway exposes its own /api/chat contract rather than an
OpenAI-compatible chat-completions route. This adapter accepts the familiar
messages list used by the app and translates it to the gateway payload.
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
        self.base_url = (constants.LLM_GATEWAY_URL if base_url is None else base_url).rstrip("/")
        self.api_key = constants.LLM_GATEWAY_API_KEY if api_key is None else api_key
        self.default_model = (
            constants.LLM_GATEWAY_DEFAULT_MODEL if default_model is None else default_model
        )
        self.chat_path = constants.LLM_GATEWAY_CHAT_PATH if chat_path is None else chat_path
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    @staticmethod
    def _prompts_from_messages(messages: List[Dict[str, str]]) -> tuple[Optional[str], str]:
        system_parts: list[str] = []
        user_parts: list[str] = []

        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", "")).strip()
            if not content:
                continue

            if role == "system":
                system_parts.append(content)
            elif role == "user":
                user_parts.append(content)
            else:
                user_parts.append(f"{role}: {content}")

        if not user_parts:
            raise ValueError("LLM Gateway chat requires at least one user message.")

        system_prompt = "\n\n".join(system_parts) or None
        user_prompt = "\n\n".join(user_parts)
        return system_prompt, user_prompt

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Fire a chat request at the gateway.

        `messages` follows the OpenAI shape:
            [{"role": "system", "content": "..."},
             {"role": "user",   "content": "..."}]

        Supported generation kwargs are mapped into the gateway config.
        Unknown kwargs are forwarded through config.extra.
        """
        if not self.api_key:
            raise RuntimeError("LLM_GATEWAY_API_KEY is not configured.")

        url = f"{self.base_url}{self.chat_path}"
        system_prompt, user_prompt = self._prompts_from_messages(messages)

        config: Dict[str, Any] = {"model": model or self.default_model}
        for key in ("temperature", "max_output_tokens", "top_p"):
            value = kwargs.pop(key, None)
            if value is not None:
                config[key] = value

        max_tokens = kwargs.pop("max_tokens", None)
        if max_tokens is not None and "max_output_tokens" not in config:
            config["max_output_tokens"] = max_tokens

        payload: Dict[str, Any] = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "config": config,
        }

        image_base64 = kwargs.pop("image_base64", None)
        if image_base64:
            payload["image_base64"] = image_base64
            payload["image_media_type"] = kwargs.pop("image_media_type", "image/png")

        if kwargs:
            config["extra"] = kwargs

        logger.debug(f"POST {url} model={config['model']}")
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload, headers=self._headers())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"LLM Gateway request failed with {response.status_code}: {detail}"
            ) from exc
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
