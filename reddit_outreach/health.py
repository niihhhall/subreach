# -*- coding: utf-8 -*-
"""Account health + shadowban defense for the outreach system.

The write paths (``sender.zernio_comment`` etc.) fire blind: they trust the API
said "posted" and mark the lead SENT. In production that is dangerous — a
*shadowban* means your comments are invisible to everyone but you, so you keep
spending API + LLM calls and reach nobody, with no error to tell you.

This module adds four defensive layers, in order of ROI:

1. **Post-send verification** — after a comment is posted, re-fetch the thread
   from a *logged-out* client and confirm the comment is actually visible.
   Catches per-subreddit AutoMod removals (the common case) and silent shadows.

2. **Shadowban / profile probe** — fetch ``/user/<name>/about.json`` with no
   auth. Since we *know* the account exists (it is connected via Zernio), a 404
   to a logged-out client strongly implies a sitewide shadowban. Also surfaces
   suspension, karma and account age.

3. **Health score + circuit breaker** — a 0-100 composite from the signals
   above plus recent removal rate and 429s. When it collapses (shadowban,
   suspension, or a removal spike) the breaker trips and blocks all sends until
   a human resets it.

4. **Rate / warm-up guardrails** — token-bucket-ish daily caps, per-subreddit
   caps, a minimum gap between sends, and a gentler cap while the account is
   still "warming up". Prevention is cheaper than detection.

Everything degrades gracefully: if ``requests`` is missing or the network is
down, probes return ``ok=False`` and the gate *fails open with a warning*
rather than crashing the pipeline (a health check must never be the thing that
takes outreach down).

Network calls here are read-only, unauthenticated GETs to public reddit.com
JSON endpoints. No credentials are ever sent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .rules import resolve_rule, should_bench

# ── tuning knobs (overridable via Campaign guardrails) ────────────────
DEFAULT_MAX_SENDS_PER_DAY = 12
DEFAULT_MAX_SENDS_PER_SUBREDDIT_PER_DAY = 3
DEFAULT_MIN_SECONDS_BETWEEN_SENDS = 90
DEFAULT_WARMUP_DAYS = 7
DEFAULT_WARMUP_MAX_SENDS_PER_DAY = 3

# removal-rate breaker: trip when this many of the last N verified sends were removed
REMOVAL_WINDOW = 5
REMOVAL_TRIP_COUNT = 3

# how long the breaker stays tripped (seconds) before it *may* auto-resume
BREAKER_COOLDOWN_REMOVALS = 6 * 3600      # removal spike — recoverable
BREAKER_COOLDOWN_BAN = 24 * 3600          # shadowban/suspension — needs a human

_USER_AGENT = "reddit-outreach-healthcheck/1.0 (defensive account monitoring)"


# ── data models ───────────────────────────────────────────────────────
@dataclass
class ProfileProbe:
    """Result of a logged-out public-profile probe."""

    username: str
    ok: bool = False                 # did the network call actually complete?
    shadowbanned: bool = False       # exists in Zernio but 404 to logged-out world
    suspended: bool = False
    comment_karma: int = 0
    link_karma: int = 0
    created_utc: float = 0.0
    http_status: int = 0
    checked_at: float = field(default_factory=time.time)
    method: str = "about.json"
    note: str = ""

    @property
    def account_age_days(self) -> float:
        if not self.created_utc:
            return 0.0
        return max(0.0, (time.time() - self.created_utc) / 86400.0)


@dataclass
class VisibilityCheck:
    """Result of verifying a just-posted comment is publicly visible."""

    post_id: str
    comment_id: str = ""
    ok: bool = False                 # did the network call complete?
    visible: bool = False
    checked_at: float = field(default_factory=time.time)
    note: str = ""


@dataclass
class HealthReport:
    account: str = ""                # stable id (Zernio account id) or username
    username: str = ""
    score: int = 100                 # 0-100, higher = healthier
    status: str = "unknown"          # healthy | degraded | at_risk | banned | unknown
    reasons: List[str] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)
    checked_at: float = field(default_factory=time.time)


@dataclass
class GateDecision:
    """Verdict from the pre-send gate."""

    allowed: bool
    reason: str = ""
    wait_seconds: int = 0            # >0 => caller should sleep then may retry


# ── low-level: unauthenticated reddit JSON ────────────────────────────
def _reddit_get(path: str, proxy: str = "", timeout: int = 20):
    """GET a public reddit.com JSON endpoint with no auth. Returns (status, json|None).

    Never raises; on any failure returns (0, None) so callers can fail open.
    """
    try:
        import requests
    except Exception:
        return 0, None

    url = f"https://www.reddit.com{path}"
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            proxies=proxies,
            timeout=timeout,
        )
    except Exception:
        return 0, None
    data = None
    try:
        data = resp.json()
    except Exception:
        data = None
    return resp.status_code, data


# ── layer 2: shadowban / profile probe ────────────────────────────────
def probe_public_profile(username: str, proxy: str = "") -> ProfileProbe:
    """Probe a Reddit account's *public* profile as an anonymous visitor.

    We already know (via Zernio) the account exists. Therefore:
      * HTTP 404          -> shadowbanned (invisible to the logged-out world)
      * 200 + is_suspended -> account suspended
      * 200 + data         -> visible; capture karma + age
      * network failure    -> ok=False (unknown; do not treat as a ban)
    """
    username = (username or "").replace("u/", "").strip()
    probe = ProfileProbe(username=username)
    if not username:
        probe.note = "no username to probe"
        return probe

    status, data = _reddit_get(f"/user/{username}/about.json", proxy=proxy)
    probe.http_status = status
    if status == 0:
        probe.note = "probe failed (no network / requests unavailable) — status unknown"
        return probe

    probe.ok = True
    if status == 404:
        probe.shadowbanned = True
        probe.note = "profile 404s to logged-out visitors while connected in Zernio -> shadowban suspected"
        return probe
    if status == 429:
        probe.ok = False
        probe.note = "429 rate-limited by reddit during probe — status unknown"
        return probe
    if status >= 400:
        probe.ok = False
        probe.note = f"unexpected HTTP {status} during probe — status unknown"
        return probe

    d = (data or {}).get("data", {}) if isinstance(data, dict) else {}
    probe.suspended = bool(d.get("is_suspended", False))
    probe.comment_karma = int(d.get("comment_karma", 0) or 0)
    probe.link_karma = int(d.get("link_karma", 0) or 0)
    probe.created_utc = float(d.get("created_utc", 0) or 0)
    probe.note = "suspended" if probe.suspended else "profile visible"
    return probe


# ── layer 1: post-send visibility verification ────────────────────────
def _collect_comment_ids(children: list) -> List[Dict[str, str]]:
    """Flatten a reddit comment listing into [{id, author, body}] (recursive)."""
    out: List[Dict[str, str]] = []
    for child in children or []:
        if not isinstance(child, dict):
            continue
        cd = child.get("data", {})
        if not isinstance(cd, dict):
            continue
        cid = str(cd.get("id", ""))
        if cid:
            out.append({
                "id": cid,
                "author": str(cd.get("author", "")),
                "body": str(cd.get("body", "")),
            })
        replies = cd.get("replies")
        if isinstance(replies, dict):
            grand = replies.get("data", {}).get("children", [])
            out.extend(_collect_comment_ids(grand))
    return out


def verify_comment_visible(
    post_id: str,
    *,
    subreddit: str = "",
    comment_id: str = "",
    body_snippet: str = "",
    proxy: str = "",
) -> VisibilityCheck:
    """Confirm a comment is publicly visible on its thread (logged-out fetch).

    Matches by comment id first, then by a body snippet (more robust to id
    prefix differences between tools). Returns ``ok=False`` if we couldn't
    fetch the thread at all — the caller should treat that as "unknown", not
    "removed".
    """
    check = VisibilityCheck(post_id=post_id, comment_id=comment_id)
    pid = str(post_id or "").replace("t3_", "")
    cid = str(comment_id or "").replace("t1_", "")
    if not pid:
        check.note = "no post id to verify against"
        return check

    status, data = _reddit_get(f"/comments/{pid}.json?limit=200&depth=10", proxy=proxy)
    if status == 0 or not isinstance(data, list) or len(data) < 2:
        check.note = f"could not fetch thread (HTTP {status}) — visibility unknown"
        return check

    check.ok = True
    listing = data[1].get("data", {}).get("children", []) if isinstance(data[1], dict) else []
    comments = _collect_comment_ids(listing)

    snippet = (body_snippet or "").strip()[:80].lower()
    for c in comments:
        if cid and c["id"] == cid:
            check.visible = True
            check.note = "comment found on thread (id match)"
            return check
        if snippet and snippet in c["body"].strip().lower():
            check.visible = True
            check.note = "comment found on thread (body match)"
            return check

    check.visible = False
    check.note = (
        "comment NOT visible to logged-out client — likely removed by AutoMod/mods "
        "or shadowed. Verify manually."
    )
    return check


# ── layer 3+4: the monitor (score, breaker, rate gate) ────────────────
class HealthMonitor:
    """Ties the health signals to the store and the send path.

    Construct once per run with the campaign guardrails, the store (for history
    + breaker state + send counts), and the proxy. Then:

      * ``guard_send(...)``       — call *before* every automated send.
      * ``verify_after_send(...)``— call *after* a confirmed comment send.
      * ``probe(...)``            — scheduled/standalone health probe.
    """

    def __init__(self, campaign, store, *, proxy: str = "",
                 account_id: str = "", username: str = "", reddit=None):
        self.campaign = campaign
        self.store = store
        self.proxy = proxy
        self.account_id = account_id or ""
        self.username = (username or "").replace("u/", "")
        self.reddit = reddit  # if it exposes account_info() (rdt), use real karma/age

    # identity used as the breaker/health key (stable id preferred)
    @property
    def key(self) -> str:
        return self.account_id or self.username or "default"

    # ── guardrail knobs (campaign overrides, else module defaults) ────
    def _g(self, attr: str, default):
        return getattr(self.campaign, attr, None) or default

    @property
    def max_per_day(self) -> int:
        return int(self._g("max_sends_per_day", DEFAULT_MAX_SENDS_PER_DAY))

    @property
    def max_per_sub_per_day(self) -> int:
        return int(self._g("max_sends_per_subreddit_per_day",
                           DEFAULT_MAX_SENDS_PER_SUBREDDIT_PER_DAY))

    @property
    def min_gap_seconds(self) -> int:
        return int(self._g("min_seconds_between_sends", DEFAULT_MIN_SECONDS_BETWEEN_SENDS))

    @property
    def warmup_days(self) -> int:
        return int(self._g("warmup_days", DEFAULT_WARMUP_DAYS))

    # ── the pre-send gate ─────────────────────────────────────────────
    def guard_send(self, *, subreddit: str = "") -> GateDecision:
        """Decide whether an automated send may proceed right now."""
        now = time.time()

        # 1) circuit breaker
        breaker = self.store.breaker_state(self.key)
        if breaker and breaker.get("breaker_tripped"):
            resume = breaker.get("resume_after") or 0
            if not resume or now < resume:
                mins = int((resume - now) / 60) if resume else -1
                when = f"~{mins} min" if mins >= 0 else "manual reset required"
                return GateDecision(
                    False,
                    reason=f"circuit breaker OPEN: {breaker.get('reason', 'unknown')} "
                           f"(resume: {when}). Run `health --reset-breaker` after fixing.",
                )
            # cooldown elapsed — auto-reset and continue
            self.store.reset_breaker(self.key)

        # 2) daily volume cap (with warm-up)
        day_ago = now - 86400
        sent_today = self.store.count_sends(since_ts=day_ago)
        cap = self.max_per_day
        if self._is_warming_up():
            cap = min(cap, int(self._g("warmup_max_sends_per_day",
                                       DEFAULT_WARMUP_MAX_SENDS_PER_DAY)))
        if sent_today >= cap:
            return GateDecision(
                False,
                reason=f"daily send cap reached ({sent_today}/{cap}"
                       f"{' — warm-up' if self._is_warming_up() else ''}). Resets in 24h.",
            )

        # 3) per-subreddit rules: auto-bench, karma/age gates, per-sub cap
        if subreddit:
            rule = resolve_rule(self.campaign, subreddit)

            # 3a) closed loop — bench subs that keep removing our sends
            removed, total = self.store.subreddit_removal_stats(subreddit)
            if should_bench(removed, total,
                            rate=float(self._g("auto_bench_removal_rate", 0.5)),
                            min_samples=int(self._g("auto_bench_min_samples", 4))):
                return GateDecision(
                    False,
                    reason=f"r/{subreddit} benched: {removed}/{total} recent sends removed. "
                           f"Its rules likely block this outreach — stop targeting it.",
                )

            # 3b) karma / account-age gates (from last health probe; skip if unknown)
            block = self._rule_eligibility(rule)
            if block:
                return GateDecision(False, reason=block)

            # 3c) per-subreddit daily cap (rule override wins over campaign default)
            sub_cap = rule.max_sends_per_day or self.max_per_sub_per_day
            sub_today = self.store.count_sends(since_ts=day_ago, subreddit=subreddit)
            if sub_today >= sub_cap:
                return GateDecision(
                    False,
                    reason=f"per-subreddit cap reached for r/{subreddit} ({sub_today}/{sub_cap}).",
                )

        # 4) minimum gap between sends (human-like pacing)
        last = self.store.last_send_ts()
        if last:
            elapsed = now - last
            if elapsed < self.min_gap_seconds:
                wait = int(self.min_gap_seconds - elapsed)
                return GateDecision(
                    False,
                    reason=f"pacing: last send {int(elapsed)}s ago, "
                           f"min gap {self.min_gap_seconds}s.",
                    wait_seconds=wait,
                )

        return GateDecision(True, reason="ok")

    def _rule_eligibility(self, rule) -> str:
        """Check karma/account-age requirements for a subreddit.

        Uses the most recent health-probe signals. If we have no probe data
        (the shadowban probe is currently 403-blocked), we FAIL OPEN — an
        unknown karma/age never blocks a send, it just can't enforce the gate.
        Returns a block reason string, or "" to allow.
        """
        if not (rule.min_comment_karma or rule.min_account_age_days):
            return ""
        latest = self.store.latest_health(self.key)
        signals = (latest or {}).get("signals") or {}
        karma = signals.get("comment_karma")
        age = signals.get("account_age_days")
        if rule.min_comment_karma and isinstance(karma, (int, float)) \
                and karma < rule.min_comment_karma:
            return (f"r/{rule.subreddit} requires ~{rule.min_comment_karma} comment karma; "
                    f"account has {int(karma)}.")
        if rule.min_account_age_days and isinstance(age, (int, float)) and 0 < age \
                and age < rule.min_account_age_days:
            return (f"r/{rule.subreddit} requires ~{rule.min_account_age_days}d account age; "
                    f"account is {int(age)}d.")
        return ""

    def _is_warming_up(self) -> bool:
        """True while the account is still inside its warm-up window.

        Uses the real Reddit account age when we have a recent probe; otherwise
        falls back to when we first saw the account locally.
        """
        latest = self.store.latest_health(self.key)
        if latest:
            signals = latest.get("signals") or {}
            age = signals.get("account_age_days")
            if isinstance(age, (int, float)) and age > 0:
                return age < self.warmup_days
        for acct in self.store.accounts():
            if acct.get("account_id") == self.account_id or acct.get("username") == self.username:
                first = acct.get("first_seen") or 0
                if first:
                    return (time.time() - first) / 86400.0 < self.warmup_days
        return False

    # ── post-send verification ────────────────────────────────────────
    def verify_after_send(self, lead, result, *, grace_seconds: int = 8) -> VisibilityCheck:
        """Verify a just-posted comment is visible; log it and trip the breaker
        on a removal spike. ``result`` is the ``SendResult`` from the sender."""
        comment_id = (result.ref or "").replace("comment:", "")
        body = lead.draft.body if lead.draft else ""
        if grace_seconds > 0:
            time.sleep(grace_seconds)  # give reddit a moment to index

        check = verify_comment_visible(
            lead.post.id,
            subreddit=lead.post.subreddit,
            comment_id=comment_id,
            body_snippet=body,
            proxy=self.proxy,
        )

        if not check.ok:
            status = "unverified"
        elif check.visible:
            status = "visible"
        else:
            status = "removed"

        self.store.log_activity(
            "verify", channel="comment", post_id=lead.post.id,
            subreddit=lead.post.subreddit, author=lead.post.author,
            account=self.username, ref=comment_id, status=status,
            detail=check.note[:200],
        )
        lead.notes.append(f"verify: {status} — {check.note}")

        if status == "removed":
            self._maybe_trip_on_removals()
        return check

    def _maybe_trip_on_removals(self) -> None:
        """Trip the breaker if recent verified sends are being removed."""
        recent = self.store.recent_verifications(limit=REMOVAL_WINDOW)
        removed = sum(1 for r in recent if r.get("status") == "removed")
        if removed >= REMOVAL_TRIP_COUNT:
            self.store.trip_breaker(
                self.key,
                reason=f"{removed}/{len(recent)} recent sends removed — likely "
                       f"AutoMod/subreddit ban or shadow. Investigate before resuming.",
                resume_after=time.time() + BREAKER_COOLDOWN_REMOVALS,
                campaign=getattr(self.campaign, "name", ""),
            )

    # ── standalone probe + scoring ────────────────────────────────────
    def probe(self) -> HealthReport:
        """Run a full health probe: shadowban + score, persist a snapshot,
        and trip the breaker on a hard ban/suspension."""
        report = HealthReport(account=self.key, username=self.username)
        probe = probe_public_profile(self.username, proxy=self.proxy)

        # Prefer authenticated karma/age from rdt `whoami` — this is the real
        # (non-403) signal that fixes the anonymous probe being blocked.
        if self.reddit is not None and hasattr(self.reddit, "account_info"):
            try:
                info = self.reddit.account_info()
            except Exception:
                info = None
            if info:
                probe.comment_karma = int(info.get("comment_karma", probe.comment_karma) or 0)
                probe.link_karma = int(info.get("link_karma", probe.link_karma) or 0)
                probe.created_utc = float(info.get("created_utc", 0) or 0) or probe.created_utc
                if not probe.ok:
                    # anon probe was blocked (403), but we reached the account
                    # authenticated — we have real karma/age to score on.
                    probe.ok = True
                    probe.note = "karma/age from rdt whoami (anon probe blocked)"

        report.signals = {
            "probe_ok": probe.ok,
            "http_status": probe.http_status,
            "shadowbanned": probe.shadowbanned,
            "suspended": probe.suspended,
            "comment_karma": probe.comment_karma,
            "link_karma": probe.link_karma,
            "account_age_days": round(probe.account_age_days, 1),
        }

        now = time.time()
        day_ago = now - 86400
        recent_verifs = self.store.recent_verifications(limit=REMOVAL_WINDOW)
        removed = sum(1 for r in recent_verifs if r.get("status") == "removed")
        rate_limited = self.store.count_rate_limit_events(since_ts=day_ago)
        report.signals["recent_removed"] = removed
        report.signals["recent_verified"] = len(recent_verifs)
        report.signals["rate_limit_events_24h"] = rate_limited

        score = 100
        reasons: List[str] = []

        if not probe.ok:
            report.status = "unknown"
            report.score = self._last_score_or(100)
            reasons.append(f"profile probe inconclusive: {probe.note}")
            report.reasons = reasons
            self._persist(report, probe)
            return report

        if probe.shadowbanned:
            score = 0
            reasons.append("SHADOWBANNED — comments/posts invisible sitewide")
        elif probe.suspended:
            score = 0
            reasons.append("account SUSPENDED by Reddit")
        else:
            if recent_verifs:
                rr = removed / len(recent_verifs)
                if rr >= 0.6:
                    score -= 50
                    reasons.append(f"high removal rate ({removed}/{len(recent_verifs)})")
                elif rr >= 0.3:
                    score -= 25
                    reasons.append(f"elevated removal rate ({removed}/{len(recent_verifs)})")
            if rate_limited >= 5:
                score -= 20
                reasons.append(f"{rate_limited} rate-limit hits in 24h — slow down")
            total_karma = probe.comment_karma + probe.link_karma
            if total_karma < 10:
                score -= 15
                reasons.append(f"very low karma ({total_karma}) — strict subs may auto-remove")
            if 0 < probe.account_age_days < self.warmup_days:
                score -= 10
                reasons.append(f"young account ({probe.account_age_days:.0f}d) — still warming up")

        score = max(0, min(100, score))
        report.score = score
        report.status = _status_for(score, probe)
        report.reasons = reasons or ["no issues detected"]

        self._persist(report, probe)

        # hard bans trip the breaker and demand a human
        if probe.shadowbanned or probe.suspended:
            self.store.trip_breaker(
                self.key,
                reason=reasons[0],
                resume_after=now + BREAKER_COOLDOWN_BAN,
                campaign=getattr(self.campaign, "name", ""),
            )
        return report

    def _persist(self, report: HealthReport, probe: ProfileProbe) -> None:
        self.store.record_health_snapshot(
            account=self.key,
            username=self.username,
            score=report.score,
            status=report.status,
            shadowbanned=(1 if probe.shadowbanned else (0 if probe.ok else -1)),
            signals=report.signals,
            campaign=getattr(self.campaign, "name", ""),
            detail="; ".join(report.reasons)[:300],
        )

    def _last_score_or(self, default: int) -> int:
        latest = self.store.latest_health(self.key)
        if latest and latest.get("score") is not None:
            return int(latest["score"])
        return default


def _status_for(score: int, probe: ProfileProbe) -> str:
    if probe.shadowbanned or probe.suspended:
        return "banned"
    if score >= 75:
        return "healthy"
    if score >= 50:
        return "degraded"
    if score >= 25:
        return "at_risk"
    return "banned"
