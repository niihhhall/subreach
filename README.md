<div align="center">

# Subreach

### Value-first Reddit outreach, on autopilot.

**Open-source, self-hostable Reddit lead-generation agent** — it finds businesses that need what you sell, qualifies them with AI, and drafts compliance-checked replies for human review. Comes with a live web dashboard.

[![License: MIT](https://img.shields.io/badge/License-MIT-3b82f6.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

</div>

---

## What is Subreach?

**Subreach is an open-source Reddit outreach and lead-generation tool that you self-host.** A pipeline of specialized agents searches Reddit for people describing a problem your product solves, scores each prospect for fit and intent, reads the thread, and drafts a genuine, value-first reply — then runs it through a compliance check and drops it into a human-review queue. It runs 24/7, keeps your account safe with built-in rate limiting and shadowban detection, and ships with a modern React dashboard to watch the whole funnel.

No Reddit API key is required (Reddit access is via [Zernio](https://zernio.com)), and the entire system runs **fully offline with a mock backend**, so you can try it with zero keys.

> **In one line:** find real Reddit prospects → AI-qualify them → draft compliant, helpful replies → review and send.

## Table of contents

- [Features](#-features)
- [How it works](#-how-it-works)
- [Quickstart](#-quickstart)
- [Configuration](#%EF%B8%8F-configuration)
- [The dashboard](#%EF%B8%8F-the-dashboard)
- [CLI](#-cli)
- [FAQ](#-faq)
- [Roadmap](#%EF%B8%8F-roadmap)
- [License](#-license)

## ✨ Features

- 🔎 **AI lead discovery** — search Reddit across your keywords × target subreddits, deduped by post.
- 🎯 **Fit + intent scoring** — every prospect is qualified (0–100) and low-fit posts are dropped.
- ✍️ **Value-first drafting** — helpful replies that lead with real value; product mention is soft and disclosed.
- 🛡️ **Compliance + safety** — per-subreddit rules, self-promo checks, rate limiting, warm-up pacing, circuit breaker.
- 🧭 **Subreddit Scout** — automatically discovers and validates new target subreddits per vertical.
- 👥 **Account warm-up swarm** — rotates multiple accounts to build genuine karma before outreach.
- 📊 **Live dashboard** — funnel, leads, review queue, handoffs, accounts, scout, and account health.
- 🔌 **No Reddit API key** — powered by Zernio; runs fully offline in mock mode for development.
- 🐳 **One-command Docker** — backend + seeded data + dashboard, up together.

## 🧭 How it works

```
 Reddit ──Zernio──►  Discovery → Qualification → Research → Personalization → Compliance ──► store
                         (watch loop, ~30 min)                                        (SQLite / Postgres)
                     Scout (daily): find + validate subreddits ─────────────────────────►  │
                     Warm swarm: rotate accounts, build karma ───────────────────────────►  │
                                                                                             │
                                     FastAPI /api/* (read-only, token-gated)  ◄─────────────┘
                                                   ▲ HTTP (JSON)
                            React dashboard: Overview · Leads · Review · Handoffs · Accounts · Scout · Performance
```

Every agent has an **LLM path** (OpenAI / Groq / Anthropic / Fireworks) **and a deterministic heuristic fallback**, so the pipeline runs end-to-end even with no API keys.

## 🚀 Quickstart

### One command (Docker) — recommended

```bash
git clone https://github.com/niihhhall/subreach.git
cd subreach
docker compose -f docker-compose.local.yml up --build
```

- 🖥️ Dashboard → **http://localhost:5300**
- 🔗 API → **http://localhost:8010** (local token: `devtoken`)

It seeds realistic demo data and needs **no Reddit or LLM keys** (mock backend).

### Local dev (hot reload)

<details>
<summary>Backend (Python 3.12) + Dashboard (Node 20)</summary>

```bash
# backend
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/seed_demo.py
DASHBOARD_TOKEN=devtoken REDDIT_BACKEND=mock uvicorn reddit_outreach.web:app --port 8010

# dashboard
cd dashboard && npm install && npm run dev -- --port 5300
```
</details>

### Go live (real Reddit + Postgres)

Set a `ZERNIO_API_KEY` and deploy the full stack (workers + scout + dashboard) on a VPS (`docker-compose.yml`), **Render** (`render.yaml`), or **Heroku** (`app.json`). See [`docs/CLOUD.md`](docs/CLOUD.md) and [`docs/DEPLOY.md`](docs/DEPLOY.md).

## ⚙️ Configuration

| Variable | Purpose |
|---|---|
| `ZERNIO_API_KEY` | Live Reddit read + publish (omit for offline mock mode) |
| `REDDIT_BACKEND` | `auto` \| `zernio` \| `rdt` \| `mock` |
| `OPENAI_API_KEY` / `GROQ_API_KEY` / `ANTHROPIC_API_KEY` / `FIREWORKS_API_KEY` | LLM-quality drafting (optional) |
| `DATABASE_URL` | Postgres for 24/7 (unset = local SQLite) |
| `DASHBOARD_TOKEN` / `CLIENT_TOKEN` | Secrets that unlock the dashboard/API |
| `CAMPAIGN` | Path to the active campaign YAML (the "mold") |

Dashboard: `VITE_API_BASE`, `VITE_CLIENT_TOKEN`, `VITE_CAMPAIGN` (see `dashboard/.env.example`).

## 🖥️ The dashboard

A live, read-only view of the pipeline. Pages map to backend endpoints:

| Page | Endpoint | Shows |
|---|---|---|
| Overview | `/api/overview` | funnel, tiers, karma, live activity |
| Leads | `/api/leads` | triaged prospects (subreddit, tier, pain points) |
| Review | `/api/queue` | drafts awaiting a human send |
| Handoffs | `/api/outreach` | leads handed off downstream |
| Accounts | `/api/swarm` | warm-up swarm accounts |
| Scout | `/api/scout` | discovered subreddits |
| Performance | `/api/health` | pipeline + account health |

## 🧩 CLI

```bash
python -m reddit_outreach.cli doctor                         # what's detected
python -m reddit_outreach.cli run     campaigns/example_campaign.yaml   # one pipeline pass
python -m reddit_outreach.cli watch   campaigns/example_campaign.yaml   # 24/7 lead finder
python -m reddit_outreach.cli scout   campaigns/example_campaign.yaml   # discover subreddits
python -m reddit_outreach.cli queue   campaigns/example_campaign.yaml   # review drafts
```

## ❓ FAQ

**Do I need a Reddit API key?** No. Reddit access is handled by Zernio, or you can run fully offline in mock mode.

**Is this a spam bot?** No. Subreach is built for *value-first* outreach: it drafts genuinely helpful replies, enforces per-subreddit rules, discloses affiliation, rate-limits sends, and keeps a human in the loop. Read each subreddit's rules — many ban self-promotion.

**Can I self-host it?** Yes — Docker, Render, Heroku, Railway, Fly, or any VPS. State lives in SQLite locally or Postgres in the cloud.

**What stack is it?** Python + FastAPI backend, React + TypeScript + Vite + Tailwind dashboard, Docker for deployment.

**Does it work without an LLM key?** Yes. Every agent falls back to deterministic heuristics.

## 🗺️ Roadmap

- ✅ Discovery, qualification, triage, scout, compliance, dashboard (read-only)
- 🔜 Dashboard write actions (send, edit, audit) from the UI
- 🔜 More channels + richer analytics

## 📄 License

[MIT](LICENSE) — free to use, modify, and self-host.

---

<div align="center">

**Keywords:** reddit outreach · reddit lead generation · reddit marketing automation · AI SDR · social selling · reddit bot · lead-gen agent · prospecting · self-hosted · FastAPI · React dashboard · open source

⭐ If Subreach helps you, consider starring the repo.

</div>
