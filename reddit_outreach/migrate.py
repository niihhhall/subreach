# -*- coding: utf-8 -*-
"""Move a local SQLite campaign DB into Supabase/Postgres, table by table.

Used once when you graduate from running on your laptop (SQLite) to a 24/7
cloud/VPS deploy (Supabase). It copies every table for the campaign — leads,
the full activity/audit log, accounts, health snapshots + breaker state,
scouted subreddits, reputation, and per-subreddit rules — preserving original
timestamps so your history and karma trend survive the move.

    python -m reddit_outreach.cli migrate-db campaigns/markeye.yaml \
        --to "postgresql://...supabase..." [--replace]

Idempotency: append-only tables (activities/health/reputation) plain-INSERT, so
re-running duplicates them — pass ``--replace`` to clear the campaign's target
rows first. Keyed tables (leads/accounts/rules/scouted/health_state) upsert or
skip-on-conflict, so they're always safe to re-run.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Dict

from .models import Lead
from .store import LeadStore, _slug


def _json_or_none(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def migrate_sqlite_to_postgres(sqlite_path: str, dsn: str, campaign: str,
                               *, replace: bool = False, log=print) -> Dict[str, int]:
    """Copy one campaign's data from a SQLite file into Postgres. Returns counts."""
    from psycopg.types.json import Json  # requires psycopg (cloud dep)
    from .store_postgres import PostgresStore

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    pg = PostgresStore(dsn, campaign)     # creates the schema if missing
    pg.conn.autocommit = False            # batch everything into ONE transaction (fast)
    counts: Dict[str, int] = {}

    try:
        # ── leads (batched executemany upsert) ──
        rows = src.execute("SELECT data_json FROM leads WHERE campaign=?",
                           (campaign,)).fetchall()
        lead_cols = ("campaign", "post_id", "subreddit", "author", "title", "url",
                     "source_query", "fit_score", "intent_score", "priority", "stage",
                     "compliance_verdict", "draft_body", "discovered_at", "updated_at",
                     "sent_at", "sent_ref", "data_json")
        lead_vals = []
        for row in rows:
            try:
                lead = Lead.from_dict(json.loads(row["data_json"]))
            except Exception:
                continue
            q = lead.qualification
            lead_vals.append((
                campaign, lead.post.id, lead.post.subreddit, lead.post.author,
                lead.post.title, lead.post.full_url, lead.source_query,
                q.fit_score if q else None, q.intent_score if q else None,
                q.priority if q else None, lead.stage,
                lead.compliance.verdict if lead.compliance else None,
                lead.draft.body if lead.draft else None,
                lead.discovered_at, time.time(), lead.sent_at, lead.sent_ref,
                Json(lead.to_dict()),
            ))
        if lead_vals:
            ph = ", ".join(["%s"] * len(lead_cols))
            sql = (f"INSERT INTO leads ({', '.join(lead_cols)}) VALUES ({ph}) "
                   "ON CONFLICT (campaign, post_id) DO UPDATE SET "
                   "stage=EXCLUDED.stage, priority=EXCLUDED.priority, "
                   "data_json=EXCLUDED.data_json, updated_at=EXCLUDED.updated_at")
            with pg.conn.cursor() as cur:
                cur.executemany(sql, lead_vals)
        counts["leads"] = len(lead_vals)
        log(f"  leads: {len(lead_vals)}")

        # ── generic table copies (batched executemany) ──
        def copy(table: str, columns, *, json_cols=(), conflict: str = "",
                 campaign_scoped: bool = True) -> int:
            where = "WHERE campaign=?" if campaign_scoped else ""
            params = (campaign,) if campaign_scoped else ()
            src_rows = src.execute(
                f"SELECT {', '.join(columns)} FROM {table} {where}", params).fetchall()
            with pg.conn.cursor() as cur:
                if replace and campaign_scoped:
                    cur.execute(f"DELETE FROM {table} WHERE campaign=%s", (campaign,))
                batch = []
                for r in src_rows:
                    batch.append([Json(_json_or_none(r[c])) if c in json_cols else r[c]
                                  for c in columns])
                if batch:
                    ph = ", ".join(["%s"] * len(columns))
                    cur.executemany(
                        f"INSERT INTO {table} ({', '.join(columns)}) "
                        f"VALUES ({ph}) {conflict}", batch)
            counts[table] = len(src_rows)
            log(f"  {table}: {len(src_rows)}")
            return len(src_rows)

        copy("activities",
             ["ts", "campaign", "action", "channel", "post_id", "subreddit",
              "author", "account", "ref", "status", "detail"])
        copy("accounts",
             ["account_id", "platform", "username", "profile_id", "first_seen", "last_used"],
             conflict="ON CONFLICT (account_id) DO NOTHING", campaign_scoped=False)
        copy("account_health",
             ["ts", "campaign", "account", "username", "score", "status",
              "shadowbanned", "signals_json", "detail"],
             json_cols=("signals_json",))
        copy("health_state",
             ["account", "campaign", "breaker_tripped", "reason", "tripped_at", "resume_after"],
             conflict="ON CONFLICT (account) DO NOTHING", campaign_scoped=False)
        copy("subreddit_rules",
             ["subreddit", "campaign", "rules_json", "fetched_at"],
             json_cols=("rules_json",),
             conflict="ON CONFLICT (subreddit) DO NOTHING", campaign_scoped=False)
        copy("scouted_subreddits",
             ["subreddit", "campaign", "vertical", "relevance", "active",
              "sample_count", "first_seen", "last_seen"],
             conflict="ON CONFLICT (campaign, subreddit) DO NOTHING")
        copy("reputation",
             ["ts", "campaign", "account", "comment_karma", "link_karma",
              "total_karma", "detail"])

        pg.conn.commit()                  # one atomic commit for the whole migration
    except Exception:
        pg.conn.rollback()
        raise
    finally:
        src.close()
        pg.close()
    return counts


def local_sqlite_path(data_dir: str, campaign_name: str) -> str:
    """Where the local SQLite DB for a campaign lives."""
    import os
    return os.path.join(data_dir, f"{_slug(campaign_name)}.db")
