# CLAUDE.md — agent context for the Reddit outreach system

Read this first. It captures the architecture, commands, conventions, and the
gotchas learned the hard way, so any AI session is productive immediately and
doesn't re-derive or break things.

## What this is
A production-grade Reddit lead-gen engine for **Markeye** (a WhatsApp AI SDR).
It finds businesses that run paid ads and lose leads after hours / have no
qualification system, and drafts value-first replies for review. Config-driven:
one codebase, many campaigns.

## Architecture
Two always-on agents coordinating through the store (DB):
- **watch loop** (`cli watch`) — every ~30 min: discovery → funnel-qualify →
  triage → draft top-N → compliance → queue. Bounded per cycle.
- **scout loop** (`cli scout --loop`) — daily: derive verticals → niche-brainstorm
  subreddits per vertical → validate against live feeds → persist to DB. The watch
  loop unions these into discovery every cycle (`Orchestrator._refresh_feeds`).

Pipeline agents (`reddit_outreach/agents/`): Discovery → Qualification → Research →
Personalization → Compliance, plus the SubredditScout. Orchestrator wires them.

## Key modules
- `orchestrator.py` — `run()` (bounded full pipeline), `find()` (discovery+qualify
  only, fast), `_prefilter()` (heuristic→LLM funnel, caps LLM batch to top ~40),
  `_qualify_concurrent()` (parallel + incremental save), `_refresh_feeds()` (merge
  DB-scouted subs).
- `agents/qualification.py` — LLM scores fit/intent + `is_prospect`/`poster_role`;
  non-prospects (advice/vendor posts) are disqualified.
- `agents/personalization.py` — rule-aware: pure-value draft (no product) where a
  sub bans self-promo; disclosed mention only where allowed.
- `agents/scout.py` — vertical-aware niche mining + live validation.
- `triage.py` — recency + saturation → sendability tier (HOT/WARM/COLD) + channel hint.
- `rules.py` — per-subreddit rule resolution (strict-by-default floor + overrides).
- `health.py` — account health, shadowban probe, circuit breaker, send gate.
- `store.py` / `store_postgres.py` — identical interface; SQLite local, Postgres cloud.
- `zernio.py` — Reddit read/write via Zernio API (429 retry+backoff built in).
- `config.py` — `Campaign` (the mold) + `Settings` (env).

## Commands
```
cli find <campaign> [--fresh --max-age-days N --tier hot]   # fast tuning loop
cli leads <campaign> [--tier hot --stage all]               # retrieve saved leads
cli scout <campaign> [--verticals a,b --apply | --loop]     # discover subreddits
cli watch <campaign> [--interval 1800 --draft-budget 10]    # 24/7 lead finder
cli run <campaign>                                          # one bounded pipeline pass
cli queue/review/stats/activity/health/send <campaign>
```

## Conventions
- Every agent has an LLM path AND a deterministic heuristic fallback (runs offline).
- The **campaign YAML is the mold** — new outreach = new campaign file, never a code fork.
- Store keys everything by campaign name (idempotent, dedup by post id).
- Tests: `python -m pytest -q` — fully offline (mock backend, monkeypatched HTTP).
  Currently ~87 passing. Add tests for new behavior.

## Gotchas (learned the hard way — don't repeat)
- **opencli needs desktop Chrome** — cannot run headless/cloud. Cloud uses `zernio`.
- **Cloud = Postgres** — Heroku/Railway/Render have ephemeral disks; SQLite is wiped.
- **opencli search is global junk**; its value is comment-reading (Phase 2). Zernio
  search is subreddit-scoped and better for discovery.
- **Reddit anonymous JSON 403s** — shadowban/verification probes fail open (unknown),
  detection is currently dark until an authenticated read path is wired.
- **LLM qualification is slow** (~12-20s/call) — always funnel (prefilter → cap batch)
  + run concurrent, or 21+ subs will time out.
- **max_leads_per_run** must be high enough (200) or feed results get truncated.
- Zernio free tier ~60 req/min — the client retries 429s with backoff; keep it.

## Deploy
See `docs/CLOUD.md`. Docker/compose (VPS) or Procfile/app.json (Heroku) / render.yaml
(Render). Two workers (watch + scout) + Postgres. `CAMPAIGN` env selects the offer.

## Phase roadmap
- Phase 1 (find pain points): ✅ done — funnel, prospect filter, triage, scout, harness.
- Phase 2 (drafting that passes + sending): drafts approved ✅; sending is health-gated.
- Phase 3 (DM outreach): send path exists (`--via dm`), use sparingly.
- Phase 4 (Markeye handoff): route interested repliers to WhatsApp/Markeye (webhook).

## Style
Direct, evidence-based. Verify with real data/tests before claiming. Keep the
harness properties (bounded, incremental-save, crash-resilient, rate-limit-aware,
idempotent) intact in any new loop.
