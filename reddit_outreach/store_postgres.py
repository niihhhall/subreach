# -*- coding: utf-8 -*-
"""Supabase / Postgres backend — same interface as the SQLite ``LeadStore``.

Selected automatically when ``DATABASE_URL`` (or ``SUPABASE_DB_URL``) is set.
Use the Postgres connection string from your Supabase project
(Settings → Database → Connection string / URI). The pooled connection string
works well for serverless / many short-lived runs.

Requires ``psycopg`` (v3):  pip install "psycopg[binary]"
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .models import Lead
from .store import (  # reuse the shared action vocabulary + helpers
    APPROVED, DISCOVERED, DISQUALIFIED, DRAFTED, REJECTED, RUN, SENT, _coerce_id,
)


class PostgresStore:
    kind = "postgres"

    def __init__(self, dsn: str, campaign_name: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - env dependent
            raise SystemExit(
                "DATABASE_URL is set but psycopg is not installed.\n"
                "Install it with:  pip install \"psycopg[binary]\""
            ) from exc

        self.campaign = campaign_name
        self.path = "supabase/postgres"
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
        self._init_schema()
        self._leads: Dict[str, Lead] = {}
        self._load()

    # ── connection resilience ──────────────────────────────────────────
    # Neon/Supabase close idle connections, so a long-running loop's connection
    # goes stale between cycles. Reconnect + retry once on a dropped connection
    # instead of failing the whole cycle.
    def _reconnect(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = self._psycopg.connect(
            self._dsn, row_factory=self._dict_row, autocommit=True)

    def _is_conn_error(self, exc: Exception) -> bool:
        return isinstance(exc, (self._psycopg.OperationalError,
                                self._psycopg.InterfaceError))

    def _exec(self, sql: str, params: tuple = ()) -> None:
        """Run a write with one reconnect-and-retry on a dropped connection."""
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
        except Exception as exc:
            if not self._is_conn_error(exc):
                raise
            self._reconnect()
            with self.conn.cursor() as cur:
                cur.execute(sql, params)

    # ── schema ────────────────────────────────────────────────────────
    def _init_schema(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    campaign           TEXT NOT NULL,
                    post_id            TEXT NOT NULL,
                    subreddit          TEXT,
                    author             TEXT,
                    title              TEXT,
                    url                TEXT,
                    source_query       TEXT,
                    fit_score          INTEGER,
                    intent_score       INTEGER,
                    priority           INTEGER,
                    stage              TEXT,
                    compliance_verdict TEXT,
                    draft_body         TEXT,
                    discovered_at      DOUBLE PRECISION,
                    updated_at         DOUBLE PRECISION,
                    sent_at            DOUBLE PRECISION,
                    sent_ref           TEXT,
                    data_json          JSONB,
                    PRIMARY KEY (campaign, post_id)
                );
                CREATE TABLE IF NOT EXISTS activities (
                    id        BIGSERIAL PRIMARY KEY,
                    ts        DOUBLE PRECISION NOT NULL,
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
                    first_seen DOUBLE PRECISION,
                    last_used  DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS account_health (
                    id           BIGSERIAL PRIMARY KEY,
                    ts           DOUBLE PRECISION NOT NULL,
                    campaign     TEXT,
                    account      TEXT,
                    username     TEXT,
                    score        INTEGER,
                    status       TEXT,
                    shadowbanned INTEGER,
                    signals_json JSONB,
                    detail       TEXT
                );
                CREATE TABLE IF NOT EXISTS health_state (
                    account         TEXT PRIMARY KEY,
                    campaign        TEXT,
                    breaker_tripped INTEGER DEFAULT 0,
                    reason          TEXT,
                    tripped_at      DOUBLE PRECISION,
                    resume_after    DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS subreddit_rules (
                    subreddit  TEXT PRIMARY KEY,
                    campaign   TEXT,
                    rules_json JSONB,
                    fetched_at DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS scouted_subreddits (
                    subreddit    TEXT NOT NULL,
                    campaign     TEXT NOT NULL,
                    vertical     TEXT,
                    relevance    INTEGER,
                    active       INTEGER,
                    sample_count INTEGER,
                    first_seen   DOUBLE PRECISION,
                    last_seen    DOUBLE PRECISION,
                    PRIMARY KEY (campaign, subreddit)
                );
                CREATE TABLE IF NOT EXISTS reputation (
                    id            BIGSERIAL PRIMARY KEY,
                    ts            DOUBLE PRECISION NOT NULL,
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

    def _load(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT data_json FROM leads WHERE campaign = %s", (self.campaign,))
            for row in cur.fetchall():
                raw = row["data_json"]
                if isinstance(raw, str):
                    raw = json.loads(raw)
                try:
                    lead = Lead.from_dict(raw)
                except Exception:
                    continue
                self._leads[lead.post.id] = lead

    # ── lead persistence ────────────────────────────────────────────────
    def _write_lead(self, lead: Lead) -> None:
        from psycopg.types.json import Json
        q = lead.qualification
        self._exec(
                """
                INSERT INTO leads (
                    campaign, post_id, subreddit, author, title, url, source_query,
                    fit_score, intent_score, priority, stage, compliance_verdict,
                    draft_body, discovered_at, updated_at, sent_at, sent_ref, data_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (campaign, post_id) DO UPDATE SET
                    subreddit=EXCLUDED.subreddit, author=EXCLUDED.author,
                    title=EXCLUDED.title, url=EXCLUDED.url,
                    source_query=EXCLUDED.source_query, fit_score=EXCLUDED.fit_score,
                    intent_score=EXCLUDED.intent_score, priority=EXCLUDED.priority,
                    stage=EXCLUDED.stage, compliance_verdict=EXCLUDED.compliance_verdict,
                    draft_body=EXCLUDED.draft_body, updated_at=EXCLUDED.updated_at,
                    sent_at=EXCLUDED.sent_at, sent_ref=EXCLUDED.sent_ref,
                    data_json=EXCLUDED.data_json
                """,
                (
                    self.campaign, lead.post.id, lead.post.subreddit, lead.post.author,
                    lead.post.title, lead.post.full_url, lead.source_query,
                    q.fit_score if q else None, q.intent_score if q else None,
                    q.priority if q else None, lead.stage,
                    lead.compliance.verdict if lead.compliance else None,
                    lead.draft.body if lead.draft else None,
                    lead.discovered_at, time.time(), lead.sent_at, lead.sent_ref,
                    Json(lead.to_dict()),
                ),
            )

    def save(self) -> None:
        for lead in self._leads.values():
            self._write_lead(lead)

    def upsert(self, lead: Lead) -> Lead:
        existing = self._leads.get(lead.post.id)
        if existing:
            return existing
        self._leads[lead.post.id] = lead
        self._write_lead(lead)
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
        self._exec(
                """
                INSERT INTO activities
                  (ts, campaign, action, channel, post_id, subreddit, author,
                   account, ref, status, detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (time.time(), self.campaign, action, channel, post_id, subreddit,
                 author, account, ref, status, detail),
            )

    def record_account(self, account_id: str, platform: str, username: str,
                       profile_id: str = "") -> None:
        account_id, username, profile_id = (
            _coerce_id(account_id), _coerce_id(username), _coerce_id(profile_id))
        now = time.time()
        self._exec(
                """
                INSERT INTO accounts (account_id, platform, username, profile_id,
                                      first_seen, last_used)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (account_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    profile_id = EXCLUDED.profile_id,
                    last_used = EXCLUDED.last_used
                """,
                (account_id, platform, username, profile_id, now, now),
            )

    # ── analytics ────────────────────────────────────────────────────────
    def _rows(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        except Exception as exc:
            if not self._is_conn_error(exc):
                raise
            self._reconnect()
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())

    def funnel(self) -> Dict[str, int]:
        rows = self._rows(
            "SELECT stage, COUNT(*) AS c FROM leads WHERE campaign=%s GROUP BY stage",
            (self.campaign,),
        )
        return {r["stage"]: r["c"] for r in rows}

    def subreddit_breakdown(self) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT subreddit,
                   COUNT(*) AS leads,
                   SUM(CASE WHEN sent_at > 0 THEN 1 ELSE 0 END) AS sent,
                   AVG(priority) AS avg_priority
            FROM leads WHERE campaign = %s
            GROUP BY subreddit ORDER BY leads DESC
            """,
            (self.campaign,),
        )

    def sends_by_channel(self) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT channel, status, COUNT(*) AS n
            FROM activities WHERE campaign = %s AND action = %s
            GROUP BY channel, status ORDER BY n DESC
            """,
            (self.campaign, SENT),
        )

    def recent_activities(self, limit: int = 20, action: str = "") -> List[Dict[str, Any]]:
        if action:
            return self._rows(
                "SELECT * FROM activities WHERE campaign=%s AND action=%s "
                "ORDER BY ts DESC LIMIT %s",
                (self.campaign, action, limit),
            )
        return self._rows(
            "SELECT * FROM activities WHERE campaign=%s ORDER BY ts DESC LIMIT %s",
            (self.campaign, limit),
        )

    def top_authors_contacted(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT author, channel, COUNT(*) AS n, MAX(ts) AS last_ts
            FROM activities
            WHERE campaign = %s AND action = %s AND author <> ''
            GROUP BY author, channel ORDER BY last_ts DESC LIMIT %s
            """,
            (self.campaign, SENT, limit),
        )

    def accounts(self) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM accounts ORDER BY last_used DESC")

    # ── account health + circuit breaker ────────────────────────────────
    def record_health_snapshot(self, *, account: str, username: str, score: int,
                               status: str, shadowbanned: int, signals: Dict[str, Any],
                               campaign: str = "", detail: str = "") -> None:
        from psycopg.types.json import Json
        self._exec(
                """
                INSERT INTO account_health
                  (ts, campaign, account, username, score, status, shadowbanned,
                   signals_json, detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (time.time(), campaign or self.campaign, account, username, score,
                 status, shadowbanned, Json(signals), detail),
            )

    def latest_health(self, account: str) -> Optional[Dict[str, Any]]:
        rows = self._rows(
            "SELECT * FROM account_health WHERE account=%s ORDER BY ts DESC LIMIT 1",
            (account,),
        )
        if not rows:
            return None
        d = rows[0]
        raw = d.get("signals_json")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        d["signals"] = raw or {}
        return d

    def health_history(self, account: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT * FROM account_health WHERE account=%s ORDER BY ts DESC LIMIT %s",
            (account, limit),
        )

    def trip_breaker(self, account: str, *, reason: str, resume_after: float,
                     campaign: str = "") -> None:
        self._exec(
                """
                INSERT INTO health_state (account, campaign, breaker_tripped, reason,
                                          tripped_at, resume_after)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (account) DO UPDATE SET
                    breaker_tripped=1, reason=EXCLUDED.reason,
                    tripped_at=EXCLUDED.tripped_at, resume_after=EXCLUDED.resume_after
                """,
                (account, campaign or self.campaign, 1, reason, time.time(), resume_after),
            )

    def reset_breaker(self, account: str) -> None:
        self._exec(
                "UPDATE health_state SET breaker_tripped=0, reason='', resume_after=0 "
                "WHERE account=%s",
                (account,),
            )

    def breaker_state(self, account: str) -> Optional[Dict[str, Any]]:
        rows = self._rows("SELECT * FROM health_state WHERE account=%s", (account,))
        return rows[0] if rows else None

    # ── send-pacing helpers ─────────────────────────────────────────────
    def count_sends(self, since_ts: float = 0.0, subreddit: str = "",
                    channel: str = "", account: str = "") -> int:
        sql = ("SELECT COUNT(*) AS c FROM activities WHERE campaign=%s AND action=%s "
               "AND status NOT IN ('error','dry-run') AND ts >= %s")
        params: list = [self.campaign, SENT, since_ts]
        if subreddit:
            sql += " AND subreddit=%s"
            params.append(subreddit.replace("r/", ""))
        if channel:
            sql += " AND channel=%s"
            params.append(channel)
        if account:
            sql += " AND account=%s"
            params.append(account)
        rows = self._rows(sql, tuple(params))
        return int(rows[0]["c"] if rows else 0)

    def activity_exists(self, action: str, post_id: str) -> bool:
        rows = self._rows(
            "SELECT 1 FROM activities WHERE campaign=%s AND action=%s AND post_id=%s "
            "AND status NOT IN ('error','dry-run') LIMIT 1",
            (self.campaign, action, post_id),
        )
        return bool(rows)

    def last_send_ts(self) -> float:
        rows = self._rows(
            "SELECT MAX(ts) AS t FROM activities WHERE campaign=%s AND action=%s "
            "AND status NOT IN ('error','dry-run')",
            (self.campaign, SENT),
        )
        return float(rows[0]["t"] or 0.0) if rows and rows[0]["t"] is not None else 0.0

    def recent_verifications(self, limit: int = 5) -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT * FROM activities WHERE campaign=%s AND action='verify' "
            "ORDER BY ts DESC LIMIT %s",
            (self.campaign, limit),
        )

    def count_rate_limit_events(self, since_ts: float = 0.0) -> int:
        rows = self._rows(
            "SELECT COUNT(*) AS c FROM activities WHERE campaign=%s AND ts >= %s "
            "AND (detail LIKE '%%429%%' OR detail LIKE '%%Rate limited%%')",
            (self.campaign, since_ts),
        )
        return int(rows[0]["c"] if rows else 0)

    # ── per-subreddit rules: removal stats (closed loop) + cache ────────
    def subreddit_removal_stats(self, subreddit: str, window_days: int = 14) -> tuple:
        since = time.time() - window_days * 86400
        rows = self._rows(
            "SELECT "
            "  SUM(CASE WHEN status='removed' THEN 1 ELSE 0 END) AS removed, "
            "  SUM(CASE WHEN status IN ('removed','visible') THEN 1 ELSE 0 END) AS total "
            "FROM activities WHERE campaign=%s AND action='verify' AND subreddit=%s AND ts>=%s",
            (self.campaign, subreddit.replace("r/", ""), since),
        )
        r = rows[0] if rows else {}
        return (int(r.get("removed") or 0), int(r.get("total") or 0))

    def record_subreddit_rules(self, subreddit: str, rules: Dict[str, Any],
                               campaign: str = "") -> None:
        from psycopg.types.json import Json
        self._exec(
                """
                INSERT INTO subreddit_rules (subreddit, campaign, rules_json, fetched_at)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (subreddit) DO UPDATE SET
                    campaign=EXCLUDED.campaign, rules_json=EXCLUDED.rules_json,
                    fetched_at=EXCLUDED.fetched_at
                """,
                (subreddit.replace("r/", ""), campaign or self.campaign, Json(rules), time.time()),
            )

    def get_subreddit_rules(self, subreddit: str) -> Optional[Dict[str, Any]]:
        rows = self._rows(
            "SELECT rules_json FROM subreddit_rules WHERE subreddit=%s",
            (subreddit.replace("r/", ""),),
        )
        if not rows:
            return None
        raw = rows[0].get("rules_json")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return None
        return raw

    # ── scouted subreddits ──────────────────────────────────────────────
    def record_scouted_subreddit(self, *, subreddit: str, vertical: str = "",
                                 relevance: int = 0, active: bool = False,
                                 sample_count: int = 0) -> None:
        now = time.time()
        self._exec(
                """
                INSERT INTO scouted_subreddits
                  (subreddit, campaign, vertical, relevance, active, sample_count,
                   first_seen, last_seen)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (campaign, subreddit) DO UPDATE SET
                    vertical=EXCLUDED.vertical, relevance=EXCLUDED.relevance,
                    active=EXCLUDED.active, sample_count=EXCLUDED.sample_count,
                    last_seen=EXCLUDED.last_seen
                """,
                (subreddit.replace("r/", ""), self.campaign, vertical, relevance,
                 1 if active else 0, sample_count, now, now),
            )

    def scouted_subreddits(self, active_only: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM scouted_subreddits WHERE campaign=%s"
        if active_only:
            sql += " AND active=1"
        sql += " ORDER BY active DESC, relevance DESC"
        return self._rows(sql, (self.campaign,))

    # ── reputation / CQS snapshots ──────────────────────────────────────
    def record_reputation(self, *, account: str, comment_karma: int, link_karma: int,
                          detail: str = "") -> None:
        self._exec(
                """
                INSERT INTO reputation (ts, campaign, account, comment_karma, link_karma,
                                        total_karma, detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (time.time(), self.campaign, account, comment_karma, link_karma,
                 comment_karma + link_karma, detail),
            )

    def reputation_history(self, account: str, limit: int = 30) -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT * FROM reputation WHERE campaign=%s AND account=%s ORDER BY ts DESC LIMIT %s",
            (self.campaign, account, limit),
        )

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
