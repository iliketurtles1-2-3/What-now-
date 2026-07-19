# AI Career Navigator

## Product Architecture

### Product outcome

AI Career Navigator turns a CV and a short interview into an evidence-based career
development workspace. The user should leave with:

1. A clear assessment of how AI may change their current work.
2. A development direction that fits their ambition, time, and budget.
3. A concrete plan containing skills, courses, projects, and milestones.
4. A workspace they can use inside the app instead of a document they must manage
   elsewhere.

The application is English-first. All interface labels, model instructions, model
outputs, validation messages, and generated content must be in English.

## Experience flow

```mermaid
flowchart TD
    A[Welcome and CV composer] --> B[CV ingestion]
    B --> B1[Pasted CV text]
    B --> B2[PDF upload and text extraction]
    B1 --> C[Validate and normalize CV]
    B2 --> C

    C --> D[Profile analysis]
    D --> E[Structured career profile]
    D --> F[Three evidence-based observations]

    E --> G[Short career interview]
    F --> G
    G --> H[Career strategy generation]

    H --> I[Assessment]
    H --> J[Development plan]
    H --> K[Positioning]

    E --> L[Course matching]
    J --> L
    L --> M[Curated course catalog]

    I --> N[In-app career workspace]
    J --> N
    K --> N
    M --> N

    N --> O[Assessment view]
    N --> P[Development roadmap]
    N --> Q[Courses and resources]
    N --> R[CV and positioning]
    N --> S[Progress tracking]
```

## Main product areas

### 1. Welcome and CV composer

The first screen contains:

- A concise welcome message.
- One chat-style text composer for pasted CV content.
- A compact PDF upload button beside the composer.
- One send action.
- A clear privacy note.

The composer may expand to a modest maximum height, but it must not become a large
form or upload panel.

### 2. Career profile

The profile analysis converts CV content into a stable internal schema. It records:

- Current role, seniority, industry, and years of experience.
- Employment history and evidence-backed task clusters.
- Skills, education, languages, and existing AI-tool signals.
- Strong career assets.
- Tasks that may face change pressure.
- Potential development directions.
- Missing or uncertain information.

Every important generated claim should reference evidence from this profile.

### 3. Career interview

The interview remains short and fixed:

- Development ambition: optimize, evolve, or reinvent.
- Weekly time available.
- Learning budget.
- The reason the user is seeking guidance now.

The answers are constraints, not decorative context. They must visibly change the
depth, pace, resources, and target direction of the development plan.

### 4. Career assessment

The assessment is one product area within the workspace. It contains:

- AI change pressure by real task.
- The reasoning and CV evidence behind each assessment.
- Defensible strengths and transferable assets.
- Three prioritized development gaps.
- A concise strategic direction.

It is rendered as native interface sections, status indicators, and expandable
details. It is not rendered from Markdown.

### 5. Development roadmap

The roadmap is the main forward-looking area of the product:

- A 100-day plan divided into practical phases.
- A 12-month trajectory with quarterly outcomes.
- Two explicit decision gates.
- A tangible artifact or proof of progress for each phase.
- Tasks that can be marked as planned, active, or complete.

For the prototype, progress exists in the current Gradio session. Persisted progress
is a later feature requiring a deliberate storage and privacy decision.

### 6. Courses and resources

Courses replace recent market signals.

Course recommendations must be grounded in a curated catalog rather than generated
from model memory. Each catalog entry should contain:

```json
{
  "id": "provider-course-slug",
  "title": "Verified course title",
  "provider": "Provider name",
  "url": "https://...",
  "skills": ["skill-a", "skill-b"],
  "level": "beginner",
  "format": "course",
  "cost_type": "free",
  "cost_note": "Free audit available",
  "time_hours": 8,
  "language": "English",
  "last_verified": "YYYY-MM-DD"
}
```

The model identifies skill gaps. Application code then filters the catalog by skill,
budget, available time, level, and language. The model may rank or explain suitable
results, but it must never invent a course or URL.

The course area should show:

- Why the course matches the user.
- Which gap it addresses.
- Time and cost.
- Provider and verified external link.
- A save-to-plan action.
- A clear fallback search phrase when no verified match exists.

### 7. Positioning

The positioning area turns the strategy into usable career assets:

- Revised CV bullets based on real experience.
- A suggested LinkedIn headline.
- A short professional narrative.
- Optional portfolio-project suggestions.

These remain editable or copyable inside the app.

### 8. Development workspace

After generation, the user stays in one application workspace with navigation
between:

- Overview
- Assessment
- Roadmap
- Courses
- Positioning

The right sidebar may show profile, plan progress, saved courses, companies, and
relevant jobs. Companies and jobs are optional enrichment; they must not block the
core workflow.

## Data architecture

```mermaid
flowchart LR
    CV[CV content] --> Profile[CareerProfile]
    Interview[Interview answers] --> Strategy[CareerStrategy]
    Profile --> Strategy
    Profile --> Gaps[Skill gaps]
    Strategy --> Gaps
    Catalog[Verified course catalog] --> Matcher[Deterministic course matcher]
    Gaps --> Matcher
    Matcher --> Recommendations[Course recommendations]
    Strategy --> Workspace[Career workspace state]
    Recommendations --> Workspace
```

The primary internal objects are:

- `CareerProfile`
- `InterviewAnswers`
- `CareerAssessment`
- `DevelopmentPlan`
- `PositioningAssets`
- `Course`
- `CourseRecommendation`
- `WorkspaceState`

Structured JSON is the interchange format between model calls and application code.
It is not the presentation format.

## Rendering and export

Markdown should no longer be the main report technology.

The application should render structured data through native UI components:

- Task assessment rows with status indicators.
- Gap cards with evidence and priority.
- Roadmap phases with checkable actions.
- Course rows with metadata and save actions.
- Editable positioning fields.

The initial export options should be:

1. A print-friendly in-app report view using HTML and CSS.
2. Browser print-to-PDF.
3. Structured JSON export for testing and debugging, hidden from ordinary users.

A server-generated PDF can be added later if user testing shows that a downloadable
artifact matters. Markdown export is unnecessary for the primary experience.

## Service boundaries

The target code structure is:

```text
app.py                    Application entry point and event wiring
config.py                 Environment and provider configuration
models.py                 Typed application schemas
cv.py                     CV validation and PDF text extraction
llm.py                    Provider-independent model interface
providers/
  openai_compatible.py    OpenRouter and compatible APIs
  anthropic.py            Anthropic API
prompts/
  profile.py              Profile extraction prompt
  strategy.py             Career strategy prompt
courses/
  catalog.json            Verified course records
  matcher.py              Deterministic filtering and ranking
discovery.py              Optional companies and jobs
workspace.py              State transitions and validation
ui/
  layout.py               Gradio application structure
  renderers.py            Structured UI rendering
  styles.css              Responsive styles
tests/
  fixtures/               Synthetic and anonymized CV inputs
  test_schemas.py
  test_courses.py
  test_workflow.py
```

The split should be introduced incrementally after the current uncommitted
`app.py` work is synchronized.

## Reliability principles

- The career workflow works without live job, company, or search APIs.
- Live enrichment is loaded separately and never delays the assessment.
- Model output is validated against typed schemas.
- One controlled repair attempt is allowed for invalid structured output.
- Course names and URLs come only from verified catalog data.
- Budget and time constraints are enforced in application code.
- CV claims must include evidence or be labeled as uncertain.
- Provider-specific behavior remains behind the model interface.
- No secret keys, CVs, or personal reports are committed to the repository.

## Product trajectory

### Prototype

- English end-to-end workflow.
- CV analysis and fixed interview.
- Structured in-app assessment and roadmap.
- Small verified course catalog.
- Session-based progress.
- Optional companies and jobs.

### User-test release

- Evaluation across representative CV types.
- Improved evidence grounding and prompt sensitivity.
- Course save-to-plan workflow.
- Responsive and accessible interface.
- Print-friendly report view.

### Later product

- Explicit opt-in persistence.
- User accounts and cross-session progress.
- Course catalog administration and scheduled verification.
- Re-analysis after completing milestones.
- Comparison between original and updated CV.
- Feedback and outcome measurement.
