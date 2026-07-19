import base64
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

from courses.matcher import match_courses


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
OPENAI_API_MODE = os.getenv("OPENAI_API_MODE", "responses").strip().lower()
OPENAI_JSON_MODE = os.getenv("OPENAI_JSON_MODE", "").strip().lower() in {"1", "true", "yes"}
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4.1",
}
MODEL = os.getenv("LLM_MODEL", DEFAULT_MODELS.get(LLM_PROVIDER, "claude-sonnet-4-6"))
MAX_PDF_BYTES = 10 * 1024 * 1024
CV_ERROR = "I could not read the CV. Please upload a PDF or paste at least 300 characters of CV text."
API_ERROR = "The analysis is not available right now. Please try again in a minute."
CONFIG_ERROR = "Missing API key for the selected provider. Check your .env or environment variables."
JSON_RESPONSE_ERROR = "The AI provider returned an invalid response. Please try again."
LIVE_DATA_TIMEOUT = float(os.getenv("LIVE_DATA_TIMEOUT", "8"))
ARBEITNOW_BASE_URL = os.getenv("ARBEITNOW_BASE_URL", "https://www.arbeitnow.com/api/job-board-api")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
LIVE_SEARCH_PROVIDER = os.getenv("LIVE_SEARCH_PROVIDER", "tavily" if TAVILY_API_KEY else "serpapi").strip().lower()
REPORT_DIR = Path(tempfile.gettempdir()) / "ai-career-navigator-reports"
REPORT_MAX_AGE_SECONDS = 24 * 60 * 60

ADAPTATION_OPTIONS = [
    "Optimize - I want to stay in my role and use AI better",
    "Develop - I am open to a role move in 6-12 months",
    "Reinvent - I am ready for a real pivot",
]
TIME_OPTIONS = ["< 2 hours/week", "2-5 hours/week", "5-10 hours/week", "> 10 hours/week"]
BUDGET_OPTIONS = ["0 EUR (free only)", "up to 50 EUR/month", "over 50 EUR/month"]

PROMPT_1 = """
You are a career analyst specialized in how AI changes professional work. You receive a CV. Extract a structured profile and write three concise first observations.

Reply ONLY with valid JSON, exactly in this schema:
{
  "profile": {
    "current_role": string,
    "seniority": "junior" | "mid" | "senior" | "lead",
    "industry": string,
    "years_experience": number,
    "roles": [{"title": string, "duration": string, "key_tasks": [string, ...]}],
    "skills": [string, ...],
    "education": [string, ...],
    "ai_tool_signals": [string, ...],
    "languages": [string, ...]
  },
  "teaser": [string, string, string]
}

Rules for the teaser observations:
- Each observation is 1-2 sentences, in English, speaking directly to the user as "you".
- Observation 1: the profile's strongest asset in the AI era.
- Observation 2: one concrete, honest exposure area, meaning tasks likely to change strongly through AI, with reasoning and without fearmongering.
- Observation 3: one surprising or non-obvious opportunity that follows from the profile.
- Be specific: refer to concrete roles, tasks, or experiences from the CV, never generic career advice.
- "ai_tool_signals": all hints of existing AI tool use; empty list if none.
""".strip()

PROMPT_2 = """
You are a career strategist for the AI economy. You receive a structured professional profile and answers from a short interview. Create a personal in-app career workspace.

PRINCIPLES:
- Write in English and address the user directly as "you". Be concrete: every statement must visibly depend on THIS profile.
- Be honest about uncertainty. Treat AI exposure as change pressure, not a replacement prophecy, and explain each assessment.
- COURSE RULE, critical: recommend only real, broadly known providers such as Coursera, DeepLearning.AI, fast.ai, Google Skillshop, LinkedIn Learning, Udemy, edX, Maven, local chambers of commerce, or Meetup. Never invent course names. If you are not sure a specific course exists, write "Search for: [course type description]" instead.
- The adaptation level controls depth: Optimize = small improvements in the current role; Develop = adjacent roles and one portfolio project; Reinvent = a full bridge including application phase.
- Time and learning budget are hard constraints. Recommend nothing that exceeds them. If budget is "0 EUR", include only free resources.

Reply ONLY with valid JSON, exactly in this schema:
{
  "exposure": [
    {"task": string, "rating": "green" | "yellow" | "red", "reasoning": string}
  ],
  "exposure_summary": string,
  "gaps": [
    {"gap": string, "why_it_matters": string}
  ],
  "plan_100": [
    {"weeks": string, "focus": string, "actions": [string, ...], "outcome": string}
  ],
  "plan_365": [
    {"quarter": "Q1" | "Q2" | "Q3" | "Q4", "theme": string, "milestones": [string, ...]}
  ],
  "decision_gates": [
    {"when": string, "question": string, "if_yes": string, "if_no": string}
  ],
  "resources": [
    {"gap": string, "free": [{"name": string, "format": "Course" | "Project" | "Community" | "On-the-job", "time_cost": string}], "paid": [{"name": string, "format": string, "cost_estimate": string, "time_cost": string}]}
  ],
  "repositioning": {
    "cv_bullets": [string, string, string],
    "linkedin_headline": string
  },
  "closing_note": string
}

QUANTITY RULES:
- exposure: 5-8 tasks from the real profile, each with one-sentence reasoning.
- gaps: exactly 3, but Optimize may use 2 if that is more honest.
- plan_100: 3-4 blocks in week granularity, e.g. "Weeks 1-2", ending with a concrete artifact.
- plan_365: 4 quarters; Q1 references the 100-day plan.
- decision_gates: exactly 2.
- resources: at least 1 free course/project option per gap; paid only if budget is above 0 EUR.
- cv_bullets: rewritten bullets based on real profile experiences, tone matched to the adaptation level.
- closing_note: 2-3 sentences, grounded and motivating, no fluff.
""".strip()


class ConfigError(RuntimeError):
    pass


def strip_json_fences(text: str) -> str:
    clean = text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    return clean.strip()


def extract_first_json_object(text: str) -> str:
    clean = strip_json_fences(text)
    if not clean:
        return clean
    start = clean.find("{")
    if start == -1:
        return clean

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(clean[start:], start=start):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return clean[start : index + 1]
    return clean


def parse_json_response(text: str) -> dict[str, Any]:
    return json.loads(extract_first_json_object(text))


def extract_text_from_response(response: Any) -> str:
    chunks = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            chunks.append(block.text)
    return "\n".join(chunks).strip()


def anthropic_client() -> Any:
    from anthropic import Anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ConfigError("ANTHROPIC_API_KEY is missing for provider 'anthropic'.")
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=120.0)


def openai_client() -> Any:
    from openai import OpenAI

    if not os.getenv("OPENAI_API_KEY"):
        raise ConfigError("OPENAI_API_KEY is missing for provider 'openai'.")
    kwargs = {"api_key": os.environ["OPENAI_API_KEY"], "timeout": 120.0}
    if os.getenv("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    return OpenAI(**kwargs)


def call_anthropic(system_prompt: str, user_content: Any, max_tokens: int) -> str:
    response = anthropic_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return extract_text_from_response(response)


def call_openai(system_prompt: str, user_content: Any, max_tokens: int) -> str:
    if OPENAI_API_MODE == "chat":
        if not isinstance(user_content, str):
            raise ValueError(CV_ERROR)
        request_args = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max_tokens,
        }
        if OPENAI_JSON_MODE:
            request_args["response_format"] = {"type": "json_object"}
        response = openai_client().chat.completions.create(**request_args)
        return response.choices[0].message.content or ""

    if OPENAI_API_MODE != "responses":
        raise RuntimeError(f"Unbekannter OPENAI_API_MODE: {OPENAI_API_MODE}")

    content = normalize_openai_responses_content(user_content)
    response = openai_client().responses.create(
        model=MODEL,
        instructions=system_prompt,
        input=[{"role": "user", "content": content}],
        max_output_tokens=max_tokens,
    )
    return getattr(response, "output_text", "") or ""


def call_model(system_prompt: str, user_content: Any, max_tokens: int) -> str:
    if LLM_PROVIDER == "anthropic":
        return call_anthropic(system_prompt, user_content, max_tokens)
    if LLM_PROVIDER == "openai":
        return call_openai(system_prompt, user_content, max_tokens)
    raise RuntimeError(f"Unbekannter LLM_PROVIDER: {LLM_PROVIDER}")


def call_json(system_prompt: str, user_content: Any, max_tokens: int) -> dict[str, Any]:
    first_response = call_model(system_prompt, user_content, max_tokens)
    try:
        return parse_json_response(first_response)
    except json.JSONDecodeError as first_error:
        repair_prompt = (
            f"{system_prompt}\n\n"
            "Your previous response was not valid JSON. Return only valid JSON matching the schema."
        )
        try:
            return parse_json_response(call_model(repair_prompt, user_content, max_tokens))
        except json.JSONDecodeError as repair_error:
            raise ValueError(JSON_RESPONSE_ERROR) from repair_error
        except Exception:
            raise
        finally:
            if first_error:
                print(f"Initial JSON parse failed: {first_error}")


def file_path(uploaded_file: Any) -> str | None:
    if uploaded_file is None:
        return None
    if isinstance(uploaded_file, str):
        return uploaded_file
    return getattr(uploaded_file, "name", None) or getattr(uploaded_file, "path", None)


def normalize_openai_responses_content(user_content: Any) -> list[dict[str, Any]]:
    if isinstance(user_content, str):
        return [{"type": "input_text", "text": user_content}]

    content = []
    for item in user_content:
        if item.get("type") == "document":
            source = item.get("source", {})
            content.append(
                {
                    "type": "input_file",
                    "filename": "lebenslauf.pdf",
                    "file_data": f"data:{source.get('media_type', 'application/pdf')};base64,{source.get('data', '')}",
                }
            )
        elif item.get("type") == "text":
            content.append({"type": "input_text", "text": item.get("text", "")})
    return content


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

    encoded_pdf = base64.b64encode(path.read_bytes()).decode("utf-8")
    return [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": encoded_pdf,
            },
        },
        {"type": "text", "text": "Analyze this PDF CV."},
    ]


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
            "hl": "de",
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


def ranked_arbeitnow_jobs(profile: dict[str, Any], *, limit: int = 50) -> list[tuple[int, dict[str, Any]]]:
    query = profile_query(profile, max_skills=2) or str(profile.get("current_role") or "")
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
) -> list[dict[str, str]]:
    query = f'hiring companies Germany "{profile_query(profile)}"'
    results = search_live_web(query, max_results=3)
    if results:
        return [
            {
                "name": item.get("title") or result_domain(item.get("url", "")),
                "why": item.get("snippet") or item.get("url") or "Live search result",
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
                "why": item.get("title", "Passende Live-Stelle gefunden"),
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
) -> list[dict[str, str]]:
    query = profile_query(profile, max_skills=2) or str(profile.get("current_role") or "")
    jobs: list[dict[str, str]] = []
    try:
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
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        jobs = []
    if jobs:
        return jobs

    results = search_live_web(f'site:linkedin.com/jobs OR site:indeed.com "{query}" Germany', max_results=3)
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


def course_suggestions(profile: dict[str, Any]) -> list[dict[str, str]]:
    query = f"AI course {profile_query(profile, max_skills=2)} Coursera edX DeepLearning.AI"
    results = search_live_web(query, max_results=3)
    if not results:
        results = search_live_web("AI productivity course Coursera edX DeepLearning.AI", max_results=3)
    return [
        {
            "name": item.get("title") or result_domain(item.get("url", "")),
            "why": item.get("snippet") or item.get("url") or "Course search result",
            "url": item.get("url", ""),
            "source": item.get("source", ""),
        }
        for item in results
        if item.get("title") or item.get("url")
    ]


def live_discovery(profile: dict[str, Any]) -> dict[str, Any]:
    discovery = {
        "companies": [],
        "jobs": [],
        "courses": [],
    }
    arbeitnow_jobs: list[tuple[int, dict[str, Any]]] = []
    try:
        if ARBEITNOW_BASE_URL:
            arbeitnow_jobs = ranked_arbeitnow_jobs(profile)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        arbeitnow_jobs = []
    try:
        discovery["companies"] = interesting_companies(profile, arbeitnow_jobs)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["companies"] = []
    try:
        discovery["jobs"] = interesting_jobs(profile, arbeitnow_jobs)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["jobs"] = []
    try:
        discovery["courses"] = course_suggestions(profile)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        discovery["courses"] = []
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
        "Course matches will appear here after the catalog is connected",
    )
    live_search_configured = bool(TAVILY_API_KEY or SERPAPI_API_KEY)
    live_note = (
        "Live data: Arbeitnow + web search"
        if live_search_configured
        else "Live data: Arbeitnow + public web search"
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
    <h2>Relevant companies</h2>
    <div class="cn-discovery-list">{company_rows}</div>
    <p class="cn-data-note">{escape_html(live_note)}</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">JOBS</div>
    <h2>Relevant roles</h2>
    <div class="cn-discovery-list">{job_rows}</div>
    <p class="cn-data-note">Live jobs via Arbeitnow, fallback via web search</p>
  </section>
  <section class="cn-side-card cn-discovery-card">
    <div class="cn-kicker">COURSES</div>
    <h2>Course direction</h2>
    <div class="cn-discovery-list">{course_rows}</div>
    <p class="cn-data-note">Temporary search fallback until the verified course catalog is merged</p>
  </section>
</aside>
"""


def app_shell_html(
    profile: dict[str, Any],
    left_html: str,
    discovery: dict[str, Any] | None = None,
    status: str = "▲ ADAPTING",
) -> str:
    sidebar = sidebar_html(profile, discovery)
    pressure = re.search(r'data-pressure="([^"]+)"', sidebar)
    pressure_color = re.search(r'data-pressure-color="([^"]+)"', sidebar)
    pressure_label = pressure.group(1) if pressure else "MEDIUM"
    pressure_color_value = pressure_color.group(1) if pressure_color else "#e0c85b"
    return f"""
<div class="cn-shell">
  <div class="cn-topbar">
    <div class="cn-brand"><div class="cn-logo">A</div><div>AI Career Navigator</div></div>
    <div class="cn-status">
      <span>STATUS <strong>{escape_html(status)}</strong></span>
      <span>CHANGE PRESSURE <strong style="color:{pressure_color_value}">{escape_html(pressure_label)}</strong></span>
    </div>
  </div>
  <div class="cn-grid">
    {left_html}
    {sidebar}
  </div>
</div>
"""


def dashboard_left_html(profile: dict[str, Any], teaser: list[str], source_label: str) -> str:
    role = escape_html(profile.get("current_role") or "CV profile")
    industry = escape_html(profile.get("industry") or "Industry inferred from the CV")
    years = profile.get("years_experience")
    years_label = f"{years:g} years" if isinstance(years, (int, float)) else "experience detected"
    teaser_items = "".join(f"<li>{escape_html(item)}</li>" for item in (teaser or [])[:3])
    return f"""
    <section class="cn-chat-panel">
      <div class="cn-accent"></div>
      <div class="cn-heading">
        <h1>Find where AI changes<br>your work.</h1>
        <p>{role}, {industry} · {escape_html(years_label)} · {escape_html(source_label)}</p>
      </div>
      <div class="cn-messages">
        <div class="cn-assistant">
          Your CV is parsed. I can now see your role profile, the first change areas, and the choices that shape your career workspace.
          <div class="cn-chips">
            <span>Assess exposure</span>
            <span>Build a 100-day plan</span>
            <span>Sharpen your narrative</span>
          </div>
        </div>
        <div class="cn-user">CV: {escape_html(source_label)}</div>
        <div class="cn-assistant">
          <strong>First observations</strong>
          <ol>{teaser_items}</ol>
        </div>
      </div>
    </section>
"""


def rating_icon(rating: str) -> str:
    return {
        "green": "LOW",
        "yellow": "MEDIUM",
        "red": "HIGH",
        "gruen": "LOW",
        "gelb": "MEDIUM",
        "rot": "HIGH",
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
        matched_gap = item["matched_gaps"][0] if item["matched_gaps"] else "general"
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
    if resources:
        report_data["resources"] = resources
    report_data["course_fallbacks"] = fallbacks
    return report_data


def render_report(data: dict[str, Any]) -> str:
    lines = ["# AI Career Workspace", ""]

    lines += ["## 1. Where AI changes your work", ""]
    for item in data.get("exposure", []):
        lines.append(
            f"- **{item.get('task', '')}** {rating_icon(item.get('rating', 'gelb'))}: {item.get('reasoning', '')}"
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
            sidebar_html(profile, {}),
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


def enforce_budget_rules(report_data: dict[str, Any], learning_budget: str) -> dict[str, Any]:
    if learning_budget.startswith("0 EUR"):
        for resource in report_data.get("resources", []):
            if isinstance(resource, dict):
                resource["paid"] = []
    return report_data


def create_report(
    profile: dict[str, Any],
    discovery: dict[str, Any],
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
        result = enforce_budget_rules(result, learning_budget)
        result = apply_verified_courses(
            result,
            learning_budget=learning_budget,
            time_budget=time_budget,
            adaptation=adaptation,
        )
        report = render_report(result)
        download_path = write_report_file(report)
        return (
            gr.update(visible=False),
            gr.update(visible=True),
            f'<article class="cn-report-content">{markdown_to_basic_html(report)}</article>',
            download_path,
            "",
        )
    except ValueError as exc:
        message = str(exc) if str(exc) != CV_ERROR else CV_ERROR
        return (gr.update(visible=True), gr.update(visible=False), "", None, message)
    except ConfigError as exc:
        print(exc)
        return (gr.update(visible=True), gr.update(visible=False), "", None, CONFIG_ERROR)
    except Exception:
        traceback.print_exc()
        return (gr.update(visible=True), gr.update(visible=False), "", None, API_ERROR)


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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
:root {
  --cn-bg: #070d0a;
  --cn-primary: #f4fff6;
  --cn-text: #d6ede0;
  --cn-soft: #9fc2ac;
  --cn-muted: #7fa88f;
  --cn-accent: #5be08a;
  --cn-warn: #e0c85b;
  --cn-alert: #e07a5b;
  --cn-line: rgba(255,255,255,.09);
}
.gradio-container {
  background: var(--cn-bg) !important;
  color: #eafbee !important;
  font-family: Inter, system-ui, sans-serif !important;
  min-height: 100vh !important;
  overflow-x: hidden !important;
}
body {
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
.container {
  width: min(1180px, calc(100vw - 32px));
  margin: 0 auto;
}
.workspace-shell {
  min-height: auto !important;
  padding: 24px 0 40px !important;
  align-content: start !important;
}
.upload-shell {
  min-height: min(620px, calc(100vh - 24px));
  display: grid;
  align-content: center;
  gap: 22px;
  background-image: radial-gradient(ellipse 900px 500px at 20% 0%, rgba(30,90,55,.25), transparent 60%);
  padding: 24px 0;
}
.upload-panel {
  border: 1px solid var(--cn-line);
  border-radius: 16px;
  padding: 28px;
  max-height: calc(100vh - 48px);
  overflow: auto;
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
.composer-input textarea {
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
.cn-shell {
  min-height: min(680px, calc(100vh - 48px));
  background: #070d0a;
  background-image: radial-gradient(ellipse 900px 500px at 20% 0%, rgba(30,90,55,.25), transparent 60%);
  padding: 28px 0 8px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 22px;
  color: #eafbee;
}
.cn-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.cn-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  font-weight: 600;
  font-size: 14.5px;
}
.cn-logo {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--cn-accent);
  color: #07130c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
}
.cn-status {
  font: 500 11.5px JetBrains Mono, monospace;
  letter-spacing: .05em;
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
  grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
  gap: 22px;
  flex: 1;
  min-height: 0;
  align-items: start;
}
.cn-live-layout {
  display: grid !important;
  grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr) !important;
  align-items: start !important;
}
.cn-chat-panel, .cn-side-card, .interview-panel, .report-shell {
  border: 1px solid var(--cn-line);
  background: transparent;
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
  background-image: linear-gradient(135deg, transparent 46%, rgba(91,224,138,.05) 47%, transparent 48%);
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
  background: rgba(255,255,255,.05);
  border-radius: 14px;
  padding: 10px 15px;
  font-size: 13.5px;
  color: #eafbee;
}
.cn-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.cn-chips span {
  border: 1px solid rgba(255,255,255,.14);
  border-radius: 999px;
  padding: 6px 13px;
  font-size: 12px;
  color: #bcd9c7;
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
  font: 500 10.5px JetBrains Mono, monospace;
  letter-spacing: .08em;
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
  font: 500 12px JetBrains Mono, monospace;
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
  font: 500 10px JetBrains Mono, monospace;
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
  font: 500 9.5px JetBrains Mono, monospace;
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
.cn-report-content {
  color: var(--cn-text);
  font-size: 14px;
  line-height: 1.65;
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
  color: #eafbee !important;
}
textarea {
  resize: vertical !important;
}
button.primary {
  background: var(--cn-accent) !important;
  color: #07130c !important;
}
.prose, .prose * {
  color: var(--cn-text);
}
@media (max-width: 900px) {
  .container {
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
  .upload-panel h1,
  .cn-heading h1 {
    font-size: 26px;
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

with gr.Blocks(title="AI Career Navigator", css=CSS) as demo:
    profile_state = gr.State({})
    discovery_state = gr.State({})

    with gr.Column(visible=True, elem_classes=["container", "upload-shell"]) as screen_upload:
        with gr.Column(elem_classes="upload-panel"):
            gr.Markdown("# AI Career Navigator")
            gr.Markdown("Welcome. Paste your CV or upload a PDF, and I will turn it into a focused career workspace with AI exposure, courses, and next steps.")
            with gr.Row(elem_classes="composer-row"):
                cv_text = gr.Textbox(
                    label="",
                    lines=1,
                    max_lines=4,
                    placeholder="Paste your CV text here, or upload a PDF next to this line...",
                    elem_classes="composer-input",
                )
                cv_file = gr.UploadButton("Upload CV", file_types=[".pdf"], file_count="single", elem_classes="composer-upload")
            start_button = gr.Button("Start analysis", variant="primary")
            gr.Markdown("Your CV is not stored. The analysis runs once through your configured AI provider.", elem_classes="privacy")
            upload_error = gr.Markdown(visible=True)

    with gr.Column(visible=False, elem_classes=["container", "workspace-shell"]) as screen_workspace:
        with gr.Row(elem_classes=["cn-grid", "cn-live-layout"]):
            with gr.Column():
                teaser_markdown = gr.HTML()
                with gr.Column(visible=True, elem_classes="interview-panel") as interaction_panel:
                    gr.Markdown("## Short interview")
                    gr.Markdown("Four answers are enough to keep the workspace specific. Large models may take 60-120 seconds.")
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
                    download_button = gr.DownloadButton("Download workspace notes")
                    reset_button = gr.Button("New analysis")
            live_sidebar = gr.HTML()

    start_event = start_button.click(
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
    start_event.then(
        fn=refresh_discovery,
        inputs=[profile_state],
        outputs=[live_sidebar, discovery_state],
        api_name=False,
        show_progress="hidden",
    )
    report_button.click(
        fn=create_report,
        inputs=[profile_state, discovery_state, adaptation, time_budget, learning_budget, trigger],
        outputs=[interaction_panel, report_panel, report_markdown, download_button, interview_error],
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
    demo.queue(default_concurrency_limit=4).launch(server_name="0.0.0.0", server_port=7860, show_error=True)
