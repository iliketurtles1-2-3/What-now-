# Recommendation Contract Review

Status: planning document. No prompts, no application code. Critiques the
proposed objects (`CareerProfile`, `InterviewAnswers`, `CareerPathway`,
`RecommendationSet`, `WorkspaceState`) against the product rules:

- No assumed startup work, entrepreneurship, Python, AI agents, or a
  technology career.
- AI is one workplace-change factor, not the destination.

Where this document references existing code, it means the current
`app.py` schemas and `courses/matcher.py` at commit `a947325`.

---

## 1. Object-by-object critique

### 1.1 CareerProfile

Today's extraction schema (current_role, seniority, industry,
years_experience, roles, skills, education, ai_tool_signals, languages) is a
tech-office silhouette. Problems and gaps:

**Missing fields (required):**

- `evidence_items[]` — every extracted claim as an addressable unit:
  `{id, kind: role|task|outcome|skill|education|credential|signal, quote,
  location_hint}` where `quote` is a **verbatim substring of the CV**. This is
  the single most important change: pathways must cite evidence by `id`, and
  code can then verify quotes actually occur in the source text. Without
  addressable evidence, "CV evidence" in a pathway is just more prose the
  model can hallucinate.
- `outcomes` distinct from tasks. "Responsible for scheduling" and "cut
  overtime 20%" are different evidence classes; pathway advantages need the
  outcome class.
- `credentials_and_licenses[]` with jurisdiction where relevant. Nurses,
  electricians, teachers, drivers, accountants — for a large share of the
  workforce the license, not the skill list, determines what pathways are
  reachable. The current schema cannot represent "licensed MRI technologist"
  except as a skill string.
- `unknowns[]` — what the CV does not say (mobility, current employment
  status, why the last role ended). The architecture doc already requires
  "missing or uncertain information"; the schema never got the field.
  Pathways that depend on an unknown must reference it (see §3).
- `inconsistencies[]` — overlapping dates, contradictory claims. Needed so
  contested evidence can be excluded as primary support.
- `employment_pattern` — enum: single_employer | portfolio_freelance |
  mixed | career_break | returning. A freelancer with three concurrent
  clients and a returner with a six-year gap both break the current
  single-`current_role` + single-number `years_experience` shape.

**Fields to change:**

- `seniority: junior|mid|senior|lead` — replace or supplement. The enum is
  tech-ladder shaped and meaningless for a Meister electrician, a ward
  nurse, or a municipal clerk. Prefer observable scope facts:
  `{people_led, budget_owned, autonomy_level, years_in_current_occupation}`,
  each backed by an evidence id, with any coarse level derived in code.
- `industry: string` → `industries[]` (portfolio careers, sector switchers).
- `ai_tool_signals` → `change_signals[]` typed
  `{kind: ai_tool|automation|digitization|process_change, evidence_id}`.
  Keep AI visible but stop privileging it — a clerk whose case processing
  was digitized has a change signal with no LLM in sight.

**Not a profile field:** `teaser` (the three observations) is presentation
derived from the profile, not part of it. Keep it out of CareerProfile so
the profile can be regenerated, corrected, and diffed independently.

### 1.2 InterviewAnswers

**Change (required):** stable enum values decoupled from display strings.
The current code matches `learning_budget.startswith("0 EUR")` and
`adaptation.startswith("Optimize")` — display-string coupling is already a
known bug class in this repo. Contract:
`{ambition: optimize|develop|reinvent, time_per_week: enum,
budget: enum, trigger_text: string}` plus display labels owned by the UI.

**Missing:**

- `trigger_interpretation` — the free-text trigger is the only place users
  volunteer urgency ("I was told my department is being restructured").
  Either the contract types what is extracted from it
  (`{category: displacement_risk|dissatisfaction|income|health|curiosity|
  external_event, urgency: low|med|high, quote}`) or it declares the trigger
  non-binding context. Do not let free text silently become a hard
  constraint; do not silently ignore it either.
- `constraints` (optional, explicit-unknown): mobility/relocation,
  schedule limits, income floor. The four fixed questions under-determine
  pathway choice — a pathway that requires relocation or an income dip is
  unfilterable today. If the product keeps the interview at four questions,
  the contract must still have the slots, valued `unknown`, so pathways
  that depend on them are forced to list that dependency as an assumption
  (§3) instead of guessing.

**Unnecessary:** nothing — the object is minimal, which is right. The gap
is typing, not question count.

### 1.3 CareerPathway

The 11 mandated fields are strong. Verdicts:

**Keep as mandated:** specific thesis, CV evidence, existing advantages,
likely work environment, assumptions to test, 7–30 day experiment, success
signals, proof artifact, development needs.

**Definitional hazard — tradeoffs vs. reasons against:** these will blur
into each other and produce padded, overlapping lists unless defined
disjointly. Contract definitions:

- `tradeoffs` = costs you accept **if you pursue it** (income dip,
  schedule, status reset, longer credentialing). At least one must be a
  real loss, not a humble-brag.
- `reasons_against` = contra-indicators for **whether to pursue it at all**
  (evidence gaps, market saturation, conflict with a stated constraint).

Validation: no near-duplicate text between the two lists. If the prompt
work later can't keep them apart, merge into `costs_and_risks[]` with a
`type` enum — but try the split first; the distinction is user-valuable.

**Missing fields (required):**

- `id` and `title` — a stable identifier and a short navigable name.
  The thesis is a claim, not a label; the workspace, WorkspaceState
  references, and regeneration all need ids.
- `cv_evidence` must be **typed references**
  `{evidence_id, relevance: string}` into `CareerProfile.evidence_items`,
  not free text. This is what makes every rule in §2 and §3 enforceable.
- `kill_signals` (or `stop_criteria`) paired with success signals. Success
  signals alone are confirmation bias with a schema. The experiment needs
  a symmetric answer to "what result tells you to drop this pathway,"
  and it must be observable within the experiment window.
- `experiment.tests_assumptions: [assumption_id]` — the experiment must
  declare which assumptions it tests; assumptions must have ids. An
  experiment that tests none of the listed assumptions is decoration.
- `constraint_fit` — `{time_fit, budget_fit, ambition_fit:
  fits|stretch|violates, note}` against InterviewAnswers. Makes constraint
  honoring checkable in code instead of vibes, and lets a pathway honestly
  say "this is a stretch for your stated 2 h/week."
- `change_outlook` — one field: how workplace change (AI included) bears on
  this pathway: `{direction: tailwind|neutral|headwind, reasoning,
  claim_class}` (§3 claim classes). This keeps the product's premise
  present without making AI the destination. Note: the proposed five-object
  list silently drops the old `CareerAssessment` — the per-task exposure
  content has to live somewhere; this field plus profile `change_signals`
  is the minimum replacement. Decide explicitly, don't lose it by accident.
- `time_to_viability` — coarse horizon enum (weeks|months|year_plus).
  Tradeoffs are abstract without it.
- `development_needs` must be structured to feed the existing course
  matcher: `[{label, priority, evidence_id_of_gap}]` — `label`/`priority`
  is exactly what `courses/matcher.py::normalize_gaps` consumes. Course
  names never originate in the pathway (existing product law: catalog or
  fallback search phrase only).

**Field rules:**

- `proof_artifact` must be producible within the experiment window and
  must not presuppose tech media. "A GitHub repo" is not a neutral default;
  a shadowing log, a signed-off trial shift, three client discovery calls
  with notes, or an inspection checklist reviewed by a Meister all qualify.
- `likely_work_environment` needs concrete descriptors — schedule shape,
  setting (site/office/home/clinic), interaction load, physical demands,
  oversight/regulation. This field is where non-office careers become real;
  don't let it degrade to "dynamic team environment."

### 1.4 RecommendationSet

**Missing (required):**

- Cardinality and composition rules, in the schema not just the prompt:
  2–4 pathways; **at least one non-reinvention** option (evolve in place /
  adjacent move); **at most one** pathway whose target is tech/AI work, and
  only when supported by cited evidence; at least one pathway whose
  experiment is not "take a course."
- `ranking_policy` — recommend **unranked** with per-pathway
  `best_if: string` ("choose this if the trial shift confirms you still
  want floor operations") instead of a rank. Fake precision in ranking is a
  genericness vector. If the product later wants a default, it must carry a
  justification field.
- `conflicts[]` — surfaced contradictions between inputs (§3.3). The set
  responds to a conflict; it never silently resolves it.
- `rejected_pathways[]` (1–2, optional but valuable) — directions
  considered and declined, each with the reason and the evidence.
  Cheap trust-builder, strong anti-generic device, and eval gold.
- `sensitivity` — "what would change this set": the unknowns/assumptions
  whose resolution would most alter the recommendations.
- `generation_metadata` — profile version/hash, interview version, model,
  prompt version, timestamp. Required for regeneration, caching, and eval.

**Unnecessary:** any duplication of profile content into the set. The set
references the profile; it does not restate it.

### 1.5 WorkspaceState

**Missing (required):**

- Per-pathway status: `exploring|committed|parked|dropped`, with
  `dropped_reason` — user rejections are constraint data for regeneration.
- Per-experiment state: `not_started|running|done`, plus
  `outcome: {signals_observed[], kill_signals_observed[], user_note}`.
  The experiment produces the user's own evidence; if the state can't hold
  it, re-analysis after an experiment (a stated later-product goal) has no
  input.
- `profile_corrections[]` — user edits to the extracted profile, with
  provenance flags (`extracted|user_confirmed|user_corrected`) on profile
  fields. Extraction will be wrong; the contract must let the user fix it
  **before** pathway generation, and downstream objects must record which
  profile version they were generated from.
- Saved courses linked to `development_needs` entries (docs already promise
  save-to-plan).
- `schema_version` on this and every persisted object.

**Unnecessary:** derived presentation strings (rendered HTML, formatted
labels). State holds facts and references; renderers derive the rest.

---

## 2. Rules that prevent generic recommendations

Marked **[code]** where enforceable by validation, **[eval]** where enforced
by the evaluation harness, **[prompt]** where deferred to prompt writing.

1. **Evidence quota** [code]: every pathway cites ≥3 distinct
   `evidence_id`s, at least one of kind `role|task|outcome` (not just the
   skills list). Thesis specifically must cite ≥1.
2. **Verbatim evidence** [code]: every cited quote must be found in the CV
   text (normalized fuzzy match). Fabricated evidence ⇒ pathway invalid.
3. **Swap test** [eval]: a pathway shown against a *different* persona's CV
   must score ≤2 on specificity. If it reads plausibly for someone else,
   it was generic. Run pairwise across the six personas below.
4. **Set diversity** [code]: pairwise, pathways must differ in at least two
   of {target role family, work environment, top development need}. No two
   pathways may share a proof artifact type and primary evidence id.
5. **Neutrality guard** [code]: reject a set containing >1 tech/AI-target
   pathway; reject startup/founder/entrepreneurship theses unless the CV
   contains cited evidence of venture-relevant history; "AI skills" or
   "Python" may appear in `development_needs` only with a task-level
   justification referencing evidence.
6. **Constraint arithmetic** [code]: experiment effort ≤ stated weekly time
   × 4; experiment cost ≤ stated budget; no experiment may require quitting
   a current job or relocating. `constraint_fit: violates` on any dimension
   ⇒ the pathway must say so explicitly or be rejected.
7. **Non-course-first** [code]: ≥1 pathway whose experiment involves
   contact with the real work (shadowing, trial task, structured
   conversations, volunteering) rather than consuming a course.
8. **Anti-boilerplate blocklist** [code, list maintained in config]:
   reject theses/advantages containing stock phrases ("leverage your
   transferable skills", "upskill in AI", "growing field", "passionate
   about") — cheap lexical guard, catches the worst failures early.
9. **Length ceilings** [code]: thesis ≤2 sentences; each list capped
   (advantages ≤4, tradeoffs ≤3, etc.). Genericness hides in padding.
10. **One uncomfortable truth** [prompt, checked in eval]: each pathway's
    tradeoffs include at least one genuine loss (income, status, identity,
    time) — evaluated by rubric, elicited by prompt.

---

## 3. Rules for evidence, uncertainty, and contradiction

### 3.1 Evidence

- Three claim classes, tagged on every substantive statement in a pathway:
  `evidence_backed` (cites `evidence_id`s), `inference` (derived; must name
  the evidence it derives from), `assumption` (no evidence; **must** appear
  in `assumptions_to_test`). [code-checkable structure]
- Quotes are verbatim CV substrings, verified in code (§2 rule 2).
- Evidence references may not point into `inconsistencies[]`-flagged
  content as a pathway's *primary* support.
- No invented statistics: numeric labor-market claims (percentages,
  salaries, "X% of jobs") are rejected unless attached to a provided data
  source object. Regex-detectable. [code]
- Protected attributes (age, health, family status, nationality) that
  appear in a CV are never valid evidence for or against a pathway.
  Evidence references into such content are rejected. [code + prompt]

### 3.2 Uncertainty

- Confidence is a 3-level enum (high/medium/low) with definitions tied to
  evidence count and directness. No numeric confidence ("87% match") —
  fake precision is banned at the schema level.
- Profile `unknowns[]` are load-bearing: a pathway that depends on an
  unknown (mobility, licensing status, income needs) must carry that
  dependency as an assumption referencing the unknown. Silent gap-filling
  is a contract violation, not a style issue.
- `sensitivity` at set level names the top unknowns whose resolution would
  change the recommendations.

### 3.3 Contradiction

- Contradictions are **represented, never resolved silently** — in either
  direction. Neither "obey the interview and ignore the CV" nor the
  reverse. `RecommendationSet.conflicts[]`:
  `{type: ambition_vs_time | budget_vs_goal | trigger_vs_ambition |
  cv_vs_selfreport | internal_cv_inconsistency, statement, response}`
  where `response` explains how the set accommodates it (e.g., "you chose
  Reinvent with <2 h/week; pathway 3 is a reinvention scaled to that
  budget, and its first decision gate is whether you can free up more
  time").
- CV-internal inconsistencies (overlapping dates, conflicting claims) live
  in `profile.inconsistencies[]` and downgrade the affected evidence.
- Success signals and kill signals must be disjoint and individually
  observable; an outcome matching both is a schema error. [code]

---

## 4. Rubric for recommendation quality

Score each dimension 1–5 per RecommendationSet. Hard gates below.

| # | Dimension | 5 looks like | 1 looks like |
|---|---|---|---|
| 1 | Evidence grounding | Every claim traceable; quotes verify; claim classes correct | Invented or unverifiable evidence |
| 2 | Specificity (swap test) | Unusable for any other persona | Reads fine for anyone |
| 3 | Set diversity | Distinct directions, environments, needs | Three flavors of the same job |
| 4 | Constraint fidelity | Time/budget/ambition arithmetic holds; violations declared | Recommends beyond stated limits silently |
| 5 | Actionability | Experiment startable within 7 days with a concrete first step | "Explore opportunities in..." |
| 6 | Falsifiability | Assumptions testable; kill signals real and observable | Only success signals; untestable claims |
| 7 | Tradeoff honesty | Names a real loss the user won't like | Padded pseudo-costs |
| 8 | Neutrality | Tech/AI/startup appears only where evidence leads | Default drift to tech careers |
| 9 | Environment realism | Concrete schedule/setting/demands, accurate for the field | Generic office-speak |
| 10 | Contradiction handling | Conflicts surfaced with a reasoned response | Silently obeyed or ignored inputs |

**Gates:**

- Fabricated evidence (dimension 1 failure by quote check): automatic fail
  regardless of other scores.
- Any dimension ≤2: set fails.
- Ship threshold for user testing: average ≥4, no dimension <3
  (consistent with the bar already in `docs/IMPLEMENTATION_PLAN.md`).

**Protocol:** automated pre-checks first (quote verification, blocklist,
constraint arithmetic, cardinality, disjoint signals) — cheap and
model-free; human/LLM-judge scoring only for sets that pass. Swap test:
score dimension 2 by presenting each pathway against one wrong persona.

---

## 5. Six test personas

Each exists to break a specific part of the contract. Synthetic; keep CVs
350–700 words except where the stressor is length.

1. **Hospitality shift lead.** 15 years hotel/restaurant operations, leads
   12 staff, scheduling, inventory, complaint handling; no degree; body
   wearing out, wants predictable hours. Interview: Develop, <2 h/week,
   0 EUR. *Stresses:* non-office environment realism, tiny constraints,
   neutrality (a good set finds ops coordination in facilities/health
   logistics or in-chain training roles; a bad one says "learn data
   analytics").
2. **Medical imaging technologist (MRI/CT).** 8 years, licensed, hospital
   shift work. Trigger: "I keep reading AI will replace radiology."
   Interview: Optimize, 2–5 h/week, up to 50 EUR. *Stresses:* honest
   AI-headwind handling without hype or tech-conversion drift; licensing
   as a hard constraint; a good set distinguishes automatable image
   interpretation from patient-facing acquisition work.
3. **Returner (bookkeeping).** 7 years SME bookkeeping, then a 6-year
   care gap, re-entering; chooses **Reinvent** with <2 h/week and 0 EUR.
   *Stresses:* career-break representation (`employment_pattern`),
   `years_experience` semantics, and above all the
   `ambition_vs_time`/`budget` **conflict object** — the set must surface
   the contradiction, not silently downgrade her to "brush up Excel."
4. **Electrician moving off the tools.** 18 years installation, Meister
   certification, knee problems. Interview: Develop, 5–10 h/week, up to
   50 EUR. *Stresses:* physical-tradeoff honesty, credential-world
   pathways (inspection, PV/heat-pump planning, vocational instructor),
   AI-neutrality — change pressure here is regulatory/energy-transition,
   and the contract must be comfortable saying AI is mostly irrelevant.
5. **Municipal clerk.** 20 years public administration, permanent
   contract, values security; trigger: case-processing digitization.
   Interview: Optimize, 2–5 h/week, 0 EUR. *Stresses:* low risk
   tolerance, internal-mobility pathways (not job-hopping), a
   digitization change signal that is not AI-flavored, and rejection of
   reinvention even where a model might find it "more interesting."
6. **Freelance graphic designer.** 10 years, three concurrent client
   engagements with overlapping dates, income falling as generative
   tools commoditize production work. Interview: Reinvent, >10 h/week,
   over 50 EUR. *Stresses:* portfolio-career profile shape, genuine AI
   displacement with urgency, `internal_cv_inconsistency` handling
   (overlapping engagements are legitimate — the contract must represent
   concurrency without flagging it as an error), craft-identity tradeoffs.

**Stress variants** (apply to any persona): (a) sparse CV ~300 words —
must trigger the clarification path, not confident pathways; (b) CV in
German while the product is English-first — language handling must be an
explicit state; (c) a pasted job ad instead of a CV — ingestion must
classify, not extract a phantom profile.

---

## 6. Failure cases the application contract must represent

The recommendation response must be a tagged union, not always a
RecommendationSet. States the schema needs:

1. `ingestion_failed` — unreadable/too short/not-a-CV, with a reason enum
   (exists partially today as `CV_ERROR`; needs typing, not a string).
2. `needs_clarification` — extraction succeeded but evidence is too thin
   or too contradictory to recommend responsibly. Carries 1–3 **specific
   questions** (each linked to the unknown it resolves). This response
   type does not exist anywhere today and is the most important addition:
   without it, the only options are refusing or guessing.
3. `constraints_unsatisfiable` — no pathway honestly fits the stated
   time/budget/ambition combination. Names the binding constraint and what
   relaxation would unlock. Never emit fake pathways to avoid this state.
4. `partial_set` — core pathways generated, optional enrichment
   (discovery, courses) unavailable; enrichment absence flagged per
   section, core intact (extends the existing per-tile discovery
   degradation).
5. `generation_invalid` — model output failed schema/evidence validation
   after the one repair attempt; distinct from provider outage. Carries
   which rules failed (drives regeneration and eval).
6. `provider_error` / `config_error` — exist today; keep distinct.
7. Per-pathway `validation: passed|failed{rules[]}` — a set with one
   failed pathway can ship the passing ones rather than all-or-nothing.
8. `development_need_unmatched` — no verified course fits a need; the
   fallback search phrase is the representation (exists in matcher; must
   be preserved per-need in the pathway, not set-globally).
9. User-driven states in WorkspaceState: all pathways rejected (with
   reasons → regeneration input); experiment completed negative (pathway
   dropped, learning recorded); profile corrected after generation
   (downstream objects marked stale via profile version reference).
10. `stale_data` flags — course `last_verified` older than a threshold;
    market/environment claims carry generation timestamp.

---

## A. Required contract changes (consolidated)

Schema/validation/state work — independent of any prompt wording:

1. Addressable, verbatim `evidence_items` in CareerProfile; typed evidence
   references everywhere else; code-side quote verification.
2. Response tagged union: RecommendationSet | needs_clarification |
   constraints_unsatisfiable | ingestion_failed | generation_invalid |
   provider/config error; `partial_set` and per-pathway validation status.
3. Stable enums decoupled from display strings (interview, budgets, all
   user-visible options) — replaces the `startswith("0 EUR")` pattern.
4. CareerPathway additions: `id`, `title`, `kill_signals`,
   `experiment.tests_assumptions`, `constraint_fit`, `change_outlook`,
   `time_to_viability`; `development_needs` shaped for
   `courses/matcher.py::normalize_gaps`; disjoint definitions for
   tradeoffs vs reasons_against.
5. RecommendationSet: cardinality/composition rules, `conflicts[]`,
   `rejected_pathways[]`, `sensitivity`, `best_if` per pathway (unranked),
   `generation_metadata`.
6. CareerProfile: `unknowns`, `inconsistencies`, `credentials_and_licenses`,
   `employment_pattern`, `outcomes`, `industries[]`, scope facts replacing
   the tech-ladder seniority enum, `change_signals` replacing
   `ai_tool_signals`; `teaser` moved out of the profile.
7. InterviewAnswers: typed trigger interpretation; explicit-unknown
   constraint slots.
8. WorkspaceState: pathway/experiment statuses with outcomes,
   `profile_corrections` + provenance, saved-course links,
   `schema_version` on all persisted objects.
9. Code-enforceable anti-generic and safety rules from §2/§3: evidence
   quota, quote verification, diversity check, neutrality guard,
   constraint arithmetic, blocklist, length ceilings, no-invented-stats,
   protected-attribute exclusion, disjoint success/kill signals.
10. Eval harness implementing §4 (automated pre-checks, gates, swap-test
    protocol) over the §5 personas and their stress variants.

## B. Deferred to prompt writing (do not encode in the contract)

- Voice and tone (second person, plain language, no fluff).
- How to elicit honest tradeoffs and the "one uncomfortable truth."
- Exact blocklist phrase inventory (config, iterated from eval failures).
- Reasoning order (evidence → hypotheses → pathways → self-check) and any
  self-critique/swap-test instruction inside the prompt.
- Few-shot examples per persona archetype.
- Wording of clarification questions and conflict `response` texts.
- How strongly to weight the trigger narrative relative to the fixed
  answers (within the typed bounds the contract sets).
