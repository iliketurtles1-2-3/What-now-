# Live Test Run

Use this after the cleanup branch has been merged into `main`.

## Goal

Run one real CV through the local app and judge the product flow, not just whether the code runs.

## Ubuntu Setup

From your Ubuntu machine:

```bash
cd ~/ai-career-navigator
git pull origin main
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If your system only has Python 3.13 or 3.14, install with:

```bash
sudo apt update
sudo apt install python3-venv python3-pip build-essential libjpeg-dev zlib1g-dev
```

The project includes `audioop-lts` for Python 3.13+ because Gradio/Pydub may need it.

## OpenRouter Configuration

Use OpenRouter through the OpenAI-compatible client:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_MODE=chat
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
export OPENAI_API_KEY="your_openrouter_api_key"
export LLM_MODEL="z-ai/glm-4.5"
export OPENAI_JSON_MODE=true
```

If the exact GLM 5.2 model slug differs in OpenRouter, replace `LLM_MODEL` with the slug shown in your OpenRouter dashboard.

## Start The App

```bash
python app.py
```

Open:

```text
http://localhost:7860
```

## Test Script

1. First screen
   - Welcome message is visible.
   - CV text field and upload button are on one line on desktop.
   - Layout does not overflow horizontally.

2. CV input
   - Paste a CV with more than 300 characters.
   - Run analysis.
   - Expected: first profile workspace appears before optional live discovery finishes.

3. First workspace
   - Teaser observations are specific to the CV.
   - Sidebar shows profile, learning, positioning, target direction, companies/jobs/courses.
   - Nothing is hidden or overlapping.

4. Short interview
   - Select adaptation level.
   - Select time budget.
   - Select learning budget.
   - Add a short trigger.
   - Generate workspace.

5. Final workspace
   - Report stays in the app.
   - Courses are real catalog courses with clickable links.
   - If budget is `0 EUR`, paid courses should not appear.
   - The 100-day plan ends in concrete artifacts.
   - CV bullets and LinkedIn headline are specific to the profile.

6. Reset
   - Click new analysis.
   - Prior errors and old report content should disappear.

## Capture Notes

Write down:

- Time from clicking `Start analysis` to first workspace.
- Time from clicking `Generate workspace` to final report.
- Any confusing text.
- Any screen-size/layout issue.
- Any course recommendation that feels wrong.
- Whether the final output feels like a product workspace or still like a document.

## Known Watch Items

- The app still uses Gradio, so some layout behavior is framework-controlled.
- Live companies/jobs are optional and should not block the core analysis.
- Course matching is deterministic, but it depends on the model producing useful gap labels.
- The exact OpenRouter model slug must match OpenRouter's current model list.
