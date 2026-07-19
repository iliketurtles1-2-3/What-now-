# Prompt Framework

Status: active working note for prompt review.

## Product Job

WTFDID should help a person turn CV evidence and personal constraints into
testable career directions. The app should not end at a report. It should create
an interactive workspace where the user can accept, reject, challenge, and refine
directions.

## Prompt Stages

### 1. Profile Understanding

Input: CV text.

Output: structured profile plus three first observations.

The prompt should:

- Extract conservative facts from the CV.
- Include domain, operational, interpersonal, commercial, regulatory, and
  judgment skills, not only technical skills.
- Preserve uncertainty instead of filling gaps.
- Surface AI/tool signals only when explicitly present.
- Avoid advice and recommendations.

### 2. Direction Strategy

Input: structured profile plus short interview answers.

Output: compatible workspace JSON with exposure, perspectives, gaps, plans,
decision gates, learning search intents, positioning, and closing note.

The prompt should:

- Generate 2-3 genuinely different perspectives.
- Keep at least one non-tech/non-AI-centered option unless the profile strongly
  supports a technical pivot.
- Explain why each direction fits using CV evidence.
- Name risks, assumptions, and losses.
- Produce proof actions and real-world experiments, not only courses.
- Produce learning search intents, not invented resource names or links.

## Anti-Generic Checklist

Reject or revise output when:

- A different CV could receive the same recommendation.
- The answer defaults to Python, AI agents, prompt engineering, or startups
  without profile evidence.
- Learning means only courses.
- A recommendation has no downside, risk, or assumption.
- The path ignores stated time, budget, or ambition.
- Company/job/resource names appear without live research or user-provided
  evidence.

## Next Prompt Work

- Add explicit unknowns and profile corrections to the schema.
- Add evidence IDs so downstream claims can cite profile facts.
- Add conflict objects for ambition/time/budget contradictions.
- Add a proper `needs_clarification` response when the CV or interview is too
  thin.
- Add evaluation fixtures for six synthetic personas before further tone tuning.
