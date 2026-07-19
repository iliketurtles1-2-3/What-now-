import json
import os
import re
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import gradio as gr

from config import ConfigError, load_runtime_settings, load_settings
from courses.matcher import match_courses
from llm import call_json as llm_call_json
from llm import call_model as llm_call_model
from llm import parse_json_response
from prompts import load_prompt


MAX_PDF_BYTES = 10 * 1024 * 1024
CV_ERROR = "I could not read the CV. Please upload a PDF or paste at least 300 characters of CV text."
API_ERROR = "The analysis is not available right now. Please try again in a minute."
CONFIG_ERROR = "The model provider is not configured correctly. Check the exported environment variables."
RUNTIME_SETTINGS = load_runtime_settings()
LIVE_DATA_TIMEOUT = RUNTIME_SETTINGS.live_data_timeout_seconds
ARBEITNOW_BASE_URL = os.getenv("ARBEITNOW_BASE_URL", "https://www.arbeitnow.com/api/job-board-api")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
LIVE_SEARCH_PROVIDER = os.getenv("LIVE_SEARCH_PROVIDER", "tavily" if TAVILY_API_KEY else "serpapi").strip().lower()
APP_NAME = "WTFDID"
APP_FULL_NAME = "What the fuck do I do?"
REPORT_DIR = Path(tempfile.gettempdir()) / "wtfdid-reports"
REPORT_MAX_AGE_SECONDS = 24 * 60 * 60

ADAPTATION_OPTIONS = [
    "Optimize - I want to stay in my role and use AI better",
    "Develop - I am open to a role move in 6-12 months",
    "Reinvent - I am ready for a real pivot",
]
TIME_OPTIONS = ["< 2 hours/week", "2-5 hours/week", "5-10 hours/week", "> 10 hours/week"]
BUDGET_OPTIONS = ["0 EUR (free only)", "up to 50 EUR/month", "over 50 EUR/month"]

PROMPT_1 = load_prompt("profile", "legacy-v1")
PROMPT_2 = load_prompt("strategy", "legacy-v1")


def call_model(system_prompt: str, user_content: Any, max_tokens: int) -> str:
    return llm_call_model(system_prompt, user_content, max_tokens)


def call_json(system_prompt: str, user_content: Any, max_tokens: int) -> dict[str, Any]:
    return llm_call_json(
        system_prompt,
        user_content,
        max_tokens,
        model_call=call_model,
    )


def file_path(uploaded_file: Any) -> str | None:
    if uploaded_file is None:
        return None
    if isinstance(uploaded_file, str):
        return uploaded_file
    return getattr(uploaded_file, "name", None) or getattr(uploaded_file, "path", None)


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages[:20]]
    except (ImportError, Exception) as exc:
        raise ValueError(CV_ERROR) from exc
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    if len(text) < 300:
        raise ValueError(CV_ERROR)
    return text


def build_cv_content(uploaded_file: Any, cv_text: str | None) -> Any:
    text = (cv_text or "").strip()
    path_value = file_path(uploaded_file)

    if text:
        if len(text) < 300:
            if not path_value:
                raise ValueError(CV_ERROR)
        else:
            return f"Analyze this pasted CV:\n\n{text}"

    if not path_value:
        raise ValueError(CV_ERROR)

    path = Path(path_value)
    if path.suffix.lower() != ".pdf" or not path.exists() or path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError(CV_ERROR)

    pdf_text = extract_pdf_text(path)
    return f"Analyze this extracted PDF CV text:\n\n{pdf_text}"


def profile_is_empty(profile: dict[str, Any]) -> bool:
    if not isinstance(profile, dict):
        return True
    meaningful_fields = [
        profile.get("current_role"),
        profile.get("industry"),
        profile.get("roles"),
        profile.get("skills"),
        profile.get("education"),
    ]
    return sum(bool(field) for field in meaningful_fields) < 3


def escape_html(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def request_json(url: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    data = None
    headers = {"Accept": "application/json", "User-Agent": "ai-career-navigator/0.1"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=LIVE_DATA_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def profile_query(profile: dict[str, Any], *, max_skills: int = 3) -> str:
    parts = [
        str(profile.get("current_role") or "").strip(),
        str(profile.get("industry") or "").strip(),
    ]
    parts.extend(str(skill).strip() for skill in (profile.get("skills") or [])[:max_skills])
    return " ".join(part for part in parts if part)


def workspace_search_context(
    profile: dict[str, Any],
    interview: dict[str, Any] | None = None,
    strategy: dict[str, Any] | None = None,
    *,
    max_terms: int = 10,
) -> str:
    terms: list[str] = []
    terms.extend(
        [
            str(profile.get("current_role") or ""),
            str(profile.get("industry") or ""),
            str(profile.get("seniority") or ""),
        ]
    )
    terms.extend(str(skill) for skill in (profile.get("skills") or [])[:5])
    if isinstance(interview, dict):
        terms.extend(
            [
                str(interview.get("adaptation_level") or ""),
                str(interview.get("trigger") or ""),
            ]
        )
    if isinstance(strategy, dict):
        for perspective in strategy.get("perspectives", [])[:3]:
            if not isinstance(perspective, dict):
                continue
            terms.extend(
                [
                    str(perspective.get("name") or ""),
                    str(perspective.get("company_profile") or ""),
                ]
            )
            terms.extend(str(role) for role in perspective.get("target_roles", [])[:3])
            terms.extend(str(term) for term in perspective.get("search_terms", [])[:4])
        for gap in strategy.get("gaps", [])[:4]:
            if isinstance(gap, dict):
                terms.append(str(gap.get("gap") or ""))
        repositioning = strategy.get("repositioning")
        if isinstance(repositioning, dict):
            terms.append(str(repositioning.get("linkedin_headline") or ""))
    cleaned: list[str] = []
    for term in terms:
        term = re.sub(r"\s+", " ", term).strip()
        if term and term not in cleaned:
            cleaned.append(term)
    return " ".join(cleaned[:max_terms])


def result_domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc
    except ValueError:
        return ""
    return host.replace("www.", "")


def keyword_set(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-zÄÖÜäöüß0-9+#.]{3,}", text.lower())}


def search_live_web(query: str, *, topic: str = "general", max_results: int = 3) -> list[dict[str, str]]:
    if not query:
        return []
    if LIVE_SEARCH_PROVIDER == "tavily" and TAVILY_API_KEY:
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "topic": topic,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
        }
        data = request_json("https://api.tavily.com/search", payload=payload)
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "source": "Tavily",
            }
            for item in data.get("results", [])[:max_results]
            if isinstance(item, dict)
        ]
    if SERPAPI_API_KEY:
        params = {
            "engine": "google",
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "num": max_results,
            "hl": "en",
        }
        if topic == "news":
            params["tbm"] = "nws"
        data = request_json("https://serpapi.com/search.json", params=params)
        source_items = data.get("news_results") if topic == "news" else data.get("organic_results")
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", "") or item.get("source", ""),
                "source": "SerpAPI",
            }
            for item in (source_items or [])[:max_results]
            if isinstance(item, dict)
        ]
    return []


def ranked_arbeitnow_jobs(
    profile: dict[str, Any],
    *,
    context_query: str | None = None,
    limit: int = 50,
) -> list[tuple[int, dict[str, Any]]]:
    query = context_query or profile_query(profile, max_skills=2) or str(profile.get("current_role") or "")
    data = request_json(ARBEITNOW_BASE_URL)
    keywords = keyword_set(query)
    ranked_items = []
    for item in data.get("data", [])[:limit]:
        if not isinstance(item, dict):
            continue
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("company_name") or ""),
                str(item.get("location") or ""),
                " ".join(str(tag) for tag in item.get("tags", []) if tag),
            ]
        )
        score = len(keywords & keyword_set(haystack))
        ranked_items.append((score, item))
    ranked_items.sort(key=lambda pair: pair[0], reverse=True)
    return ranked_items


def interesting_companies(
    profile: dict[str, Any],
    arbeitnow_jobs: list[tuple[int, dict[str, Any]]] | None = None,
    *,
    context_query: str | None = None,
) -> list[dict[str, str]]:
    query = (
        f"companies hiring for {context_query or profile_query(profile)} Germany Europe "
        "what the company works on career fit"
    )
    results = search_live_web(query, max_results=3)
    if results:
        return [
            {
                "name": item.get("title") or result_domain(item.get("url", "")),
                "why": item.get("snippet") or item.get("url") or "Company profile from live search",
                "url": item.get("url", ""),
                "source": item.get("source", ""),
            }
            for item in results
            if item.get("title") or item.get("url")
        ]

    companies = []
    seen = set()
    for score, item in (arbeitnow_jobs or []):
        if score == 0:
            break
        company = item.get("company_name", "")
        if not company or company in seen:
            continue
        seen.add(company)
        companies.append(
            {
                "name": company,
                "why": item.get("title", "Relevant live role found"),
                "url": item.get("url", ""),
                "source": "Arbeitnow",
            }
        )
        if len(companies) == 3:
            break
    return companies


def interesting_jobs(
    profile: dict[str, Any],
    arbeitnow_jobs: list[tuple[int, dict[str, Any]]] | None = None,
    *,
    context_query: str | None = None,
) -> list[dict[str, str]]:
    query = context_query or profile_query(profile, max_skills=2) or str(profile.get("current_role") or "")
    jobs: list[dict[str, str]] = []
    for score, item in (arbeitnow_jobs or []):
        if score == 0:
            break
        if not isinstance(item, dict):
            continue
        title = item.get("title", "")
        company = item.get("company_name", "")
        location = item.get("location", "")
        url = item.get("url", "")
        if title:
            jobs.append(
                {
                    "title": title,
                    "why": " · ".join(part for part in [company, location] if part) or "Live job from Arbeitnow",
                    "url": url,
                    "source": "Arbeitnow",
                }
            )
        if len(jobs) == 3:
            break
    if jobs:
        return jobs

    results = search_live_web(f'specific open jobs "{query}" Germany remote Europe', max_results=3)
    return [
        {
            "title": item.get("title") or "Live job result",
            "why": item.get("snippet") or item.get("url") or "Live search result",
            "url": item.get("url", ""),
            "source": item.get("source", ""),
        }
        for item in results
        if item.get("title") or item.get("url")
    ]


def course_suggestions(profile: dict[str, Any], strategy: dict[str, Any] | None = None) -> list[dict[str, str]]:
    targets: Any = profile.get("skills") or []
    if isinstance(strategy, dict) and strategy.get("gaps"):
        targets = strategy.get("gaps")
    result = match_courses(
        targets,
        language="English",
        limit=3,
    )
    return [
        {
            "name": item["course"]["title"],
            "why": "; ".join(item.get("why", [])),
            "url": item["course"]["url"],
            "source": item["course"]["provider"],
        }
        for item in result["recommendations"]
    ]


def project_suggestions(profile: dict[str, Any], strategy: dict[str, Any] | None = None) -> list[dict[str, str]]:
    gaps = strategy.get("gaps", []) if isinstance(strategy, dict) else []
    gap_terms = ", ".join(str(gap.get("gap") or "") for gap in gaps[:3] if isinstance(gap, dict))
    base = workspace_search_context(profile, strategy=strategy)
    suggestions = [
        {
            "name": "Proof project",
            "why": f"Build a small public artifact around {gap_terms or base}: a workflow map, before/after case, or decision aid.",
            "url": "",
            "source": "Workspace",
        },
        {
            "name": "Work sample",
            "why": "Turn one real task from your role into a portfolio-quality example with clear constraints, tradeoffs, and outcome.",
            "url": "",
            "source": "Workspace",
        },
    ]
    return suggestions


def live_resource_search(query: str, label: str) -> list[dict[str, str]]:
    results = search_live_web(query, max_results=3)
    return [
        {
            "name": item.get("title") or result_domain(item.get("url", "")) or label,
            "why": item.get("snippet") or item.get("url") or "Live search result",
            "url": item.get("url", ""),
            "source": item.get("source", ""),
        }
        for item in results
        if item.get("title") or item.get("url")
    ]


def provider_status() -> dict[str, str]:
    try:
        settings = load_settings()
    except ConfigError:
        return {
            "provider": "not configured",
            "model": "missing",
            "model_status": "check settings",
        }
    return {
        "provider": "OpenRouter" if settings.is_openrouter else settings.provider.title(),
        "model": settings.model,
        "model_status": "ready" if settings.api_key else "missing key",
    }


def search_status_label() -> str:
    if TAVILY_API_KEY:
        return "Tavily ready"
    if SERPAPI_API_KEY:
        return "SerpAPI ready"
    return "web search off"


def app_header_html() -> str:
    status = provider_status()
    return f"""
<header class="cn-appbar">
  <div class="cn-brand">
    <div class="cn-logo" aria-hidden="true"><span class="cn-logo-face"></span></div>
    <div>
      <strong>{APP_NAME}</strong>
      <span>{APP_FULL_NAME}</span>
    </div>
  </div>
  <nav class="cn-app-actions" aria-label="Application controls">
    <details class="cn-settings">
      <summary>Settings</summary>
      <div class="cn-settings-panel">
        <div><span>Model</span><strong>{escape_html(status["provider"])} · {escape_html(status["model"])}</strong></div>
        <div><span>Status</span><strong>{escape_html(status["model_status"])}</strong></div>
        <div><span>Search</span><strong>{escape_html(search_status_label())}</strong></div>
      </div>
    </details>
    <div class="cn-account" title="Local prototype account">
      <span>Local</span>
      <strong>FF</strong>
    </div>
  </nav>
</header>
"""


def live_discovery(
    profile: dict[str, Any],
    interview: dict[str, Any] | None = None,
    strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_query = workspace_search_context(profile, interview, strategy)
    discovery = {
        "companies": [],
        "jobs": [],
        "courses": [],
        "events": [],
        "people": [],
        "books": [],
        "projects": [],
    }
    arbeitnow_jobs: list[tuple[int, dict[str, Any]]] = []
    try:
        if ARBEITNOW_BASE_URL:
            arbeitnow_jobs = ranked_arbeitnow_jobs(profile, context_query=context_query)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        arbeitnow_jobs = []
    try:
        discovery["companies"] = interesting_companies(profile, arbeitnow_jobs, context_query=context_query)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["companies"] = []
    try:
        discovery["jobs"] = interesting_jobs(profile, arbeitnow_jobs, context_query=context_query)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["jobs"] = []
    try:
        discovery["events"] = live_resource_search(f"events meetups conferences {context_query} Germany Europe", "Event")
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["events"] = []
    try:
        discovery["people"] = live_resource_search(f"people communities newsletters experts {context_query}", "People")
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["people"] = []
    try:
        discovery["books"] = live_resource_search(f"best books for {context_query} career skill development", "Book")
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["books"] = []
    discovery["courses"] = course_suggestions(profile, strategy)
    discovery["projects"] = project_suggestions(profile, strategy)
    return discovery


def exposure_level_for_task(task: str) -> tuple[str, str]:
    lower = task.lower()
    high_terms = [
        "report",
        "analysis",
        "analyse",
        "data",
        "daten",
        "content",
        "text",
        "research",
        "recherche",
        "document",
        "dokument",
        "crm",
        "seo",
    ]
    low_terms = [
        "stakeholder",
        "leadership",
        "strategy",
        "führung",
        "strategie",
        "negotiation",
        "verhandlung",
        "consulting",
        "beratung",
        "team",
        "customer",
        "client",
        "kunden",
        "communication",
        "kommunikation",
    ]
    if any(term in lower for term in high_terms):
        return ("high", "#e07a5b")
    if any(term in lower for term in low_terms):
        return ("low", "#5be08a")
    return ("medium", "#e0c85b")


def discovery_rows(
    items: Any,
    primary_key: str,
    secondary_key: str,
    empty_label: str,
) -> str:
    rows = []
    if isinstance(items, list):
        for item in items[:3]:
            if not isinstance(item, dict):
                continue
            primary = escape_html(item.get(primary_key))
            secondary = escape_html(item.get(secondary_key))
            if primary:
                source = escape_html(item.get("source"))
                raw_url = str(item.get("url") or "")
                parsed_url = urllib.parse.urlparse(raw_url)
                url = escape_html(raw_url) if parsed_url.scheme in {"http", "https"} else ""
                source_label = f'<em>{source}</em>' if source else ""
                link_label = f' <a href="{url}" target="_blank" rel="noopener noreferrer">open</a>' if url else ""
                rows.append(
                    f'<div class="cn-discovery-item"><strong>{primary}</strong>'
                    f'<span>{secondary}</span><small>{source_label}{link_label}</small></div>'
                )
    if not rows:
        rows.append(f'<div class="cn-muted">{escape_html(empty_label)}</div>')
    return "".join(rows)


def named_discovery_rows(items: Any, empty_label: str) -> str:
    return discovery_rows(items, "name", "why", empty_label)


def pending_sidebar_html(profile: dict[str, Any]) -> str:
    role = escape_html(profile.get("current_role") or "CV profile")
    industry = escape_html(profile.get("industry") or "Industry inferred from the CV")
    skills = [escape_html(skill) for skill in (profile.get("skills") or [])[:4]]
    skill_line = " · ".join(skills) if skills else "skills still need clarification"
    return f"""
<aside class="cn-sidebar" data-pressure="PENDING" data-pressure-color="#7fa88f">
  <section class="cn-side-card cn-profile">
    <div class="cn-kicker">PROFILE</div>
    <h2>{role}</h2>
    <p>{industry}</p>
    <div class="cn-detail">
      <div><span class="cn-ok">✓</span> CV parsed</div>
      <div><span class="cn-ok">✓</span> {skill_line}</div>
      <div class="cn-muted">- no live search yet</div>
    </div>
  </section>
  <section class="cn-side-card">
    <div class="cn-kicker">SEARCH PAUSED</div>
    <h2>Pick a perspective first</h2>
    <p>Jobs, companies, courses, events, people, books, and project ideas unlock after your answers create a real target direction.</p>
    <div class="cn-detail">
      <div>NEEDED <span class="cn-accent-text">expectations</span></div>
      <div>NEEDED <span class="cn-accent-text">constraints</span></div>
      <div>NEEDED <span class="cn-accent-text">no-go zones</span></div>
    </div>
  </section>
</aside>
"""


def sidebar_html(
    profile: dict[str, Any],
    discovery: dict[str, Any] | None = None,
) -> str:
    discovery = discovery if isinstance(discovery, dict) else {}
    role = escape_html(profile.get("current_role") or "CV profile")
    industry = escape_html(profile.get("industry") or "Industry inferred from the CV")
    years = profile.get("years_experience")
    years_label = f"{years:g} years" if isinstance(years, (int, float)) else "experience detected"
    seniority = escape_html(profile.get("seniority") or "mid")
    skills = [escape_html(skill) for skill in (profile.get("skills") or [])[:4]]
    ai_signals = profile.get("ai_tool_signals") or []
    roles = profile.get("roles") or []

    task_candidates: list[str] = []
    for item in roles:
        for task in item.get("key_tasks", [])[:2]:
            if task not in task_candidates:
                task_candidates.append(task)
    if not task_candidates:
        task_candidates = list(profile.get("skills") or [])[:3]
    task_rows = []
    for task in task_candidates[:3]:
        label, color = exposure_level_for_task(str(task))
        task_rows.append(
            f'<div class="cn-row"><span>{escape_html(task)}</span><span style="color:{color}">● {label}</span></div>'
        )
    while len(task_rows) < 3:
        task_rows.append('<div class="cn-row cn-muted"><span>Additional task</span><span>- after report</span></div>')

    skill_line = " · ".join(skills) if skills else "Skills will be prioritized in the workspace"
    ai_line = "AI tool signals detected" if ai_signals else "No AI tool signals detected in the CV"
    company_rows = discovery_rows(
        discovery.get("companies"), "name", "why", "Added after analysis"
    )
    job_rows = discovery_rows(
        discovery.get("jobs"), "title", "why", "Added after analysis"
    )
    course_rows = discovery_rows(
        discovery.get("courses"),
        "name",
        "why",
        "Course matches will update after skills and gaps are known",
    )
    event_rows = named_discovery_rows(discovery.get("events"), "Add Tavily to find relevant events")
    people_rows = named_discovery_rows(discovery.get("people"), "Add Tavily to find people and communities")
    book_rows = named_discovery_rows(discovery.get("books"), "Add Tavily to find books and reading paths")
    project_rows = named_discovery_rows(discovery.get("projects"), "Side project ideas appear after analysis")
    live_search_configured = bool(TAVILY_API_KEY or SERPAPI_API_KEY)
    live_note = (
        "Live data: Arbeitnow + web search"
        if live_search_configured
        else "Live data: Arbeitnow; web search not configured"
    )
    pressure = "MEDIUM"
    pressure_color = "#e0c85b"
    if task_candidates:
        levels = [exposure_level_for_task(str(task))[0] for task in task_candidates[:3]]
        if levels.count("high") >= 2:
            pressure, pressure_color = "HIGH", "#e07a5b"
        elif levels.count("low") >= 2:
            pressure, pressure_color = "LOW", "#5be08a"

    return f"""
<aside class="cn-sidebar" data-pressure="{pressure}" data-pressure-color="{pressure_color}">
  <section class="cn-side-card cn-profile">
    <div class="cn-kicker">PROFILE</div>
    <h2>{role}</h2>
    <p>{industry} · {seniority} · {escape_html(years_label)}</p>
    <div class="cn-detail">{''.join(task_rows)}</div>
  </section>
  <section class="cn-side-card">
    <div class="cn-kicker">LEARN</div>
    <h2>100-day plan</h2>
    <p>{escape_html(ai_line)} · time budget comes next</p>
    <div class="cn-detail">
      <div><span class="cn-ok">✓</span> Profile extracted</div>
      <div><span class="cn-ok">✓</span> Change areas marked</div>
      <div class="cn-muted">- learning path after your answers</div>
    </div>
  </section>
  <section class="cn-side-card">
    <div class="cn-kicker">POSITIONING</div>
    <h2>Narrative</h2>
    <p>{skill_line}</p>
    <div class="cn-detail">FOCUS <span class="cn-accent-text">CV bullets + LinkedIn headline</span></div>
  </section>
  <section class="cn-side-card">
    <div class="cn-kicker">NEXT ROLE</div>
    <h2>Target direction</h2>
    <p>Derived from adaptation level, time budget, and learning budget</p>
    <div class="cn-detail">TOP FIT <span class="cn-accent-text">after workspace generation</span></div>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">COMPANIES</div>
    <h2>Companies to inspect</h2>
    <div class="cn-discovery-list">{company_rows}</div>
    <p class="cn-data-note">{escape_html(live_note)}</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">JOBS</div>
    <h2>Specific openings</h2>
    <div class="cn-discovery-list">{job_rows}</div>
    <p class="cn-data-note">Updated from current profile, answers, and generated gaps</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">COURSES</div>
    <h2>Skill courses</h2>
    <div class="cn-discovery-list">{course_rows}</div>
    <p class="cn-data-note">Matched from the verified local course catalog: skills first, then gaps</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">PROJECTS</div>
    <h2>Proof work</h2>
    <div class="cn-discovery-list">{project_rows}</div>
    <p class="cn-data-note">Artifacts that prove judgment, not tool fandom</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">EVENTS</div>
    <h2>Rooms to enter</h2>
    <div class="cn-discovery-list">{event_rows}</div>
    <p class="cn-data-note">Live web search when Tavily or SerpAPI is configured</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">PEOPLE</div>
    <h2>People to learn from</h2>
    <div class="cn-discovery-list">{people_rows}</div>
    <p class="cn-data-note">Communities, newsletters, operators, and practitioners</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">BOOKS</div>
    <h2>Reading path</h2>
    <div class="cn-discovery-list">{book_rows}</div>
    <p class="cn-data-note">Broader skill gaps, not only technical tooling</p>
  </section>
</aside>
"""


def profile_questions(profile: dict[str, Any]) -> list[str]:
    role = str(profile.get("current_role") or "your current role")
    industry = str(profile.get("industry") or "this field")
    skills = [str(skill) for skill in (profile.get("skills") or []) if skill]
    skill = skills[0] if skills else "your strongest skill"
    task = ""
    for role_item in profile.get("roles") or []:
        if isinstance(role_item, dict):
            tasks = role_item.get("key_tasks") or []
            if tasks:
                task = str(tasks[0])
                break
    task = task or skill
    return [
        f"Which part of {role} do you want more of: {task}, strategy, people work, execution, or something else?",
        f"What should the next role avoid repeating from your current work in {industry}?",
        f"Which problem space would make this feel worth it: the current industry, an adjacent field, or a sharper mission?",
        f"What proof could you realistically build in 30 days that would make someone believe your next direction?",
    ]


def dashboard_left_html(profile: dict[str, Any], teaser: list[str], source_label: str) -> str:
    role = escape_html(profile.get("current_role") or "CV profile")
    industry = escape_html(profile.get("industry") or "Industry inferred from the CV")
    years = profile.get("years_experience")
    years_label = f"{years:g} years" if isinstance(years, (int, float)) else "experience detected"
    teaser_items = "".join(f"<li>{escape_html(item)}</li>" for item in (teaser or [])[:3])
    question_items = "".join(f"<li>{escape_html(item)}</li>" for item in profile_questions(profile))
    return f"""
    <section class="cn-chat-panel">
      <div class="cn-accent"></div>
      <div class="cn-heading">
        <h1>Find where AI changes<br>your work.</h1>
        <p>{role}, {industry} · {escape_html(years_label)} · {escape_html(source_label)}</p>
      </div>
      <div class="cn-messages">
        <div class="cn-assistant">
          Your CV is parsed. Before searching jobs or companies, I need your direction. The useful output is not a generic report; it is a set of testable career perspectives.
          <div class="cn-chips">
            <span>Clarify direction</span>
            <span>Test perspectives</span>
            <span>Search after fit</span>
          </div>
        </div>
        <div class="cn-user">CV: {escape_html(source_label)}</div>
        <div class="cn-assistant">
          <strong>First observations</strong>
          <ol>{teaser_items}</ol>
        </div>
        <div class="cn-assistant cn-question-list">
          <strong>Questions to answer before discovery</strong>
          <ol>{question_items}</ol>
        </div>
      </div>
    </section>
"""


def rating_label(rating: str) -> str:
    return {
        "green": "LOW",
        "yellow": "MEDIUM",
        "red": "HIGH",
    }.get(str(rating).lower(), "MEDIUM")


def time_budget_to_hours(time_budget: str | None) -> float | None:
    if not time_budget:
        return None
    if time_budget.startswith("< 2"):
        return 8
    if time_budget.startswith("2-5"):
        return 20
    if time_budget.startswith("5-10"):
        return 40
    if time_budget.startswith("> 10"):
        return 80
    return None


def adaptation_to_course_level(adaptation: str | None) -> str | None:
    if not adaptation:
        return None
    if adaptation.startswith("Optimize"):
        return "beginner"
    if adaptation.startswith("Develop"):
        return "intermediate"
    if adaptation.startswith("Reinvent"):
        return "advanced"
    return None


def verified_course_resources(
    gaps: list[dict[str, Any]],
    *,
    learning_budget: str,
    time_budget: str,
    adaptation: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not gaps:
        return [], []

    result = match_courses(
        gaps,
        budget=learning_budget,
        time_hours=time_budget_to_hours(time_budget),
        level=adaptation_to_course_level(adaptation),
        limit=6,
    )
    resources_by_gap: dict[str, dict[str, Any]] = {}

    for item in result["recommendations"]:
        course = item["course"]
        matched_gap = item["matched_gap_labels"][0] if item["matched_gap_labels"] else "General"
        resource = resources_by_gap.setdefault(matched_gap, {"gap": matched_gap, "free": [], "paid": []})
        target = "free" if course["cost_type"] in {"free", "audit_free"} else "paid"
        resource[target].append(
            {
                "name": course["title"],
                "provider": course["provider"],
                "url": course["url"],
                "format": course["format"].replace("_", " ").title(),
                "time_cost": f'{course["time_hours"]:g} hours',
                "cost_estimate": course["cost_note"],
                "why": "; ".join(item.get("why", [])),
            }
        )

    return list(resources_by_gap.values()), result["fallbacks"]


def apply_verified_courses(
    report_data: dict[str, Any],
    *,
    learning_budget: str,
    time_budget: str,
    adaptation: str,
) -> dict[str, Any]:
    resources, fallbacks = verified_course_resources(
        report_data.get("gaps", []),
        learning_budget=learning_budget,
        time_budget=time_budget,
        adaptation=adaptation,
    )
    report_data["resources"] = resources
    report_data["course_fallbacks"] = fallbacks
    return report_data


def render_report(data: dict[str, Any]) -> str:
    lines = ["# AI Career Workspace", ""]

    lines += ["## 1. Where AI changes your work", ""]
    for item in data.get("exposure", []):
        lines.append(
            f"- **{item.get('task', '')}** {rating_label(item.get('rating', 'yellow'))}: {item.get('reasoning', '')}"
        )
    lines += ["", data.get("exposure_summary", ""), ""]

    lines += ["## 2. Your most important gaps", ""]
    for idx, gap in enumerate(data.get("gaps", []), start=1):
        lines.append(f"{idx}. **{gap.get('gap', '')}**: {gap.get('why_it_matters', '')}")
    lines.append("")

    lines += ["## 3. Your first 100 days", ""]
    for block in data.get("plan_100", []):
        lines.append(f"**{block.get('weeks', '')}: {block.get('focus', '')}**")
        for action in block.get("actions", []):
            lines.append(f"- {action}")
        lines.append(f"Outcome: {block.get('outcome', '')}")
        lines.append("")

    lines += ["## 4. Your 365-day roadmap", ""]
    for quarter in data.get("plan_365", []):
        lines.append(f"**{quarter.get('quarter', '')}: {quarter.get('theme', '')}**")
        for milestone in quarter.get("milestones", []):
            lines.append(f"- {milestone}")
        lines.append("")
    lines += ["### Decision gates", ""]
    for gate in data.get("decision_gates", []):
        lines.append(f"- **{gate.get('when', '')}:** {gate.get('question', '')}")
        lines.append(f"  - If yes: {gate.get('if_yes', '')}")
        lines.append(f"  - If no: {gate.get('if_no', '')}")
    lines.append("")

    lines += ["## 5. Courses and learning resources", ""]
    for resource in data.get("resources", []):
        lines.append(f"**{resource.get('gap', '')}**")
        lines.append("**Free:**")
        for item in resource.get("free", []):
            name = item.get("name", "")
            url = item.get("url")
            label = f"[{name}]({url})" if url else name
            provider = item.get("provider", "")
            lines.append(f"- {label} - {provider} ({item.get('format', '')}, {item.get('time_cost', '')})")
        paid = resource.get("paid", [])
        if paid:
            lines.append("**Paid:**")
            for item in paid:
                name = item.get("name", "")
                url = item.get("url")
                label = f"[{name}]({url})" if url else name
                provider = item.get("provider", "")
                lines.append(
                    f"- {label} - {provider} ({item.get('format', '')}, {item.get('cost_estimate', '')}, {item.get('time_cost', '')})"
                )
        lines.append("")
    fallbacks = data.get("course_fallbacks", [])
    if fallbacks:
        lines.append("**Still to research:**")
        for fallback in fallbacks:
            lines.append(f"- Search for: {fallback.get('search_phrase', fallback.get('gap', 'course'))}")
        lines.append("")

    repositioning = data.get("repositioning", {})
    lines += ["## 6. Your new narrative", ""]
    for bullet in repositioning.get("cv_bullets", []):
        lines.append(f"- {bullet}")
    lines.append("")
    lines.append(f"> {repositioning.get('linkedin_headline', '')}")
    lines.append("")
    lines.append(f"*{data.get('closing_note', '')}*")
    lines.append("")
    lines.append(
        "*Note: AI exposure assessments are informed estimates, not certainties. This workspace was created with AI support.*"
    )
    return "\n".join(lines)


def list_html(items: Any, *, ordered: bool = False, empty: str = "No items yet.") -> str:
    if not isinstance(items, list) or not items:
        return f'<p class="cn-muted">{escape_html(empty)}</p>'
    tag = "ol" if ordered else "ul"
    rows = "".join(f"<li>{escape_html(item)}</li>" for item in items if item)
    return f"<{tag}>{rows}</{tag}>" if rows else f'<p class="cn-muted">{escape_html(empty)}</p>'


def exposure_cards_html(items: Any) -> str:
    cards = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            rating = rating_label(item.get("rating", "yellow"))
            cards.append(
                f"""
<article class="cn-work-card cn-exposure-card" data-rating="{escape_html(rating.lower())}">
  <div class="cn-card-topline"><span>{escape_html(rating)}</span></div>
  <h3>{escape_html(item.get("task") or "Task")}</h3>
  <p>{escape_html(item.get("reasoning") or "No reasoning returned.")}</p>
</article>
"""
            )
    return "".join(cards) or '<p class="cn-muted">No exposure cards returned.</p>'


def gaps_html(gaps: Any) -> str:
    cards = []
    if isinstance(gaps, list):
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            priority = escape_html(gap.get("priority") or "focus")
            cards.append(
                f"""
<article class="cn-work-card">
  <div class="cn-card-topline"><span>Priority {priority}</span></div>
  <h3>{escape_html(gap.get("gap") or "Development gap")}</h3>
  <p>{escape_html(gap.get("why_it_matters") or "This needs more evidence.")}</p>
</article>
"""
            )
    return "".join(cards) or '<p class="cn-muted">No gap cards returned.</p>'


def plan_100_html(blocks: Any) -> str:
    cards = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            cards.append(
                f"""
<details class="cn-work-card cn-plan-card" open>
  <summary>
    <span>{escape_html(block.get("weeks") or "Next phase")}</span>
    <strong>{escape_html(block.get("focus") or "Focus area")}</strong>
  </summary>
  {list_html(block.get("actions"), empty="No actions returned.")}
  <p class="cn-outcome"><strong>Outcome:</strong> {escape_html(block.get("outcome") or "Outcome not specified.")}</p>
</details>
"""
            )
    return "".join(cards) or '<p class="cn-muted">No 100-day plan returned.</p>'


def roadmap_html(blocks: Any, gates: Any) -> str:
    quarters = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            quarters.append(
                f"""
<article class="cn-work-card">
  <div class="cn-card-topline"><span>{escape_html(block.get("quarter") or "Quarter")}</span></div>
  <h3>{escape_html(block.get("theme") or "Theme")}</h3>
  {list_html(block.get("milestones"), empty="No milestones returned.")}
</article>
"""
            )
    gate_cards = []
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            gate_cards.append(
                f"""
<details class="cn-work-card cn-decision-card">
  <summary><span>{escape_html(gate.get("when") or "Decision gate")}</span><strong>{escape_html(gate.get("question") or "Decision")}</strong></summary>
  <div class="cn-two-column">
    <p><strong>If yes:</strong> {escape_html(gate.get("if_yes") or "")}</p>
    <p><strong>If no:</strong> {escape_html(gate.get("if_no") or "")}</p>
  </div>
</details>
"""
            )
    return "".join(quarters + gate_cards) or '<p class="cn-muted">No roadmap returned.</p>'


def course_cards_html(resources: Any, fallbacks: Any) -> str:
    cards = []
    if isinstance(resources, list):
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            items = []
            for bucket in ("free", "paid"):
                for item in resource.get(bucket, []) if isinstance(resource.get(bucket), list) else []:
                    if not isinstance(item, dict):
                        continue
                    raw_url = str(item.get("url") or "")
                    parsed_url = urllib.parse.urlparse(raw_url)
                    href = escape_html(raw_url) if parsed_url.scheme in {"http", "https"} else ""
                    link = (
                        f'<a href="{href}" target="_blank" rel="noopener noreferrer">Open course</a>'
                        if href
                        else '<span class="cn-muted">No link</span>'
                    )
                    items.append(
                        f"""
<article class="cn-course-card">
  <h4>{escape_html(item.get("name") or "Course")}</h4>
  <p>{escape_html(item.get("provider") or "")} · {escape_html(item.get("format") or "")} · {escape_html(item.get("time_cost") or "")}</p>
  <small>{escape_html(item.get("cost_estimate") or bucket.title())}</small>
  {link}
</article>
"""
                    )
            cards.append(
                f"""
<details class="cn-work-card cn-resource-card" open>
  <summary><span>Course path</span><strong>{escape_html(resource.get("gap") or "Learning gap")}</strong></summary>
  <div class="cn-course-grid">{''.join(items) or '<p class="cn-muted">No verified courses for this gap.</p>'}</div>
</details>
"""
            )
    if isinstance(fallbacks, list) and fallbacks:
        fallback_items = "".join(
            f"<li>{escape_html(item.get('search_phrase') or item.get('gap') or 'Research course')}</li>"
            for item in fallbacks
            if isinstance(item, dict)
        )
        if fallback_items:
            cards.append(f'<details class="cn-work-card"><summary><span>Research queue</span><strong>Missing course evidence</strong></summary><ul>{fallback_items}</ul></details>')
    return "".join(cards) or '<p class="cn-muted">No course resources returned.</p>'


def narrative_html(repositioning: Any, closing_note: str) -> str:
    data = repositioning if isinstance(repositioning, dict) else {}
    bullets = list_html(data.get("cv_bullets"), empty="No positioning bullets returned.")
    headline = escape_html(data.get("linkedin_headline") or "Headline not generated.")
    return f"""
<section class="cn-work-card cn-narrative-card">
  <div class="cn-card-topline"><span>Positioning</span></div>
  <h3>{headline}</h3>
  {bullets}
  <p class="cn-outcome">{escape_html(closing_note)}</p>
</section>
"""


def perspectives_html(perspectives: Any) -> str:
    cards = []
    if isinstance(perspectives, list):
        for item in perspectives:
            if not isinstance(item, dict):
                continue
            roles = ", ".join(str(role) for role in item.get("target_roles", [])[:4] if role)
            terms = ", ".join(str(term) for term in item.get("search_terms", [])[:4] if term)
            cards.append(
                f"""
<article class="cn-work-card cn-perspective-card">
  <div class="cn-card-topline"><span>Perspective</span></div>
  <h3>{escape_html(item.get("name") or "Career perspective")}</h3>
  <p>{escape_html(item.get("why_it_fits") or "Fit rationale missing.")}</p>
  <p><strong>Target roles:</strong> {escape_html(roles or "Needs target roles.")}</p>
  <p><strong>Company profile:</strong> {escape_html(item.get("company_profile") or "Needs company profile.")}</p>
  <p><strong>Risk:</strong> {escape_html(item.get("risks") or "Needs risk statement.")}</p>
  <small>{escape_html(terms)}</small>
</article>
"""
            )
    return "".join(cards) or '<p class="cn-muted">No perspectives returned. The next prompt pass needs to propose 2-3 target directions before discovery.</p>'


def render_workspace_html(data: dict[str, Any]) -> str:
    return f"""
<section class="cn-workspace">
  <nav class="cn-workspace-tabs" aria-label="Workspace windows">
    <a href="#perspectives">Perspectives</a>
    <a href="#exposure">Exposure</a>
    <a href="#gaps">Gaps</a>
    <a href="#plan">Plan</a>
    <a href="#roadmap">Roadmap</a>
    <a href="#courses">Courses</a>
    <a href="#narrative">Narrative</a>
    <a href="#feedback">Feedback</a>
  </nav>
  <div class="cn-window-board">
    <section id="perspectives" class="cn-work-section cn-window cn-window-wide">
      <div class="cn-window-bar"><span>00</span><h2>Directions to test first</h2></div>
      <div class="cn-card-grid">{perspectives_html(data.get("perspectives"))}</div>
    </section>
    <section id="exposure" class="cn-work-section cn-window">
      <div class="cn-window-bar"><span>01</span><h2>Where AI changes the work</h2></div>
      <p>{escape_html(data.get("exposure_summary") or "")}</p>
      <div class="cn-card-grid">{exposure_cards_html(data.get("exposure"))}</div>
    </section>
    <section id="gaps" class="cn-work-section cn-window">
      <div class="cn-window-bar"><span>02</span><h2>Development gaps</h2></div>
      <div class="cn-card-grid">{gaps_html(data.get("gaps"))}</div>
    </section>
    <section id="plan" class="cn-work-section cn-window">
      <div class="cn-window-bar"><span>03</span><h2>Your first 100 days</h2></div>
      <div class="cn-stack">{plan_100_html(data.get("plan_100"))}</div>
    </section>
    <section id="roadmap" class="cn-work-section cn-window">
      <div class="cn-window-bar"><span>04</span><h2>365-day roadmap</h2></div>
      <div class="cn-card-grid">{roadmap_html(data.get("plan_365"), data.get("decision_gates"))}</div>
    </section>
    <section id="courses" class="cn-work-section cn-window">
      <div class="cn-window-bar"><span>05</span><h2>Courses and resources</h2></div>
      <div class="cn-stack">{course_cards_html(data.get("resources"), data.get("course_fallbacks"))}</div>
    </section>
    <section id="narrative" class="cn-work-section cn-window">
      <div class="cn-window-bar"><span>06</span><h2>Narrative</h2></div>
      {narrative_html(data.get("repositioning"), data.get("closing_note") or "")}
    </section>
    <section id="feedback" class="cn-work-section cn-window">
      <div class="cn-window-bar"><span>07</span><h2>What to challenge next</h2></div>
      <div class="cn-feedback-grid">
        <article class="cn-work-card"><h3>This is wrong</h3><p>Mark assumptions, missing context, or recommendations that do not fit your real constraints.</p></article>
        <article class="cn-work-card"><h3>More like this</h3><p>Choose the companies, roles, projects, or learning directions that feel promising and search deeper.</p></article>
        <article class="cn-work-card"><h3>Too generic</h3><p>Force the next pass to anchor every suggestion in a CV fact, target company, event, project, or skill gap.</p></article>
      </div>
    </section>
  </div>
</section>
"""


def markdown_to_basic_html(markdown: str) -> str:
    html_lines = []
    in_list = False
    in_quote = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if in_quote:
                html_lines.append("</blockquote>")
                in_quote = False
            continue
        if line.startswith("|"):
            continue
        if line.startswith("# "):
            html_lines.append(f"<h1>{escape_html(line[2:])}</h1>")
            continue
        if line.startswith("## "):
            html_lines.append(f"<h2>{escape_html(line[3:])}</h2>")
            continue
        if line.startswith("### "):
            html_lines.append(f"<h3>{escape_html(line[4:])}</h3>")
            continue
        if line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{inline_markdown(line[2:])}</li>")
            continue
        if line.startswith("> "):
            if not in_quote:
                html_lines.append("<blockquote>")
                in_quote = True
            html_lines.append(f"<p>{inline_markdown(line[2:])}</p>")
            continue
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        if in_quote:
            html_lines.append("</blockquote>")
            in_quote = False
        html_lines.append(f"<p>{inline_markdown(line)}</p>")
    if in_list:
        html_lines.append("</ul>")
    if in_quote:
        html_lines.append("</blockquote>")
    return "\n".join(html_lines)


def inline_markdown(text: str) -> str:
    escaped = escape_html(text)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.*?)\*", r"<em>\1</em>", escaped)
    return escaped


def write_report_file(markdown: str) -> str:
    prune_report_files()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".md", encoding="utf-8", dir=REPORT_DIR)
    with handle:
        handle.write(markdown)
    return handle.name


def prune_report_files(max_age_seconds: int = REPORT_MAX_AGE_SECONDS) -> None:
    if not REPORT_DIR.exists():
        return
    cutoff = time.time() - max_age_seconds
    for path in REPORT_DIR.glob("*.md"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def start_analysis(uploaded_file: Any, cv_text: str | None):
    try:
        content = build_cv_content(uploaded_file, cv_text)
        result = call_json(PROMPT_1, content, 2000)
        profile = result.get("profile", {})
        if profile_is_empty(profile):
            raise ValueError(CV_ERROR)
        teaser = result.get("teaser", [])
        return (
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=False),
            dashboard_left_html(profile, teaser, "Profile from your CV"),
            pending_sidebar_html(profile),
            profile,
            {},
            "",
        )
    except ValueError as exc:
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            "",
            "",
            {},
            {},
            str(exc) if str(exc) == CV_ERROR else API_ERROR,
        )
    except ConfigError as exc:
        print(exc)
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            "",
            "",
            {},
            {},
            CONFIG_ERROR,
        )
    except Exception:
        print("start_analysis failed")
        traceback.print_exc()
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            "",
            "",
            {},
            {},
            API_ERROR,
        )


def refresh_discovery(profile: dict[str, Any]):
    if not profile:
        return "", {}
    discovery = live_discovery(profile)
    return sidebar_html(profile, discovery), discovery


def create_report(
    profile: dict[str, Any],
    adaptation: str,
    time_budget: str,
    learning_budget: str,
    trigger: str,
):
    try:
        if not profile:
            raise ValueError(CV_ERROR)
        if not adaptation or not time_budget or not learning_budget:
            raise ValueError("Please answer the three required questions.")

        interview = {
            "adaptation_level": adaptation,
            "time_budget": time_budget,
            "learning_budget": learning_budget,
            "trigger": (trigger or "").strip(),
        }
        user_payload = json.dumps({"profile": profile, "interview": interview}, ensure_ascii=False, indent=2)
        result = call_json(PROMPT_2, f"Create the career workspace from this data:\n\n{user_payload}", 8000)
        result = apply_verified_courses(
            result,
            learning_budget=learning_budget,
            time_budget=time_budget,
            adaptation=adaptation,
        )
        discovery = live_discovery(profile, interview, result)
        report = render_report(result)
        download_path = write_report_file(report)
        return (
            gr.update(visible=False),
            gr.update(visible=True),
            render_workspace_html(result),
            download_path,
            sidebar_html(profile, discovery),
            discovery,
            "",
        )
    except ValueError as exc:
        message = str(exc) if str(exc) != CV_ERROR else CV_ERROR
        return (gr.update(visible=True), gr.update(visible=False), "", None, gr.update(), gr.update(), message)
    except ConfigError as exc:
        print(exc)
        return (gr.update(visible=True), gr.update(visible=False), "", None, gr.update(), gr.update(), CONFIG_ERROR)
    except Exception:
        print("create_report failed")
        traceback.print_exc()
        return (gr.update(visible=True), gr.update(visible=False), "", None, gr.update(), gr.update(), API_ERROR)


def reset_app():
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        None,
        "",
        "",
        "",
        {},
        {},
        None,
        None,
        None,
        "",
        "",
        None,
        "",
        "",
    )


CSS = """
:root {
  --cn-bg: #111a15;
  --cn-bg-2: #18261e;
  --cn-panel: rgba(255,255,255,.045);
  --cn-panel-strong: rgba(255,255,255,.075);
  --cn-primary: #fbfff9;
  --cn-text: #e4f1e8;
  --cn-soft: #c0d7c8;
  --cn-muted: #a3b9ab;
  --cn-accent: #68d391;
  --cn-accent-strong: #8ee6ad;
  --cn-warn: #d8b75b;
  --cn-alert: #df8068;
  --cn-line: rgba(255,255,255,.16);
}
html,
body,
gradio-app,
.gradio-container {
  background-color: var(--cn-bg) !important;
  color: var(--cn-text) !important;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
  min-height: 100vh !important;
  overflow-x: hidden !important;
  max-width: none !important;
  padding: 0 !important;
}
.gradio-container {
  isolation: isolate !important;
}
.gradio-container::before {
  content: "" !important;
  position: fixed !important;
  inset: 0 !important;
  z-index: -1 !important;
  pointer-events: none !important;
  background:
    radial-gradient(circle at 16% 0%, rgba(104,211,145,.2), transparent 34rem),
    radial-gradient(circle at 92% 10%, rgba(216,183,91,.12), transparent 30rem),
    linear-gradient(135deg, #101a14, var(--cn-bg-2) 56%, #0d1511) !important;
}
.gradio-container > * {
  position: relative !important;
  z-index: 1 !important;
}
.gradio-container,
.gradio-container * {
  box-sizing: border-box !important;
}
.gradio-container,
.gradio-container section,
.gradio-container .block,
.gradio-container .form {
  outline-color: rgba(104,211,145,.75) !important;
}
.gradio-container *:focus-visible {
  outline: 2px solid rgba(104,211,145,.75) !important;
  outline-offset: 2px !important;
}
body {
  margin: 0 !important;
  overflow-x: hidden !important;
}
footer,
.built-with,
.gradio-container > div:last-child img,
.gradio-container > div:last-child svg,
.gradio-container [style*="position: fixed"],
.gradio-container [class*="floating"] {
  display: none !important;
}
.cn-container {
  width: min(1180px, calc(100vw - 32px)) !important;
  max-width: calc(100vw - 32px) !important;
  margin: 0 auto !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
}
.workspace-shell {
  min-height: auto !important;
  padding: 24px 0 40px !important;
  align-content: start !important;
}
.cn-appbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.cn-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  font-weight: 600;
  font-size: 14.5px;
}
.cn-brand div:last-child {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cn-brand span {
  color: var(--cn-muted);
  font-size: 12px;
  font-weight: 500;
}
.cn-logo {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: radial-gradient(circle at 38% 28%, #fff7a8 0 24%, #ffd64d 42%, #f29b1d 77%);
  color: #3d2700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 -3px 0 rgba(88,54,0,.22), 0 0 0 1px rgba(255,255,255,.18);
}
.cn-logo-face {
  position: relative;
  width: 22px;
  height: 22px;
  display: block;
}
.cn-logo-face::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 5px;
  width: 4px;
  height: 5px;
  border-radius: 50%;
  background: #6d4200;
  box-shadow: 10px 0 0 #6d4200;
}
.cn-logo-face::after {
  content: "";
  position: absolute;
  left: 2px;
  right: 2px;
  bottom: 3px;
  height: 7px;
  border: 2px solid #744700;
  border-radius: 3px;
  background: repeating-linear-gradient(90deg, #f7f7ef 0 4px, #bfc5c5 4px 5px);
  box-shadow: inset 0 3px 0 rgba(255,255,255,.55);
}
.cn-app-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  min-width: 0;
}
.cn-settings {
  position: relative;
}
.cn-settings summary,
.cn-account {
  min-height: 34px;
  border: 1px solid var(--cn-line);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--cn-text);
  background: var(--cn-panel);
  font-size: 12px;
}
.cn-settings summary {
  cursor: pointer;
  list-style: none;
}
.cn-settings summary::-webkit-details-marker {
  display: none;
}
.cn-settings-panel {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 10;
  width: min(320px, calc(100vw - 32px));
  border: 1px solid var(--cn-line);
  border-radius: 8px;
  padding: 12px;
  background: #17231c;
  box-shadow: 0 16px 40px rgba(0,0,0,.35);
}
.cn-settings-panel div {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
  border-top: 1px solid var(--cn-line);
  font-size: 12px;
}
.cn-settings-panel div:first-child {
  border-top: 0;
  padding-top: 0;
}
.cn-settings-panel span {
  color: var(--cn-muted);
}
.cn-settings-panel strong {
  color: var(--cn-primary);
  text-align: right;
}
.cn-account {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cn-account span {
  color: var(--cn-muted);
}
.cn-account strong {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(104,211,145,.18);
  color: var(--cn-accent-strong);
  font-size: 11px;
}
.upload-shell {
  min-height: auto;
  display: grid;
  align-content: start;
  gap: 22px;
  padding: clamp(24px, 6vh, 56px) 0 32px;
}
.upload-panel {
  border: 1px solid var(--cn-line);
  border-radius: 16px;
  padding: 28px;
  max-height: none;
  overflow: visible;
  background: var(--cn-panel);
  box-shadow: 0 18px 46px rgba(0,0,0,.18);
}
.upload-panel h1 {
  color: var(--cn-primary);
  font-size: 34px;
  line-height: 1.12;
  margin-bottom: 8px;
}
.upload-panel p, .privacy {
  color: var(--cn-muted);
  font-size: 13.5px;
}
.upload-panel button {
  min-height: 42px !important;
}
.composer-row {
  display: grid !important;
  grid-template-columns: minmax(0, 1fr) auto !important;
  align-items: stretch !important;
  gap: 10px !important;
}
.composer-row > .form,
.composer-input,
.composer-input .wrap,
.composer-input label,
.composer-input .input-container {
  min-width: 0 !important;
  width: 100% !important;
  max-width: 100% !important;
}
.composer-input label > span {
  display: none !important;
}
.composer-input textarea {
  width: 100% !important;
  max-width: 100% !important;
  min-height: 48px !important;
  height: 48px !important;
  max-height: 120px !important;
  border-radius: 8px !important;
  line-height: 1.45 !important;
}
.composer-upload button,
.composer-row button {
  min-width: 132px !important;
  height: 48px !important;
  border-radius: 8px !important;
}
.composer-file {
  min-width: 132px !important;
  max-width: 220px !important;
}
.composer-file .wrap,
.composer-file label,
.composer-file .container,
.composer-file .file-preview,
.composer-file .file-preview-holder {
  min-height: 48px !important;
  max-height: 70px !important;
}
.composer-file label > span {
  display: none !important;
}
.composer-file .file-preview-holder,
.composer-file .file-preview {
  overflow: hidden !important;
}
.cn-shell {
  min-height: min(680px, calc(100vh - 48px));
  background: transparent;
  padding: 28px 0 8px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 22px;
  color: var(--cn-text);
}
.cn-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.cn-status {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--cn-muted);
  display: flex;
  gap: 22px;
  flex-wrap: wrap;
}
.cn-status strong, .cn-accent-text, .cn-ok {
  color: var(--cn-accent);
}
.cn-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 360px);
  gap: 22px;
  flex: 1;
  min-height: 0;
  align-items: start;
  width: 100% !important;
  max-width: 100% !important;
  margin: 0 !important;
}
.cn-live-layout {
  display: grid !important;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 360px) !important;
  align-items: start !important;
}
.cn-live-layout > *,
.cn-grid > * {
  min-width: 0 !important;
  max-width: 100% !important;
}
.cn-chat-panel, .cn-side-card, .interview-panel, .report-shell {
  border: 1px solid var(--cn-line);
  background: var(--cn-panel);
}
.cn-chat-panel {
  border-radius: 20px;
  padding: 36px;
  display: flex;
  flex-direction: column;
  gap: 26px;
  min-height: 0;
  position: relative;
  overflow: hidden;
}
.cn-accent {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(135deg, transparent 46%, rgba(104,211,145,.045) 47%, transparent 48%);
  pointer-events: none;
}
.cn-heading, .cn-messages {
  position: relative;
}
.cn-heading h1 {
  font-size: 30px;
  line-height: 1.2;
  font-weight: 700;
  margin: 0 0 8px;
  color: var(--cn-primary);
}
.cn-heading p, .cn-side-card p {
  margin: 0;
  color: var(--cn-muted);
  font-size: 13px;
}
.cn-messages {
  flex: 1;
  min-height: 180px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.cn-assistant {
  max-width: min(82%, 680px);
  font-size: 14px;
  line-height: 1.6;
  color: var(--cn-text);
}
.cn-assistant ol {
  margin: 8px 0 0 20px;
  padding: 0;
}
.cn-user {
  align-self: flex-end;
  max-width: min(70%, 520px);
  background: var(--cn-panel-strong);
  border-radius: 14px;
  padding: 10px 15px;
  font-size: 13.5px;
  color: var(--cn-text);
}
.cn-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.cn-chips span {
  border: 1px solid var(--cn-line);
  border-radius: 999px;
  padding: 6px 13px;
  font-size: 12px;
  color: var(--cn-soft);
  background: rgba(255,255,255,.035);
}
.cn-sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  position: sticky;
  top: 18px;
}
.cn-side-card {
  border-radius: 18px;
  padding: 22px 24px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-height: 0;
}
.cn-profile {
  flex: 1.1;
}
.cn-kicker {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: .06em;
  color: var(--cn-muted);
  text-transform: uppercase;
}
.cn-side-card h2 {
  margin: 0;
  font-weight: 700;
  font-size: 18px;
  line-height: 1.2;
  color: var(--cn-primary);
}
.cn-detail {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--cn-text);
}
.cn-discovery-card {
  flex: 0 0 auto;
}
.cn-discovery-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cn-discovery-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding-top: 9px;
  border-top: 1px solid var(--cn-line);
}
.cn-discovery-item:first-child {
  padding-top: 2px;
  border-top: 0;
}
.cn-discovery-item strong {
  color: var(--cn-text);
  font-size: 13px;
  line-height: 1.3;
}
.cn-discovery-item span {
  color: var(--cn-muted);
  font-size: 11.5px;
  line-height: 1.4;
}
.cn-discovery-item small {
  color: var(--cn-soft);
  font-size: 10.5px;
  font-weight: 600;
}
.cn-discovery-item a {
  color: var(--cn-accent);
  text-decoration: none;
}
.cn-discovery-item a:hover {
  text-decoration: underline;
}
.cn-side-card .cn-data-note {
  margin: 2px 0 0;
  font-size: 10px;
  font-weight: 600;
  color: var(--cn-muted);
}
.cn-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.cn-row span:first-child {
  min-width: 0;
  overflow-wrap: anywhere;
}
.cn-row span:last-child {
  flex: 0 0 auto;
}
.cn-muted {
  color: var(--cn-muted);
}
.cn-report-panel {
  overflow: auto;
}
.cn-report-content,
.cn-workspace {
  color: var(--cn-text);
  font-size: 14px;
  line-height: 1.65;
}
.cn-workspace {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.cn-workspace-tabs {
  position: sticky;
  top: 0;
  z-index: 4;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 0 12px;
  background: rgba(17,26,21,.92);
  backdrop-filter: blur(10px);
}
.cn-workspace-tabs a {
  border: 1px solid var(--cn-line);
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--cn-text);
  text-decoration: none;
  font-size: 12px;
}
.cn-workspace-tabs a:hover {
  border-color: rgba(104,211,145,.5);
}
.cn-window-board {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}
.cn-work-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  scroll-margin-top: 54px;
}
.cn-window {
  min-height: 220px;
  border: 1px solid var(--cn-line);
  border-radius: 8px;
  padding: 14px;
  background: var(--cn-panel);
  box-shadow: 0 16px 34px rgba(0,0,0,.14);
}
.cn-window-wide {
  grid-column: 1 / -1;
}
.cn-window-bar {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin: -4px -4px 10px;
  padding: 6px 8px 10px;
  border-bottom: 1px solid var(--cn-line);
}
.cn-window-bar span,
.cn-card-topline span,
.cn-work-card summary span {
  color: var(--cn-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.cn-window-bar h2 {
  margin: 0;
  color: var(--cn-primary);
  font-size: 16px;
}
.cn-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.cn-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cn-work-card {
  border: 1px solid var(--cn-line);
  border-radius: 8px;
  padding: 16px;
  background: rgba(255,255,255,.04);
}
.cn-work-card h3,
.cn-work-card h4 {
  margin: 4px 0 8px;
  color: var(--cn-primary);
  line-height: 1.25;
}
.cn-work-card p,
.cn-work-card ul,
.cn-work-card ol {
  margin: 0 0 10px;
}
.cn-work-card li {
  margin: 0 0 6px;
}
.cn-work-card summary {
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 10px;
}
.cn-work-card summary strong {
  color: var(--cn-primary);
  font-size: 15px;
}
.cn-question-list {
  border-left: 2px solid rgba(104,211,145,.48);
  padding-left: 14px;
}
.cn-perspective-card small {
  display: block;
  color: var(--cn-muted);
  font-size: 11px;
  font-weight: 600;
  margin-top: 8px;
}
.cn-exposure-card[data-rating="high"] {
  border-color: rgba(223,128,104,.48);
}
.cn-exposure-card[data-rating="medium"] {
  border-color: rgba(216,183,91,.48);
}
.cn-exposure-card[data-rating="low"] {
  border-color: rgba(104,211,145,.44);
}
.cn-course-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.cn-course-card {
  border: 1px solid var(--cn-line);
  border-radius: 8px;
  padding: 12px;
}
.cn-course-card h4 {
  font-size: 14px;
}
.cn-course-card small {
  display: block;
  color: var(--cn-muted);
  margin-bottom: 8px;
}
.cn-course-card a {
  color: var(--cn-accent);
  text-decoration: none;
  font-size: 12px;
}
.cn-two-column {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.cn-feedback-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.cn-outcome {
  color: var(--cn-soft);
}
.cn-report-content h1,
.cn-report-content h2,
.cn-report-content h3 {
  color: var(--cn-primary);
  line-height: 1.2;
}
.cn-report-content h1 {
  font-size: 28px;
  margin: 0 0 14px;
}
.cn-report-content h2 {
  font-size: 19px;
  margin: 24px 0 8px;
}
.cn-report-content h3 {
  font-size: 15px;
  margin: 18px 0 8px;
}
.cn-report-content p,
.cn-report-content ul {
  margin: 0 0 12px;
}
.cn-report-content li {
  margin: 0 0 7px;
}
.cn-report-content blockquote {
  border-left: 3px solid var(--cn-accent);
  margin: 14px 0;
  padding-left: 14px;
  color: var(--cn-soft);
}
.interview-panel, .report-shell {
  border-radius: 18px;
  padding: 22px 24px;
  margin-top: 18px;
}
.interview-panel h2 {
  color: var(--cn-primary);
  margin: 0 0 4px;
  font-size: 20px;
}
.interview-panel p {
  color: var(--cn-soft);
  margin: 0 0 18px;
  font-size: 13px;
}
label, .wrap label {
  color: var(--cn-soft) !important;
}
textarea, input {
  color: var(--cn-text) !important;
}
textarea {
  resize: vertical !important;
}
button.primary {
  background: var(--cn-accent) !important;
  color: #102016 !important;
}
.prose, .prose * {
  color: var(--cn-text);
}
@media (max-width: 900px) {
  .cn-container {
    width: min(100%, calc(100vw - 20px));
  }
  .cn-grid {
    grid-template-columns: 1fr;
  }
  .cn-live-layout {
    grid-template-columns: 1fr !important;
  }
  .cn-topbar {
    align-items: flex-start;
    flex-direction: column;
  }
  .cn-chat-panel {
    padding: 22px;
  }
  .cn-card-grid,
  .cn-course-grid,
  .cn-two-column,
  .cn-feedback-grid,
  .cn-window-board {
    grid-template-columns: 1fr;
  }
  .cn-shell {
    min-height: auto;
    padding-top: 18px;
  }
  .cn-sidebar {
    display: grid;
    grid-template-columns: 1fr 1fr;
    position: static;
  }
  .cn-side-card {
    min-height: 150px;
  }
  .interview-panel .form {
    min-width: 0 !important;
  }
}
@media (max-width: 640px) {
  .upload-panel {
    padding: 20px;
    max-height: none;
  }
  .composer-row {
    grid-template-columns: 1fr !important;
  }
  .composer-upload,
  .composer-upload button,
  .composer-row button {
    width: 100% !important;
  }
  .upload-panel h1,
  .cn-heading h1 {
    font-size: 26px;
  }
  .cn-appbar {
    align-items: flex-start;
    flex-direction: column;
  }
  .cn-app-actions {
    width: 100%;
    justify-content: space-between;
  }
  .cn-sidebar {
    grid-template-columns: 1fr;
  }
  .cn-assistant,
  .cn-user {
    max-width: 100%;
  }
  .interview-panel {
    padding: 18px;
  }
}
"""

with gr.Blocks(title=APP_NAME) as demo:
    profile_state = gr.State({})
    discovery_state = gr.State({})

    with gr.Column(visible=True, elem_classes=["cn-container", "upload-shell"]) as screen_upload:
        gr.HTML(app_header_html())
        with gr.Column(elem_classes="upload-panel"):
            gr.Markdown(f"# {APP_NAME}")
            gr.Markdown("Welcome. Paste your CV or upload a PDF, and I will turn it into a focused career strategy workspace: directions, evidence, tradeoffs, and next moves.")
            with gr.Row(elem_classes="composer-row"):
                cv_text = gr.Textbox(
                    label="",
                    show_label=False,
                    lines=1,
                    max_lines=4,
                    placeholder="Paste your CV text here, or upload a PDF next to this line...",
                    elem_classes="composer-input",
                )
                cv_file = gr.File(
                    label="Upload CV",
                    file_types=[".pdf"],
                    file_count="single",
                    elem_classes="composer-file",
                )
            start_button = gr.Button("Start analysis", variant="primary")
            gr.Markdown("Your CV is not stored. The analysis runs once through your configured AI provider.", elem_classes="privacy")
            upload_error = gr.Markdown(visible=True)

    with gr.Column(visible=False, elem_classes=["cn-container", "workspace-shell"]) as screen_workspace:
        gr.HTML(app_header_html())
        with gr.Row(elem_classes=["cn-grid", "cn-live-layout"]):
            with gr.Column():
                teaser_markdown = gr.HTML()
                with gr.Column(visible=True, elem_classes="interview-panel") as interaction_panel:
                    gr.Markdown("## Short interview")
                    gr.Markdown("Four answers are enough to keep the workspace specific. The next step proposes directions before it searches roles and companies.")
                    with gr.Row():
                        adaptation = gr.Radio(ADAPTATION_OPTIONS, label="Adaptation level", interactive=True)
                        time_budget = gr.Radio(TIME_OPTIONS, label="Time budget", interactive=True)
                    with gr.Row():
                        learning_budget = gr.Radio(BUDGET_OPTIONS, label="Learning budget", interactive=True)
                        trigger = gr.Textbox(label="Trigger", placeholder="What brought you here today?", lines=4)
                    report_button = gr.Button("Generate workspace", variant="primary")
                    gr.Markdown("This view stays visible while the workspace is generated.", elem_classes="privacy")
                    interview_error = gr.Markdown()
                with gr.Column(visible=False, elem_classes="report-shell") as report_panel:
                    report_markdown = gr.HTML()
                    download_button = gr.DownloadButton("Export backup notes")
                    reset_button = gr.Button("New analysis")
            live_sidebar = gr.HTML()

    start_button.click(
        fn=start_analysis,
        inputs=[cv_file, cv_text],
        outputs=[
            screen_upload,
            screen_workspace,
            interaction_panel,
            report_panel,
            teaser_markdown,
            live_sidebar,
            profile_state,
            discovery_state,
            upload_error,
        ],
        api_name=False,
        show_progress="full",
        scroll_to_output=False,
    )
    report_button.click(
        fn=create_report,
        inputs=[profile_state, adaptation, time_budget, learning_budget, trigger],
        outputs=[
            interaction_panel,
            report_panel,
            report_markdown,
            download_button,
            live_sidebar,
            discovery_state,
            interview_error,
        ],
        api_name=False,
        show_progress="full",
        scroll_to_output=False,
    )
    reset_button.click(
        fn=reset_app,
        inputs=[],
        outputs=[
            screen_upload,
            screen_workspace,
            interaction_panel,
            report_panel,
            cv_file,
            cv_text,
            teaser_markdown,
            live_sidebar,
            profile_state,
            discovery_state,
            adaptation,
            time_budget,
            learning_budget,
            trigger,
            report_markdown,
            download_button,
            upload_error,
            interview_error,
        ],
        api_name=False,
        scroll_to_output=False,
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch(
        server_name=RUNTIME_SETTINGS.server_name,
        server_port=RUNTIME_SETTINGS.server_port,
        show_error=True,
        css=CSS,
    )
