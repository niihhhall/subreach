# Cloud Deployment — one-shot, any platform

This system runs as **two always-on agents** plus a **read-only dashboard**, all
coordinating through one database:

- **watch** — every 30 min: finds ad-runner / after-hours-lead prospects across the
  campaign's subreddits, qualifies + triages them, drafts value-first replies.
- **scout** — once a day: discovers + validates new target subreddits into the DB,
  which the watch agent then picks up automatically (no restart).
- **web** — a token-gated dashboard that reads the same DB and shows the funnel,
  triaged leads, the approved queue, Phase-2 engagement, account health + karma
  trend, scouted subreddits, and the activity log. It never writes or posts.

## Three rules that apply to every cloud target

1. **Use Postgres, not SQLite.** Heroku / Railway / Render have **ephemeral disks** —
   a restart wipes the filesystem, so SQLite leads would vanish. Set `DATABASE_URL`
   and the app switches to Postgres automatically. (On a VPS/Docker with a real
   volume, SQLite is fine — but the compose file below uses Postgres anyway.)
2. **Backend must be `zernio`** (or `rdt`). `opencli` needs a desktop Chrome and
   **cannot run headless** in a container/dyno. `REDDIT_BACKEND=zernio` is set for you.
3. **Run both processes.** `watch` and `scout` are separate long-running workers.

## Required environment variables

| Var | Required | Notes |
|-----|----------|-------|
| `ZERNIO_API_KEY` | ✅ | live Reddit read + send |
| `FIREWORKS_API_KEY` | ✅ (or another LLM key) | qualification + drafting |
| `OUTREACH_LLM_PROVIDER` | – | `fireworks` |
| `OUTREACH_LLM_MODEL` | – | `accounts/fireworks/models/deepseek-v4-pro` |
| `REDDIT_BACKEND` | – | `zernio` (mandatory on cloud) |
| `DATABASE_URL` | ✅ on cloud | Postgres connection string (auto-set by add-ons) |
| `CAMPAIGN` | – | which campaign file to run (default `campaigns/markeye.yaml`) |
| `DASHBOARD_TOKEN` | ✅ for the dashboard | shared secret that gates the web UI; unset = dashboard locks itself |
| `MARKEYE_WEBHOOK_URL` | Phase 4 only | where handoffs POST (blank = dry-run preview) |
| `MARKEYE_WEBHOOK_SECRET` | Phase 4 only | HMAC secret so Markeye can verify the handoff |

Never commit keys. Set them in the platform's env/secrets UI.

---

## Option A — Docker / any VPS (recommended)

Everything (both agents + Postgres) in one command:

```bash
# put your keys in .env first (ZERNIO_API_KEY, FIREWORKS_API_KEY)
docker compose up -d --build
docker compose logs -f watch     # or: logs -f scout
```

`restart: unless-stopped` survives crashes **and** host reboots. Postgres data
persists in the `pgdata` volume. Change `CAMPAIGN` in `docker-compose.yml` to run
a different offer.

## Option B — Heroku (one-click)

Uses `app.json` + `Procfile` + `runtime.txt`. Provisions Postgres and both workers.

```bash
heroku create my-outreach
heroku addons:create heroku-postgresql:essential-0
heroku config:set ZERNIO_API_KEY=... FIREWORKS_API_KEY=... \
  OUTREACH_LLM_PROVIDER=fireworks OUTREACH_LLM_MODEL=accounts/fireworks/models/deepseek-v4-pro \
  REDDIT_BACKEND=zernio CAMPAIGN=campaigns/markeye.yaml
git push heroku main
heroku ps:scale watch=1 scout=1
```
(Both are worker dynos — no free tier; ~$5-7/dyno/mo + Postgres.)

## Option C — Railway

Detects the `Procfile`. Add the **PostgreSQL** plugin (sets `DATABASE_URL`), set the
env vars above, and enable both `watch` and `scout` processes.

## Option D — Render (blueprint)

Uses `render.yaml`: **New → Blueprint → this repo**. It creates the Postgres DB and
both workers. Fill in `ZERNIO_API_KEY` and `FIREWORKS_API_KEY` (marked `sync:false`).

---

## Outreach phases (what the CLI can do)

The pipeline runs in phases so you can dial risk up slowly:

- **Phase 1 — find & qualify:** `find` / `run` discover posts, qualify prospects,
  triage by sendability, and draft value-first comments you review (`queue`).
- **Phase 2 — engagement / CQS:** `engage` scores threads worth a genuine,
  non-promo comment to build contributor quality; `engage --write N` drafts them.
  Posting is health-gated and held while an account is shadowbanned.
- **Phase 3 — DM outreach:** `dm <campaign>` drafts personal cold DMs to qualified
  prospects. **Highest ban-risk in the system** — so it's OFF by default
  (`dm_enabled: false`), separately capped (`max_dms_per_day`), health-gated, and
  dry-run unless you pass `--confirm`. Warm the account first.
- **Phase 4 — handoff to Markeye:** `handoff <campaign> --id <post_id> --confirm`
  POSTs a signed (`X-Markeye-Signature`) payload to Markeye, which owns the
  WhatsApp SDR (BANT / Calendly / 5-message cadence). We do **not** rebuild that
  here — this is a clean, idempotent webhook handoff. Blank URL = dry-run preview.
  `handoff <campaign> --pending` lists leads ready to hand off.

## The dashboard (web process)

A lightweight, **read-only** ops UI — track everything without the terminal.

```bash
# 1. pick a long random secret
export DASHBOARD_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(24))")
# 2. run it (local)
uvicorn reddit_outreach.web:app --host 0.0.0.0 --port 8000
# 3. open once with the token; a cookie remembers you afterwards
#    http://localhost:8000/?token=YOUR_TOKEN
```

- **Docker:** the `web` service is already in `docker-compose.yml` (port 8000).
  Add `DASHBOARD_TOKEN=...` to `.env`, then `docker compose up -d`.
- **Heroku / Render:** the `web` process is defined in `Procfile` / `render.yaml`.
  Render + Heroku set `DASHBOARD_TOKEN` for you (a generated secret); read it from
  the dashboard's env and open `https://<your-app>/?token=...`.
- **Multi-campaign:** if `campaigns/` holds more than one file, a switcher appears
  in the header; or hit `/?campaign=<name>`.
- **Auth model:** unset token → the UI shows a setup notice and leaks nothing;
  wrong token → login page; right token → access (via `?token=` once, cookie after).
  There are no write endpoints, so nothing can be changed from the browser. Always
  serve it over HTTPS (the platform router does this on Heroku/Render).
- **Liveness:** `GET /health-check` is unauthenticated for load-balancer probes.

## Reusing this for other outreach (the "mold")

**Do not fork the code per offer.** The campaign YAML *is* the mold — one codebase,
many campaigns. To run a different outreach, add a campaign file and point a
deployment at it via `CAMPAIGN`:

```
campaigns/markeye-aisdr.yaml       # office-hours lead SDR
campaigns/markeye-automation.yaml  # AI automation builds
campaigns/markeye-fbads.yaml       # Facebook-ads lead gen
```

**Recommended: one deployment per offer** (Model A) — same image, different
`CAMPAIGN` + its own Reddit account + its own database. Clean isolation, separate
ban-risk, separate dashboards. Every code improvement propagates by redeploying the
same image; you never hand-copy agents between forks.

The store namespaces all data by campaign name, so multiple campaigns can also
share one deployment/DB if you prefer (Model B) — cheaper, shared blast radius.
