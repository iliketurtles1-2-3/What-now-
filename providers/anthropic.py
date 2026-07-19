from __future__ import annotations

from typing import Any

from config import AppSettings, ConfigError


class AnthropicProvider:
    def __init__(self, settings: AppSettings, client: Any | None = None):
        self.settings = settings
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.api_key:
            raise ConfigError("ANTHROPIC_API_KEY is missing for provider 'anthropic'.")

        from anthropic import Anthropic

        self._client = Anthropic(
            api_key=self.settings.api_key,
            timeout=self.settings.timeout_seconds,
        )
        return self._client

    def complete(self, system_prompt: str, user_content: Any, max_tokens: int) -> str:
        response = self._get_client().messages.create(
            model=self.settings.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        chunks = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        return "\n".join(chunks).strip()
