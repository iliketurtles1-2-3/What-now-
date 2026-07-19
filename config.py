from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping


SUPPORTED_PROVIDERS = {"anthropic", "openai"}
SUPPORTED_OPENAI_API_MODES = {"chat", "responses"}
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4.1",
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppSettings:
    provider: str
    model: str
    api_key: str
    openai_api_mode: str = "responses"
    openai_json_mode: bool = False
    openai_base_url: str | None = None
    timeout_seconds: float = 120.0

    @property
    def is_openrouter(self) -> bool:
        return "openrouter.ai" in (self.openai_base_url or "").lower()


@dataclass(frozen=True)
class RuntimeSettings:
    live_data_timeout_seconds: float = 8.0
    server_name: str = "0.0.0.0"
    server_port: int = 7860


def load_settings(values: Mapping[str, str] | None = None) -> AppSettings:
    env = values if values is not None else environ
    provider = env.get("LLM_PROVIDER", "anthropic").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"Unsupported LLM_PROVIDER '{provider}'. "
            f"Choose one of: {', '.join(sorted(SUPPORTED_PROVIDERS))}."
        )

    openai_api_mode = env.get("OPENAI_API_MODE", "responses").strip().lower()
    if provider == "openai" and openai_api_mode not in SUPPORTED_OPENAI_API_MODES:
        raise ConfigError(
            f"Unsupported OPENAI_API_MODE '{openai_api_mode}'. "
            f"Choose one of: {', '.join(sorted(SUPPORTED_OPENAI_API_MODES))}."
        )

    base_url = env.get("OPENAI_BASE_URL", "").strip() or None
    api_key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    api_key = env.get(api_key_name, "").strip()
    if provider == "openai" and not api_key and base_url and "openrouter.ai" in base_url.lower():
        api_key = env.get("OPENROUTER_API_KEY", "").strip()

    model = env.get("LLM_MODEL", "").strip() or DEFAULT_MODELS[provider]
    json_mode = env.get("OPENAI_JSON_MODE", "").strip().lower() in {"1", "true", "yes"}

    try:
        timeout_seconds = float(env.get("LLM_TIMEOUT_SECONDS", "120"))
    except ValueError as exc:
        raise ConfigError("LLM_TIMEOUT_SECONDS must be a number.") from exc
    if timeout_seconds <= 0:
        raise ConfigError("LLM_TIMEOUT_SECONDS must be greater than zero.")

    return AppSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        openai_api_mode=openai_api_mode,
        openai_json_mode=json_mode,
        openai_base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def load_runtime_settings(values: Mapping[str, str] | None = None) -> RuntimeSettings:
    env = values if values is not None else environ
    timeout = positive_float(env.get("LIVE_DATA_TIMEOUT"), default=8.0)
    port = positive_int(env.get("GRADIO_SERVER_PORT"), default=7860, maximum=65535)
    server_name = env.get("GRADIO_SERVER_NAME", "0.0.0.0").strip() or "0.0.0.0"
    return RuntimeSettings(
        live_data_timeout_seconds=timeout,
        server_name=server_name,
        server_port=port,
    )


def positive_float(value: str | None, *, default: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def positive_int(value: str | None, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if 0 < parsed <= maximum else default
