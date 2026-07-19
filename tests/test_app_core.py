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

    def test_learning_resources_are_search_tasks_without_catalog(self):
        suggestions = app.learning_resource_suggestions(
            {"skills": ["prompt engineering"], "current_role": "Coordinator"}
        )

        self.assertTrue(suggestions)
        self.assertTrue(any("YouTube" in item["name"] for item in suggestions))
        self.assertTrue(any("GitHub" in item["name"] for item in suggestions))
        self.assertTrue(all(item["source"] == "Queued" for item in suggestions))
        sidebar = app.sidebar_html({"current_role": "Coordinator", "skills": []}, {})
        self.assertIn("Dynamic search across courses, YouTube, GitHub, books, events, and communities", sidebar)
        if not (app.TAVILY_API_KEY or app.SERPAPI_API_KEY):
            self.assertIn("web search not configured", sidebar)

    def test_sidebar_includes_broader_discovery_categories(self):
        sidebar = app.sidebar_html(
            {"current_role": "Coordinator", "skills": ["stakeholder management"]},
            {
                "research_tasks": [
                    {
                        "perspective": "Climate partnerships operator",
                        "area": "Companies",
                        "question": "Which organizations could plausibly hire this person?",
                        "evidence_target": "Company, fit angle, risk, source.",
                        "status": "researched",
                        "findings": [{"name": "Climate Co", "url": "https://example.com"}],
                    }
                ],
                "companies": [{"name": "Climate Co", "why": "Builds grid software"}],
                "jobs": [{"title": "Partnerships Associate", "why": "Berlin"}],
                "courses": [{"name": "Negotiation", "why": "Gap fit"}],
                "events": [{"name": "Energy Meetup", "why": "Meet operators"}],
                "people": [{"name": "Operator newsletter", "why": "Practical examples"}],
                "books": [{"name": "The Mom Test", "why": "Customer discovery"}],
                "projects": [{"name": "Proof project", "why": "Show judgment"}],
            },
        )

        self.assertIn("Research queue", sidebar)
        self.assertIn("Evidence to collect", sidebar)
        self.assertIn("Climate partnerships operator", sidebar)
        self.assertIn("Companies to inspect", sidebar)
        self.assertIn("Specific openings", sidebar)
        self.assertIn("Resource search", sidebar)
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

    def test_workspace_context_uses_perspective_search_terms(self):
        query = app.workspace_search_context(
            {"current_role": "Business Development Working Student", "industry": "Cleantech", "skills": ["sales"]},
            {"adaptation_level": "Develop", "trigger": "find better target companies"},
            {
                "perspectives": [
                    {
                        "name": "Climate partnerships operator",
                        "target_roles": ["Partnerships Associate", "Ecosystem Manager"],
                        "company_profile": "B2B climate software companies selling to energy teams",
                        "search_terms": ["climate partnerships jobs", "energy transition ecosystem roles"],
                    }
                ],
                "gaps": [{"gap": "commercial discovery"}],
            },
        )

        self.assertIn("Climate partnerships operator", query)
        self.assertIn("Partnerships Associate", query)
        self.assertIn("climate partnerships jobs", query)

    def test_research_tasks_are_built_from_perspectives(self):
        tasks = app.build_research_tasks(
            {"current_role": "Radiologic Technologist", "industry": "Healthcare", "skills": ["MRI"]},
            {"adaptation_level": "Develop", "trigger": "move toward healthtech"},
            {
                "perspectives": [
                    {
                        "name": "Radiology workflow specialist",
                        "target_roles": ["Clinical Application Specialist"],
                        "company_profile": "medical imaging software companies",
                        "search_terms": ["radiology workflow jobs"],
                    }
                ]
            },
        )

        self.assertGreaterEqual(len(tasks), 5)
        self.assertTrue(all(task["perspective"] == "Radiology workflow specialist" for task in tasks))
        self.assertIn("Companies", {task["area"] for task in tasks})
        self.assertIn("Specific roles", {task["area"] for task in tasks})
        self.assertIn("medical imaging software companies", tasks[0]["query"])

    def test_research_task_rows_render_findings_and_evidence_target(self):
        html = app.research_task_rows(
            [
                {
                    "perspective": "Radiology workflow specialist",
                    "area": "Specific roles",
                    "question": "Which current openings fit?",
                    "evidence_target": "Role, company, application angle.",
                    "status": "researched",
                    "findings": [{"name": "Clinical Application Specialist", "url": "https://example.com/job"}],
                }
            ],
            "empty",
        )

        self.assertIn("Radiology workflow specialist", html)
        self.assertIn("Role, company, application angle.", html)
        self.assertIn('href="https://example.com/job"', html)

    def test_pending_sidebar_pauses_discovery_before_perspective(self):
        sidebar = app.pending_sidebar_html(
            {"current_role": "Coordinator", "industry": "Energy", "skills": ["stakeholder management"]}
        )

        self.assertIn("SEARCH PAUSED", sidebar)
        self.assertIn("Pick a perspective first", sidebar)
        self.assertNotIn("Specific openings", sidebar)

    def test_dashboard_asks_profile_specific_drilldown_questions(self):
        html = app.dashboard_left_html(
            {
                "current_role": "Business Development Working Student",
                "industry": "Cleantech",
                "skills": ["market research"],
                "roles": [{"key_tasks": ["founder support"]}],
            },
            ["You connect partnerships and research."],
            "Profile from your CV",
        )

        self.assertIn('class="cn-layer-stack"', html)
        self.assertIn("Profile understanding", html)
        self.assertIn("What I understood before asking more", html)
        self.assertIn("Strong evidence", html)
        self.assertIn("Unclear", html)
        self.assertIn("Questions that matter", html)
        self.assertIn("<details", html)
        self.assertIn("Questions to answer before discovery", html)
        self.assertIn("Next: answer the short interview below", html)
        self.assertIn("founder support", html)
        self.assertIn("Cleantech", html)

    def test_profile_understanding_flags_missing_confidence_inputs(self):
        understanding = app.profile_understanding({"current_role": "Analyst"})

        self.assertIn("Target industry needs confirmation.", understanding["unclear"])
        self.assertIn("Skill strengths need confirmation.", understanding["unclear"])
        self.assertTrue(any("AI/tool usage" in item for item in understanding["unclear"]))
        self.assertTrue(any("Current role: Analyst" in item for item in understanding["detected"]))

    def test_create_report_requires_and_passes_clarifying_answers(self):
        profile = {
            "current_role": "Radiologic Technologist",
            "industry": "Healthcare",
            "skills": ["MRI"],
            "roles": [{"key_tasks": ["perform MRI exams"]}],
        }
        first_attempt = app.create_report(
            profile,
            app.ADAPTATION_OPTIONS[1],
            app.TIME_OPTIONS[1],
            app.BUDGET_OPTIONS[0],
            "",
            "",
            "",
            "",
            "",
        )
        self.assertIn("profile-specific", first_attempt[-1])

        captured_payload = {}

        def fake_call_json(system_prompt, user_content, max_tokens):
            captured_payload["content"] = user_content
            return {
                "perspectives": [],
                "exposure": [],
                "exposure_summary": "",
                "gaps": [],
                "plan_100": [],
                "plan_365": [],
                "decision_gates": [],
                "resources": [],
                "repositioning": {"cv_bullets": [], "linkedin_headline": ""},
                "closing_note": "",
            }

        with patch.object(app, "call_json", fake_call_json), patch.object(app, "live_discovery", return_value={}), patch.object(
            app, "write_report_file", return_value="report.md"
        ):
            app.create_report(
                profile,
                app.ADAPTATION_OPTIONS[1],
                app.TIME_OPTIONS[1],
                app.BUDGET_OPTIONS[0],
                "I need a move.",
                "more patient-facing advisory work",
                "",
                "healthtech operations",
                "",
            )

        self.assertIn("clarifying_answers", captured_payload["content"])
        self.assertIn("more patient-facing advisory work", captured_payload["content"])
        self.assertIn("healthtech operations", captured_payload["content"])

    def test_workspace_renderer_uses_interactive_sections_not_markdown_document(self):
        html = app.render_workspace_html(
            {
                "perspectives": [
                    {
                        "name": "Climate partnerships operator",
                        "target_roles": ["Partnerships Associate"],
                        "company_profile": "B2B climate companies",
                        "why_it_fits": "Uses research and stakeholder work.",
                        "risks": "Needs clearer commercial proof.",
                        "search_terms": ["climate partnerships"],
                    }
                ],
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
        self.assertIn('class="cn-tab-panels"', html)
        self.assertIn('type="radio"', html)
        self.assertIn('for="cn-tab-perspectives"', html)
        self.assertIn("<details", html)
        self.assertIn("Directions to test first", html)
        self.assertIn("Climate partnerships operator", html)
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
