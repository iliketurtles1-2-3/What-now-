import json
import unittest
from pathlib import Path

from courses.matcher import load_catalog, match_courses


class CourseMatcherTests(unittest.TestCase):
    def test_catalog_contains_required_verified_course_fields(self):
        catalog = load_catalog()

        self.assertTrue(20 <= len(catalog) <= 30)
        for course in catalog:
            self.assertTrue(course["url"].startswith("https://"))
            self.assertTrue(course["skills"])
            self.assertIn(course["level"], {"beginner", "intermediate", "advanced"})
            self.assertIn(
                course["cost_type"],
                {"free", "audit_free", "subscription", "paid"},
            )
            self.assertIsInstance(course["time_hours"], int | float)
            self.assertEqual(course["language"], "English")
            self.assertEqual(course["last_verified"], "2026-07-19")

    def test_catalog_json_is_plain_list_for_app_loading(self):
        catalog_path = Path(__file__).parents[1] / "courses" / "catalog.json"
        raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

        self.assertIsInstance(raw_catalog, list)
        self.assertTrue(all("id" in course for course in raw_catalog))

    def test_zero_budget_only_returns_free_compatible_courses(self):
        result = match_courses(
            ["prompt engineering", "generative ai"],
            budget=0,
            time_hours=10,
            level="beginner",
        )

        self.assertTrue(result["recommendations"])
        self.assertLessEqual(
            {
                item["course"]["cost_type"]
                for item in result["recommendations"]
            },
            {"free", "audit_free"},
        )

    def test_ranking_prioritizes_earlier_skill_gaps(self):
        result = match_courses(
            ["prompt engineering", "data visualization"],
            budget=0,
            time_hours=10,
            level="beginner",
            limit=3,
        )

        top = result["recommendations"][0]
        self.assertIn("prompt engineering", top["matched_gaps"])

    def test_time_budget_filters_long_courses(self):
        result = match_courses(
            ["python", "machine learning"],
            budget=0,
            time_hours=4,
            level="beginner",
        )

        self.assertTrue(result["recommendations"])
        self.assertTrue(
            all(
                item["course"]["time_hours"] <= 4
                for item in result["recommendations"]
            )
        )

    def test_fallback_search_phrase_for_unmatched_gap(self):
        result = match_courses(
            ["quantum portfolio optimization"],
            budget=0,
            time_hours=2,
            language="English",
            level="beginner",
        )

        self.assertEqual(result["recommendations"], [])
        self.assertEqual(
            result["fallbacks"],
            [
                {
                    "gap": "quantum portfolio optimization",
                    "search_phrase": (
                        "quantum portfolio optimization course beginner English free"
                    ),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()

