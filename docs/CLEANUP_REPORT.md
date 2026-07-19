# Cleanup & Issues Report v2 — AI Career Navigator

Re-audit date: 2026-07-19 (second pass). Scope: full re-review of `app.py`,
`courses/matcher.py`, `courses/catalog.json`, `tests/`, `.gitignore`, `README.md`,
and `docs/` at commit `a947325`. Supersedes the v1 report from earlier today.

Verified working: `python -m py_compile app.py courses/matcher.py` passes;
`python -m unittest tests.test_app_core` passes 7/7; all 6 functions in
`tests/test_courses.py` pass when invoked manually (see finding N2 for why
"manually"). Line numbers refer to `app.py` at `a947325`.

---

## Status of v1 findings

Resolved since v1 (verified in code, no action needed):

- CSS `[class*="assistant"]` no longer hides the app's own chat bubbles — the
  overbroad hide-rules were removed.
- Live discovery no longer blocks the first screen — `start_analysis` returns
  immediately and `start_event.then(refresh_discovery, ...)` fills the sidebar
  afterward (`app.py:1741-1765`).
- The Arbeitnow feed is fetched once in `live_discovery` and passed to both
  consumers.
- Short pasted text + valid PDF now falls through to the PDF (tested).
- `reset_app` clears `interview_error` (18 outputs, matching).
- Config errors surface as a distinct `CONFIG_ERROR` message via `ConfigError`.
- Invalid model JSON maps to `JSON_RESPONSE_ERROR` instead of leaking parser
  internals; `call_json` now does a structured repair attempt and
  `extract_first_json_object` handles prose-wrapped JSON (both tested).
- `discovery_rows` only links `http`/`https` URLs (tested).
- Report temp files go to a dedicated dir with 24-hour pruning
  (`write_report_file`/`prune_report_files`).
- v1 dead code deleted (DuckDuckGo scraper chain, `render_teaser`,
  `dashboard_html`, `report_shell_html`, `live_enabled`, DEBUG prints).
- `.gitignore` added; `__pycache__` and the zip are untracked and ignored.
- English migration of UI, prompts, and report largely done (plan P1).
- Verified course catalog + deterministic matcher landed (plan P5) with tests.

Still open from v1 (carried forward):

- **O1. Default model ID `claude-sonnet-4-6` unverified** (`app.py:23,26`,
  `README.md:62,143`). If it is not a served model ID, every out-of-the-box
  Anthropic run fails with the generic API error. Verify against current
  Anthropic docs; the current Sonnet ID is `claude-sonnet-5` as of this audit.
- **O2. Google Fonts `@import`** (`app.py:1232`) still leaks visitor IPs to
  Google — a recurring GDPR problem for the German target audience and at odds
  with the "your CV is not stored" privacy posture. Self-host or use system fonts.
- **O3. Exact-phrase company search query** (`app.py:460`):
  `f'hiring companies Germany "{profile_query(profile)}"'` quotes the whole
  role+industry+skills string as one phrase — near-guaranteed zero results.
  Unquote or quote individual terms.
- **O4. `.agents/` is still an empty directory** — delete.
- **O5. Leftover German strings**: error texts `Unbekannter OPENAI_API_MODE` /
  `Unbekannter LLM_PROVIDER` (`app.py:228,245`), upload filename
  `lebenslauf.pdf` (`app.py:287`), fallback string
  `"Passende Live-Stelle gefunden"` (`app.py:486`), and the German default
  `'gelb'` passed to `rating_icon` (`app.py:927`). All work today (the rating
  map keeps German keys) but violate plan P1's "no German in the primary
  workflow".

---

## New findings (introduced or exposed by the recent changes)

### N1. Budget cap above zero is not actually enforced

`courses/matcher.py:157-166` — `course_fits_constraints` only special-cases
`max_budget_eur == 0`. For "up to 50 EUR/month" the parsed cap (50) is never
compared to anything, because catalog entries have no numeric cost field (only
`cost_type` + free-text `cost_note`). A 300-EUR subscription course passes the
"up to 50 EUR" filter. Related latent bug: `parse_budget("over 50 EUR/month")`
returns 50 as a *maximum*, inverting the option's meaning ("over 50" = high
budget, not capped at 50) — harmless today, wrong the moment numeric filtering
is added. **Fix:** add a numeric `cost_eur_per_month` (or similar) field to the
catalog and compare it; treat "over X" budgets as uncapped.

### N2. Half the test suite cannot run in this environment

`tests/test_courses.py` is pytest-style (module-level functions, bare asserts)
but pytest is not installed and not in `requirements.txt`; `python -m pytest`
fails with "No module named pytest" and `unittest` does not collect
function-style tests. The tests do pass when invoked manually. Also
`test_catalog_json_is_plain_list_for_app_loading` opens
`Path("courses/catalog.json")` relative to CWD, so it breaks when run from any
other directory. **Fix:** add a `requirements-dev.txt` (or extras) with pytest,
or convert to `unittest` style like `test_app_core.py`; resolve the catalog
path via `Path(__file__).parents[1]`. Then add a minimal CI workflow that runs
the whole suite — nothing runs these tests automatically today.

### N3. Invented LLM courses still reach the user when the catalog has no match

`apply_verified_courses` (`app.py:902-918`) replaces `resources` only when the
matcher returned something. When it returns nothing, the LLM-generated
resources (which the architecture doc says must never be shown — the model may
invent names) are kept, *and* `course_fallbacks` for every gap are appended, so
the report shows unverified courses plus "Still to research" lines for the same
gaps. **Fix:** when verified matches are empty, drop the LLM resource names and
show only the fallback search phrases (or clearly label LLM suggestions as
unverified).

### N4. Report shows normalized-lowercase gap labels

`verified_course_resources` (`app.py:882-899`) keys `resources_by_gap` by
`item["matched_gaps"][0]`, which is the *normalized id* (lowercased) from
`normalize_gaps`, so section headers in the final report render as e.g.
"prompt engineering" instead of the model's original gap phrasing. Map ids back
to original labels (the matcher already carries `label` per gap).

### N5. Sidebar COURSES tile ignores the catalog it advertises

`course_suggestions` (`app.py:541-555`) still populates the sidebar via live
web search, and its data note reads "Temporary search fallback until the
verified course catalog is merged" (`app.py:760`) — but the catalog *is*
merged. The tile should call `match_courses` on profile skills (offline,
deterministic, no API key needed) and the stale note should go. Bonus: without
a Tavily/SerpAPI key this tile is currently always empty.

### N6. `app_shell_html` is now dead code

`app.py:766-791` — its only former callers (`dashboard_html`,
`report_shell_html`) were deleted in the cleanup; nothing references it (one
grep hit: the definition). Deleting it also removes the regex-parsing-own-HTML
hack it contained. If a combined shell is wanted later, rebuild it from
`sidebar_html` returning structured values.

### N7. Dead `except` clause in `interesting_jobs`

`app.py:502-524` — the `try/except (OSError, URLError, JSONDecodeError)` used
to guard a network call; the function now only iterates an in-memory list, so
the handler is unreachable. Remove it (network errors are already handled in
`live_discovery`).

### N8. Misleading "public web search" label without a search provider

`sidebar_html` (`app.py:699-704`): when neither Tavily nor SerpAPI is
configured, the note says "Live data: Arbeitnow + public web search" — but the
public (DuckDuckGo) fallback was removed, so no web search exists on that path
and the companies tile stays empty forever. Say "web search not configured"
(and consider hiding the companies tile in that case).

### N9. Doc inconsistencies

- `docs/LIVE_TEST_RUN.md:40` exports `LLM_MODEL="z-ai/glm-4.5"` while
  `README.md:93` uses `z-ai/glm-5.2`, and the surrounding text talks about
  "GLM 5.2". Align on one slug.
- `LIVE_TEST_RUN.md` pins `python3.12 -m venv` while README says Python 3.11+
  and the repo also documents Python 3.14 workarounds. State one supported
  range.
- `rating_icon` (`app.py:826`) no longer returns icons — it returns
  LOW/MEDIUM/HIGH text. Rename (`rating_label`) during the next touch.
- Minor: `call_json` (`app.py:248-266`) contains a no-op
  `except Exception: raise` and logs the first parse failure from a `finally`
  attached to the repair attempt — works, but simplify to a plain
  `print`/log before the repair call.

### N10. Catalog "last_verified" dates need real verification

All 25 catalog entries carry `last_verified: 2026-07-19` (today). If these were
stamped rather than actually checked, that field is misleading — and the
product's core trust claim ("every displayed course exists and has a verified
URL", plan P5) rests on it. An agent with network access should fetch all 25
URLs and confirm 200s + correct titles; fix or remove any that fail, and only
then keep the date.

### N11. Unused `discovery` parameter on `create_report`

`app.py:1159-1166` — `discovery_state` is wired as an input but the function
body never uses it. Either drop the input + parameter, or (better, per the
product docs) pass discovery/company context into PROMPT_2 so the strategy can
reference real jobs.

---

## Suggested execution order for the fixing agent

1. **N2** — make the whole test suite runnable (dev deps + path fix + CI);
   everything after this gets regression coverage for free.
2. **N6, N7, N11** — dead-code removals; one mechanical commit.
3. **N3, N4** — course-resource correctness in the report path.
4. **N1** — numeric budget enforcement (catalog schema change + matcher +
   tests).
5. **N5, N8** — sidebar course tile from catalog; honest live-data notes.
6. **O1** — verify/replace the default model ID (quick, high user impact).
7. **O3, O5, N9** — query fix, German leftovers, doc alignment; small batch.
8. **N10** — catalog URL verification run (needs network).
9. **O2, O4** — fonts self-hosting and empty-dir removal.

Steps 2-5 each deserve their own commit. After each: `python -m py_compile
app.py courses/matcher.py`, run the full test suite, and one manual pasted-CV
run per `docs/LIVE_TEST_RUN.md`.
