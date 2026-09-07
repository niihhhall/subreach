# Deploy, migrate to Supabase, and observe

This covers the three things you asked: **where to host**, **how to move the DB
into Supabase**, and **how to watch everything**. (Base infra + env vars live in
`CLOUD.md`; this is the swarm + Supabase + observability layer.)

---

## 1. Where to host — Heroku vs VPS (honest take)

Both work because **Zernio fronts every Reddit call** — the Reddit-facing
requests go through Zernio's infrastructure/OAuth, not your server's IP. That
removes the usual "datacenter IP gets flagged" problem that normally makes
cloud-hosted Reddit bots risky. So pick on operations, not IP:

| | Heroku (PaaS) | VPS (Docker) |
|---|---|---|
| Setup | easiest — `git push`, uses `Procfile` | `docker compose up -d` |
| Cost | ~$5-7/worker/mo + Postgres | one box (~$5-12/mo) runs everything |
| Persistence | ephemeral disk → **must** use Postgres | volume-backed Postgres in compose |
| Restarts | daily dyno cycling (loops are crash-safe, so fine) | only on your terms |
| Best for | least ops, fastest to live | cheapest always-on, full control |

**My recommendation for this pilot:** a small **VPS with `docker compose`**.
One box runs `db` + `watch` + `scout` + `warm` + `web`, the roster mounts as a
file, and nothing cycles under you. Heroku is the right call only if you want
zero server management and don't mind paying per worker.

**Processes** (all defined for you in `Procfile`, `docker-compose.yml`, `render.yaml`):
- `web` — the dashboard (observe everything)
- `watch` — Phase 1 lead finder
- `scout` — subreddit discovery
- `warm` — the warm-up swarm (`--confirm --loop`) — **scale this to 1 only when
  you're ready to post**; it ships at quantity 0 on Heroku so nothing posts by accident.

### Heroku
```bash
heroku create your-app
heroku addons:create heroku-postgresql:essential-0
heroku config:set REDDIT_BACKEND=zernio CAMPAIGN=campaigns/markeye.yaml \
  OUTREACH_LLM_PROVIDER=fireworks OUTREACH_LLM_MODEL=accounts/fireworks/models/deepseek-v4-pro \
  FIREWORKS_API_KEY=... DASHBOARD_TOKEN="$(openssl rand -hex 24)"
# swarm keys + roster (roster as a JSON/YAML string, since there's no file):
heroku config:set ZERNIO_KEY_ACCT1=... ZERNIO_KEY_ACCT2=... ZERNIO_KEY_ACCT3=...
heroku config:set SWARM_ACCOUNTS="$(cat accounts.yaml)"
git push heroku main
heroku ps:scale web=1 watch=1 scout=1        # warm stays 0 until you're ready
# when ready to warm up:
heroku ps:scale warm=1
```

### VPS (Docker)
```bash
# put keys in .env and fill accounts.yaml, then:
docker compose up -d --build
docker compose logs -f warm      # watch the swarm
```

---

## 2. Move the whole database into Supabase

Right now your data is a local SQLite file per campaign (`data/<campaign>.db`).
Supabase is just managed Postgres, so the move is: **get the connection string
→ run one command → point the deploy at it.**

1. **Get the Supabase connection string.** Supabase dashboard → Project →
   Settings → Database → Connection string → **URI**. Use the connection-pooler
   URI for cloud (looks like
   `postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres`).

2. **Install the Postgres driver** (once): `pip install "psycopg[binary]"`.

3. **Run the migration** — copies leads, the full activity/audit log, accounts,
   health snapshots + breaker state, scouted subreddits, reputation, and rules,
   preserving original timestamps (so your karma trend and history survive):
   ```bash
   python -m reddit_outreach.cli migrate-db campaigns/markeye.yaml \
       --to "postgresql://postgres.<ref>:<pw>@...pooler.supabase.com:5432/postgres"
   ```
   Re-running is safe for keyed tables; add `--replace` to also clear and
   re-copy the append-only history (activities/health/reputation) without dupes.

4. **Point everything at Supabase.** Set `DATABASE_URL` to the same URI in your
   deploy (Heroku config / compose env / `.env`). Every worker **and** the
   dashboard then read/write Supabase automatically — the store switches backends
   on `DATABASE_URL` alone, no code change.

5. **Verify:** open the dashboard (it now reads Supabase) or run
   `python -m reddit_outreach.cli stats campaigns/markeye.yaml` and confirm the
   funnel counts match what you had locally.

Do the migration **once**, before the cloud workers start writing, so you don't
split history across two databases.

---

## 3. Observe everything

**The dashboard is the control tower** (`web` process, token-gated, read-only):
- **Overview** — funnel, account health, karma, breaker at a glance
- **Swarm** — per-account warm-up: subreddits, comments today vs cap, karma,
  health, breaker, awake/asleep window, whether the key is present
- **Health** — per-account probe history + karma-trend chart + comment
  verifications (visible/removed) — this is where a shadowban shows up early
- **Outreach** — Phase 3 DM drafts + Phase 4 handoff log
- **Leads / Queue / Engagement / Scout / Activity** — the rest of the pipeline

Open it at `https://<your-app>/?token=<DASHBOARD_TOKEN>` (Heroku/Render terminate
HTTPS for you). On a bare VPS, put it behind a reverse proxy with TLS.

**Logs (the swarm narrates each cycle):**
```bash
# Docker
docker compose logs -f warm
# Heroku
heroku logs -t --dyno warm
```
Each cycle prints per-account `engageable / drafted / posted / blocked` and any
breaker trips or "outside active hours" skips.

**What to watch during the 2-week warm-up:**
- **Karma climbing** on the Swarm/Health pages = warm-up is working.
- **Breaker OPEN** on any account = a removal/shadow spike was detected; that
  account backs off automatically. Investigate before resuming.
- **Comment verifications = removed** = a subreddit is nuking the comments; swap
  that sub out of the account's roster.
- **Health status → banned/at_risk** = stop that account; do not promote it to
  outreach.

Promote an account from warm-up to real outreach only after ~2 weeks of climbing
karma, a healthy status, and no breaker trips.
