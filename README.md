# KI-Karriere-Check

Working Gradio prototype for CV analysis: upload or paste a CV, get a German teaser, answer four fixed questions, then receive a German markdown career report.

The app is model-provider agnostic through environment variables. It currently supports:

- `LLM_PROVIDER=anthropic`
- `LLM_PROVIDER=openai` for OpenAI or OpenAI-compatible APIs via `OPENAI_BASE_URL`

## Quick Start On A Linux VPS

Requirements:

- Python 3.11+
- A reachable API key for your chosen model provider
- Port `7860` open in your firewall/security group

```bash
git clone YOUR_REPO_URL ai-career-navigator
cd ai-career-navigator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Anthropic example:

```bash
export LLM_PROVIDER=anthropic
export LLM_MODEL=claude-sonnet-4-6
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
Environment=LLM_MODEL=claude-sonnet-4-6
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
- PDF upload requires `LLM_PROVIDER=anthropic` or `LLM_PROVIDER=openai` with `OPENAI_API_MODE=responses`.
- Some OpenAI-compatible providers may not support JSON response formatting. If that happens, use Anthropic or OpenAI Responses for the CV test run.
- Files are not persisted by the app. The markdown report download is generated in the system temp directory for the current session.

## Sample CV Text For Testing

Anna Müller

Senior Marketing Managerin mit 9 Jahren Erfahrung in B2B-SaaS, zuletzt bei einem mittelständischen Softwareanbieter für HR-Tools. Verantwortlich für Content-Strategie, Kampagnenplanung, Newsletter, Webinar-Konzeption, LinkedIn-Kommunikation und die Koordination externer Agenturen. Führte ein kleines Team aus zwei Content-Spezialistinnen und einem Performance-Marketer.

Berufserfahrung:
2021 bis heute: Senior Marketing Managerin, PeopleFlow GmbH. Aufbau einer Thought-Leadership-Strategie für HR-Entscheider, Planung von Quartalskampagnen, Briefing von Design und Sales, Auswertung von HubSpot- und LinkedIn-Daten, Erstellung von Landingpages und Case Studies. Erste Nutzung von ChatGPT für Themenrecherche, Gliederungen und Varianten von Anzeigen-Texten.

2017 bis 2021: Content Marketing Managerin, CloudDesk AG. Redaktion von Blogartikeln, Whitepapern und Kunden-Newslettern, SEO-Recherche, Zusammenarbeit mit Produktmanagement und Vertrieb. Einführung eines Redaktionsplans und monatlicher Performance-Reports.

2014 bis 2017: Junior Marketing Specialist, Messeagentur Berlin. Organisation von Fachmessen, Pflege von CRM-Daten, Erstellung von Präsentationen und Nachbereitung von Leads.

Skills: Content Marketing, B2B-Kommunikation, HubSpot, Google Analytics, LinkedIn Ads, SEO, Webinar-Konzeption, Stakeholder-Management, Projektplanung, Deutsch Muttersprache, Englisch fließend.

Ausbildung: Master in Kommunikationswissenschaft, Bachelor in Betriebswirtschaft.
