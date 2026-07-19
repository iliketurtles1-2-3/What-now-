# AI Career Navigator

# WTFDID

What the fuck do I do? Working Gradio prototype for interactive CV analysis and
career development.

The product is being redesigned as an English, in-app career workspace. Users
upload or paste a CV, receive an evidence-based assessment, answer four fixed
questions, and build a development plan with live learning research and practical
milestones.

Product and implementation documentation:

- [Product architecture](docs/PRODUCT_ARCHITECTURE.md)
- [Implementation plan and backlog](docs/IMPLEMENTATION_PLAN.md)
- [Recommendation contract review](docs/RECOMMENDATION_CONTRACT_REVIEW.md)
- [Prompt framework](docs/PROMPT_FRAMEWORK.md)

The current runtime still reflects parts of the earlier German Markdown-report
prototype. The linked implementation plan tracks the migration to the new
experience.

The app is model-provider agnostic through environment variables. It currently supports:

- `LLM_PROVIDER=anthropic`
- `LLM_PROVIDER=openai` for OpenAI or OpenAI-compatible APIs via `OPENAI_BASE_URL`

## Development Workflow With Two Codex Instances

Use a separate Git worktree for each active Codex instance. Each instance should
work on its own branch, keep changes scoped, and commit locally without pushing.

One integration instance should then review the local commits, cherry-pick or merge
them into the integration branch, resolve conflicts, run the test suite, and push
only after the combined branch is verified.

## Quick Start On A Linux VPS

Requirements:

- Python 3.12 (the verified development, CI, and deployment runtime)
- A reachable API key for your chosen model provider
- Port `7860` open in your firewall/security group

```bash
git clone YOUR_REPO_URL ai-career-navigator
cd ai-career-navigator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you previously installed dependencies with older pins, refresh the environment instead of layering new packages on top:

```bash
cd ~/ai-career-navigator
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install --upgrade --upgrade-strategy eager --force-reinstall -r requirements.txt
```

Anthropic example:

```bash
export LLM_PROVIDER=anthropic
export LLM_MODEL=claude-sonnet-5
export ANTHROPIC_API_KEY=your_api_key_here
python app.py
```

OpenAI example with PDF upload support:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_MODE=responses
export LLM_MODEL=gpt-4.1
export OPENAI_API_KEY=your_api_key_here
python app.py
```

OpenAI-compatible endpoint example for pasted CV text:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_MODE=chat
export LLM_MODEL=your_model_name
export OPENAI_API_KEY=your_api_key_here
export OPENAI_BASE_URL=https://your-provider.example.com/v1
python app.py
```

OpenRouter + GLM example:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_MODE=chat
export LLM_MODEL=z-ai/glm-5.2
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
export OPENROUTER_API_KEY=your_openrouter_key_here
unset OPENAI_JSON_MODE
python app.py
```

Leave `OPENAI_JSON_MODE` unset for OpenRouter unless your selected model explicitly supports OpenAI JSON mode.

## Live Discovery Tiles

The sidebar tiles use live data at runtime:

- Jobs: Arbeitnow job board API by default (`ARBEITNOW_BASE_URL`)
- Companies: Tavily or SerpAPI web search
- Learning resources: Tavily or SerpAPI searches across courses, YouTube, GitHub, books, events, communities, and practice projects

Configure one search provider for full live tiles:

```bash
export TAVILY_API_KEY=your_tavily_key_here
```

or:

```bash
export SERPAPI_API_KEY=your_serpapi_key_here
export LIVE_SEARCH_PROVIDER=serpapi
```

Without Tavily or SerpAPI, the app still tries live jobs from Arbeitnow, but company and learning-resource tiles show queued search tasks instead of AI-invented links.

The app binds to `0.0.0.0:7860` by default. Override the binding with
`GRADIO_SERVER_NAME` and `GRADIO_SERVER_PORT`. Open:

```text
http://YOUR_SERVER_IP:7860
```

## Run As A Systemd Service

Create `/etc/systemd/system/wtfdid.service`:

```ini
[Unit]
Description=WTFDID Gradio App
After=network.target

[Service]
User=YOUR_LINUX_USER
WorkingDirectory=/home/YOUR_LINUX_USER/ai-career-navigator
Environment=LLM_PROVIDER=anthropic
Environment=LLM_MODEL=claude-sonnet-5
Environment=ANTHROPIC_API_KEY=your_api_key_here
ExecStart=/home/YOUR_LINUX_USER/ai-career-navigator/.venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable wtfdid
sudo systemctl start wtfdid
sudo systemctl status wtfdid
```

## Reverse Proxy With Nginx

Minimal Nginx site:

```nginx
server {
    server_name your-domain.example;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Add TLS with Certbot if you use a domain:

```bash
sudo certbot --nginx -d your-domain.example
```

## Notes About CV Testing

- Pasted CV text works with every configured provider.
- PDF upload is extracted locally with `pypdf` and then sent as text, so it works with OpenRouter and other OpenAI-compatible chat providers without native PDF/file support.
- Most OpenAI-compatible providers support `OPENAI_API_MODE=chat`, which is best for this app.
- Some OpenAI-compatible providers may not support JSON response formatting. If that happens, use Anthropic or OpenAI Responses for the CV test run.
- Files are not persisted by the app. The backup notes export is generated in the system temp directory for the current session.

## Python Support

Python 3.12 is the release target and the only version currently verified in CI. Python 3.13 and 3.14 may work with the pinned `audioop-lts` compatibility package, but they are not claimed as supported until they pass the same installation and test workflow. The project pins current Pillow, OpenAI, Anthropic, and Gradio dependencies to avoid the older Pillow build and `HfFolder` import failures.

If imports fail after a dependency update, recreate the virtual environment:

```bash
cd ~/ai-career-navigator
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

## Sample CV Text For Testing

Anna Miller

Senior Marketing Manager with nine years of B2B SaaS experience, most recently at a mid-sized HR software company. Responsible for content strategy, campaign planning, newsletters, webinars, LinkedIn communication, and external agency coordination. Managed two content specialists and one performance marketer.

Experience:
2021 to present: Senior Marketing Manager, PeopleFlow GmbH. Built a thought-leadership program for HR decision makers, planned quarterly campaigns, briefed design and sales teams, analyzed HubSpot and LinkedIn data, and produced landing pages and case studies. Introduced ChatGPT for topic research, outlines, and advertising-copy variants.

2017 to 2021: Content Marketing Manager, CloudDesk AG. Wrote blog articles, white papers, and customer newsletters; conducted SEO research; partnered with product management and sales; and introduced an editorial calendar with monthly performance reporting.

2014 to 2017: Junior Marketing Specialist, Berlin Events Agency. Organized trade fairs, maintained CRM data, prepared presentations, and followed up sales leads.

Skills: Content marketing, B2B communication, HubSpot, Google Analytics, LinkedIn Ads, SEO, webinar production, stakeholder management, project planning. Native German and fluent English.

Education: MA in Communication Studies; BA in Business Administration.
