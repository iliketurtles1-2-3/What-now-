import base64
import json
import os
import re
import tempfile
import traceback
from pathlib import Path
from typing import Any

import gradio as gr


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
OPENAI_API_MODE = os.getenv("OPENAI_API_MODE", "responses").strip().lower()
OPENAI_JSON_MODE = os.getenv("OPENAI_JSON_MODE", "").strip().lower() in {"1", "true", "yes"}
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4.1",
}
MODEL = os.getenv("LLM_MODEL", DEFAULT_MODELS.get(LLM_PROVIDER, "claude-sonnet-4-6"))
MAX_PDF_BYTES = 10 * 1024 * 1024
CV_ERROR = "Der Lebenslauf konnte nicht gelesen werden. Bitte lade ein PDF hoch oder füge den Text direkt ein."
API_ERROR = "Die Analyse ist gerade nicht verfügbar. Bitte versuche es in einer Minute erneut."

ADAPTATION_OPTIONS = [
    "🟢 Optimieren – Ich will in meiner Rolle bleiben und smarter mit KI arbeiten",
    "🟡 Weiterentwickeln – Ich bin offen für einen Rollenwechsel in 6–12 Monaten",
    "🔴 Neu erfinden – Ich bin bereit für einen echten Pivot",
]
TIME_OPTIONS = ["< 2 Std./Woche", "2–5 Std./Woche", "5–10 Std./Woche", "> 10 Std./Woche"]
BUDGET_OPTIONS = ["0 € (nur kostenlos)", "bis 50 €/Monat", "über 50 €/Monat"]

PROMPT_1 = """
Du bist ein Karriereanalyst, spezialisiert auf die Auswirkungen von KI auf Berufsbilder. Du erhältst einen Lebenslauf. Extrahiere ein strukturiertes Profil und formuliere drei prägnante erste Beobachtungen.

Antworte NUR mit validem JSON, exakt in diesem Schema:
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

Regeln für die Teaser-Beobachtungen:
- Jede Beobachtung 1–2 Sätze, auf Deutsch, per Du.
- Beobachtung 1: Stärkstes Asset des Profils im KI-Zeitalter.
- Beobachtung 2: Eine konkrete, ehrliche Exponierung (welche Tätigkeiten sich durch KI stark verändern werden) – ohne Panikmache, mit Begründung.
- Beobachtung 3: Eine überraschende oder nicht offensichtliche Chance, die sich aus dem Profil ergibt.
- Sei spezifisch: beziehe dich auf konkrete Stationen/Tätigkeiten aus dem Lebenslauf, nie generisch.
- "ai_tool_signals": alle Hinweise auf bereits vorhandene KI-Tool-Nutzung; leere Liste wenn keine.
""".strip()

PROMPT_2 = """
Du bist ein Karrierestratege für die KI-Ökonomie. Du erhältst ein strukturiertes Berufsprofil und die Antworten aus einem Kurzinterview. Erstelle einen persönlichen Report.

GRUNDPRINZIPIEN:
- Sprich den Nutzer mit Du an. Deutsch. Konkret statt generisch: Jede Aussage muss sich erkennbar auf DIESES Profil beziehen. Wenn zwei verschiedene Lebensläufe denselben Report bekämen, hast du versagt.
- Ehrlichkeit über Unsicherheit: Formuliere KI-Exponierung als "Veränderungsdruck", nicht als Ersetzungs-Prophezeiung. Begründe jede Einschätzung.
- RESSOURCEN-REGEL (kritisch): Empfiehl NUR real existierende, breit bekannte Anbieter (z. B. Coursera, DeepLearning.AI, fast.ai, Google Skillshop, LinkedIn Learning, Udemy, edX, Maven, lokale IHK-Angebote, Meetup). Erfinde NIEMALS Kursnamen. Wenn du keinen konkreten Kurs sicher kennst, schreibe stattdessen: "Suche nach: [Kurstyp-Beschreibung]".
- Das Adaptionslevel steuert die Tiefe: Optimieren = kleine Schritte in der aktuellen Rolle; Weiterentwickeln = angrenzende Rollen, ein Portfolio-Projekt; Neu erfinden = vollständige Brücke inkl. Bewerbungsphase.
- Zeitbudget und Lernbudget sind harte Constraints: Empfiehl nichts, was sie überschreitet. Bei Budget "0 €" ausschließlich kostenlose Ressourcen.

Antworte NUR mit validem JSON, exakt in diesem Schema:
{
  "exposure": [
    {"task": string, "rating": "gruen" | "gelb" | "rot", "reasoning": string}
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
    {"gap": string, "free": [{"name": string, "format": "Kurs" | "Projekt" | "Community" | "On-the-Job", "time_cost": string}], "paid": [{"name": string, "format": string, "cost_estimate": string, "time_cost": string}]}
  ],
  "repositioning": {
    "cv_bullets": [string, string, string],
    "linkedin_headline": string
  },
  "closing_note": string
}

MENGENVORGABEN:
- exposure: 5–8 Aufgaben aus dem realen Profil, jede mit 1-Satz-Begründung.
- gaps: genau 3 (Optimieren: 2 reichen).
- plan_100: 3–4 Blöcke in Wochen-Granularität (z. B. "Woche 1–2"), endet mit einem konkreten Artefakt.
- plan_365: 4 Quartale; Q1 verweist auf den 100-Tage-Plan.
- decision_gates: genau 2.
- resources: pro Gap mindestens 1 kostenlose Option; bezahlte nur wenn Budget > 0 €.
- cv_bullets: umgeschriebene Bullets basierend auf echten Stationen des Profils, Ton passend zum Adaptionslevel.
- closing_note: 2–3 Sätze, motivierend aber nüchtern, keine Floskeln.
""".strip()


def strip_json_fences(text: str) -> str:
    clean = text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    return clean.strip()


def parse_json_response(text: str) -> dict[str, Any]:
    return json.loads(strip_json_fences(text))


def extract_text_from_response(response: Any) -> str:
    chunks = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            chunks.append(block.text)
    return "\n".join(chunks).strip()


def anthropic_client() -> Any:
    from anthropic import Anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY fehlt")
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=120.0)


def openai_client() -> Any:
    from openai import OpenAI

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY fehlt")
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
    last_error = None
    for _ in range(2):
        try:
            return parse_json_response(call_model(system_prompt, user_content, max_tokens))
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        except Exception:
            raise
    raise ValueError(f"JSON konnte nicht gelesen werden: {last_error}")


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
            raise ValueError(CV_ERROR)
        return f"Analysiere diesen eingefügten Lebenslauf:\n\n{text}"

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
        {"type": "text", "text": "Analysiere diesen PDF-Lebenslauf."},
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


def render_teaser(teaser: list[str]) -> str:
    items = teaser[:3] if isinstance(teaser, list) else []
    while len(items) < 3:
        items.append("Keine Beobachtung verfügbar.")
    bullets = "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, start=1))
    return f"## Erste Beobachtungen\n\n{bullets}"


def escape_html(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def exposure_level_for_task(task: str) -> tuple[str, str]:
    lower = task.lower()
    high_terms = ["report", "analyse", "daten", "content", "text", "recherche", "dokument", "crm", "seo"]
    low_terms = ["stakeholder", "führung", "strategie", "verhandlung", "beratung", "team", "kunden", "kommunikation"]
    if any(term in lower for term in high_terms):
        return ("hoch", "#e07a5b")
    if any(term in lower for term in low_terms):
        return ("niedrig", "#5be08a")
    return ("mittel", "#e0c85b")


def dashboard_html(profile: dict[str, Any], teaser: list[str], source_label: str) -> str:
    role = escape_html(profile.get("current_role") or "Profil aus Lebenslauf")
    industry = escape_html(profile.get("industry") or "Branche wird aus dem Profil abgeleitet")
    years = profile.get("years_experience")
    years_label = f"{years:g} Jahre" if isinstance(years, (int, float)) else "Erfahrung erkannt"
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
        task_rows.append('<div class="cn-row cn-muted"><span>Weitere Aufgabe</span><span>— nach Report</span></div>')

    teaser_items = "".join(f"<li>{escape_html(item)}</li>" for item in (teaser or [])[:3])
    skill_line = " · ".join(skills) if skills else "Skills werden im Report priorisiert"
    ai_line = "KI-Signale erkannt" if ai_signals else "Noch keine KI-Tool-Signale im CV"
    pressure = "MEDIUM"
    pressure_color = "#e0c85b"
    if task_candidates:
        levels = [exposure_level_for_task(str(task))[0] for task in task_candidates[:3]]
        if levels.count("hoch") >= 2:
            pressure, pressure_color = "HIGH", "#e07a5b"
        elif levels.count("niedrig") >= 2:
            pressure, pressure_color = "LOW", "#5be08a"

    return f"""
<div class="cn-shell">
  <div class="cn-topbar">
    <div class="cn-brand"><div class="cn-logo">A</div><div>AI Career Navigator</div></div>
    <div class="cn-status">
      <span>STATUS <strong>▲ ADAPTING</strong></span>
      <span>CHANGE PRESSURE <strong style="color:{pressure_color}">{pressure}</strong></span>
    </div>
  </div>
  <div class="cn-grid">
    <section class="cn-chat-panel">
      <div class="cn-accent"></div>
      <div class="cn-heading">
        <h1>Finde heraus, wo KI<br>deine Arbeit verändert.</h1>
        <p>{role}, {industry} · {escape_html(years_label)} · {escape_html(source_label)}</p>
      </div>
      <div class="cn-messages">
        <div class="cn-assistant">
          Dein Lebenslauf ist geparst. Ich sehe jetzt dein Rollenprofil, erste Veränderungsfelder und die nächsten Entscheidungen, die deinen Report steuern.
          <div class="cn-chips">
            <span>Exponierung prüfen</span>
            <span>100-Tage-Plan bauen</span>
            <span>Narrativ schärfen</span>
          </div>
        </div>
        <div class="cn-user">📄 {escape_html(source_label)}</div>
        <div class="cn-assistant">
          <strong>Erste Beobachtungen</strong>
          <ol>{teaser_items}</ol>
        </div>
      </div>
    </section>
    <aside class="cn-sidebar">
      <section class="cn-side-card cn-profile">
        <div class="cn-kicker">PROFILE</div>
        <h2>{role}</h2>
        <p>{industry} · {seniority} · {escape_html(years_label)}</p>
        <div class="cn-detail">{''.join(task_rows)}</div>
      </section>
      <section class="cn-side-card">
        <div class="cn-kicker">LEARN</div>
        <h2>100-Tage-Plan</h2>
        <p>{escape_html(ai_line)} · Zeitbudget folgt im Interview</p>
        <div class="cn-detail">
          <div><span class="cn-ok">✓</span> Profil extrahiert</div>
          <div><span class="cn-ok">✓</span> Veränderungsfelder markiert</div>
          <div class="cn-muted">— Lernpfad nach deinen Antworten</div>
        </div>
      </section>
      <section class="cn-side-card">
        <div class="cn-kicker">POSITIONING</div>
        <h2>Narrativ</h2>
        <p>{skill_line}</p>
        <div class="cn-detail">FOKUS <span class="cn-accent-text">CV-Bullets + LinkedIn Headline</span></div>
      </section>
      <section class="cn-side-card">
        <div class="cn-kicker">NEXT ROLE</div>
        <h2>Zielrichtung</h2>
        <p>Wird aus Adaptionslevel, Zeitbudget und Budget abgeleitet</p>
        <div class="cn-detail">TOP FIT <span class="cn-accent-text">nach Report-Erstellung</span></div>
      </section>
    </aside>
  </div>
</div>
"""


def rating_icon(rating: str) -> str:
    return {"gruen": "🟢", "gelb": "🟡", "rot": "🔴"}.get(str(rating).lower(), "🟡")


def render_report(data: dict[str, Any]) -> str:
    lines = ["# Dein KI-Karriere-Report", ""]

    lines += ["## 1. Wo KI deine Arbeit verändert", "", "| Aufgabe | Einschätzung | Begründung |", "|---|---|---|"]
    for item in data.get("exposure", []):
        lines.append(
            f"| {item.get('task', '')} | {rating_icon(item.get('rating', 'gelb'))} | {item.get('reasoning', '')} |"
        )
    lines += ["", data.get("exposure_summary", ""), ""]

    lines += ["## 2. Deine 3 wichtigsten Lücken", ""]
    for idx, gap in enumerate(data.get("gaps", []), start=1):
        lines.append(f"{idx}. **{gap.get('gap', '')}**: {gap.get('why_it_matters', '')}")
    lines.append("")

    lines += ["## 3. Deine ersten 100 Tage", ""]
    for block in data.get("plan_100", []):
        lines.append(f"**{block.get('weeks', '')}: {block.get('focus', '')}**")
        for action in block.get("actions", []):
            lines.append(f"- {action}")
        lines.append(f"→ Ergebnis: {block.get('outcome', '')}")
        lines.append("")

    lines += ["## 4. Dein 365-Tage-Fahrplan", ""]
    for quarter in data.get("plan_365", []):
        lines.append(f"**{quarter.get('quarter', '')}: {quarter.get('theme', '')}**")
        for milestone in quarter.get("milestones", []):
            lines.append(f"- {milestone}")
        lines.append("")
    lines += ["### Entscheidungspunkte", ""]
    for gate in data.get("decision_gates", []):
        lines.append(f"- **{gate.get('when', '')}:** {gate.get('question', '')}")
        lines.append(f"  - Wenn ja: {gate.get('if_yes', '')}")
        lines.append(f"  - Wenn nein: {gate.get('if_no', '')}")
    lines.append("")

    lines += ["## 5. Lernressourcen", ""]
    for resource in data.get("resources", []):
        lines.append(f"**{resource.get('gap', '')}**")
        lines.append("**Kostenlos:**")
        for item in resource.get("free", []):
            lines.append(f"- {item.get('name', '')} ({item.get('format', '')}, {item.get('time_cost', '')})")
        paid = resource.get("paid", [])
        if paid:
            lines.append("**Kostenpflichtig:**")
            for item in paid:
                lines.append(
                    f"- {item.get('name', '')} ({item.get('format', '')}, {item.get('cost_estimate', '')}, {item.get('time_cost', '')})"
                )
        lines.append("")

    repositioning = data.get("repositioning", {})
    lines += ["## 6. Dein neues Narrativ", ""]
    for bullet in repositioning.get("cv_bullets", []):
        lines.append(f"- {bullet}")
    lines.append("")
    lines.append(f"> {repositioning.get('linkedin_headline', '')}")
    lines.append("")
    lines.append(f"*{data.get('closing_note', '')}*")
    lines.append("")
    lines.append(
        "*Hinweis: KI-Exponierungs-Einschätzungen sind fundierte Prognosen, keine Gewissheiten. Dieser Report wurde KI-gestützt erstellt.*"
    )
    return "\n".join(lines)


def write_report_file(markdown: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".md", encoding="utf-8")
    with handle:
        handle.write(markdown)
    return handle.name


def start_analysis(uploaded_file: Any, cv_text: str | None):
    print("DEBUG start_analysis called", flush=True)
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
            gr.update(visible=False),
            dashboard_html(profile, teaser, "Profil aus deinem CV"),
            profile,
            "",
        )
    except ValueError as exc:
        return (
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            "",
            {},
            str(exc) if str(exc) == CV_ERROR else API_ERROR,
        )
    except Exception:
        traceback.print_exc()
        return (gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), "", {}, API_ERROR)


def enforce_budget_rules(report_data: dict[str, Any], learning_budget: str) -> dict[str, Any]:
    if learning_budget.startswith("0 €"):
        for resource in report_data.get("resources", []):
            if isinstance(resource, dict):
                resource["paid"] = []
    return report_data


def create_report(profile: dict[str, Any], adaptation: str, time_budget: str, learning_budget: str, trigger: str):
    print("DEBUG create_report called", flush=True)
    try:
        if not profile:
            raise ValueError(CV_ERROR)
        if not adaptation or not time_budget or not learning_budget:
            raise ValueError("Bitte beantworte die drei Pflichtfragen.")

        interview = {
            "adaptionslevel": adaptation,
            "zeitbudget": time_budget,
            "lernbudget": learning_budget,
            "ausloeser": (trigger or "").strip(),
        }
        user_payload = json.dumps({"profile": profile, "interview": interview}, ensure_ascii=False, indent=2)
        result = call_json(PROMPT_2, f"Erstelle den Report aus diesen Daten:\n\n{user_payload}", 8000)
        result = enforce_budget_rules(result, learning_budget)
        report = render_report(result)
        download_path = write_report_file(report)
        return (
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            report,
            download_path,
            "",
        )
    except ValueError as exc:
        message = str(exc) if str(exc) != CV_ERROR else CV_ERROR
        return (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), "", None, message)
    except Exception:
        traceback.print_exc()
        return (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), "", None, API_ERROR)


def reset_app():
    print("DEBUG reset_app called", flush=True)
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
        None,
        "",
        "",
        {},
        None,
        None,
        None,
        "",
        "",
        None,
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
.gradio-container > div:last-child svg {
  display: none !important;
}
.container {
  width: min(1180px, calc(100vw - 32px));
  margin: 0 auto;
}
.upload-shell {
  min-height: auto;
  display: grid;
  align-content: center;
  gap: 22px;
  background-image: radial-gradient(ellipse 900px 500px at 20% 0%, rgba(30,90,55,.25), transparent 60%);
  padding: 24px 0;
}
.upload-panel {
  border: 1px solid var(--cn-line);
  border-radius: 20px;
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
.upload-panel .file-preview,
.upload-panel [data-testid="file-preview"],
.upload-panel .upload-container,
.upload-panel .dropzone,
.upload-panel [class*="dropzone"] {
  min-height: 140px !important;
  max-height: 190px !important;
}
.upload-panel textarea {
  min-height: 160px !important;
  height: 180px !important;
}
.upload-panel button {
  min-height: 42px !important;
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
  grid-template-columns: minmax(0, 1.3fr) minmax(320px, 1fr);
  gap: 22px;
  flex: 1;
  min-height: 0;
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

with gr.Blocks(title="KI-Karriere-Check", css=CSS) as demo:
    profile_state = gr.State({})

    with gr.Column(visible=True, elem_classes=["container", "upload-shell"]) as screen_upload:
        with gr.Column(elem_classes="upload-panel"):
            gr.Markdown("# KI-Karriere-Check")
            gr.Markdown("Lade deinen Lebenslauf hoch und sieh, wo KI deine Arbeit verändert, welche Lücken wirklich zählen und wie du dich positionierst.")
            cv_file = gr.File(label="Lebenslauf als PDF hochladen", file_types=[".pdf"], file_count="single")
            cv_text = gr.Textbox(label="Oder Lebenslauf als Text einfügen", lines=6, placeholder="Mindestens 300 Zeichen ...")
            start_button = gr.Button("Analyse starten", variant="primary")
            gr.Markdown("Dein Lebenslauf wird nicht gespeichert. Die Analyse erfolgt einmalig über den konfigurierten KI-Anbieter.", elem_classes="privacy")
            upload_error = gr.Markdown(visible=True)

    with gr.Column(visible=False, elem_classes="container") as screen_interview:
        teaser_markdown = gr.HTML()
        with gr.Column(elem_classes="interview-panel"):
            gr.Markdown("## Kurzinterview")
            gr.Markdown("Vier Antworten reichen, damit der Report nicht generisch wird. Die Report-Erstellung kann mit großen Modellen 60–120 Sekunden dauern.")
            with gr.Row():
                adaptation = gr.Radio(ADAPTATION_OPTIONS, label="Adaptionslevel", interactive=True)
                time_budget = gr.Radio(TIME_OPTIONS, label="Zeitbudget", interactive=True)
            with gr.Row():
                learning_budget = gr.Radio(BUDGET_OPTIONS, label="Lernbudget", interactive=True)
                trigger = gr.Textbox(label="Auslöser", placeholder="Was hat dich heute hierher gebracht?", lines=4)
            report_button = gr.Button("Vollständigen Report erstellen", variant="primary")
            gr.Markdown("Während der Erstellung bleibt diese Ansicht sichtbar. Warte bitte, bis der Report automatisch erscheint.", elem_classes="privacy")
            interview_error = gr.Markdown()

    with gr.Column(visible=False, elem_classes=["container", "report-shell"]) as screen_report:
        report_markdown = gr.Markdown()
        download_button = gr.DownloadButton("Report als Markdown herunterladen")
        reset_button = gr.Button("Neue Analyse")

    start_button.click(
        fn=start_analysis,
        inputs=[cv_file, cv_text],
        outputs=[screen_upload, screen_interview, screen_report, teaser_markdown, profile_state, upload_error],
        api_name=False,
        show_progress="full",
        scroll_to_output=True,
    )
    report_button.click(
        fn=create_report,
        inputs=[profile_state, adaptation, time_budget, learning_budget, trigger],
        outputs=[screen_upload, screen_interview, screen_report, report_markdown, download_button, interview_error],
        api_name=False,
        show_progress="full",
        scroll_to_output=True,
    )
    reset_button.click(
        fn=reset_app,
        inputs=[],
        outputs=[
            screen_upload,
            screen_interview,
            screen_report,
            cv_file,
            cv_text,
            teaser_markdown,
            profile_state,
            adaptation,
            time_budget,
            learning_budget,
            trigger,
            report_markdown,
            download_button,
            upload_error,
        ],
        api_name=False,
        scroll_to_output=True,
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch(server_name="0.0.0.0", server_port=7860, show_error=True)
