from __future__ import annotations

from typing import Any

from config import AppSettings, ConfigError


class OpenAICompatibleProvider:
    def __init__(self, settings: AppSettings, client: Any | None = None):
        self.settings = settings
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.api_key:
            key_name = "OPENROUTER_API_KEY or OPENAI_API_KEY" if self.settings.is_openrouter else "OPENAI_API_KEY"
            raise ConfigError(f"{key_name} is missing for provider 'openai'.")

        from openai import OpenAI

        kwargs: dict[str, Any] = {
            "api_key": self.settings.api_key,
            "timeout": self.settings.timeout_seconds,
        }
        if self.settings.openai_base_url:
            kwargs["base_url"] = self.settings.openai_base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def complete(self, system_prompt: str, user_content: Any, max_tokens: int) -> str:
        if self.settings.openai_api_mode == "chat":
            request_args: dict[str, Any] = {
                "model": self.settings.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chat_user_content(user_content)},
                ],
                "max_tokens": max_tokens,
            }
            if self.settings.openai_json_mode:
                request_args["response_format"] = {"type": "json_object"}
            response = self._get_client().chat.completions.create(**request_args)
            return response.choices[0].message.content or ""

        if self.settings.openai_api_mode == "responses":
            response = self._get_client().responses.create(
                model=self.settings.model,
                instructions=system_prompt,
                input=[
                    {
                        "role": "user",
                        "content": responses_user_content(user_content),
                    }
                ],
                max_output_tokens=max_tokens,
            )
            return getattr(response, "output_text", "") or ""

        raise ConfigError(
            f"Unsupported OPENAI_API_MODE '{self.settings.openai_api_mode}'."
        )


def chat_user_content(user_content: Any) -> Any:
    if isinstance(user_content, str):
        return user_content

    content: list[dict[str, Any]] = []
    for item in user_content:
        if item.get("type") == "document":
            source = item.get("source", {})
            content.append(
                {
                    "type": "file",
                    "file": {
                        "filename": "cv.pdf",
                        "file_data": data_url(source),
                    },
                }
            )
        elif item.get("type") == "text":
            content.append({"type": "text", "text": item.get("text", "")})
    return content


def responses_user_content(user_content: Any) -> list[dict[str, Any]]:
    if isinstance(user_content, str):
        return [{"type": "input_text", "text": user_content}]

    content: list[dict[str, Any]] = []
    for item in user_content:
        if item.get("type") == "document":
            source = item.get("source", {})
            content.append(
                {
                    "type": "input_file",
                    "filename": "cv.pdf",
                    "file_data": data_url(source),
                }
            )
        elif item.get("type") == "text":
            content.append({"type": "input_text", "text": item.get("text", "")})
    return content


def data_url(source: dict[str, Any]) -> str:
    media_type = source.get("media_type", "application/pdf")
    return f"data:{media_type};base64,{source.get('data', '')}"
