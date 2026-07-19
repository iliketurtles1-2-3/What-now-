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
        "File",
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

    def test_build_cv_content_short_text_plus_valid_pdf_extracts_text(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "cv.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsynthetic test pdf\n")

            with patch.object(app, "extract_pdf_text", return_value="Extracted CV text " * 30):
                content = app.build_cv_content(str(pdf_path), "short")

        self.assertIsInstance(content, str)
        self.assertTrue(content.startswith("Analyze this extracted PDF CV text:"))
        self.assertIn("Extracted CV text", content)

    def test_build_cv_content_long_text_is_accepted(self):
        cv_text = "Senior analyst with Python, SQL, stakeholder management, and reporting experience. " * 8

        content = app.build_cv_content(None, cv_text)

        self.assertTrue(content.startswith("Analyze this pasted CV:"))
        self.assertIn("Senior analyst", content)

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

    def test_unverified_model_courses_are_removed_when_catalog_has_no_match(self):
        report = {
            "gaps": [{"gap": "Quantum portfolio optimization", "priority": 1}],
            "resources": [
                {
                    "gap": "Quantum portfolio optimization",
                    "free": [{"name": "Invented model course"}],
                    "paid": [],
                }
            ],
        }

        result = app.apply_verified_courses(
            report,
            learning_budget="0 EUR (free only)",
            time_budget="< 2 hours/week",
            adaptation="Optimize - I want to stay in my role and use AI better",
        )

        self.assertEqual(result["resources"], [])
        self.assertEqual(
            result["course_fallbacks"][0]["gap"],
            "Quantum portfolio optimization",
        )

    def test_verified_course_resources_keep_original_gap_label(self):
        resources, _ = app.verified_course_resources(
            [{"gap": "Prompt Engineering", "priority": 1}],
            learning_budget="0 EUR (free only)",
            time_budget="2-5 hours/week",
            adaptation="Optimize - I want to stay in my role and use AI better",
        )

        self.assertTrue(resources)
        self.assertEqual(resources[0]["gap"], "Prompt Engineering")

    def test_sidebar_courses_use_catalog_and_discovery_note_is_honest(self):
        suggestions = app.course_suggestions(
            {"skills": ["prompt engineering"], "current_role": "Coordinator"}
        )

        self.assertTrue(suggestions)
        self.assertTrue(all(item["url"].startswith("https://") for item in suggestions))
        sidebar = app.sidebar_html({"current_role": "Coordinator", "skills": []}, {})
        self.assertIn("verified local course catalog", sidebar)
        if not (app.TAVILY_API_KEY or app.SERPAPI_API_KEY):
            self.assertIn("web search not configured", sidebar)

    def test_sidebar_includes_broader_discovery_categories(self):
        sidebar = app.sidebar_html(
            {"current_role": "Coordinator", "skills": ["stakeholder management"]},
            {
                "companies": [{"name": "Climate Co", "why": "Builds grid software"}],
                "jobs": [{"title": "Partnerships Associate", "why": "Berlin"}],
                "courses": [{"name": "Negotiation", "why": "Gap fit"}],
                "events": [{"name": "Energy Meetup", "why": "Meet operators"}],
                "people": [{"name": "Operator newsletter", "why": "Practical examples"}],
                "books": [{"name": "The Mom Test", "why": "Customer discovery"}],
                "projects": [{"name": "Proof project", "why": "Show judgment"}],
            },
        )

        self.assertIn("Companies to inspect", sidebar)
        self.assertIn("Specific openings", sidebar)
        self.assertIn("Rooms to enter", sidebar)
        self.assertIn("People to learn from", sidebar)
        self.assertIn("Reading path", sidebar)
        self.assertIn("Proof work", sidebar)

    def test_workspace_context_uses_interview_and_generated_gaps(self):
        query = app.workspace_search_context(
            {"current_role": "Marketing Manager", "industry": "Cleantech", "skills": ["partnerships"]},
            {"adaptation_level": "Develop", "trigger": "find climate roles"},
            {"gaps": [{"gap": "commercial strategy"}]},
        )

        self.assertIn("Marketing Manager", query)
        self.assertIn("find climate roles", query)
        self.assertIn("commercial strategy", query)

    def test_workspace_renderer_uses_interactive_sections_not_markdown_document(self):
        html = app.render_workspace_html(
            {
                "exposure": [{"task": "Reporting", "rating": "red", "reasoning": "Repeatable analysis"}],
                "exposure_summary": "Reporting can be partly automated.",
                "gaps": [{"gap": "Workflow design", "priority": 1, "why_it_matters": "Turns tools into leverage."}],
                "plan_100": [{"weeks": "Weeks 1-2", "focus": "Map work", "actions": ["Interview users"], "outcome": "A task map"}],
                "plan_365": [{"quarter": "Q1", "theme": "Build proof", "milestones": ["Prototype"]}],
                "decision_gates": [{"when": "Day 30", "question": "Is it useful?", "if_yes": "Scale", "if_no": "Narrow"}],
                "resources": [],
                "repositioning": {"cv_bullets": ["Built AI-assisted reporting flow"], "linkedin_headline": "AI workflow builder"},
                "closing_note": "Keep it specific.",
            }
        )

        self.assertIn('class="cn-workspace"', html)
        self.assertIn('class="cn-window-board"', html)
        self.assertIn("<details", html)
        self.assertIn("Workflow design", html)
        self.assertIn("What to challenge next", html)
        self.assertNotIn("# AI Career Workspace", html)

    def test_header_surfaces_settings_account_and_search_status(self):
        html = app.app_header_html()

        self.assertIn("Settings", html)
        self.assertIn("Local", html)
        self.assertIn(app.search_status_label(), html)


if __name__ == "__main__":
    unittest.main()
