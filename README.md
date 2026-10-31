<div align="center">

# Subreach

**Find real buyers on Reddit, qualify them with AI, and draft helpful replies that respect each community's rules.**

[![CI](https://github.com/niihhhall/subreach/actions/workflows/ci.yml/badge.svg)](https://github.com/niihhhall/subreach/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-3b82f6.svg)](LICENSE)
![Tests](https://img.shields.io/badge/tests-183%20passing-brightgreen)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

---

Subreach is an open-source, self-hosted Reddit lead-generation agent. It searches Reddit for people who describe a problem your product solves, scores each post for fit and buying intent, reads the thread, and drafts a genuine, value-first reply. Every draft goes through a compliance check and lands in a review queue, so a person decides what gets sent. A live web dashboard shows the whole funnel.

You can try the full system with no keys at all: it ships with an offline mock backend and demo data.

> **In one line:** find real Reddit prospects → qualify them with AI → draft helpful, rule-checked replies → review and send.

## Table of contents

- [About the project](#about-the-project)
- [Features](#features)
- [How it works](#how-it-works)
- [Install and run](#install-and-run)
- [How to use it](#how-to-use-it)
- [Configuration](#configuration)
- [The dashboard](#the-dashboard)
- [Tests](#tests)
- [Project structure](#project-structure)
- [Project status and roadmap](#project-status-and-roadmap)
- [How to contribute](#how-to-contribute)
- [Security](#security)
- [Credits](#credits)
- [License](#license)

## About the project

### The problem

Reddit is full of people who say, in their own words, "I have this problem and I need a fix". For a founder, an agency or a sales team, those posts are warm leads. Finding them by hand is slow: you search dozens of subreddits, read long threads, and most posts turn out to be advice-givers or other vendors. Replying badly is worse. Promotional replies break subreddit rules, and accounts that post them get banned or shadowbanned.

### What Subreach does

Subreach automates the slow parts and keeps the risky part in human hands:

1. You describe your offer once in a campaign file: product, value proposition, ideal customer, keywords and target subreddits.
2. Subreach searches those subreddits on a schedule and drops duplicates.
3. It scores every post for fit and intent (0 to 100) and removes posts from people who are not buyers.
4. It ranks the rest as HOT, WARM or COLD by how recent the post is and how crowded the thread already is.
5. For the best leads, it reads the thread and writes a reply that helps first. Where a subreddit bans self-promotion, the reply contains no product mention at all. Where it is allowed, the mention is soft and disclosed.
6. A compliance check approves, rejects or sends the draft back for revision.
7. You review the queue and send. Every send passes an account health check first.

### Why it is built this way

- **One campaign file per offer.** New outreach means a new YAML file, not a code fork. The same engine runs any number of campaigns.
- **AI with a safety net.** Every agent has an LLM path (OpenAI, Groq, Anthropic or Fireworks) and a deterministic heuristic fallback, so the pipeline runs end to end even with no LLM key.
- **No Reddit API key needed.** Live Reddit access goes through [Zernio](https://zernio.com), and local tools (`opencli`, `rdt`) are supported too.
- **Built to run unattended.** Loops are bounded per cycle, save progress as they go, survive crashes, respect rate limits and never process the same post twice.
- **Python and FastAPI** for the agent pipeline and a small read-only API. **React, TypeScript, Vite and Tailwind** for the dashboard. **SQLite** locally and **Postgres** in the cloud, behind the same interface.

### Challenges we hit

- **LLM scoring is slow** (about 12 to 20 seconds per call). A cheap heuristic prefilter now caps the LLM batch at about 40 posts per run, and the LLM calls run in parallel with incremental saves.
- **Cloud disks are temporary.** Heroku, Railway and Render wipe local files on restart, so cloud deploys use Postgres.
- **Anonymous Reddit reads are blocked (HTTP 403).** Shadowban probes therefore report "unknown" today instead of blocking a send. See [Project status](#project-status-and-roadmap).
- **Rate limits.** The Zernio free tier allows about 60 requests per minute, so the client retries HTTP 429 responses with backoff.

## Features

- 🔎 **Lead discovery:** searches your keywords across your target subreddits and their feeds, with no duplicates.
- 🎯 **Fit and intent scoring:** every post gets a 0 to 100 score, and non-prospects such as vendors and advice posts are dropped.
- 🌡️ **Triage:** HOT, WARM and COLD tiers by recency and thread saturation, with a channel hint.
- ✍️ **Value-first drafting:** replies that lead with real help, with rule-aware product mentions.
- 🛡️ **Compliance and safety:** per-subreddit rules (strict by default), self-promotion checks, rate limits, warm-up pacing, a send circuit breaker and a health gate before every send.
- 🧭 **Subreddit Scout:** finds and validates new target subreddits for each vertical in your ideal customer profile, once a day.
- 👥 **Account warm-up swarm:** rotates several accounts to build karma with helpful, non-promotional comments (dry-run unless you confirm).
- 💬 **Optional DMs and handoff:** draft cold DMs (off by default, capped) and hand ready leads to another system through a signed webhook.
- 📊 **Live dashboard:** funnel, leads, review queue, handoffs, accounts, scout results and account health.
- 🔌 **Runs offline:** a mock Reddit backend and heuristic agents let you develop and demo with zero keys.
- 🐳 **One-command Docker:** API, demo data and dashboard come up together.

## How it works

```
 Reddit ─(Zernio / rdt / opencli)─►  Discovery → Qualification → Triage → Research → Personalization → Compliance ─► store
                                        (watch loop, every 15 to 30 min)                                     (SQLite / Postgres)
                                     Scout (daily): find and validate subreddits ──────────────────────────────►  │
                                     Warm-up swarm: rotate accounts, build karma ──────────────────────────────►  │
                                                                                                                   │
                                                    FastAPI /api/* (read-only, token-gated)  ◄─────────────────────┘
                                                                  ▲ HTTP (JSON)
                              React dashboard: Overview · Leads · Review · Handoffs · Accounts · Scout · Performance
```

Two long-running loops share one database:

- **`watch`** runs the full pipeline on a fixed interval (15 minutes by default, 30 minutes in the deploy configs) and drafts only the top leads per cycle.
- **`scout`** runs daily, finds new subreddits for each vertical, checks them against live feeds and saves them. The `watch` loop adds them to discovery on its next cycle.

## Install and run

### Option 1: Docker (recommended, no keys needed)

You need [Docker](https://www.docker.com/) with Compose.

```bash
git clone https://github.com/niihhhall/subreach.git
cd subreach
docker compose -f docker-compose.local.yml up --build
```

- Dashboard: **http://localhost:5300**
- API: **http://localhost:8010** (local token: `devtoken`)

This starts the API, seeds realistic demo data into a local SQLite file under `./data`, and serves the dashboard. It uses the mock Reddit backend, so no Reddit or LLM keys are needed. The `devtoken` token and open CORS setting are for local use only.

### Option 2: Local development (hot reload)

You need Python 3.12 and Node.js 20 or newer.

```bash
# Backend
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/seed_demo.py
DASHBOARD_TOKEN=devtoken REDDIT_BACKEND=mock uvicorn reddit_outreach.web:app --port 8010
```

On Windows PowerShell, set the variables first: `$env:DASHBOARD_TOKEN="devtoken"; $env:REDDIT_BACKEND="mock"`, then run the `uvicorn` command.

```bash
# Dashboard (second terminal)
cd dashboard
npm install
npm run dev -- --port 5300
```

`setup.sh` and `setup.ps1` also exist. They install the package and start the interactive `setup` wizard, which writes your `.env`, checks your keys and connects a Reddit account. Note that they install from `pyproject.toml`, which does not include the web dependencies yet, so run `pip install -r requirements.txt` as well if you want the dashboard.

### Option 3: Go live (real Reddit and Postgres)

1. Get a `ZERNIO_API_KEY` from [Zernio](https://zernio.com) and connect your Reddit account (`python -m reddit_outreach.cli zernio-setup`).
2. Set `DATABASE_URL` to a Postgres database.
3. Deploy the full stack (watch, scout and warm workers, plus the web process):
   - a VPS with `docker-compose.yml`,
   - **Render** with `render.yaml`,
   - **Heroku** with `app.json` and `Procfile`,
   - or Linux with systemd using `deploy/reddit-outreach.service`.

Full guides: [`docs/CLOUD.md`](docs/CLOUD.md) and [`docs/DEPLOY.md`](docs/DEPLOY.md). The React dashboard can be deployed on its own (for example on Vercel with `dashboard/vercel.json`); see [`dashboard/README.md`](dashboard/README.md).

## How to use it

### 1. Write a campaign

A campaign is one YAML file in `campaigns/`. Copy [`campaigns/example_campaign.yaml`](campaigns/example_campaign.yaml) and fill in your product, value proposition, ideal customer, keywords, subreddits and guardrails. Unknown keys are rejected, so typos fail early. [`campaigns/markeye.yaml`](campaigns/markeye.yaml) is a full real-world example, and [`campaigns/example-digital-products.yaml`](campaigns/example-digital-products.yaml) is a second template.

### 2. Run the pipeline

All commands use `python -m reddit_outreach.cli <command> <campaign>`.

```bash
python -m reddit_outreach.cli doctor                                   # show detected backends and keys
python -m reddit_outreach.cli find  campaigns/example_campaign.yaml    # discovery + scoring only, fast
python -m reddit_outreach.cli run   campaigns/example_campaign.yaml    # one full pipeline pass
python -m reddit_outreach.cli queue campaigns/example_campaign.yaml    # approved drafts waiting for review
python -m reddit_outreach.cli review campaigns/example_campaign.yaml <post_id>        # full detail for one lead
python -m reddit_outreach.cli send  campaigns/example_campaign.yaml --via manual      # copy the draft, open the thread
```

### 3. Run it around the clock

```bash
python -m reddit_outreach.cli watch campaigns/example_campaign.yaml --interval 1800 --draft-budget 10   # pipeline every 30 min
python -m reddit_outreach.cli scout campaigns/example_campaign.yaml --loop    # daily subreddit discovery
```

### All commands

| Command | What it does |
|---|---|
| `setup` | Interactive setup: writes `.env`, checks keys, connects Reddit |
| `doctor` | Shows the detected Reddit backend, LLM provider and storage |
| `find` | Discovery and scoring only, a fast report for tuning your ideal customer profile |
| `run` | One full, bounded pipeline pass |
| `watch` | Runs the pipeline continuously |
| `scout` | Finds and validates target subreddits for each vertical |
| `leads` | Lists saved leads (no network) |
| `queue` | Shows approved drafts waiting for review |
| `review` | Shows full detail for one lead |
| `export` | Exports the queue to CSV |
| `send` | Sends an approved draft: `manual`, `comment`, `dm` or `post` |
| `zernio-setup` | Shows Zernio profiles and connects a Reddit account |
| `zernio-post` | Publishes an approved draft as a Reddit post through Zernio |
| `engage` | Scores threads worth a genuine reputation-building comment |
| `warm` | Runs the account warm-up swarm |
| `dm` | Drafts personal DMs to qualified prospects (high ban risk, off by default) |
| `handoff` | Sends a ready lead to another system through a signed webhook |
| `reputation` | Karma trend and comment outcomes; backs off if reputation drops |
| `health` | Probes account health and manages the send circuit breaker |
| `stats` | Funnel, subreddit, send and account analytics |
| `activity` | Shows the raw activity log |
| `migrate-db` | Copies a local SQLite database into Postgres |

Run any command with `--help` for its options.

### Safety defaults

- `send` with `comment`, `dm` or `post`, plus `warm`, `dm` and `handoff`, are **dry-runs** until you add `--confirm`.
- `watch --auto-comment` posts approved drafts without a person in the loop. It is off by default. Leave it off unless you accept that risk.
- Read each subreddit's rules before you send. Many communities ban self-promotion, and Reddit can suspend accounts that break its rules. You are responsible for how you use this tool.

## Configuration

Copy `.env.example` to `.env`, or set these as environment variables.

| Variable | Purpose |
|---|---|
| `ZERNIO_API_KEY` | Live Reddit read and publish through Zernio (leave unset for offline mock mode) |
| `REDDIT_BACKEND` | `auto` (default: `opencli` > `rdt` > `zernio` > `mock`), `opencli`, `rdt`, `zernio` or `mock` |
| `REDDIT_FALLBACK` | Optional second backend for reads only |
| `REDDIT_PROXY` | Optional proxy for networks that Reddit blocks |
| `OPENAI_API_KEY` / `GROQ_API_KEY` / `ANTHROPIC_API_KEY` / `FIREWORKS_API_KEY` | LLM-quality scoring and drafting (optional) |
| `OUTREACH_LLM_PROVIDER` / `OUTREACH_LLM_MODEL` | Choose the LLM provider and model (default `auto`) |
| `DATABASE_URL` | Postgres for 24/7 use (unset = local SQLite under `OUTREACH_DATA_DIR`, default `data`) |
| `DASHBOARD_TOKEN` | Secret that unlocks the web dashboard and API |
| `CLIENT_TOKEN` | Separate secret for the React dashboard API (falls back to `DASHBOARD_TOKEN`) |
| `CORS_ORIGINS` | Allowed dashboard origins (set this explicitly in production) |
| `CAMPAIGN` | Path to the active campaign YAML |
| `MARKEYE_WEBHOOK_URL` / `MARKEYE_WEBHOOK_SECRET` | Handoff webhook target and HMAC secret (blank = dry-run) |
| `SWARM_ACCOUNTS` / `SWARM_ACCOUNTS_B64` | Warm-up swarm roster for cloud deploys (locally, use `accounts.yaml` from `accounts.example.yaml`) |

`opencli` needs desktop Chrome, so it cannot run on a server. Cloud deploys use `zernio`.

Dashboard variables: `VITE_API_BASE`, `VITE_CLIENT_TOKEN` and `VITE_CAMPAIGN` (see `dashboard/.env.example`). Vite puts `VITE_CLIENT_TOKEN` into the public JavaScript bundle, so use a separate `CLIENT_TOKEN`, never your `DASHBOARD_TOKEN`.

## The dashboard

The React dashboard is a live, read-only view of the pipeline. It refreshes every 30 seconds. Each page reads one API endpoint:

| Page | Endpoint | Shows |
|---|---|---|
| Overview | `/api/overview` | Funnel, tiers, karma and live activity |
| Leads | `/api/leads` | Triaged prospects with subreddit, tier and pain points |
| Review | `/api/queue` | Drafts waiting for a person to send |
| Handoffs | `/api/outreach` | Leads handed off downstream |
| Accounts | `/api/swarm` | Warm-up swarm accounts |
| Scout | `/api/scout` | Discovered subreddits |
| Performance | `/api/health` | Pipeline and account health |

The backend also serves a simple server-rendered dashboard at `/` (pages for leads, queue, engagement, outreach, threads, swarm, health, scout and activity), unlocked with `DASHBOARD_TOKEN`.

## Tests

The test suite runs fully offline. It uses the mock Reddit backend and fakes every HTTP call, so it needs no keys.

```bash
pip install -r requirements.txt pytest httpx2
python -m pytest -q
```

Current result: **183 passed**. `httpx2` is needed because the installed FastAPI test client requires it. If you have real LLM keys in your shell, unset them before you run the tests.

Every pull request runs the tests and a dashboard build in GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Project structure

```
subreach/
├── reddit_outreach/        Python package: CLI, orchestrator, stores, API, safety
│   └── agents/             Discovery, qualification, research, personalization, compliance, scout, ...
├── dashboard/              React + TypeScript + Vite dashboard
├── campaigns/              Campaign YAML files (one per offer)
├── tests/                  Offline test suite (pytest)
├── scripts/seed_demo.py    Demo data for the dashboard
├── docs/                   Cloud and deploy guides
├── deploy/                 systemd unit and a GitHub Actions template
├── docker-compose*.yml     Local demo stack and full production stack
├── render.yaml, app.json   Render and Heroku deploy configs
└── CLAUDE.md               Architecture notes for AI coding agents
```

## Project status and roadmap

| Area | Status |
|---|---|
| Discovery, scoring, triage, Scout, compliance | ✅ Done |
| Drafting and health-gated sending | ✅ Done (tested offline) |
| DMs and webhook handoff | ✅ Code paths done, off by default |
| SQLite storage | ✅ Done |
| Postgres storage and migration | 🟡 Written, not yet covered by tests |
| Shadowban detection | 🟡 Reports "unknown" today because anonymous Reddit reads are blocked |
| React dashboard (read-only views) | 🟡 Seven pages live; engagement, threads and DM drafts pages still missing |
| Dashboard write actions (send, edit, audit) | 🔜 Planned |
| Reply and opt-in detection before handoff | 🔜 Planned |
| More channels and richer analytics | 🔜 Planned |

See [`CHANGELOG.md`](CHANGELOG.md) for what changed in each release.

## How to contribute

Contributions are welcome: bug reports, ideas, docs fixes and code. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to set up, test and open a pull request, and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Do not open a public issue for a security problem. Report it privately through [GitHub security advisories](https://github.com/niihhhall/subreach/security/advisories/new). See [`SECURITY.md`](SECURITY.md).

## Credits

- Built by [@niihhhall](https://github.com/niihhhall).
- Reddit access through [Zernio](https://zernio.com), with optional `rdt` and `opencli` backends. The CLI was first built on top of Agent-Reach.
- Badges from [shields.io](https://shields.io). Code of Conduct adapted from the [Contributor Covenant](https://www.contributor-covenant.org/). Changelog format from [Keep a Changelog](https://keepachangelog.com/).
- README structure follows [How to Write a Good README File for Your GitHub Project](https://www.freecodecamp.org/news/how-to-write-a-good-readme-file/) by Hillary Nyakundi on freeCodeCamp.

## License

[MIT](LICENSE). You are free to use, change and self-host Subreach.

---

<div align="center">

⭐ If Subreach helps you, please star the repo.

</div>
