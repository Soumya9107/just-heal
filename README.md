# Self-Healing Scraper

A web scraper that detects when a target site's layout changes, diagnoses the
break, rewrites its own extraction logic, and re-verifies — without a human
in the loop. Built for the WeMakeDevs "Into the Scrape-Verse" hackathon.

## The problem

Most scraping tutorials end the moment the scraper works. In production,
scrapers break silently: a class gets renamed, a price format changes, a
wrapper div gets added — and the scraper keeps running, just returning
garbage or empty fields instead of erroring out loudly. This project treats
that moment as the *start* of the interesting work, not a failure state to
avoid.

## Architecture

```
                ┌─────────────┐
                │  Run         │  brightdata scraper run <collector_id>
                └──────┬──────┘
                       │
                       ▼
                ┌─────────────┐
                │  Validate    │  check output against expected schema
                └──────┬──────┘
                       │
              ┌────────┴────────┐
              │                 │
           healthy           unhealthy
              │                 │
              ▼                 ▼
         ┌─────────┐     ┌──────────────┐
         │  Done    │     │  Diagnose     │  fetch current HTML,
         │  (exit 0)│     │  (Claude API) │  compare to schema + last-good HTML
         └─────────┘     └──────┬───────┘
                                 │
                                 ▼
                         ┌──────────────┐
                         │  Heal         │  brightdata scraper create
                         │               │  with updated extraction description
                         └──────┬───────┘
                                 │
                                 ▼
                         ┌──────────────┐
                         │  Re-run &     │  loop back to Validate,
                         │  re-verify    │  max 3 attempts
                         └──────────────┘
```

## Project layout

```
self-healing-scraper/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── validator.py              # schema + validation logic
├── diagnose.py                # Claude-based break diagnosis
├── heal_loop.py                # orchestration: run -> validate -> heal -> re-verify
├── demo_pages/
│   ├── baseline.html          # working page structure
│   └── broken.html            # simulated site-change for demos
└── .github/workflows/
    └── scraper.yml             # scheduled + manual CI run
```

## Components

| File | Responsibility |
|---|---|
| `validator.py` | Defines the expected output schema and checks scraped records against it (type, required fields, allowed values, plausibility) |
| `diagnose.py` | Sends the validation failure + current page HTML to Claude, gets back a diagnosis and a new plain-English extraction description |
| `heal_loop.py` | Orchestrates run → validate → diagnose → heal → re-verify, capped at 3 attempts |
| `.github/workflows/scraper.yml` | Runs the loop on a schedule (cron) and on manual trigger, so healing happens unattended |

## How healing works

1. **Detection isn't just "did the request succeed."** A 200 response with
   malformed data is still a failure. `validator.py` checks field presence,
   type, and plausibility (e.g. price must be numeric and non-negative,
   availability must be one of a known set of values).
2. **Diagnosis is LLM-driven, not selector-matching.** Instead of trying to
   auto-detect *which* CSS selector changed, we hand Claude the current HTML,
   the last known-good HTML, and the validation failure report, and ask it to
   describe what changed and propose a new natural-language extraction
   description.
3. **Repair goes through Scraper Studio's own interface.** Because
   collectors are description-driven rather than selector-hardcoded, the
   "fix" is just re-creating the collector with an updated description —
   the same mechanism a human would use, just automated.
4. **Every heal attempt is re-validated** before being accepted, and the
   loop caps at 3 attempts so a genuinely broken page fails loudly (CI
   goes red) instead of retrying forever.

## Setup

1. Install the Bright Data CLI and authenticate:
   ```bash
   npm install -g @brightdata/cli   # confirm exact package name in current docs
   brightdata login
   ```
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your keys (or export them
   directly in your shell):
   ```bash
   export ANTHROPIC_API_KEY=...
   export BRIGHTDATA_API_KEY=...
   ```
4. Serve the demo page locally:
   ```bash
   cd demo_pages && python -m http.server 8000
   ```
5. Create your first collector against the baseline page:
   ```bash
   brightdata scraper create http://localhost:8000/baseline.html \
     "extract product name, price, and availability" -o create.json
   jq -r '.collector_id' create.json > collector_id.txt
   ```
6. Run the healing loop:
   ```bash
   python heal_loop.py
   ```

**Note:** if Scraper Studio needs a public URL rather than localhost, tunnel
the demo page with `ngrok http 8000` or `cloudflared tunnel` and update
`TARGET_URL` in `heal_loop.py` accordingly.

## Demo: watch it break and heal

We test this against a self-hosted mirror page rather than a live production
site, so the break is reproducible and repeatable:

```bash
# baseline.html has clean, working structure - scraper runs green
cp demo_pages/broken.html demo_pages/baseline.html   # simulate a real site change
python heal_loop.py                                    # watch it detect, diagnose, heal, re-verify
```

The GitHub Actions workflow also accepts a `simulate_break` manual trigger
input for the same demo without needing a terminal.

## What it can and can't heal (current limitations)

- Structural changes: renamed classes, added wrapper elements, moved fields
- Format changes: price format, date format, text-vs-enum availability values
- NOT anti-bot / CAPTCHA blocks — these are handled by Bright Data's Web
  Unlocker layer already, not by this healing loop
- NOT fully paywalled or login-gated content — out of scope per hackathon rules
- Confidence-gated: if Claude's diagnosis confidence comes back "low," we
  still attempt the heal but flag it in logs for human review rather than
  silently trusting it

## Why this matters

Scrapers are usually treated as disposable — write it, run it once, done.
Anything that runs on a schedule against real websites needs to survive the
layout changing underneath it. This is a small, concrete demonstration of
that: the system's job isn't just to extract data, it's to keep extracting
data correctly even when the target changes.
