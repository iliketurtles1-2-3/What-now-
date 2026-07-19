# AI Career Navigator

Working Gradio prototype for CV analysis and career development.

The product is being redesigned as an English, in-app career workspace. Users will
upload or paste a CV, receive an evidence-based assessment, answer four fixed
questions, and build a development plan with verified courses and practical
milestones.

Product and implementation documentation:

- [Product architecture](docs/PRODUCT_ARCHITECTURE.md)
- [Implementation plan and backlog](docs/IMPLEMENTATION_PLAN.md)

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
- Companies and recent signals: Tavily or SerpAPI web/news search

Configure one search provider for full live tiles:

```bash
export TAVILY_API_KEY=your_tavily_key_here
```

or:

```bash
export SERPAPI_API_KEY=your_serpapi_key_here
export LIVE_SEARCH_PROVIDER=serpapi
```

Without Tavily or SerpAPI, the app still tries live jobs from Arbeitnow, but company and recent-news tiles show a configuration note instead of AI-invented results.

The app binds to `0.0.0.0:7860`. Open:

```text
http://YOUR_SERVER_IP:7860
```

## Run As A Systemd Service

Create `/etc/systemd/system/ki-karriere-check.service`:

```ini
[Unit]
Description=KI-Karriere-Check Gradio App
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
sudo systemctl enable ki-karriere-check
sudo systemctl start ki-karriere-check
sudo systemctl status ki-karriere-check
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
- PDF upload is sent directly to the provider as file/document input. Anthropic uses a PDF document block. OpenAI uses Responses API file input.
- Most OpenAI-compatible providers support `OPENAI_API_MODE=chat`, which is best for pasted CV text.
- PDF upload works with Anthropic document input, OpenAI Responses file input, and OpenRouter chat file input. Other OpenAI-compatible chat endpoints may not implement the same file-part contract.
- Some OpenAI-compatible providers may not support JSON response formatting. If that happens, use Anthropic or OpenAI Responses for the CV test run.
- Files are not persisted by the app. The markdown report download is generated in the system temp directory for the current session.

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

Anna Müller

Senior Marketing Managerin mit 9 Jahren Erfahrung in B2B-SaaS, zuletzt bei einem mittelständischen Softwareanbieter für HR-Tools. Verantwortlich für Content-Strategie, Kampagnenplanung, Newsletter, Webinar-Konzeption, LinkedIn-Kommunikation und die Koordination externer Agenturen. Führte ein kleines Team aus zwei Content-Spezialistinnen und einem Performance-Marketer.

Berufserfahrung:
2021 bis heute: Senior Marketing Managerin, PeopleFlow GmbH. Aufbau einer Thought-Leadership-Strategie für HR-Entscheider, Planung von Quartalskampagnen, Briefing von Design und Sales, Auswertung von HubSpot- und LinkedIn-Daten, Erstellung von Landingpages und Case Studies. Erste Nutzung von ChatGPT für Themenrecherche, Gliederungen und Varianten von Anzeigen-Texten.

2017 bis 2021: Content Marketing Managerin, CloudDesk AG. Redaktion von Blogartikeln, Whitepapern und Kunden-Newslettern, SEO-Recherche, Zusammenarbeit mit Produktmanagement und Vertrieb. Einführung eines Redaktionsplans und monatlicher Performance-Reports.

2014 bis 2017: Junior Marketing Specialist, Messeagentur Berlin. Organisation von Fachmessen, Pflege von CRM-Daten, Erstellung von Präsentationen und Nachbereitung von Leads.

Skills: Content Marketing, B2B-Kommunikation, HubSpot, Google Analytics, LinkedIn Ads, SEO, Webinar-Konzeption, Stakeholder-Management, Projektplanung, Deutsch Muttersprache, Englisch fließend.

Ausbildung: Master in Kommunikationswissenschaft, Bachelor in Betriebswirtschaft.
