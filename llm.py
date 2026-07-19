from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from config import AppSettings, ConfigError, load_settings
from providers import AnthropicProvider, OpenAICompatibleProvider


JSON_RESPONSE_ERROR = "The AI provider returned an invalid response. Please try again."
ModelCall = Callable[[str, Any, int], str]


def strip_json_fences(text: str) -> str:
    clean = text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    return clean.strip()


def extract_first_json_object(text: str) -> str:
    clean = strip_json_fences(text)
    if not clean:
        return clean
    start = clean.find("{")
    if start == -1:
        return clean

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(clean[start:], start=start):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return clean[start : index + 1]
    return clean


def parse_json_response(text: str) -> dict[str, Any]:
    result = json.loads(extract_first_json_object(text))
    if not isinstance(result, dict):
        raise json.JSONDecodeError("Top-level response must be a JSON object", text, 0)
    return result


def call_model(
    system_prompt: str,
    user_content: Any,
    max_tokens: int,
    *,
    settings: AppSettings | None = None,
) -> str:
    active_settings = settings or load_settings()
    if active_settings.provider == "anthropic":
        provider = AnthropicProvider(active_settings)
    elif active_settings.provider == "openai":
        provider = OpenAICompatibleProvider(active_settings)
    else:
        raise ConfigError(f"Unsupported LLM provider '{active_settings.provider}'.")
    return provider.complete(system_prompt, user_content, max_tokens)


def call_json(
    system_prompt: str,
    user_content: Any,
    max_tokens: int,
    *,
    model_call: ModelCall | None = None,
) -> dict[str, Any]:
    invoke = model_call or call_model
    first_response = invoke(system_prompt, user_content, max_tokens)
    try:
        return parse_json_response(first_response)
    except json.JSONDecodeError as first_error:
        print(f"Initial JSON parse failed: {first_error}")

    repair_prompt = (
        f"{system_prompt}\n\n"
        "Your previous response was not valid JSON. Return only valid JSON matching the schema."
    )
    try:
        return parse_json_response(invoke(repair_prompt, user_content, max_tokens))
    except json.JSONDecodeError as repair_error:
        raise ValueError(JSON_RESPONSE_ERROR) from repair_error
