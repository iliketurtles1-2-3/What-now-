from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REQUIRED_FIELDS = {
    "id": str,
    "title": str,
    "provider": str,
    "url": str,
    "skills": list,
    "level": str,
    "format": str,
    "cost_type": str,
    "cost_note": str,
    "time_hours": (int, float),
    "language": str,
    "last_verified": str,
}

VALID_LEVELS = {"beginner", "intermediate", "advanced"}
VALID_COST_TYPES = {"free", "audit_free", "subscription", "paid"}
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
SPACE_PATTERN = re.compile(r"\s+")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_catalog(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_text(value: str) -> str:
    return SPACE_PATTERN.sub(" ", unescape(value)).strip().lower()


def title_similarity(catalog_title: str, page_title: str) -> float:
    catalog_words = set(re.findall(r"[a-z0-9]+", normalize_text(catalog_title)))
    page_words = set(re.findall(r"[a-z0-9]+", normalize_text(page_title)))
    if not catalog_words or not page_words:
        return 0.0
    return len(catalog_words & page_words) / len(catalog_words)


def extract_title(html: bytes, content_type: str = "") -> str | None:
    encoding = "utf-8"
    match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    if match:
        encoding = match.group(1)
    text = html.decode(encoding, errors="replace")
    title_match = TITLE_PATTERN.search(text)
    if not title_match:
        return None
    return SPACE_PATTERN.sub(" ", unescape(title_match.group(1))).strip()


def is_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_entry_schema(entry: Any, index: int) -> dict[str, Any]:
    result = {
        "index": index,
        "id": entry.get("id") if isinstance(entry, dict) else None,
        "valid": True,
        "errors": [],
        "warnings": [],
    }
    if not isinstance(entry, dict):
        result["valid"] = False
        result["errors"].append("entry must be an object")
        return result

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in entry:
            result["errors"].append(f"missing required field: {field}")
            continue
        value = entry[field]
        if not isinstance(value, expected_type):
            result["errors"].append(f"field has wrong type: {field}")
            continue
        if isinstance(value, str) and not value.strip():
            result["errors"].append(f"field is empty: {field}")

    if "url" in entry and isinstance(entry["url"], str) and not is_https_url(entry["url"]):
        result["errors"].append("url must be HTTPS")
    if isinstance(entry.get("skills"), list) and not entry["skills"]:
        result["errors"].append("skills must not be empty")
    if isinstance(entry.get("skills"), list) and not all(isinstance(skill, str) and skill.strip() for skill in entry["skills"]):
        result["errors"].append("skills must contain non-empty strings")
    if isinstance(entry.get("level"), str) and entry["level"] not in VALID_LEVELS:
        result["errors"].append("level is not recognized")
    if isinstance(entry.get("cost_type"), str) and entry["cost_type"] not in VALID_COST_TYPES:
        result["errors"].append("cost_type is not recognized")
    if isinstance(entry.get("time_hours"), (int, float)) and entry["time_hours"] <= 0:
        result["errors"].append("time_hours must be positive")
    if isinstance(entry.get("last_verified"), str) and not DATE_PATTERN.match(entry["last_verified"]):
        result["errors"].append("last_verified must use YYYY-MM-DD")

    result["valid"] = not result["errors"]
    return result


def fetch_url(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "ai-career-catalog-verifier/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(262_144)
        headers = response.headers
        return {
            "status": getattr(response, "status", response.getcode()),
            "final_url": response.geturl(),
            "title": extract_title(body, headers.get("Content-Type", "")),
        }


def validate_entry_http(entry: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = entry.get("url", "")
    result = {
        "status": None,
        "final_url": None,
        "redirected": False,
        "page_title": None,
        "title_similarity": None,
        "errors": [],
        "warnings": [],
    }
    try:
        fetched = fetch_url(url, timeout)
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        result["errors"].append(f"http error: {exc.code}")
        return result
    except urllib.error.URLError as exc:
        result["errors"].append(f"url error: {exc.reason}")
        return result
    except TimeoutError:
        result["errors"].append("request timed out")
        return result

    result["status"] = fetched["status"]
    result["final_url"] = fetched["final_url"]
    result["page_title"] = fetched["title"]
    result["redirected"] = fetched["final_url"] != url
    if not (200 <= int(fetched["status"]) < 400):
        result["errors"].append(f"unexpected HTTP status: {fetched['status']}")

    page_title = fetched.get("title")
    if not page_title:
        result["warnings"].append("page title not found")
        return result

    similarity = title_similarity(entry.get("title", ""), page_title)
    result["title_similarity"] = round(similarity, 3)
    if similarity < 0.5:
        result["warnings"].append("page title differs from catalog title")
    return result


def verify_catalog(catalog_path: Path, offline: bool = False, timeout: float = 10.0) -> dict[str, Any]:
    report = {
        "catalog_path": str(catalog_path),
        "offline": offline,
        "valid": True,
        "summary": {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "warnings": 0,
        },
        "entries": [],
        "errors": [],
    }
    try:
        catalog = load_catalog(catalog_path)
    except (OSError, json.JSONDecodeError) as exc:
        report["valid"] = False
        report["errors"].append(str(exc))
        return report

    if not isinstance(catalog, list):
        report["valid"] = False
        report["errors"].append("catalog root must be a list")
        return report

    seen_ids = set()
    for index, entry in enumerate(catalog):
        entry_report = validate_entry_schema(entry, index)
        if entry_report["id"] in seen_ids:
            entry_report["errors"].append("duplicate id")
            entry_report["valid"] = False
        if entry_report["id"]:
            seen_ids.add(entry_report["id"])

        if entry_report["valid"] and not offline:
            http_report = validate_entry_http(entry, timeout)
            entry_report["http"] = http_report
            entry_report["warnings"].extend(http_report["warnings"])
            if http_report["errors"]:
                entry_report["errors"].extend(http_report["errors"])
                entry_report["valid"] = False

        report["entries"].append(entry_report)

    report["summary"]["total"] = len(report["entries"])
    report["summary"]["valid"] = sum(1 for entry in report["entries"] if entry["valid"])
    report["summary"]["invalid"] = report["summary"]["total"] - report["summary"]["valid"]
    report["summary"]["warnings"] = sum(len(entry["warnings"]) for entry in report["entries"])
    report["valid"] = report["summary"]["invalid"] == 0 and not report["errors"]
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the course catalog.")
    parser.add_argument(
        "catalog",
        nargs="?",
        default="courses/catalog.json",
        help="Path to courses/catalog.json",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run schema and HTTPS URL validation only.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds for online validation.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = verify_catalog(Path(args.catalog), offline=args.offline, timeout=args.timeout)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
