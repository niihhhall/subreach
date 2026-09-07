# -*- coding: utf-8 -*-
"""Command-line interface for the Reddit multi-agent outreach system.

Commands:
    run       Run the full pipeline for a campaign
    queue     Show approved drafts awaiting human review
    review    Inspect a single lead in detail
    export    Export the outreach queue to CSV
    health    Probe account health / shadowban status; manage the send breaker
    doctor    Show detected Reddit backend + LLM provider

Usage:
    python -m reddit_outreach.cli run campaigns/example_campaign.yaml
    python -m reddit_outreach.cli queue campaigns/example_campaign.yaml
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time

from .config import Campaign, Settings
from .models import Stage
from .orchestrator import Orchestrator
from .reddit_client import RedditClient
from .store import LeadStore, open_store
from .llm import LLM
from .zernio import ZernioClient, ZernioError
from .sender import manual_send, zernio_publish, zernio_comment, zernio_dm
from .health import HealthMonitor
from .triage import triage_lead


def _ensure_utf8():
    if sys.platform == "win32" and not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _load_dotenv(path: str = ".env") -> None:
    """Minimal, dependency-free .env loader. Existing env vars win."""
    for key, value in _read_env_file(path).items():
        os.environ.setdefault(key, value)


def _read_env_file(path: str = ".env") -> dict:
    """Parse a .env file into a dict (empty if missing)."""
    out: dict = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _write_env_file(values: dict, path: str = ".env") -> None:
    """Write a tidy .env with only the keys we manage (skips blanks)."""
    order = ["ZERNIO_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY",
             "FIREWORKS_API_KEY", "OUTREACH_LLM_PROVIDER", "OUTREACH_LLM_MODEL",
             "DATABASE_URL", "REDDIT_BACKEND", "OUTREACH_DATA_DIR"]
    lines = ["# reddit-outreach config — gitignored. Do not commit secrets.\n"]
    for key in order:
        val = values.get(key, "")
        if val:
            lines.append(f"{key}={val}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def main(argv=None):
    _ensure_utf8()
    _load_dotenv()
    parser = argparse.ArgumentParser(
        prog="reddit-outreach",
        description="Multi-agent Reddit outreach pipeline (built on Agent-Reach).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser(
        "setup", help="One-shot interactive setup: write .env, verify keys, connect Reddit")
    p_setup.add_argument("--zernio-key", default="")
    p_setup.add_argument("--llm-key", default="", help="OpenAI/Groq/Anthropic key (auto-detected by prefix)")
    p_setup.add_argument("--database-url", default="", help="Supabase/Postgres URL (blank = local SQLite)")
    p_setup.add_argument("--yes", action="store_true",
                         help="Non-interactive: use flags + existing .env, no prompts")

    p_run = sub.add_parser("run", help="Run the full pipeline for a campaign")
    p_run.add_argument("campaign", help="Path to campaign YAML/JSON file")
    p_run.add_argument("--limit", type=int, default=10, help="Results per search query")
    p_run.add_argument("--draft-budget", type=int, default=10,
                       help="Max leads to draft per run (top by sendability; keeps cycles bounded)")

    p_scout = sub.add_parser(
        "scout", help="Niche-mine target subreddits per vertical from the ICP "
                      "(derive verticals → niche brainstorm → live validation → rank)")
    p_scout.add_argument("campaign")
    p_scout.add_argument("--verticals", default="",
                        help="Comma-separated verticals to niche into "
                             "(e.g. solar,logistics,manufacturing). Default: derive from ICP")
    p_scout.add_argument("--per-vertical", type=int, default=10,
                        help="Max subreddits to brainstorm per vertical")
    p_scout.add_argument("--apply", action="store_true",
                        help="Append this run's new validated subreddits to feed_subreddits")
    p_scout.add_argument("--apply-stored", action="store_true",
                        help="Skip scouting; apply ALL active scouted subs (from every "
                             "past run) to feed_subreddits. Fast, no LLM/validation.")
    p_scout.add_argument("--no-validate", action="store_true",
                        help="Skip the live feed check (brainstorm only)")
    p_scout.add_argument("--loop", action="store_true",
                        help="Run 24/7: keep discovering + validating subreddits into the DB")
    p_scout.add_argument("--interval", type=int, default=86400,
                        help="[--loop] seconds between scout cycles (default 86400 = daily)")
    p_scout.add_argument("--once", action="store_true",
                        help="[--loop] run a single cycle and exit")

    p_engage = sub.add_parser(
        "engage", help="Phase 2: score threads worth a genuine reputation-building "
                       "comment (CQS) — dry-run, no posting")
    p_engage.add_argument("campaign")
    p_engage.add_argument("--limit", type=int, default=8, help="Results per query/feed")
    p_engage.add_argument("--subreddits", default="", help="Comma-separated subreddit override")
    p_engage.add_argument("--write", type=int, default=0, metavar="N",
                        help="Also draft engagement comments for the top N threads (dry-run)")
    p_engage.add_argument("--confirm", action="store_true",
                        help="[--write] Actually POST the ready comments (health-gated, "
                             "comment-only). Requires rdt backend + logged-in account.")

    p_dm = sub.add_parser(
        "dm", help="Phase 3: draft personal cold DMs to qualified prospects "
                   "(HIGH ban-risk — OFF unless dm_enabled + --confirm; dry-run otherwise)")
    p_dm.add_argument("campaign")
    p_dm.add_argument("--limit", type=int, default=8,
                      help="How many top prospects to draft DMs for")
    p_dm.add_argument("--min-priority", type=int, default=0,
                      help="Only DM prospects at/above this priority")
    p_dm.add_argument("--max-sends", type=int, default=3,
                      help="[--confirm] max DMs to actually send this run (spam guard)")
    p_dm.add_argument("--confirm", action="store_true",
                      help="Actually send ready DMs (needs dm_enabled: true in the "
                           "campaign + a Zernio Reddit account). Dry-run without this.")

    p_ho = sub.add_parser(
        "handoff", help="Phase 4: hand a lead off to Markeye (the WhatsApp SDR) via a "
                        "signed webhook — dry-run unless --confirm")
    p_ho.add_argument("campaign")
    p_ho.add_argument("--id", default="", help="Post id of the lead to hand off")
    p_ho.add_argument("--whatsapp", default="",
                      help="Recipient WhatsApp number, if you collected it")
    p_ho.add_argument("--reason", default="", help="Why they're being handed off")
    p_ho.add_argument("--pending", action="store_true",
                      help="List leads ready to hand off (DM'd/approved, not yet handed off)")
    p_ho.add_argument("--confirm", action="store_true",
                      help="Actually POST to Markeye (needs handoff_webhook_url or "
                           "MARKEYE_WEBHOOK_URL). Dry-run preview without this.")

    p_warm = sub.add_parser(
        "warm", help="Warm-up swarm: rotate multiple accounts to build genuine karma "
                     "via helpful, non-promo comments (dry-run unless --confirm)")
    p_warm.add_argument("campaign")
    p_warm.add_argument("--accounts", default="accounts.yaml",
                        help="Path to the swarm roster (default accounts.yaml)")
    p_warm.add_argument("--limit", type=int, default=6,
                        help="Results per subreddit feed, per account")
    p_warm.add_argument("--confirm", action="store_true",
                        help="Actually post warm-up comments (per-account health-gated "
                             "+ capped + jittered). Dry-run without this.")
    p_warm.add_argument("--loop", action="store_true",
                        help="Run continuously (24/7 warm-up across the roster)")
    p_warm.add_argument("--interval", type=int, default=21600,
                        help="[--loop] seconds between cycles (default 21600 = 6h)")
    p_warm.add_argument("--once", action="store_true",
                        help="[--loop] run a single cycle and exit")

    p_mig = sub.add_parser(
        "migrate-db", help="Copy a campaign's local SQLite DB into Supabase/Postgres "
                           "(leads, activity history, health, karma — all of it)")
    p_mig.add_argument("campaign")
    p_mig.add_argument("--to", default="",
                       help="Target Postgres/Supabase DSN (default: DATABASE_URL env)")
    p_mig.add_argument("--from-dir", default="",
                       help="Local data dir holding the SQLite file (default: OUTREACH_DATA_DIR or 'data')")
    p_mig.add_argument("--replace", action="store_true",
                       help="Clear the campaign's target rows first (idempotent re-run)")

    p_find = sub.add_parser(
        "find", help="Phase 1: discovery + qualification only — a fast, cheap "
                     "ranked report to tune ICP precision (no drafting/sending)")
    p_find.add_argument("campaign")
    p_find.add_argument("--limit", type=int, default=8, help="Results per search query")
    p_find.add_argument("--min-priority", type=int, default=0,
                        help="Only show leads at/above this priority score")
    p_find.add_argument("--max-age-days", type=int, default=0,
                        help="Drop posts older than N days (0 = keep all, just tag them)")
    p_find.add_argument("--tier", default="", choices=["", "hot", "warm", "cold"],
                        help="Only show this sendability tier")
    p_find.add_argument("--subreddits", default="",
                        help="Comma-separated subreddits to override the campaign "
                             "(narrow the scope for fast iteration)")
    p_find.add_argument("--fresh", action="store_true",
                        help="Re-score from scratch (uses a scratch data dir so ICP "
                             "changes take effect without stale cached leads)")

    p_queue = sub.add_parser("queue", help="Show approved drafts awaiting review")
    p_queue.add_argument("campaign")
    p_queue.add_argument("--all", action="store_true", help="Include revise/rejected too")

    p_leads = sub.add_parser(
        "leads", help="List saved leads (read-only, no network) — retrieve what "
                      "`find` discovered, any time")
    p_leads.add_argument("campaign")
    p_leads.add_argument("--stage", default="active",
                        help="active (default: qualified→approved) | all | or a "
                             "specific stage (qualified/approved/drafted/...)")
    p_leads.add_argument("--min-priority", type=int, default=0)
    p_leads.add_argument("--max-age-days", type=int, default=0,
                        help="Drop posts older than N days (0 = keep all)")
    p_leads.add_argument("--tier", default="", choices=["", "hot", "warm", "cold"])
    p_leads.add_argument("--limit", type=int, default=50)

    p_review = sub.add_parser("review", help="Show full detail for one lead")
    p_review.add_argument("campaign")
    p_review.add_argument("post_id")

    p_export = sub.add_parser("export", help="Export the queue to CSV")
    p_export.add_argument("campaign")
    p_export.add_argument("-o", "--output", default="", help="Output CSV path")

    sub.add_parser("doctor", help="Show detected backends").add_argument(
        "campaign", nargs="?", default=""
    )

    # ── zernio-setup ──
    sub.add_parser("zernio-setup",
                   help="Show Zernio profiles/accounts; connect a Reddit account")

    # ── send (manual assist, or via Zernio comment/dm/post) ──
    p_send = sub.add_parser(
        "send", help="Send an approved draft: manual assist, or via Zernio comment/dm/post")
    p_send.add_argument("campaign")
    p_send.add_argument("--id", default="", help="Target a specific post id (default: top approved)")
    p_send.add_argument("--via", choices=["manual", "comment", "dm", "post"], default="manual",
                        help="manual (clipboard+browser) | comment (reply on thread) | "
                             "dm (message author) | post (new submission)")
    p_send.add_argument("--confirm", action="store_true",
                        help="Actually send (comment/dm/post default to a dry-run preview)")
    p_send.add_argument("--subreddit", default="", help="[via post] target subreddit")
    p_send.add_argument("--no-open", action="store_true", help="[via manual] don't open the browser")

    # ── zernio-post (publish a draft as a Reddit submission via Zernio) ──
    p_zp = sub.add_parser(
        "zernio-post",
        help="Publish an approved draft as a Reddit submission via Zernio (draft by default)")
    p_zp.add_argument("campaign")
    p_zp.add_argument("--id", required=True, help="Post id of the lead to publish")
    p_zp.add_argument("--subreddit", default="", help="Target subreddit (default: lead's own)")
    p_zp.add_argument("--title", default="", help="Submission title (default: derived)")
    p_zp.add_argument("--mode", choices=["draft", "publish", "schedule"], default="draft",
                      help="draft (safe default) | publish now | schedule")
    p_zp.add_argument("--at", default="", help="ISO datetime for --mode schedule")
    p_zp.add_argument("--tz", default="UTC", help="Timezone for scheduling")

    # ── health (account health + shadowban probe + circuit breaker) ──
    p_rep = sub.add_parser(
        "reputation", help="CQS/reputation dashboard: karma trend + comment outcomes; "
                           "backs off the account if reputation dips")
    p_rep.add_argument("campaign")
    p_rep.add_argument("--track", action="store_true",
                      help="Re-read recent posted comments to capture upvotes/removals")

    p_health = sub.add_parser(
        "health", help="Probe account health / shadowban status; manage the send circuit breaker")
    p_health.add_argument("campaign")
    p_health.add_argument("--reset-breaker", action="store_true",
                          help="Clear a tripped circuit breaker after you've fixed the issue")
    p_health.add_argument("--history", action="store_true",
                          help="Show recent health snapshots instead of a live probe")

    # ── stats (analytics dashboard) ──
    sub.add_parser("stats", help="Analytics: funnel, subreddits, sends, accounts").add_argument(
        "campaign"
    )

    # ── activity (raw event log) ──
    p_act = sub.add_parser("activity", help="Show the raw activity/outreach log")
    p_act.add_argument("campaign")
    p_act.add_argument("--limit", type=int, default=25)
    p_act.add_argument("--action", default="", help="Filter by action (e.g. sent, approved, run)")

    # ── watch (24/7 always-on agent) ──
    p_watch = sub.add_parser(
        "watch", help="Run the pipeline continuously, watching target subreddits for new posts")
    p_watch.add_argument("campaign")
    p_watch.add_argument("--interval", type=int, default=900,
                         help="Seconds between polls (default 900 = 15 min)")
    p_watch.add_argument("--limit", type=int, default=10, help="Results per query/feed per poll")
    p_watch.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    p_watch.add_argument("--draft-budget", type=int, default=10,
                         help="Max leads to draft per cycle (top by sendability; bounds cycle time)")
    p_watch.add_argument("--auto-comment", action="store_true",
                         help="Auto-post replies for approved leads (rate-limited). Off by default.")
    p_watch.add_argument("--max-sends", type=int, default=3,
                         help="[--auto-comment] max replies per cycle (spam guardrail)")
    p_watch.add_argument("--min-priority", type=int, default=80,
                         help="[--auto-comment] only auto-reply to leads at/above this priority")
    p_watch.add_argument("--health-every", type=int, default=4,
                         help="Run an account-health/shadowban probe every N cycles "
                              "(0 = never). Trips the send breaker on a detected ban.")

    args = parser.parse_args(argv)

    if args.command == "setup":
        return _cmd_setup(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "scout":
        return _cmd_scout(args)
    if args.command == "engage":
        return _cmd_engage(args)
    if args.command == "dm":
        return _cmd_dm(args)
    if args.command == "handoff":
        return _cmd_handoff(args)
    if args.command == "warm":
        return _cmd_warm(args)
    if args.command == "migrate-db":
        return _cmd_migrate_db(args)
    if args.command == "find":
        return _cmd_find(args)
    if args.command == "queue":
        return _cmd_queue(args)
    if args.command == "leads":
        return _cmd_leads(args)
    if args.command == "review":
        return _cmd_review(args)
    if args.command == "export":
        return _cmd_export(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "zernio-setup":
        return _cmd_zernio_setup(args)
    if args.command == "send":
        return _cmd_send(args)
    if args.command == "zernio-post":
        return _cmd_zernio_post(args)
    if args.command == "watch":
        return _cmd_watch(args)
    if args.command == "reputation":
        return _cmd_reputation(args)
    if args.command == "health":
        return _cmd_health(args)
    if args.command == "stats":
        return _cmd_stats(args)
    if args.command == "activity":
        return _cmd_activity(args)
    return 0


def _load(campaign_path: str):
    campaign = Campaign.load(campaign_path)
    settings = Settings.from_env()
    return campaign, settings


def _cmd_setup(args) -> int:
    """Interactive one-shot setup: collect keys, write .env, verify, connect Reddit."""
    interactive = sys.stdin.isatty() and not args.yes

    def mask(v: str) -> str:
        return (v[:6] + "…" + v[-4:]) if v and len(v) > 12 else ("set" if v else "")

    def ask(prompt: str, default: str = "", secret: bool = False) -> str:
        if not interactive:
            return default
        shown = f" [{mask(default) if secret else default}]" if default else ""
        try:
            val = input(f"{prompt}{shown}: ").strip()
        except EOFError:
            return default
        return val or default

    print("\n=== reddit-outreach setup ===\n")
    existing = _read_env_file(".env")

    # 1) Zernio key (the one thing that unlocks live Reddit + sending)
    zkey = args.zernio_key or ask(
        "Zernio API key (get one free at https://zernio.com → Settings → API Keys;\n"
        "  leave blank to run in offline mock mode)",
        existing.get("ZERNIO_API_KEY", ""), secret=True,
    )

    # 2) Optional LLM key (auto-detect provider by prefix)
    llm = args.llm_key or ask(
        "LLM API key for better drafts — OpenAI/Groq/Anthropic (optional, Enter to skip)",
        "", secret=True,
    )
    llm_env = {}
    if llm.startswith("sk-ant-"):
        llm_env["ANTHROPIC_API_KEY"] = llm
    elif llm.startswith("gsk_"):
        llm_env["GROQ_API_KEY"] = llm
    elif llm.startswith("fw_"):
        llm_env["FIREWORKS_API_KEY"] = llm
    elif llm.startswith("sk-"):
        llm_env["OPENAI_API_KEY"] = llm
    elif llm:
        llm_env["OPENAI_API_KEY"] = llm
    # keep any previously-set LLM keys if the user skipped
    for k in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "FIREWORKS_API_KEY"):
        if k not in llm_env and existing.get(k):
            llm_env[k] = existing[k]

    # 3) Storage: SQLite (default) or Supabase/Postgres
    dburl = args.database_url or ask(
        "Supabase/Postgres URL for shared cloud storage (optional, Enter = local SQLite)",
        existing.get("DATABASE_URL", ""),
    )

    values = {"ZERNIO_API_KEY": zkey, "DATABASE_URL": dburl,
              "REDDIT_BACKEND": existing.get("REDDIT_BACKEND", "auto"), **llm_env}
    _write_env_file(values)
    print("\n✓ Wrote .env (gitignored).")

    # reload so the checks below see the new values
    for k, v in values.items():
        if v:
            os.environ[k] = v

    if dburl:
        print("  Storage: Supabase/Postgres — run `pip install \"psycopg[binary]\"` if you haven't.")
    else:
        print("  Storage: local SQLite (./data).")

    # 4) Verify + connect Reddit
    print("\nChecking environment...\n")
    _cmd_doctor(argparse.Namespace(campaign=""))

    zernio = ZernioClient()
    if zernio.configured:
        try:
            acct = zernio.find_reddit_account()
        except ZernioError as exc:
            print(f"\nZernio check failed: {exc}")
            acct = None
        if not acct:
            print("\nNo Reddit account connected yet. Run this to get a connect URL:")
            print("  python -m reddit_outreach.cli zernio-setup")

    print("\n=== Setup complete ===")
    print("Next:")
    print("  1. Edit campaigns/example_campaign.yaml for your product + subreddits")
    print("  2. python -m reddit_outreach.cli run campaigns/example_campaign.yaml")
    print("  3. python -m reddit_outreach.cli queue campaigns/example_campaign.yaml")
    return 0


def _cmd_run(args) -> int:
    campaign, settings = _load(args.campaign)
    orch = Orchestrator(campaign, settings)
    print(f"Campaign: {campaign.name}")
    print(orch.environment())
    print("-" * 60)
    report = orch.run(limit_per_query=args.limit, draft_budget=args.draft_budget)
    print("-" * 60)
    print("Pipeline complete.")
    print(report.summary())
    print(f"\nReview approved drafts:  python -m reddit_outreach.cli queue {args.campaign}")
    return 0


def _cmd_scout(args) -> int:
    campaign, settings = _load(args.campaign)

    # fast path: commit everything scouted across past runs, no LLM/network
    if args.apply_stored:
        store = open_store(settings, campaign.name)
        stored = store.scouted_subreddits(active_only=True)
        store.close()
        existing = {s.lower() for s in campaign.feed_subreddits}
        new_subs, seen = [], set()
        for r in stored:
            n = r["subreddit"]
            if n.lower() in existing or n.lower() in seen:
                continue  # case-insensitive dedup (Reddit sub names aren't case-sensitive)
            seen.add(n.lower())
            new_subs.append(n)
        if not new_subs:
            print("No new active scouted subreddits to apply (all already in the campaign).")
            return 0
        added = _apply_feed_subreddits(args.campaign, new_subs)
        print(f"✓ Applied {added} scouted subreddit(s) to feed_subreddits in {args.campaign}:")
        for s in new_subs:
            print(f"  - {s}")
        return 0

    verticals = [v.strip() for v in args.verticals.split(",") if v.strip()] or None

    if args.loop:
        return _scout_loop(args, campaign, settings, verticals)

    orch = Orchestrator(campaign, settings)

    print(f"Scouting subreddits for '{campaign.name}'")
    print(orch.environment())
    if verticals:
        print(f"Verticals: {', '.join(verticals)}")
    print("(deriving verticals from ICP...)" if not verticals else "")
    print("-" * 70)

    results = orch.scout.run(verticals=verticals, per_vertical=args.per_vertical,
                             validate=not args.no_validate)
    # persist every validated result so the list accumulates across runs
    for c in results:
        orch.store.record_scouted_subreddit(
            subreddit=c["name"], vertical=c.get("vertical", ""),
            relevance=c.get("relevance", 0), active=bool(c.get("active")),
            sample_count=c.get("sample_count", 0))
    orch.close()

    if not results:
        print("No candidates returned (needs an LLM key for brainstorming). "
              "Set OPENAI/GROQ/ANTHROPIC/FIREWORKS_API_KEY and retry.")
        return 0

    existing = {s.lower() for s in campaign.feed_subreddits}
    active = [c for c in results if c.get("active")] if not args.no_validate else results
    inactive = [c for c in results if not c.get("active")] if not args.no_validate else []

    # group by vertical for a readable niche map
    by_vertical: dict = {}
    for c in active:
        by_vertical.setdefault(c.get("vertical", "general"), []).append(c)

    print(f"\n{len(active)} validated subreddit(s) across {len(by_vertical)} vertical(s):\n")
    for vertical in sorted(by_vertical):
        print(f"■ {vertical}")
        for c in sorted(by_vertical[vertical], key=lambda x: x["relevance"], reverse=True):
            new = "" if c["name"].lower() in existing else "  ⭐NEW"
            print(f"   [{c['relevance']:>3}] r/{c['name']}{new}")
            if c.get("reason"):
                print(f"         {c['reason']}")
        print()

    if inactive:
        print(f"Dropped (no posts — nonexistent/private/misnamed): "
              f"{', '.join('r/' + c['name'] for c in inactive[:20])}\n")

    new_subs = [c["name"] for c in active if c["name"].lower() not in existing]
    if not new_subs:
        print("No new subreddits beyond what's already in the campaign.")
        return 0

    if args.apply:
        added = _apply_feed_subreddits(args.campaign, new_subs)
        print("-" * 70)
        print(f"✓ Added {added} new subreddit(s) to feed_subreddits in {args.campaign}")
    else:
        print("-" * 70)
        print(f"{len(new_subs)} NEW subreddit(s). Re-run with --apply to add them "
              f"to the campaign, or paste under feed_subreddits::")
        for s in new_subs:
            print(f"  - {s}")
    return 0


def _scout_loop(args, campaign, settings, verticals) -> int:
    """24/7 Scout: crash-resilient loop that keeps discovering + validating
    subreddits into the DB. The watch loop reads them automatically (via the
    store), so the two agents coordinate without restarts."""
    import time as _t

    def log(msg: str) -> None:
        print(f"[{_t.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

    log(f"scout-loop start '{campaign.name}' — interval={args.interval}s "
        f"verticals={','.join(verticals) if verticals else 'auto-derive'} "
        f"per_vertical={args.per_vertical} once={args.once}")

    cycle = 0
    consecutive_errors = 0
    try:
        while True:
            cycle += 1
            try:
                found, active, new = _scout_cycle(campaign, settings, verticals,
                                                  args.per_vertical)
                log(f"cycle {cycle}: candidates={found} active={active} new_to_db={new}")
                consecutive_errors = 0
            except Exception as exc:  # a bad cycle never kills the loop
                consecutive_errors += 1
                log(f"cycle {cycle} ERROR ({consecutive_errors}): {type(exc).__name__}: {exc}")
                if not args.once:
                    _t.sleep(min(900, 60 * consecutive_errors))
            if args.once:
                break
            _t.sleep(max(300, args.interval))
    except KeyboardInterrupt:
        log("scout-loop stopped by user")
    return 0


def _scout_cycle(campaign, settings, verticals, per_vertical: int):
    """One Scout pass: discover → validate → persist to DB. Returns
    (candidates, active_count, new_to_db). Persists incrementally."""
    orch = Orchestrator(campaign, settings)
    try:
        existing = {r["subreddit"].lower() for r in orch.store.scouted_subreddits()}
        results = orch.scout.run(verticals=verticals, per_vertical=per_vertical, validate=True)
        active = 0
        new = 0
        for c in results:
            is_active = bool(c.get("active"))
            if is_active:
                active += 1
            if c["name"].lower() not in existing:
                new += 1
            orch.store.record_scouted_subreddit(
                subreddit=c["name"], vertical=c.get("vertical", ""),
                relevance=c.get("relevance", 0), active=is_active,
                sample_count=c.get("sample_count", 0))
        return len(results), active, new
    finally:
        orch.close()


def _apply_feed_subreddits(campaign_path: str, new_subs: list) -> int:
    """Append new subreddits under the campaign's feed_subreddits: block.

    Inserts before the `feed_sort:` line (which follows the list); appends to the
    file end if no feed_sort line exists. Preserves comments (text-level edit).
    """
    with open(campaign_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # avoid duplicates already present in the file text
    present = {l.strip().lstrip("- ").strip().lower() for l in lines if l.strip().startswith("- ")}
    to_add = [s for s in new_subs if s.lower() not in present]
    if not to_add:
        return 0

    block = [f"  # added by scout {time.strftime('%Y-%m-%d')}\n"]
    block += [f"  - {s}\n" for s in to_add]

    insert_at = None
    in_feed = False
    for i, line in enumerate(lines):
        if line.startswith("feed_subreddits:"):
            in_feed = True
            continue
        if in_feed and line.strip().startswith("feed_sort:"):
            insert_at = i
            break
    if insert_at is None:
        lines.append("\n")
        lines.extend(block)
    else:
        lines[insert_at:insert_at] = block

    with open(campaign_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return len(to_add)


def _cmd_engage(args) -> int:
    campaign, settings = _load(args.campaign)
    if args.subreddits:
        subs = [s.strip().replace("r/", "") for s in args.subreddits.split(",") if s.strip()]
        campaign.subreddits = subs
        campaign.feed_subreddits = [s for s in campaign.feed_subreddits if s in subs] or subs

    orch = Orchestrator(campaign, settings)
    print(f"Engagement scan for '{campaign.name}' (reputation/CQS — no posting)")
    print(orch.environment())
    print("-" * 70)

    engageable = orch.engage(limit_per_query=args.limit)
    post_results = []
    if args.write and engageable:
        orch.write_comments(engageable, budget=args.write)
        if args.confirm:
            post_results = orch.post_engagement_comments(engageable, budget=args.write,
                                                         confirm=True)
    orch.close()

    if not engageable:
        print("No threads worth engaging right now. Try more subreddits or a larger --limit.")
        return 0

    from .triage import age_tag, saturation_tag, post_age_days
    print(f"\n{len(engageable)} thread(s) worth a genuine comment (ranked):\n")
    for lead in engageable:
        e = lead.engagement
        age = post_age_days(lead.post.created_utc)
        age_s = f"{age:.0f}d" if age >= 0 else "age?"
        print(f"[engage {e.score}]  value_add={e.value_add} sub_fit={e.sub_fit}  "
              f"| {age_s} · {lead.post.num_comments} comments ({saturation_tag(lead.post.num_comments)})  "
              f"r/{lead.post.subreddit}")
        print(f"  {lead.post.title.replace(chr(10), ' ')}")
        print(f"  {lead.post.full_url}")
        if e.angle:
            print(f"  angle: {e.angle}")
        if args.write and lead.draft and lead.draft.body:
            q = lead.comment_quality
            tag = f"[{q.verdict} · helpful={q.helpful} human={q.human}]" if q else ""
            print(f"  ── drafted comment {tag}:")
            print(f"     {lead.draft.body.replace(chr(10), ' ')}")
        print()
    print("-" * 70)
    if post_results:
        print("Posting results (health-gated, comment-only):")
        for lead, status, note in post_results:
            icon = {"posted": "✅", "blocked": "⛔", "dry-run": "·", "error": "⚠️"}.get(status, "·")
            print(f"  {icon} [{status}] r/{lead.post.subreddit} {lead.post.id} — {note}")
    else:
        print("Dry-run: comments drafted, nothing posted. Add --write N --confirm to post "
              "(health-gated) — and hold until the shadowban lifts.")
    return 0


def _cmd_dm(args) -> int:
    campaign, settings = _load(args.campaign)
    orch = Orchestrator(campaign, settings)
    live = args.confirm and getattr(campaign, "dm_enabled", False)
    print(f"DM outreach — '{campaign.name}' (Phase 3, {'LIVE SEND' if live else 'dry-run'})")
    print(orch.environment())
    if args.confirm and not campaign.dm_enabled:
        print("NOTE: --confirm ignored — dm_enabled is false in the campaign (safety guard).")
    print("-" * 70)

    targets = orch.dm_targets(budget=args.limit, min_priority=args.min_priority)
    if not targets:
        print("No qualified prospects to DM yet. Build the lead pool first:")
        print(f"  python -m reddit_outreach.cli find {args.campaign}")
        orch.close()
        return 0

    orch.write_dms(targets, budget=args.limit)
    results = orch.send_dms(targets, budget=args.max_sends, confirm=args.confirm)
    orch.close()

    print(f"\n{sum(1 for l in targets if l.draft and l.draft.body)} DM draft(s):\n")
    for lead in targets:
        if not (lead.draft and lead.draft.body):
            continue
        q = lead.dm_quality
        pr = lead.qualification.priority if lead.qualification else 0
        tag = (f"[{q.verdict} · personal={q.personal} non_spammy={q.non_spammy}]"
               if q else "")
        print(f"→ u/{lead.post.author}  r/{lead.post.subreddit}  priority={pr}  {tag}")
        print(f"  {lead.post.full_url}")
        print(f"  {lead.draft.body.replace(chr(10), ' ')}")
        print()

    print("-" * 70)
    if results:
        for lead, status, note in results:
            icon = {"posted": "✅", "blocked": "⛔", "dry-run": "·", "error": "⚠️"}.get(status, "·")
            print(f"  {icon} [{status}] u/{lead.post.author} — {note}")
    if not campaign.dm_enabled:
        print("\nDMs are OFF for this campaign (safety). To enable — accepting Reddit's "
              "high ban-risk for cold DMs — set `dm_enabled: true` in the campaign YAML,")
        print("keep `max_dms_per_day` low, then re-run with --confirm.")
    return 0


def _cmd_handoff(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)

    if args.pending or not args.id:
        candidates = [
            l for l in store.all()
            if l.stage in (Stage.DM_SENT.value, Stage.APPROVED.value)
            and l.stage != Stage.HANDED_OFF.value
            and not store.activity_exists("handoff", l.post.id)
        ]
        candidates.sort(key=lambda l: l.qualification.priority if l.qualification else 0,
                        reverse=True)
        store.close()
        if not candidates:
            print("No leads pending handoff (need stage dm_sent/approved, not yet handed off).")
            return 0
        print(f"Leads ready to hand off to Markeye ({len(candidates)}):\n")
        for l in candidates[:50]:
            pr = l.qualification.priority if l.qualification else 0
            print(f"  [{l.stage:9}] priority={pr:<3} id={l.post.id}  u/{l.post.author}  "
                  f"r/{l.post.subreddit}")
            print(f"     {l.post.title[:90]}")
        print(f"\nHand one off:  python -m reddit_outreach.cli handoff {args.campaign} "
              f"--id <id> [--whatsapp <num>] --confirm")
        return 0

    lead = store.get(args.id)
    if not lead:
        print(f"No lead with id {args.id}")
        store.close()
        return 1

    result = orchestrate_handoff(campaign, store, lead, args)
    store.close()

    print(f"[{result.status}] {result.message}")
    if result.status == "dry-run":
        import json as _json
        print("\nPayload that would be POSTed to Markeye:")
        print(_json.dumps(result.payload, indent=2, ensure_ascii=False))
        print("\nTo go live: set `handoff_webhook_url` in the campaign (or the "
              "MARKEYE_WEBHOOK_URL env var) + `handoff_secret`, then add --confirm.")
        print("Markeye owns the WhatsApp SDR (BANT/Calendly/5-msg) — this only hands over.")
    return 0 if result.ok else 1


def orchestrate_handoff(campaign, store, lead, args):
    """Emit a single handoff via HandoffClient (kept tiny + testable)."""
    from .handoff import HandoffClient
    client = HandoffClient(campaign, store)
    return client.emit(lead, whatsapp=args.whatsapp, reason=args.reason,
                       confirm=args.confirm)


def _cmd_migrate_db(args) -> int:
    from .migrate import migrate_sqlite_to_postgres, local_sqlite_path
    campaign = Campaign.load(args.campaign)
    dsn = args.to or os.environ.get("DATABASE_URL", "") or os.environ.get("SUPABASE_DB_URL", "")
    if not dsn:
        print("No target given. Pass --to \"postgresql://...supabase...\" or set DATABASE_URL.")
        return 1
    data_dir = args.from_dir or os.environ.get("OUTREACH_DATA_DIR", "data")
    src_path = local_sqlite_path(data_dir, campaign.name)
    if not os.path.exists(src_path):
        print(f"No local SQLite DB at {src_path}. Nothing to migrate.")
        return 1

    print(f"Migrating '{campaign.name}'")
    print(f"  from: {src_path}")
    print(f"  to:   Supabase/Postgres{'  (--replace: clearing target rows first)' if args.replace else ''}")
    print("-" * 60)
    try:
        counts = migrate_sqlite_to_postgres(src_path, dsn, campaign.name,
                                            replace=args.replace)
    except SystemExit as exc:
        print(str(exc))
        return 1
    except Exception as exc:
        print(f"Migration failed: {type(exc).__name__}: {exc}")
        return 1
    print("-" * 60)
    print(f"✓ Done. Rows copied: {sum(counts.values())} total "
          f"({', '.join(f'{k}={v}' for k, v in counts.items())})")
    print("Point your deploy at this DATABASE_URL and the workers/dashboard use it.")
    return 0


def _cmd_warm(args) -> int:
    from .swarm import SwarmRunner, load_accounts

    campaign, settings = _load(args.campaign)
    accounts, warnings = load_accounts(args.accounts)

    mode = "LIVE (posting)" if args.confirm else "dry-run"
    print(f"Warm-up swarm — '{campaign.name}' ({mode})")
    for w in warnings:
        print(f"  ⚠ {w}")
    usable = [a for a in accounts if a.usable]
    if not usable:
        print(f"\nNo usable accounts. Edit {args.accounts} (assign subreddits) and set "
              "each key in .env (api_key_env). See accounts.example.yaml.")
        return 1
    print(f"{len(usable)} usable account(s): "
          + ", ".join(f"{a.label} [{', '.join('r/' + s for s in a.subreddits)}]"
                      for a in usable))
    print("-" * 70)

    runner = SwarmRunner(campaign, settings)

    def _print(results):
        for r in results:
            print(f"■ {r['label']}  ({', '.join('r/' + s for s in r['subreddits'])})")
            cap = r.get("cap", 0)
            cap_s = f" cap={r.get('sent_today', 0)}/{cap}/day" if cap else ""
            print(f"   engageable={r['engageable']} drafted={r['drafted']} "
                  f"posted={r['posted']} dry-run={r['dryrun']} blocked={r['blocked']} "
                  f"replies={r.get('reply_posted', 0) + r.get('reply_dryrun', 0)}{cap_s}")
            for n in r["notes"][:6]:
                print(f"     - {n}")

    def _cycle():
        return runner.warm_cycle(accounts, limit_per_query=args.limit,
                                 confirm=args.confirm)

    if not args.loop:
        _print(_cycle())
        runner.close()
        print("-" * 70)
        if not args.confirm:
            print("Dry-run: drafted warm-up comments, nothing posted. Add --confirm to post.")
        print("Reminder: never cross-vote/comment between these accounts, keep subs "
              "distinct, and give it ~2 weeks before using any account for outreach.")
        return 0

    # 24/7 loop (crash-resilient), mirrors watch/scout
    def log(msg: str) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

    log(f"warm-loop start — interval={args.interval}s confirm={args.confirm} "
        f"accounts={len(usable)}")
    cycle = 0
    errors = 0
    try:
        while True:
            cycle += 1
            try:
                results = _cycle()
                posted = sum(r["posted"] for r in results)
                drafted = sum(r["drafted"] for r in results)
                log(f"cycle {cycle}: drafted={drafted} posted={posted}")
                _print(results)
                errors = 0
            except Exception as exc:
                errors += 1
                log(f"cycle {cycle} ERROR ({errors}): {type(exc).__name__}: {exc}")
                if not args.once:
                    time.sleep(min(1800, 120 * errors))
            if args.once:
                break
            time.sleep(max(600, args.interval))
    except KeyboardInterrupt:
        log("warm-loop stopped by user")
    finally:
        runner.close()
    return 0


def _cmd_find(args) -> int:
    campaign, settings = _load(args.campaign)

    # optional scope override for fast iteration
    if args.subreddits:
        subs = [s.strip().replace("r/", "") for s in args.subreddits.split(",") if s.strip()]
        campaign.subreddits = subs
        campaign.feed_subreddits = [s for s in campaign.feed_subreddits if s in subs]
    # --fresh isolates scoring in a scratch dir so ICP edits aren't masked by
    # previously-cached leads (dedup is by post id).
    if args.fresh:
        settings.data_dir = os.path.join(settings.data_dir, "_find_scratch")
        settings.database_url = ""  # scratch is always local

    orch = Orchestrator(campaign, settings)
    print(f"Finding leads for '{campaign.name}'")
    print(orch.environment())
    print(f"Subreddits: {', '.join('r/' + s for s in campaign.subreddits) or '(global)'}")
    print("-" * 70)

    qualified = orch.find(limit_per_query=args.limit)
    orch.close()

    # triage each lead (age + saturation + sendability), then filter + sort
    triaged = [(l, triage_lead(l)) for l in qualified]
    shown = [
        (l, t) for (l, t) in triaged
        if (l.qualification.priority if l.qualification else 0) >= args.min_priority
        and (args.max_age_days <= 0 or (0 <= t.age_days <= args.max_age_days))
        and (not args.tier or t.tier == args.tier)
    ]
    shown.sort(key=lambda lt: lt[1].score, reverse=True)

    if not shown:
        print("No qualifying leads found. Try broadening keywords/subreddits, "
              "raising --max-age-days, lowering --min-priority, or raising --limit.")
        return 0

    print(f"\n{len(shown)} lead(s) (of {len(qualified)} qualified prospects; "
          f"sorted by sendability):\n")
    for lead, t in shown:
        q = lead.qualification
        age = f"{t.age_days:.0f}d" if t.age_days >= 0 else "age?"
        print(f"[{_tier_icon(t.tier)} {t.tier.upper():4} {t.score:>3}]  "
              f"priority={q.priority} fit={q.fit_score} intent={q.intent_score}  "
              f"| {age} old · {t.num_comments} comments ({t.saturation_tag})  r/{lead.post.subreddit}")
        print(f"  {lead.post.title.replace(chr(10), ' ')}")
        print(f"  {lead.post.full_url}")
        if q.pain_points:
            print(f"  pains: {'; '.join(q.pain_points[:3])}")
        print(f"  → {t.channel_hint}")
        print()

    print("-" * 70)
    print("Tiers: HOT = fresh + uncrowded + asking · WARM = act soon · "
          "COLD = old/crowded but may still be unsolved.")
    print("Tune precision: edit keywords/icp/min_fit_score, then re-run `find --fresh`.")
    print(f"Draft + review the good ones with:  python -m reddit_outreach.cli run {args.campaign}")
    return 0


def _tier_icon(tier: str) -> str:
    return {"hot": "🔥", "warm": "🌤", "cold": "❄", "skip": "⏭"}.get(tier, "·")


def _cmd_queue(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    stages = [Stage.APPROVED.value]
    if args.all:
        stages += [Stage.NEEDS_REVISION.value, Stage.REJECTED.value]
    leads = store.by_stage(*stages)
    leads.sort(key=lambda l: l.qualification.priority if l.qualification else 0, reverse=True)

    if not leads:
        print("No drafts in the queue yet. Run the pipeline first.")
        return 0

    print(f"Outreach queue for '{campaign.name}' ({len(leads)} item(s)):\n")
    for lead in leads:
        pr = lead.qualification.priority if lead.qualification else 0
        verdict = lead.compliance.verdict if lead.compliance else "?"
        print(f"[{lead.stage.upper()}] priority={pr} verdict={verdict}  id={lead.post.id}")
        print(f"  r/{lead.post.subreddit} — {lead.post.title}")
        print(f"  {lead.post.full_url}")
        if lead.draft:
            preview = lead.draft.body.replace("\n", " ")
            print(f"  draft: {preview[:160]}{'…' if len(preview) > 160 else ''}")
        print()
    return 0


def _cmd_leads(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)

    active = [Stage.QUALIFIED.value, Stage.RESEARCHED.value, Stage.DRAFTED.value,
              Stage.APPROVED.value, Stage.NEEDS_REVISION.value, Stage.SENT.value]
    if args.stage == "active":
        leads = store.by_stage(*active)
    elif args.stage == "all":
        leads = store.all()
    else:
        leads = store.by_stage(args.stage)

    triaged = [(l, triage_lead(l)) for l in leads]
    triaged = [
        (l, t) for (l, t) in triaged
        if (l.qualification.priority if l.qualification else 0) >= args.min_priority
        and (args.max_age_days <= 0 or (0 <= t.age_days <= args.max_age_days))
        and (not args.tier or t.tier == args.tier)
    ]
    triaged.sort(key=lambda lt: lt[1].score, reverse=True)
    triaged = triaged[: args.limit]

    if not triaged:
        print(f"No saved leads for '{campaign.name}' (stage={args.stage}). "
              f"Run: python -m reddit_outreach.cli find {args.campaign}")
        return 0

    print(f"Saved leads for '{campaign.name}' — stage={args.stage} "
          f"({len(triaged)} shown, sorted by sendability):\n")
    for lead, t in triaged:
        q = lead.qualification
        pr = q.priority if q else 0
        age = f"{t.age_days:.0f}d" if t.age_days >= 0 else "age?"
        sent = "  ✓sent" if lead.sent_at else ""
        print(f"[{_tier_icon(t.tier)} {t.tier.upper():4} {t.score:>3}] "
              f"priority={pr:<3} | {age} old · {t.num_comments} comments "
              f"({t.saturation_tag})  r/{lead.post.subreddit}  id={lead.post.id}{sent}")
        print(f"  {lead.post.title.replace(chr(10), ' ')}")
        print(f"  {lead.post.full_url}")
        if q and q.pain_points:
            print(f"  pains: {'; '.join(q.pain_points[:3])}")
        print(f"  → {t.channel_hint}")
        print()
    print("-" * 60)
    print(f"Full detail on one lead:  python -m reddit_outreach.cli review {args.campaign} <id>")
    return 0


def _cmd_review(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    lead = store.get(args.post_id)
    if not lead:
        print(f"No lead with id {args.post_id}")
        return 1

    print(f"Post {lead.post.id} — r/{lead.post.subreddit}")
    print(f"Title: {lead.post.title}")
    print(f"URL:   {lead.post.full_url}")
    print(f"Stage: {lead.stage}")
    print("-" * 60)
    if lead.qualification:
        q = lead.qualification
        print(f"Qualification: fit={q.fit_score} intent={q.intent_score} priority={q.priority}")
        print(f"  reasons: {'; '.join(q.reasons)}")
        if q.pain_points:
            print(f"  pains:   {'; '.join(q.pain_points)}")
    if lead.research:
        print(f"\nResearch angle: {lead.research.angle}")
        print(f"Summary: {lead.research.summary}")
    if lead.draft:
        print("\n--- DRAFT ---")
        print(lead.draft.body)
    if lead.compliance:
        c = lead.compliance
        print(f"\nCompliance: {c.verdict}")
        for issue in c.issues:
            print(f"  - {issue}")
        if c.revised_body:
            print("\n--- SUGGESTED REVISION ---")
            print(c.revised_body)
    return 0


def _cmd_export(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    leads = store.by_stage(Stage.APPROVED.value, Stage.NEEDS_REVISION.value)
    leads.sort(key=lambda l: l.qualification.priority if l.qualification else 0, reverse=True)

    out_path = args.output or os.path.join(settings.data_dir, f"{campaign.name}_queue.csv")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "post_id", "subreddit", "author", "priority", "fit", "intent",
        "verdict", "url", "title", "draft",
    ])
    for lead in leads:
        q = lead.qualification
        writer.writerow([
            lead.post.id, lead.post.subreddit, lead.post.author,
            q.priority if q else "", q.fit_score if q else "", q.intent_score if q else "",
            lead.compliance.verdict if lead.compliance else "",
            lead.post.full_url, lead.post.title,
            lead.draft.body if lead.draft else "",
        ])
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
    print(f"Exported {len(leads)} row(s) to {out_path}")
    return 0


def _cmd_reputation(args) -> int:
    from .reputation import ReputationTracker
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    zernio = ZernioClient()
    acct = _record_send_account(store, zernio)
    reddit = RedditClient(settings.reddit_backend, proxy=settings.proxy, zernio=zernio)
    tracker = ReputationTracker(campaign, store, reddit,
                                account_id=acct.get("account_id", ""),
                                username=acct.get("username", ""))

    print(f"Reputation / CQS — '{campaign.name}'")
    print("=" * 60)

    snap = tracker.snapshot()
    if snap:
        print(f"karma snapshot: comment={snap.get('comment_karma')} "
              f"link={snap.get('link_karma')}")
    else:
        print("karma snapshot unavailable (needs rdt backend + logged-in cookies)")

    if args.track:
        print("tracking recent posted comments (re-reading threads)...")
        tracker.track_recent()

    r = tracker.assess()
    icon = {"healthy": "🟢", "building": "🟡", "at_risk": "🔴", "unknown": "⚪"}.get(r.status, "⚪")
    print(f"\n{icon} status: {r.status.upper()}")
    delta = f"{r.karma_delta:+d}" if r.karma_delta is not None else "n/a"
    print(f"  comment karma: {r.comment_karma}  (Δ since last: {delta})")
    print(f"  comments tracked: {r.tracked}  visible: {r.visible}  removed: {r.removed}")
    print(f"  avg comment score: {r.avg_comment_score}")
    for reason in r.reasons:
        print(f"  - {reason}")
    breaker = store.breaker_state(tracker.key)
    if breaker and breaker.get("breaker_tripped"):
        print(f"\n🔴 breaker OPEN — {breaker.get('reason', '')}")
    store.close()
    return 0


def _cmd_health(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    zernio = ZernioClient()
    acct = _record_send_account(store, zernio)
    account_id = acct.get("account_id", "")
    username = acct.get("username", "")
    if not username:
        # fall back to any account we've recorded
        accts = store.accounts()
        if accts:
            account_id = accts[0].get("account_id", "")
            username = accts[0].get("username", "")
    reddit = RedditClient(settings.reddit_backend, proxy=settings.proxy, zernio=zernio)
    monitor = HealthMonitor(campaign, store, proxy=settings.proxy,
                            account_id=account_id, username=username, reddit=reddit)

    print(f"Account health — campaign '{campaign.name}'")
    print("=" * 60)

    if args.reset_breaker:
        store.reset_breaker(monitor.key)
        print(f"✅ circuit breaker reset for account '{monitor.key}'. Sends re-enabled.")
        return 0

    if not username:
        print("No connected Reddit account found. Connect one first:")
        print("  python -m reddit_outreach.cli zernio-setup")
        return 1

    if args.history:
        hist = store.health_history(monitor.key, limit=15)
        if not hist:
            print("No health snapshots yet. Run `health` without --history to probe.")
            return 0
        print(f"\nHealth history for u/{username} (most recent):")
        for h in hist:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["ts"]))
            print(f"  [{when}] score={h['score']:<3} {h['status']:<9} {h.get('detail', '')}")
        return 0

    # live probe
    print(f"Probing u/{username} (logged-out) ...\n")
    report = monitor.probe()
    icon = {"healthy": "🟢", "degraded": "🟡", "at_risk": "🟠",
            "banned": "🔴", "unknown": "⚪"}.get(report.status, "⚪")
    print(f"{icon} status: {report.status.upper()}   score: {report.score}/100")
    for r in report.reasons:
        print(f"   - {r}")
    s = report.signals
    print("\nSignals:")
    print(f"   shadowbanned={s.get('shadowbanned')} suspended={s.get('suspended')} "
          f"karma={s.get('comment_karma', 0) + s.get('link_karma', 0)} "
          f"age={s.get('account_age_days', 0)}d")
    print(f"   recent removed={s.get('recent_removed', 0)}/{s.get('recent_verified', 0)} "
          f"rate_limit_events_24h={s.get('rate_limit_events_24h', 0)}")

    # send budget + breaker
    now = time.time()
    sent_today = store.count_sends(since_ts=now - 86400)
    print(f"\nSend budget (last 24h): {sent_today}/{monitor.max_per_day}"
          f"{'  (warm-up)' if monitor._is_warming_up() else ''}")
    breaker = store.breaker_state(monitor.key)
    if breaker and breaker.get("breaker_tripped"):
        resume = breaker.get("resume_after") or 0
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(resume)) if resume else "manual"
        print(f"🔴 circuit breaker OPEN — {breaker.get('reason', '')}")
        print(f"   auto-resume: {when}   (or run: health {args.campaign} --reset-breaker)")
    else:
        print("🟢 circuit breaker closed — sends allowed")
    return 0


def _cmd_stats(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)

    print(f"Analytics for '{campaign.name}'")
    print("=" * 60)

    funnel = store.funnel()
    if funnel:
        print("\nPipeline funnel (leads by stage):")
        for stage, n in sorted(funnel.items(), key=lambda kv: -kv[1]):
            print(f"  {stage:16} {n}")

    subs = store.subreddit_breakdown()
    if subs:
        print("\nSubreddits (leads / sent / avg priority):")
        for r in subs[:15]:
            ap = f"{r['avg_priority']:.0f}" if r["avg_priority"] is not None else "-"
            print(f"  r/{(r['subreddit'] or '?'):20} leads={r['leads']:<4} "
                  f"sent={r['sent'] or 0:<4} avg_priority={ap}")

    sends = store.sends_by_channel()
    if sends:
        print("\nOutreach sends (channel / status / count):")
        for r in sends:
            print(f"  {r['channel'] or '?':8} {r['status'] or '?':10} {r['n']}")
    else:
        print("\nOutreach sends: none yet")

    authors = store.top_authors_contacted(10)
    if authors:
        print("\nPeople contacted (most recent):")
        for r in authors:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last_ts"]))
            print(f"  u/{r['author']:20} via {r['channel'] or '?':8} x{r['n']}  ({when})")

    accts = store.accounts()
    if accts:
        print("\nConnected account(s) we outreach as:")
        for a in accts:
            print(f"  {a['platform']}: u/{a['username']}  (id {a['account_id']})")

    if getattr(store, "kind", "sqlite") == "postgres":
        print("\nBacked by Supabase/Postgres. Query it in the Supabase SQL editor, e.g.:")
        print("  SELECT subreddit, COUNT(*) FROM leads GROUP BY subreddit ORDER BY 2 DESC;")
    else:
        print(f"\nDB file: {store.path}")
        print("Query it directly with any SQLite tool, e.g.:")
        print(f"  sqlite3 \"{store.path}\" \"SELECT subreddit, COUNT(*) FROM leads GROUP BY subreddit;\"")
    return 0


def _cmd_activity(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    rows = store.recent_activities(limit=args.limit, action=args.action)
    if not rows:
        print("No activity logged yet.")
        return 0
    print(f"Activity log for '{campaign.name}' (most recent {len(rows)}):\n")
    for r in rows:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
        bits = [f"[{when}]", r["action"].upper()]
        if r["channel"]:
            bits.append(f"via {r['channel']}")
        if r["subreddit"]:
            bits.append(f"r/{r['subreddit']}")
        if r["author"]:
            bits.append(f"u/{r['author']}")
        if r["status"]:
            bits.append(f"({r['status']})")
        line = " ".join(bits)
        if r["detail"]:
            line += f" — {r['detail']}"
        print(line)
    return 0


def _cmd_doctor(args) -> int:
    settings = Settings.from_env()
    zernio = ZernioClient()
    reddit = RedditClient(settings.reddit_backend, proxy=settings.proxy, zernio=zernio)
    llm = LLM(settings.llm_provider, settings.llm_model)
    print("Reddit outreach — environment check")
    print("-" * 60)
    print(f"Reddit backend : {reddit.backend}"
          f"{'  (LIVE)' if reddit.is_live else '  (mock — no live data)'}")
    print(f"LLM provider   : {llm.provider}"
          f"{f'  ({llm.model})' if llm.available else '  (heuristic fallback — set an API key)'}")
    print(f"Zernio (send)  : {'configured' if zernio.configured else 'not configured (set ZERNIO_API_KEY)'}")
    db = "Supabase/Postgres (DATABASE_URL set)" if settings.database_url else "SQLite (local file)"
    print(f"Database       : {db}")
    if zernio.configured:
        try:
            acct = zernio.find_reddit_account()
            if acct:
                print(f"  Reddit account: u/{acct.get('username')} (id {acct.get('_id')})")
            else:
                print("  No Reddit account connected — run: python -m reddit_outreach.cli zernio-setup")
        except ZernioError as exc:
            print(f"  Zernio check failed: {exc}")
    if reddit.backend == "mock":
        print("\nTo enable live Reddit data, either set ZERNIO_API_KEY (recommended — no")
        print("Reddit API key needed) or install an Agent-Reach backend:")
        print("  agent-reach install --channels opencli    # desktop, reuses Chrome login")
        print("  pipx install 'git+https://github.com/public-clis/rdt-cli.git'  # server")
    if not llm.available:
        print("\nTo enable LLM-quality drafting, set one of:")
        print("  OPENAI_API_KEY, GROQ_API_KEY, or ANTHROPIC_API_KEY")
    return 0


def _cmd_zernio_setup(args) -> int:
    zernio = ZernioClient()
    if not zernio.configured:
        print("ZERNIO_API_KEY is not set. Export it (or add it to .env), then re-run.")
        print("Get a key at https://zernio.com → Settings → API Keys")
        return 1
    try:
        profiles = zernio.list_profiles()
        accounts = zernio.list_accounts()
    except ZernioError as exc:
        print(f"Zernio error: {exc}")
        return 1

    print("Zernio profiles:")
    for p in profiles:
        print(f"  - {p.get('name')}  (id {p.get('_id')})")
    print("\nConnected accounts:")
    for a in accounts:
        print(f"  - {a.get('platform')}: u/{a.get('username')}  (id {a.get('_id')})")

    reddit_acct = next((a for a in accounts if a.get("platform") == "reddit"), None)
    if reddit_acct:
        print(f"\n✅ Reddit is connected: u/{reddit_acct.get('username')}")
        print("You're ready to search and publish. Try:")
        print("  python -m reddit_outreach.cli run <campaign>")
        return 0

    # no reddit account — produce a connect URL
    profile_id = profiles[0]["_id"] if profiles else ""
    if not profile_id:
        prof = zernio.create_profile("Reddit Outreach", "Created by reddit-outreach")
        profile_id = prof.get("_id", "")
    try:
        info = zernio.get_connect_url("reddit", profile_id)
    except ZernioError as exc:
        print(f"\nCould not get a connect URL: {exc}")
        return 1
    print("\nNo Reddit account connected yet. Open this URL in your browser to authorize:")
    print(f"  {info.get('authUrl')}")
    print("After authorizing, re-run this command to confirm.")
    return 0


def _pick_send_target(store: LeadStore, post_id: str):
    if post_id:
        return store.get(post_id)
    approved = [l for l in store.by_stage(Stage.APPROVED.value) if not l.sent_at]
    approved.sort(key=lambda l: l.qualification.priority if l.qualification else 0, reverse=True)
    return approved[0] if approved else None


def _cmd_send(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    lead = _pick_send_target(store, args.id)
    if not lead:
        print("Nothing to send. No approved, unsent leads found "
              "(run the pipeline, or check `queue`).")
        return 1
    if lead.stage != Stage.APPROVED.value:
        print(f"Warning: lead {lead.post.id} is '{lead.stage}', not 'approved'. Sending anyway.")

    print(f"[{args.via}] r/{lead.post.subreddit} — {lead.post.title}")
    print(f"  {lead.post.full_url}\n")
    print("--- DRAFT ---")
    print(lead.draft.body if lead.draft else "(no draft)")
    print("-------------\n")

    zernio = ZernioClient()
    account_name = ""
    monitor = None
    if args.via != "manual":
        acct = _record_send_account(store, zernio)
        account_name = acct.get("username", "")
        monitor = HealthMonitor(campaign, store, proxy=settings.proxy,
                                account_id=acct.get("account_id", ""), username=account_name)

    # pre-send health/rate gate for automated writes that affect reach
    if monitor and args.via in ("comment", "post") and args.confirm:
        gate = monitor.guard_send(subreddit=(args.subreddit or lead.post.subreddit))
        if not gate.allowed:
            print(f"⛔ send blocked by health gate: {gate.reason}")
            return 2

    if args.via == "manual":
        result = manual_send(lead, open_browser=not args.no_open)
        if result.ok:
            lead.sent_at = time.time()
            lead.sent_ref = "manual"
            lead.stage = Stage.SENT.value
    elif args.via == "comment":
        result = zernio_comment(lead, zernio, confirm=args.confirm)
    elif args.via == "dm":
        result = zernio_dm(lead, zernio, confirm=args.confirm)
    else:  # post
        result = zernio_publish(
            lead, zernio, subreddit=args.subreddit,
            mode=("publish" if args.confirm else "draft"),
        )

    print(result.message)
    if result.status != "dry-run":
        store.save()
        store.log_activity(
            "sent", channel=args.via, post_id=lead.post.id,
            subreddit=lead.post.subreddit, author=lead.post.author,
            account=account_name, ref=result.ref, status=result.status,
            detail=result.message[:200],
        )
        # post-send verification: did the comment actually land publicly?
        if monitor and args.via == "comment" and result.ok \
                and getattr(campaign, "verify_sends", True):
            check = monitor.verify_after_send(lead, result)
            store.save()
            icon = {"visible": "✅", "removed": "⚠️", "unverified": "❓"}.get(
                "visible" if check.visible else ("unverified" if not check.ok else "removed"), "❓")
            print(f"{icon} verification: {check.note}")
    else:
        print("\n(Nothing was sent. Add --confirm to actually post.)")
    return 0 if result.ok else 1


def _record_send_account(store, zernio: ZernioClient) -> dict:
    """Look up + persist the Reddit account we send as.

    Returns ``{"account_id", "username"}`` (empty strings if unavailable).
    """
    if not zernio.configured:
        return {"account_id": "", "username": ""}
    try:
        acct = zernio.find_reddit_account()
    except Exception:
        acct = None
    if not acct:
        accts = store.accounts()
        if accts:
            return {"account_id": accts[0].get("account_id", ""),
                    "username": accts[0].get("username", "")}
        return {"account_id": "", "username": ""}
    store.record_account(acct.get("_id", ""), "reddit",
                         acct.get("username", ""), acct.get("profileId", ""))
    return {"account_id": acct.get("_id", ""), "username": acct.get("username", "")}


def _cmd_watch(args) -> int:
    import time as _t

    def log(msg: str) -> None:
        line = f"[{_t.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)

    campaign, settings = _load(args.campaign)
    orch = Orchestrator(campaign, settings)
    log(f"watch start '{campaign.name}' — {orch.environment().replace(chr(10), ' | ')}")
    log(f"interval={args.interval}s auto_comment={args.auto_comment} "
        f"max_sends={args.max_sends} min_priority={args.min_priority} "
        f"health_every={args.health_every} once={args.once}")

    cycle = 0
    consecutive_errors = 0
    try:
        while True:
            cycle += 1
            try:
                # periodic account-health / shadowban probe (trips breaker on a ban)
                if args.health_every and (cycle == 1 or cycle % args.health_every == 0):
                    _probe_health(orch, settings, log)

                report = orch.run(limit_per_query=args.limit, draft_budget=args.draft_budget)
                log(f"cycle {cycle}: {report.summary()}")
                if args.auto_comment and report.approved:
                    _auto_comment(orch, args, log)
                consecutive_errors = 0
            except Exception as exc:  # never let one bad cycle kill the loop
                consecutive_errors += 1
                log(f"cycle {cycle} ERROR ({consecutive_errors}): {type(exc).__name__}: {exc}")
                # exponential backoff on repeated failures, capped at 10 min
                if not args.once:
                    _t.sleep(min(600, 30 * consecutive_errors))

            if args.once:
                break
            _t.sleep(max(30, args.interval))
    except KeyboardInterrupt:
        log("stopped by user")
    return 0


def _probe_health(orch: Orchestrator, settings, log=print) -> None:
    """Run a scheduled account-health/shadowban probe during watch.

    Fails soft: any probe error is logged and swallowed so a health check can
    never take the always-on loop down. A detected shadowban/suspension trips
    the send circuit breaker inside ``monitor.probe()``.
    """
    zernio = orch.zernio
    if not zernio.configured:
        return
    try:
        acct = _record_send_account(orch.store, zernio)
        username = acct.get("username", "")
        if not username:
            return
        monitor = HealthMonitor(orch.campaign, orch.store, proxy=settings.proxy,
                                account_id=acct.get("account_id", ""), username=username,
                                reddit=orch.reddit)
        report = monitor.probe()
        icon = {"healthy": "🟢", "degraded": "🟡", "at_risk": "🟠",
                "banned": "🔴", "unknown": "⚪"}.get(report.status, "⚪")
        log(f"  health {icon} u/{username}: {report.status} ({report.score}/100) "
            f"— {report.reasons[0] if report.reasons else ''}")
    except Exception as exc:
        log(f"  health probe skipped: {type(exc).__name__}: {exc}")


def _auto_comment(orch: Orchestrator, args, log=print) -> None:
    """Rate-limited auto-reply for high-priority approved, unsent leads.

    Every send passes the account-health gate first (circuit breaker + rate +
    warm-up), and each landed comment is verified for public visibility so a
    silent shadowban/removal spike trips the breaker instead of burning the
    account for days.
    """
    zernio = orch.zernio
    approved = [
        l for l in orch.store.by_stage(Stage.APPROVED.value)
        if not l.sent_at and l.qualification and l.qualification.priority >= args.min_priority
    ]
    approved.sort(key=lambda l: l.qualification.priority, reverse=True)
    sent = 0
    acct = _record_send_account(orch.store, zernio)
    account_name = acct.get("username", "")
    monitor = HealthMonitor(orch.campaign, orch.store, proxy=orch.settings.proxy,
                            account_id=acct.get("account_id", ""), username=account_name)

    for lead in approved[: args.max_sends]:
        gate = monitor.guard_send(subreddit=lead.post.subreddit)
        if not gate.allowed:
            log(f"  auto-comment SKIP {lead.post.id}: {gate.reason}")
            if gate.wait_seconds <= 0:
                # a hard block (breaker/cap) applies to the whole cycle — stop early
                break
            continue

        result = zernio_comment(lead, zernio, confirm=True)
        tag = "OK" if result.ok else "!!"
        log(f"  auto-comment [{tag}] {lead.post.id}: {result.message}")
        if result.status != "dry-run":
            orch.store.save()
            orch.store.log_activity(
                "sent", channel="comment", post_id=lead.post.id,
                subreddit=lead.post.subreddit, author=lead.post.author,
                account=account_name, ref=result.ref, status=result.status,
                detail=result.message[:200],
            )
            if result.ok and getattr(orch.campaign, "verify_sends", True):
                check = monitor.verify_after_send(lead, result)
                orch.store.save()
                log(f"    verify {lead.post.id}: {check.note}")
        if result.ok:
            sent += 1
        time.sleep(5)  # be gentle with Reddit
    if sent:
        log(f"  auto-commented on {sent} lead(s) this cycle")


def _cmd_zernio_post(args) -> int:
    campaign, settings = _load(args.campaign)
    store = open_store(settings, campaign.name)
    lead = store.get(args.id)
    if not lead:
        print(f"No lead with id {args.id}")
        return 1
    if not lead.draft or not lead.draft.body.strip():
        print("That lead has no draft to publish.")
        return 1

    zernio = ZernioClient()
    if not zernio.configured:
        print("ZERNIO_API_KEY is not set.")
        return 1

    target_sub = args.subreddit or lead.post.subreddit
    if args.mode == "publish":
        print(f"⚠️  This will PUBLISH a live Reddit submission to r/{target_sub} "
              f"as your connected account.")
    elif args.mode == "schedule":
        print(f"This will SCHEDULE a Reddit submission to r/{target_sub} for {args.at}.")
    else:
        print(f"Creating a Zernio DRAFT submission for r/{target_sub} (nothing goes live).")

    result = zernio_publish(
        lead, zernio,
        subreddit=args.subreddit, title=args.title,
        mode=args.mode, scheduled_for=args.at, timezone=args.tz,
    )
    print(result.message)
    if result.ok:
        store.save()
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
