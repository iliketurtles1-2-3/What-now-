import importlib.util
import sys
import types
import unittest
from unittest.mock import patch


def install_gradio_stub_if_needed():
    if importlib.util.find_spec("gradio") is not None:
        return

    class Component:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def click(self, *args, **kwargs):
            return Event()

    class Event:
        def then(self, *args, **kwargs):
            return self

    gradio = types.ModuleType("gradio")
    for name in [
        "Blocks",
        "Column",
        "Row",
        "State",
        "Markdown",
        "Textbox",
        "UploadButton",
        "Button",
        "HTML",
        "Radio",
        "DownloadButton",
    ]:
        setattr(gradio, name, Component)
    gradio.update = lambda **kwargs: kwargs
    sys.modules["gradio"] = gradio


install_gradio_stub_if_needed()
import app


class AppCoreTests(unittest.TestCase):
    def test_build_cv_content_short_text_alone_fails(self):
        with self.assertRaisesRegex(ValueError, app.CV_ERROR):
            app.build_cv_content(None, "too short")

    def test_build_cv_content_short_text_plus_valid_pdf_uses_pdf(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "cv.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsynthetic test pdf\n")

            content = app.build_cv_content(str(pdf_path), "short")

        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "document")
        self.assertEqual(content[0]["source"]["media_type"], "application/pdf")

    def test_build_cv_content_long_text_is_accepted(self):
        cv_text = "Senior analyst with Python, SQL, stakeholder management, and reporting experience. " * 8

        content = app.build_cv_content(None, cv_text)

        self.assertTrue(content.startswith("Analyze this pasted CV:"))
        self.assertIn("Senior analyst", content)

    def test_enforce_budget_rules_zero_eur_removes_paid_resources(self):
        report = {
            "resources": [
                {
                    "gap": "Prompt engineering",
                    "free": [{"name": "Free option"}],
                    "paid": [{"name": "Paid option"}],
                }
            ]
        }

        result = app.enforce_budget_rules(report, "0 EUR (free only)")

        self.assertEqual(result["resources"][0]["paid"], [])

    def test_discovery_rows_links_http_urls_only(self):
        html = app.discovery_rows(
            [
                {"title": "Safe", "why": "https link", "url": "https://example.com", "source": "Test"},
                {"title": "Also safe", "why": "http link", "url": "http://example.com", "source": "Test"},
                {"title": "Unsafe", "why": "script link", "url": "javascript:alert(1)", "source": "Test"},
            ],
            "title",
            "why",
            "empty",
        )

        self.assertIn('href="https://example.com"', html)
        self.assertIn('href="http://example.com"', html)
        self.assertNotIn("javascript:alert", html)

    def test_extract_first_json_object_from_wrapped_response(self):
        wrapped = 'Here is the JSON:\n{"profile": {"role": "Analyst"}, "teaser": ["one"]}\nDone.'

        self.assertEqual(
            app.parse_json_response(wrapped),
            {"profile": {"role": "Analyst"}, "teaser": ["one"]},
        )

    def test_call_json_repairs_invalid_first_response(self):
        responses = iter(["not json", '{"ok": true}'])

        def fake_call_model(system_prompt, user_content, max_tokens):
            if "Your previous response was not valid JSON" in system_prompt:
                self.assertEqual(user_content, "payload")
            return next(responses)

        with patch.object(app, "call_model", fake_call_model):
            self.assertEqual(app.call_json("schema prompt", "payload", 100), {"ok": True})


if __name__ == "__main__":
    unittest.main()
