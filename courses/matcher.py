from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CATALOG_PATH = Path(__file__).with_name("catalog.json")
FREE_COMPATIBLE_COSTS = {"free", "audit_free"}
VALID_COST_TYPES = FREE_COMPATIBLE_COSTS | {"subscription", "paid"}
LEVEL_ORDER = {"beginner": 0, "intermediate": 1, "advanced": 2}
DEFAULT_LANGUAGE = "English"


@dataclass(frozen=True)
class MatchConstraints:
    max_budget_eur: float | None = None
    max_time_hours: float | None = None
    language: str = DEFAULT_LANGUAGE
    level: str | None = None


def load_catalog(path: str | Path = CATALOG_PATH) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as catalog_file:
        courses = json.load(catalog_file)
    if not isinstance(courses, list):
        raise ValueError("Course catalog must be a list.")
    for course in courses:
        validate_course(course)
    return courses


def validate_course(course: dict[str, Any]) -> None:
    required = {
        "id",
        "title",
        "provider",
        "url",
        "skills",
        "level",
        "format",
        "cost_type",
        "cost_note",
        "cost_eur",
        "time_hours",
        "language",
        "last_verified",
    }
    missing = sorted(required - set(course))
    if missing:
        raise ValueError(f"Course {course.get('id', '<unknown>')} misses fields: {', '.join(missing)}")
    if not str(course["url"]).startswith("https://"):
        raise ValueError(f"Course {course['id']} must use a verified HTTPS URL.")
    if course["level"] not in LEVEL_ORDER:
        raise ValueError(f"Course {course['id']} has unsupported level: {course['level']}")
    if course["cost_type"] not in VALID_COST_TYPES:
        raise ValueError(f"Course {course['id']} has unsupported cost_type: {course['cost_type']}")
    if not isinstance(course["skills"], list) or not course["skills"]:
        raise ValueError(f"Course {course['id']} must contain at least one skill.")
    cost_eur = course["cost_eur"]
    if cost_eur is not None and (
        not isinstance(cost_eur, int | float) or isinstance(cost_eur, bool) or cost_eur < 0
    ):
        raise ValueError(f"Course {course['id']} must use a non-negative numeric cost_eur or null.")
    if course["cost_type"] in FREE_COMPATIBLE_COSTS and cost_eur != 0:
        raise ValueError(f"Course {course['id']} must use cost_eur 0 for free-compatible access.")
    if (
        not isinstance(course["time_hours"], int | float)
        or isinstance(course["time_hours"], bool)
        or course["time_hours"] <= 0
    ):
        raise ValueError(f"Course {course['id']} must use positive numeric time_hours.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(course["last_verified"])):
        raise ValueError(f"Course {course['id']} must use YYYY-MM-DD last_verified.")


def match_courses(
    skill_gaps: Iterable[str | dict[str, Any]],
    *,
    budget: str | float | int | None = None,
    time_hours: float | int | None = None,
    language: str = DEFAULT_LANGUAGE,
    level: str | None = None,
    catalog: list[dict[str, Any]] | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    gaps = normalize_gaps(skill_gaps)
    constraints = MatchConstraints(
        max_budget_eur=parse_budget(budget),
        max_time_hours=float(time_hours) if time_hours is not None else None,
        language=language,
        level=normalize_text(level) if level else None,
    )
    courses = catalog if catalog is not None else load_catalog()
    eligible = [course for course in courses if course_fits_constraints(course, constraints)]

    recommendations = []
    covered_gaps: set[str] = set()
    for course in eligible:
        score, matched_gaps, reasons = score_course(course, gaps, constraints)
        if score <= 0:
            continue
        covered_gaps.update(matched_gaps)
        recommendations.append(
            {
                "course": course,
                "score": round(score, 3),
                "matched_gaps": matched_gaps,
                "matched_gap_labels": [
                    gap["label"] for gap in gaps if gap["id"] in matched_gaps
                ],
                "why": reasons,
            }
        )

    recommendations.sort(
        key=lambda item: (
            -item["score"],
            item["course"]["time_hours"],
            LEVEL_ORDER[item["course"]["level"]],
            item["course"]["title"].lower(),
        )
    )
    selected = recommendations[:limit]
    selected_gap_ids = {gap for item in selected for gap in item["matched_gaps"]}

    return {
        "recommendations": selected,
        "fallbacks": [
            fallback_for_gap(gap["label"], constraints)
            for gap in gaps
            if gap["id"] not in selected_gap_ids
        ],
    }


def normalize_gaps(skill_gaps: Iterable[str | dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, gap in enumerate(skill_gaps):
        if isinstance(gap, dict):
            label = str(gap.get("gap") or gap.get("skill") or gap.get("name") or "").strip()
            priority = int(gap.get("priority", index + 1))
        else:
            label = str(gap).strip()
            priority = index + 1
        if not label:
            continue
        normalized.append(
            {
                "id": normalize_text(label),
                "label": label,
                "tokens": tokenize(label),
                "priority": max(priority, 1),
            }
        )
    return normalized


def parse_budget(budget: str | float | int | None) -> float | None:
    if budget is None:
        return None
    if isinstance(budget, int | float):
        return float(budget)
    clean = budget.strip().lower()
    if clean in {"", "unknown", "any", "unlimited"}:
        return None
    if re.search(r"\b(over|above|more than)\b", clean):
        return None
    if "free" in clean or clean.startswith("0"):
        return 0.0
    numbers = re.findall(r"\d+(?:[.,]\d+)?", clean)
    if not numbers:
        return None
    return float(numbers[-1].replace(",", "."))


def course_fits_constraints(course: dict[str, Any], constraints: MatchConstraints) -> bool:
    if constraints.language and normalize_text(course["language"]) != normalize_text(constraints.language):
        return False
    if constraints.max_time_hours is not None and float(course["time_hours"]) > constraints.max_time_hours:
        return False
    if constraints.max_budget_eur is not None:
        cost_eur = course.get("cost_eur")
        if cost_eur is None or float(cost_eur) > constraints.max_budget_eur:
            return False
    if constraints.level and not level_is_suitable(course["level"], constraints.level):
        return False
    return True


def score_course(
    course: dict[str, Any],
    gaps: list[dict[str, Any]],
    constraints: MatchConstraints,
) -> tuple[float, list[str], list[str]]:
    course_skills = [normalize_text(skill) for skill in course["skills"]]
    course_tokens = set().union(*(tokenize(skill) for skill in course["skills"]))
    matched_gaps = []
    matched_labels = []
    score = 0.0

    for gap in gaps:
        exact = gap["id"] in course_skills
        token_overlap = len(gap["tokens"] & course_tokens)
        if not exact and token_overlap == 0:
            continue
        matched_gaps.append(gap["id"])
        matched_labels.append(gap["label"])
        priority_weight = 1 / gap["priority"]
        score += 8 * priority_weight if exact else 3 * token_overlap * priority_weight

    reasons = []
    if matched_gaps:
        reasons.append("Addresses prioritized skill gap: " + ", ".join(matched_labels))
    else:
        return 0.0, [], []
    if constraints.max_time_hours is not None:
        time_fit = max(constraints.max_time_hours - float(course["time_hours"]), 0)
        score += min(time_fit / max(constraints.max_time_hours, 1), 1.0)
        reasons.append(f"Fits within {constraints.max_time_hours:g} available hours")
    if constraints.max_budget_eur is not None:
        score += 1.5
        if constraints.max_budget_eur == 0:
            reasons.append("Fits a zero-budget constraint")
        else:
            reasons.append(f"Fits within a {constraints.max_budget_eur:g} EUR budget")
    elif course["cost_type"] in FREE_COMPATIBLE_COSTS:
        score += 0.5
    if constraints.level and course["level"] == constraints.level:
        score += 1.0
        reasons.append(f"Matches requested {constraints.level} level")
    elif constraints.level and level_is_suitable(course["level"], constraints.level):
        score += 0.25
    return score, matched_gaps, reasons


def level_is_suitable(course_level: str, requested_level: str) -> bool:
    return LEVEL_ORDER[course_level] <= LEVEL_ORDER[requested_level]


def fallback_for_gap(gap: str, constraints: MatchConstraints) -> dict[str, str]:
    parts = [gap, "course"]
    if constraints.level:
        parts.append(constraints.level)
    if constraints.language:
        parts.append(constraints.language)
    if constraints.max_budget_eur == 0:
        parts.append("free")
    elif constraints.max_budget_eur is not None:
        parts.append(f"under {constraints.max_budget_eur:g} EUR")
    return {
        "gap": gap,
        "search_phrase": " ".join(parts),
    }


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def tokenize(value: str) -> set[str]:
    stopwords = {"and", "for", "with", "the", "to", "of", "in", "a", "an", "basics", "fundamentals"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalize_text(value))
        if token not in stopwords
    }
