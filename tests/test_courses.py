import json
from pathlib import Path

from courses.matcher import load_catalog, match_courses


def test_catalog_contains_required_verified_course_fields():
    catalog = load_catalog()

    assert 20 <= len(catalog) <= 30
    for course in catalog:
        assert course["url"].startswith("https://")
        assert course["skills"]
        assert course["level"] in {"beginner", "intermediate", "advanced"}
        assert course["cost_type"] in {"free", "audit_free", "subscription", "paid"}
        assert isinstance(course["time_hours"], int | float)
        assert course["language"] == "English"
        assert course["last_verified"] == "2026-07-19"


def test_catalog_json_is_plain_list_for_app_loading():
    catalog_path = Path("courses/catalog.json")
    raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert isinstance(raw_catalog, list)
    assert all("id" in course for course in raw_catalog)


def test_zero_budget_only_returns_free_compatible_courses():
    result = match_courses(
        ["prompt engineering", "generative ai"],
        budget=0,
        time_hours=10,
        level="beginner",
    )

    assert result["recommendations"]
    assert {
        item["course"]["cost_type"]
        for item in result["recommendations"]
    } <= {"free", "audit_free"}


def test_ranking_prioritizes_earlier_skill_gaps():
    result = match_courses(
        ["prompt engineering", "data visualization"],
        budget=0,
        time_hours=10,
        level="beginner",
        limit=3,
    )

    top = result["recommendations"][0]
    assert "prompt engineering" in top["matched_gaps"]


def test_time_budget_filters_long_courses():
    result = match_courses(
        ["python", "machine learning"],
        budget=0,
        time_hours=4,
        level="beginner",
    )

    assert result["recommendations"]
    assert all(item["course"]["time_hours"] <= 4 for item in result["recommendations"])


def test_fallback_search_phrase_for_unmatched_gap():
    result = match_courses(
        ["quantum portfolio optimization"],
        budget=0,
        time_hours=2,
        language="English",
        level="beginner",
    )

    assert result["recommendations"] == []
    assert result["fallbacks"] == [
        {
            "gap": "quantum portfolio optimization",
            "search_phrase": "quantum portfolio optimization course beginner English free",
        }
    ]

