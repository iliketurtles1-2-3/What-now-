# AI Career Navigator Implementation Plan

## Working agreement

Until the current `app.py` changes are committed, only one coding agent should edit
that file. Other work should stay in documentation, tests, schemas, or separate
modules to avoid overlapping changes.

Real CVs must remain local and untracked. Test fixtures committed to the repository
must be synthetic or thoroughly anonymized.

`docs/CLEANUP_REPORT.md` is the active technical-debt audit. Its open findings are
release work, not optional polish. They are assigned to the phases below so cleanup
and the framework redesign do not create competing backlogs.

## Cleanup gates

### Baseline gate

- [x] N2: make every existing test discoverable with the standard library.
- [x] N2: removed the obsolete course-catalog path from the active workflow.
- [x] N2: add a minimal CI workflow for compilation and the complete test suite.
- [x] Keep local `.claude/` and `.agents/` configuration out of the repository.

### Framework-core gate

- [x] O1: verify provider default model IDs against current official documentation.
- [x] O5: remove the remaining German internal strings and defaults.
- [x] N6: remove `app_shell_html` rather than carrying dead rendering code forward.
- [x] N7: remove the unreachable exception handler from `interesting_jobs`.
- [x] N9: rename `rating_icon` and simplify model-response repair logging.
- [x] N11: remove the unused discovery input from strategy generation. Optional,
      noisy discovery data must not influence the core recommendation contract.
- [x] Move `css` from the deprecated Gradio `Blocks` constructor argument to
      `launch()` while preserving test imports and the responsive layout.

### Learning-research gate

- [x] N3: discard model-generated named resources and URLs in all cases.
- [x] N4: preserve original skill-gap labels in learning presentation.
- [x] N1: carry budget and time constraints into learning search intents.
- [x] N1: treat "over X" as an uncapped budget tier.
- [x] N5: replace the sidebar course area with dynamic learning-resource research.
- [x] N10: remove catalog URL verification; live resources are checked through research tasks.

### Experience and discovery gate

- [x] O2: remove the Google Fonts import and use a privacy-safe font stack.
- [x] O3: replace the over-constrained exact-phrase company query.
- [x] N8: accurately label or hide web discovery when no provider is configured.
- [ ] O4: remove obsolete local empty agent directories where present.

### Documentation gate

- [x] N9: align the GLM model slug across the live-test guide and README.
- [x] N9: define one supported Python range across installation documentation.
- [ ] Replace the long-report and generic roadmap assumptions in this plan with
      the persistent pathway-comparison workspace contract.

## Definition of v0.1

The v0.1 release is complete when a user can:

1. Paste or upload a CV from a compact English welcome screen.
2. Receive three specific, evidence-based observations.
3. Answer the four fixed career questions.
4. Navigate an in-app assessment, roadmap, learning plan, and positioning area.
5. Save recommended learning resources or proof projects to their current-session development plan.
6. Print the result cleanly or save it as PDF through the browser.
7. Complete the workflow even when optional discovery services are unavailable.

## Priority backlog

### P0 — Stabilize the current branch

- [x] Account for the other Codex instance's work without absorbing hidden
      `app.py` changes.
- [x] Review the uncommitted state and keep local agent/cache files untracked.
- [x] Commit and push a recoverable baseline checkpoint.
- [x] Confirm `python app.py` starts with the pinned dependencies on Python 3.12.
- [ ] Run one pasted-CV happy path with OpenRouter and GLM 5.2.

Acceptance:

- The repository has a clean, understood baseline.
- No personal CV, API key, cache file, or design archive is committed accidentally.

### P1 — Convert the product to English

- [ ] Translate all visible labels, helper text, progress states, and errors.
- [ ] Replace German option values with stable internal enum values and English
      display labels.
- [ ] Rewrite both model prompts for English output.
- [ ] Translate report section names and fallback messages.
- [ ] Update README examples and product description.

Acceptance:

- No German text appears in the primary workflow.
- Internal logic does not depend on translated display strings.

### P2 — Define structured product schemas

- [ ] Add typed schemas for profile, interview, assessment, plan, positioning, and
      learning research findings.
- [ ] Separate model response validation from presentation rendering.
- [ ] Add required-field and quantity validation.
- [ ] Add one structured repair attempt for malformed model output.
- [ ] Enforce budget and time constraints in code.

Acceptance:

- Invalid responses fail with a useful in-app error.
- Rendering functions receive validated objects instead of arbitrary dictionaries.

### P3 — Redesign the first screen

- [ ] Add one welcoming assistant message.
- [ ] Add a compact expanding CV text composer.
- [ ] Place the PDF upload action beside the composer.
- [ ] Add a familiar send icon with a tooltip.
- [ ] Remove the large upload drop zone and form-like first screen.
- [ ] Verify desktop and mobile widths.

Acceptance:

- The complete first interaction fits comfortably in the first viewport.
- Uploading and pasting remain equally discoverable.
- No control overlaps or causes horizontal scrolling.

### P4 — Replace Markdown report rendering

- [ ] Render assessment tasks as structured rows.
- [ ] Render gaps as prioritized sections with supporting evidence.
- [ ] Render the roadmap as phases and checkable actions.
- [ ] Render decision gates as explicit choices.
- [ ] Render positioning assets in editable/copyable fields.
- [ ] Add workspace navigation between overview, assessment, roadmap, learning, and
      positioning.
- [ ] Remove the Markdown download as the primary completion action.
- [ ] Add print-specific CSS for browser print-to-PDF.

Acceptance:

- The report never appears as one long Markdown document.
- Users can scan, navigate, and act on individual recommendations.
- Printing produces a readable report without application controls.

### P5 — Build the learning research layer

- [x] Delete the static course catalog and deterministic matcher.
- [ ] Define learning research task and finding schemas.
- [ ] Search across courses, YouTube, GitHub, books, events, communities, and practice projects.
- [ ] Rank findings by profile fit, skill gap, time, budget, language, evidence quality, and freshness.
- [ ] Show queued search phrases when Tavily or SerpAPI is not configured.
- [ ] Add source freshness and domain indicators to learning cards.
- [ ] Add a save-to-plan action in the learning interface.
- [x] Remove recent market signals from the interface and code path.

Acceptance:

- Every displayed external resource has a source URL from live research.
- A zero budget prioritizes free resources, open materials, communities, and projects.
- Recommendations explain their relationship to a specific skill gap and direction.

### P6 — Improve the prompts with evaluation data

- [ ] Prepare 4–6 synthetic or anonymized CVs covering different seniority levels,
      roles, languages, and career intentions.
- [ ] Define an evaluation rubric before revising prompts.
- [ ] Test whether profile claims are supported by CV evidence.
- [ ] Test the same CV with optimize, evolve, and reinvent answers.
- [ ] Rewrite prompts based on observed failures.
- [ ] Reduce unnecessary output and latency.
- [ ] Log timings for profile analysis and strategy generation.

Acceptance:

- Different CVs produce meaningfully different assessments.
- Different interview answers produce meaningfully different roadmaps.
- Recommendations do not invent experience, named resources, or URLs.

### P7 — Make development actionable

- [ ] Allow roadmap actions to be marked planned, active, or complete.
- [ ] Allow a learning resource or project to be attached to a roadmap phase.
- [ ] Show current-session progress in the sidebar.
- [ ] Add a next-action summary to the workspace overview.
- [ ] Add a reset confirmation before deleting current-session work.

Acceptance:

- The user has at least one clear next action after generating the strategy.
- The workspace changes as actions and learning resources are selected.

### P8 — Resilience and optional discovery

- [ ] Run companies and jobs after the core profile is visible.
- [ ] Add strict timeouts and independent failure handling.
- [ ] Hide unavailable enrichment without blocking the workflow.
- [ ] Remove public HTML scraping where reliability or terms are uncertain.
- [ ] Clearly distinguish verified external data from model-generated explanation.

Acceptance:

- Profile and strategy generation work with all discovery services disabled.
- A discovery timeout does not delay or erase the core result.

### P9 — Test and release

- [ ] Add schema, learning-resource, budget, and rendering tests.
- [ ] Test pasted CV and PDF input.
- [ ] Test missing key, timeout, malformed JSON, short CV, and non-CV input.
- [ ] Test desktop and mobile layouts.
- [ ] Update English README and VPS instructions.
- [ ] Run a clean Ubuntu installation test.
- [ ] Tag the user-test release.

## Evaluation rubric

Score each dimension from 1 to 5:

| Dimension | Question |
|---|---|
| Profile accuracy | Does the profile reflect the CV without invented facts? |
| Evidence grounding | Can each important assessment be traced to CV evidence? |
| Specificity | Would a different CV receive a meaningfully different result? |
| Interview sensitivity | Do ambition, time, budget, and trigger change the plan? |
| Actionability | Does the user know what to do next? |
| Feasibility | Does the plan fit the stated time and budget? |
| Learning quality | Are resources real, relevant, current, varied, and correctly linked? |
| Positioning quality | Are the narrative and CV bullets credible and usable? |
| Clarity | Can the result be understood without reading a long document? |
| Trust | Are uncertainty and limitations communicated honestly? |

Target for user testing: no score below 3 and an average of at least 4.

## Suggested execution order

1. Establish the clean baseline.
2. Convert language and define schemas.
3. Build the compact entry screen.
4. Replace Markdown rendering with the workspace views.
5. Add the learning research layer.
6. Evaluate and revise prompts using representative CVs.
7. Add progress interactions.
8. Harden optional discovery and deployment.

This order creates a testable product early while keeping prompt improvements tied
to observable user outcomes.
