import unittest
from types import SimpleNamespace

from config import AppSettings, ConfigError, load_runtime_settings, load_settings
from llm import call_json
from prompts import load_prompt
from providers.anthropic import AnthropicProvider
from providers.openai_compatible import OpenAICompatibleProvider


class FakeCreate:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class ConfigurationTests(unittest.TestCase):
    def test_openrouter_key_and_model_are_loaded_without_openai_key(self):
        settings = load_settings(
            {
                "LLM_PROVIDER": "openai",
                "OPENAI_API_MODE": "chat",
                "OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
                "OPENROUTER_API_KEY": "test-key",
                "LLM_MODEL": "z-ai/glm-5.2",
            }
        )

        self.assertEqual(settings.api_key, "test-key")
        self.assertEqual(settings.model, "z-ai/glm-5.2")
        self.assertTrue(settings.is_openrouter)

    def test_current_anthropic_default_is_used(self):
        settings = load_settings({"LLM_PROVIDER": "anthropic"})

        self.assertEqual(settings.model, "claude-sonnet-5")

    def test_invalid_provider_and_api_mode_fail_early(self):
        with self.assertRaisesRegex(ConfigError, "Unsupported LLM_PROVIDER"):
            load_settings({"LLM_PROVIDER": "unknown"})
        with self.assertRaisesRegex(ConfigError, "Unsupported OPENAI_API_MODE"):
            load_settings(
                {
                    "LLM_PROVIDER": "openai",
                    "OPENAI_API_MODE": "invalid",
                }
            )

    def test_runtime_settings_accept_custom_server_values(self):
        settings = load_runtime_settings(
            {
                "LIVE_DATA_TIMEOUT": "12.5",
                "GRADIO_SERVER_NAME": "127.0.0.1",
                "GRADIO_SERVER_PORT": "9876",
            }
        )

        self.assertEqual(settings.live_data_timeout_seconds, 12.5)
        self.assertEqual(settings.server_name, "127.0.0.1")
        self.assertEqual(settings.server_port, 9876)

    def test_malformed_runtime_values_fall_back_without_blocking_startup(self):
        settings = load_runtime_settings(
            {
                "LIVE_DATA_TIMEOUT": "ten",
                "GRADIO_SERVER_PORT": "occupied",
            }
        )

        self.assertEqual(settings.live_data_timeout_seconds, 8.0)
        self.assertEqual(settings.server_port, 7860)

    def test_prompt_loader_uses_versioned_files_and_rejects_traversal(self):
        self.assertIn("evidence-aware profile", load_prompt("profile", "v2"))
        with self.assertRaises(ValueError):
            load_prompt("../profile", "v2")

    def test_v2_strategy_prompt_blocks_generic_ai_career_advice(self):
        prompt = load_prompt("strategy", "v2")

        self.assertIn("Do not default to", prompt)
        self.assertIn("At most one perspective may be primarily", prompt)
        self.assertIn("Do not recommend only courses", prompt)
        self.assertIn("search intents", prompt)

    def test_v2_profile_prompt_generates_case_specific_questions(self):
        prompt = load_prompt("profile", "v2")

        self.assertIn("follow_up_questions", prompt)
        self.assertIn("case-specific questions", prompt)
        self.assertIn("Do not assume the person should build a project", prompt)


class ProviderTests(unittest.TestCase):
    def test_openai_compatible_chat_supports_pdf_content_and_json_mode(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )
        create = FakeCreate(completion)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=create),
            responses=SimpleNamespace(),
        )
        settings = AppSettings(
            provider="openai",
            model="z-ai/glm-5.2",
            api_key="test-key",
            openai_api_mode="chat",
            openai_json_mode=True,
            openai_base_url="https://openrouter.ai/api/v1",
        )
        content = [
            {
                "type": "document",
                "source": {
                    "media_type": "application/pdf",
                    "data": "cGRm",
                },
            },
            {"type": "text", "text": "Analyze this PDF CV."},
        ]

        result = OpenAICompatibleProvider(settings, client).complete(
            "system",
            content,
            100,
        )

        self.assertEqual(result, '{"ok": true}')
        request = create.calls[0]
        self.assertEqual(request["response_format"], {"type": "json_object"})
        user_parts = request["messages"][1]["content"]
        self.assertEqual(user_parts[0]["type"], "file")
        self.assertEqual(user_parts[0]["file"]["filename"], "cv.pdf")
        self.assertTrue(user_parts[0]["file"]["file_data"].startswith("data:application/pdf;base64,"))

    def test_openai_responses_mode_uses_input_file_shape(self):
        create = FakeCreate(SimpleNamespace(output_text="done"))
        client = SimpleNamespace(
            chat=SimpleNamespace(),
            responses=create,
        )
        settings = AppSettings(
            provider="openai",
            model="gpt-4.1",
            api_key="test-key",
            openai_api_mode="responses",
        )

        result = OpenAICompatibleProvider(settings, client).complete(
            "system",
            [
                {
                    "type": "document",
                    "source": {"media_type": "application/pdf", "data": "cGRm"},
                }
            ],
            100,
        )

        self.assertEqual(result, "done")
        file_part = create.calls[0]["input"][0]["content"][0]
        self.assertEqual(file_part["type"], "input_file")
        self.assertEqual(file_part["filename"], "cv.pdf")

    def test_anthropic_provider_extracts_text_blocks(self):
        create = FakeCreate(
            SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="first"),
                    SimpleNamespace(type="tool_use", text="ignored"),
                    SimpleNamespace(type="text", text="second"),
                ]
            )
        )
        client = SimpleNamespace(messages=create)
        settings = AppSettings(
            provider="anthropic",
            model="claude-sonnet-5",
            api_key="test-key",
        )

        result = AnthropicProvider(settings, client).complete("system", "user", 100)

        self.assertEqual(result, "first\nsecond")
        self.assertEqual(create.calls[0]["model"], "claude-sonnet-5")

    def test_json_call_repairs_once(self):
        responses = iter(["not-json", '{"ok": true}'])
        prompts = []

        def fake_call(system_prompt, user_content, max_tokens):
            prompts.append(system_prompt)
            return next(responses)

        result = call_json("schema", "payload", 100, model_call=fake_call)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(prompts), 2)
        self.assertIn("previous response was not valid JSON", prompts[1])


if __name__ == "__main__":
    unittest.main()
