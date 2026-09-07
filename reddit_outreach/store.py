# -*- coding: utf-8 -*-
"""SQLite-backed persistence + activity log + analytics.

Three tables, one DB file per campaign at ``<data_dir>/<campaign>.db``:

* ``leads``      — current state, one row per Reddit post (dedup by post id).
                   Answers "which subreddits, who, what stage, what score".
* ``activities`` — append-only event log of every meaningful action, especially
                   sends (comment / reply / dm / post / manual). Answers
                   "when did we reach out, where, to whom, as which account,
                   with what result".
* ``accounts``   — the connected Reddit account(s) we outreach as.

``LeadStore`` keeps the same interface the pipeline already used (upsert / all /
by_stage / get / save) so nothing else had to change, and adds ``log_activity``,
``record_account`` and the analytics query methods.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from .models import Lead


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "campaign"


def _coerce_id(value) -> str:
    """Coerce an id-ish field to a plain string.

    Zernio sometimes returns nested objects (e.g. ``profileId`` as a dict) where
    a scalar id is expected; pull out a sensible id or fall back to str().
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("_id") or value.get("id") or "")
    return str(value)


# action vocabulary for the activity log
DISCOVERED = "discovered"
QUALIFIED = "qualified"
DISQUALIFIED = "disqualified"
DRAFTED = "drafted"
APPROVED = "approved"
REJECTED = "rejected"
SENT = "sent"            # a real outreach send (channel says comment/dm/post/manual)
RUN = "run"             # a pipeline cycle summary


class LeadStore:
    kind = "sqlite"

    def __init__(self, data_dir: str, campaign_name: str):
        self.campaign = campaign_name
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, f"{_slug(campaign_name)}.db")
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._leads: Dict[str, Lead] = {}
        self._load()

    # ── schema ────────────────────────────────────────────────────────
    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                campaign          TEXT NOT NULL,
                post_id           TEXT NOT NULL,
                subreddit         TEXT,
                author            TEXT,
                title             TEXT,
                url               TEXT,
                source_query      TEXT,
                fit_score         INTEGER,
                intent_score      INTEGER,
                priority          INTEGER,
                stage             TEXT,
                compliance_verdict TEXT,
                draft_body        TEXT,
                discovered_at     REAL,
                updated_at        REAL,
                sent_at           REAL,
                sent_ref          TEXT,
                data_json         TEXT,
                PRIMARY KEY (campaign, post_id)
            );
            CREATE TABLE IF NOT EXISTS activities (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        REAL NOT NULL,
                campaign  TEXT NOT NULL,
                action    TEXT NOT NULL,
                channel   TEXT,
                post_id   TEXT,
                subreddit TEXT,
                author    TEXT,
                account   TEXT,
                ref       TEXT,
                status    TEXT,
                detail    TEXT
            );
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                platform   TEXT,
                username   TEXT,
                profile_id TEXT,
                first_seen REAL,
                last_used  REAL
            );
            CREATE TABLE IF NOT EXISTS account_health (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL NOT NULL,
                campaign     TEXT,
                account      TEXT,
                username     TEXT,
                score        INTEGER,
                status       TEXT,
                shadowbanned INTEGER,
                signals_json TEXT,
                detail       TEXT
            );
            CREATE TABLE IF NOT EXISTS health_state (
                account         TEXT PRIMARY KEY,
                campaign        TEXT,
                breaker_tripped INTEGER DEFAULT 0,
                reason          TEXT,
                tripped_at      REAL,
                resume_after    REAL
            );
            CREATE TABLE IF NOT EXISTS subreddit_rules (
                subreddit  TEXT PRIMARY KEY,
                campaign   TEXT,
                rules_json TEXT,
                fetched_at REAL
            );
            CREATE TABLE IF NOT EXISTS scouted_subreddits (
                subreddit    TEXT NOT NULL,
                campaign     TEXT NOT NULL,
                vertical     TEXT,
                relevance    INTEGER,
                active       INTEGER,
                sample_count INTEGER,
                first_seen   REAL,
                last_seen    REAL,
                PRIMARY KEY (campaign, subreddit)
            );
            CREATE TABLE IF NOT EXISTS reputation (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            REAL NOT NULL,
                campaign      TEXT,
                account       TEXT,
                comment_karma INTEGER,
                link_karma    INTEGER,
                total_karma   INTEGER,
                detail        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_leads_campaign_stage
                ON leads (campaign, stage);
            CREATE INDEX IF NOT EXISTS idx_act_campaign_action
                ON activities (campaign, action);
            CREATE INDEX IF NOT EXISTS idx_act_campaign_ts
                ON activities (campaign, ts);
            CREATE INDEX IF NOT EXISTS idx_health_account_ts
                ON account_health (account, ts);
            """
        )
        self.conn.commit()

    def _load(self) -> None:
        rows = self.conn.execute(
            "SELECT data_json FROM leads WHERE campaign = ?", (self.campaign,)
        ).fetchall()
        for row in rows:
            try:
                lead = Lead.from_dict(json.loads(row["data_json"]))
            except Exception:
                continue
            self._leads[lead.post.id] = lead

    # ── lead persistence (compatible interface) ────────────────────────
    def _write_lead(self, lead: Lead) -> None:
        q = lead.qualification
        self.conn.execute(
            """
            INSERT OR REPLACE INTO leads (
                campaign, post_id, subreddit, author, title, url, source_query,
                fit_score, intent_score, priority, stage, compliance_verdict,
                draft_body, discovered_at, updated_at, sent_at, sent_ref, data_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                self.campaign, lead.post.id, lead.post.subreddit, lead.post.author,
                lead.post.title, lead.post.full_url, lead.source_query,
                q.fit_score if q else None, q.intent_score if q else None,
                q.priority if q else None, lead.stage,
                lead.compliance.verdict if lead.compliance else None,
                lead.draft.body if lead.draft else None,
                lead.discovered_at, time.time(), lead.sent_at, lead.sent_ref,
                json.dumps(lead.to_dict(), ensure_ascii=False),
            ),
        )

    def save(self) -> None:
        for lead in self._leads.values():
            self._write_lead(lead)
        self.conn.commit()

    def upsert(self, lead: Lead) -> Lead:
        existing = self._leads.get(lead.post.id)
        if existing:
            return existing
        self._leads[lead.post.id] = lead
        self._write_lead(lead)
        self.conn.commit()
        return lead

    def all(self) -> List[Lead]:
        return list(self._leads.values())

    def by_stage(self, *stages: str) -> List[Lead]:
        wanted = set(stages)
        return [l for l in self._leads.values() if l.stage in wanted]

    def get(self, post_id: str) -> Optional[Lead]:
        return self._leads.get(post_id)

    # ── activity log ────────────────────────────────────────────────────
    def log_activity(self, action: str, *, channel: str = "", post_id: str = "",
                     subreddit: str = "", author: str = "", account: str = "",
                     ref: str = "", status: str = "", detail: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO activities
              (ts, campaign, action, channel, post_id, subreddit, author,
               account, ref, status, detail)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (time.time(), self.campaign, action, channel, post_id, subreddit,
             author, account, ref, status, detail),
        )
        self.conn.commit()

    def record_account(self, account_id: str, platform: str, username: str,
                       profile_id: str = "") -> None:
        account_id, username, profile_id = (
            _coerce_id(account_id), _coerce_id(username), _coerce_id(profile_id))
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO accounts (account_id, platform, username, profile_id,
                                  first_seen, last_used)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(account_id) DO UPDATE SET
                username = excluded.username,
                profile_id = excluded.profile_id,
                last_used = excluded.last_used
            """,
            (account_id, platform, username, profile_id, now, now),
        )
        self.conn.commit()

    # ── analytics queries ───────────────────────────────────────────────
    def funnel(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT stage, COUNT(*) c FROM leads WHERE campaign=? GROUP BY stage",
            (self.campaign,),
        ).fetchall()
        return {r["stage"]: r["c"] for r in rows}

    def subreddit_breakdown(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT subreddit,
                   COUNT(*) AS leads,
                   SUM(CASE WHEN sent_at > 0 THEN 1 ELSE 0 END) AS sent,
                   AVG(priority) AS avg_priority
            FROM leads WHERE campaign = ?
            GROUP BY subreddit ORDER BY leads DESC
            """,
            (self.campaign,),
        ).fetchall()
        return [dict(r) for r in rows]

    def sends_by_channel(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT channel, status, COUNT(*) AS n
            FROM activities
            WHERE campaign = ? AND action = ?
            GROUP BY channel, status ORDER BY n DESC
            """,
            (self.campaign, SENT),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_activities(self, limit: int = 20, action: str = "") -> List[Dict[str, Any]]:
        if action:
            rows = self.conn.execute(
                "SELECT * FROM activities WHERE campaign=? AND action=? "
                "ORDER BY ts DESC LIMIT ?",
                (self.campaign, action, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM activities WHERE campaign=? ORDER BY ts DESC LIMIT ?",
                (self.campaign, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def top_authors_contacted(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT author, channel, COUNT(*) AS n, MAX(ts) AS last_ts
            FROM activities
            WHERE campaign = ? AND action = ? AND author != ''
            GROUP BY author, channel ORDER BY last_ts DESC LIMIT ?
            """,
            (self.campaign, SENT, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def accounts(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM accounts ORDER BY last_used DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── account health + circuit breaker ────────────────────────────────
    def record_health_snapshot(self, *, account: str, username: str, score: int,
                               status: str, shadowbanned: int, signals: Dict[str, Any],
                               campaign: str = "", detail: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO account_health
              (ts, campaign, account, username, score, status, shadowbanned,
               signals_json, detail)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (time.time(), campaign or self.campaign, account, username, score,
             status, shadowbanned, json.dumps(signals, ensure_ascii=False), detail),
        )
        self.conn.commit()

    def latest_health(self, account: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM account_health WHERE account=? ORDER BY ts DESC LIMIT 1",
            (account,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["signals"] = json.loads(d.get("signals_json") or "{}")
        except Exception:
            d["signals"] = {}
        return d

    def health_history(self, account: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM account_health WHERE account=? ORDER BY ts DESC LIMIT ?",
            (account, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def trip_breaker(self, account: str, *, reason: str, resume_after: float,
                     campaign: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO health_state (account, campaign, breaker_tripped, reason,
                                      tripped_at, resume_after)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(account) DO UPDATE SET
                breaker_tripped=1, reason=excluded.reason,
                tripped_at=excluded.tripped_at, resume_after=excluded.resume_after
            """,
            (account, campaign or self.campaign, 1, reason, time.time(), resume_after),
        )
        self.conn.commit()

    def reset_breaker(self, account: str) -> None:
        self.conn.execute(
            "UPDATE health_state SET breaker_tripped=0, reason='', resume_after=0 "
            "WHERE account=?",
            (account,),
        )
        self.conn.commit()

    def breaker_state(self, account: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM health_state WHERE account=?", (account,)
        ).fetchone()
        return dict(row) if row else None

    # ── send-pacing helpers (read from the activity log) ────────────────
    def count_sends(self, since_ts: float = 0.0, subreddit: str = "",
                    channel: str = "", account: str = "") -> int:
        sql = ("SELECT COUNT(*) c FROM activities WHERE campaign=? AND action=? "
               "AND status NOT IN ('error','dry-run') AND ts >= ?")
        params: list = [self.campaign, SENT, since_ts]
        if subreddit:
            sql += " AND subreddit=?"
            params.append(subreddit.replace("r/", ""))
        if channel:
            sql += " AND channel=?"
            params.append(channel)
        if account:
            sql += " AND account=?"
            params.append(account)
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return int(row["c"] if row else 0)

    def activity_exists(self, action: str, post_id: str) -> bool:
        """True if we've already logged this action for this post (idempotency)."""
        row = self.conn.execute(
            "SELECT 1 FROM activities WHERE campaign=? AND action=? AND post_id=? "
            "AND status NOT IN ('error','dry-run') LIMIT 1",
            (self.campaign, action, post_id),
        ).fetchone()
        return row is not None

    def last_send_ts(self) -> float:
        row = self.conn.execute(
            "SELECT MAX(ts) t FROM activities WHERE campaign=? AND action=? "
            "AND status NOT IN ('error','dry-run')",
            (self.campaign, SENT),
        ).fetchone()
        return float(row["t"] or 0.0) if row else 0.0

    def recent_verifications(self, limit: int = 5) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM activities WHERE campaign=? AND action='verify' "
            "ORDER BY ts DESC LIMIT ?",
            (self.campaign, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_rate_limit_events(self, since_ts: float = 0.0) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM activities WHERE campaign=? AND ts >= ? "
            "AND (detail LIKE '%429%' OR detail LIKE '%Rate limited%')",
            (self.campaign, since_ts),
        ).fetchone()
        return int(row["c"] if row else 0)

    # ── per-subreddit rules: removal stats (closed loop) + cache ────────
    def subreddit_removal_stats(self, subreddit: str, window_days: int = 14) -> tuple:
        """Return (removed, total) verified sends for a subreddit in the window.

        Only counts verifications with a definitive verdict (visible/removed);
        'unverified' (couldn't fetch) is excluded so a dark probe never benches.
        """
        since = time.time() - window_days * 86400
        row = self.conn.execute(
            "SELECT "
            "  SUM(CASE WHEN status='removed' THEN 1 ELSE 0 END) removed, "
            "  SUM(CASE WHEN status IN ('removed','visible') THEN 1 ELSE 0 END) total "
            "FROM activities WHERE campaign=? AND action='verify' AND subreddit=? AND ts>=?",
            (self.campaign, subreddit.replace("r/", ""), since),
        ).fetchone()
        return (int(row["removed"] or 0), int(row["total"] or 0)) if row else (0, 0)

    def record_subreddit_rules(self, subreddit: str, rules: Dict[str, Any],
                               campaign: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO subreddit_rules (subreddit, campaign, rules_json, fetched_at)
            VALUES (?,?,?,?)
            ON CONFLICT(subreddit) DO UPDATE SET
                campaign=excluded.campaign, rules_json=excluded.rules_json,
                fetched_at=excluded.fetched_at
            """,
            (subreddit.replace("r/", ""), campaign or self.campaign,
             json.dumps(rules, ensure_ascii=False), time.time()),
        )
        self.conn.commit()

    def get_subreddit_rules(self, subreddit: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT rules_json FROM subreddit_rules WHERE subreddit=?",
            (subreddit.replace("r/", ""),),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["rules_json"] or "{}")
        except Exception:
            return None

    # ── scouted subreddits (from the Subreddit Scout) ───────────────────
    def record_scouted_subreddit(self, *, subreddit: str, vertical: str = "",
                                 relevance: int = 0, active: bool = False,
                                 sample_count: int = 0) -> None:
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO scouted_subreddits
              (subreddit, campaign, vertical, relevance, active, sample_count,
               first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(campaign, subreddit) DO UPDATE SET
                vertical=excluded.vertical, relevance=excluded.relevance,
                active=excluded.active, sample_count=excluded.sample_count,
                last_seen=excluded.last_seen
            """,
            (subreddit.replace("r/", ""), self.campaign, vertical, relevance,
             1 if active else 0, sample_count, now, now),
        )
        self.conn.commit()

    def scouted_subreddits(self, active_only: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM scouted_subreddits WHERE campaign=?"
        if active_only:
            sql += " AND active=1"
        sql += " ORDER BY active DESC, relevance DESC"
        return [dict(r) for r in self.conn.execute(sql, (self.campaign,)).fetchall()]

    # ── reputation / CQS snapshots ──────────────────────────────────────
    def record_reputation(self, *, account: str, comment_karma: int, link_karma: int,
                          detail: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO reputation (ts, campaign, account, comment_karma, link_karma,
                                    total_karma, detail)
            VALUES (?,?,?,?,?,?,?)
            """,
            (time.time(), self.campaign, account, comment_karma, link_karma,
             comment_karma + link_karma, detail),
        )
        self.conn.commit()

    def reputation_history(self, account: str, limit: int = 30) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM reputation WHERE campaign=? AND account=? ORDER BY ts DESC LIMIT ?",
            (self.campaign, account, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def open_store(settings, campaign_name: str):
    """Return the right store for the environment.

    Uses Supabase/Postgres when ``settings.database_url`` is set, else the
    local SQLite file. Both expose the identical interface, so nothing else in
    the app needs to know which one it got.
    """
    if getattr(settings, "database_url", ""):
        from .store_postgres import PostgresStore
        return PostgresStore(settings.database_url, campaign_name)
    return LeadStore(settings.data_dir, campaign_name)
