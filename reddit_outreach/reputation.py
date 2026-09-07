# -*- coding: utf-8 -*-
"""Reputation / CQS tracker — the feedback loop that keeps the account safe.

Three jobs:
  1. **Snapshot karma** via ``rdt whoami`` over time → a karma trend (rising =
     healthy engagement; flat/falling = trouble).
  2. **Track posted comments** — re-read each comment we posted, capture its
     upvotes and whether it's still visible (upvoted+visible = good; downvoted
     or removed = bad).
  3. **Assess + gate** — combine karma trend + comment outcomes into a CQS proxy
     status, and trip the health circuit breaker if reputation is declining, so
     the account backs off before it gets re-flagged.

This is what makes Phase-2 engagement self-correcting instead of blind.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# thresholds
REMOVAL_RATE_TRIP = 0.30        # trip if >=30% of tracked comments were removed
MIN_TRACKED_FOR_TRIP = 4        # ...over at least this many tracked comments
BREAKER_COOLDOWN = 12 * 3600    # reputation-triggered back-off window


@dataclass
class ReputationReport:
    account: str = ""
    comment_karma: int = 0
    link_karma: int = 0
    karma_delta: Optional[int] = None       # vs previous snapshot (None if first)
    tracked: int = 0
    visible: int = 0
    removed: int = 0
    avg_comment_score: float = 0.0
    status: str = "unknown"                 # healthy | building | at_risk | unknown
    reasons: List[str] = field(default_factory=list)


class ReputationTracker:
    def __init__(self, campaign, store, reddit, *, account_id: str = "", username: str = ""):
        self.campaign = campaign
        self.store = store
        self.reddit = reddit
        self.account_id = account_id or ""
        self.username = (username or "").replace("u/", "")

    @property
    def key(self) -> str:
        return self.account_id or self.username or "default"

    # ── 1. karma snapshot ─────────────────────────────────────────────
    def snapshot(self) -> Optional[Dict[str, int]]:
        """Record the account's current karma via whoami. None if unavailable."""
        info = None
        if self.reddit is not None and hasattr(self.reddit, "account_info"):
            try:
                info = self.reddit.account_info()
            except Exception:
                info = None
        if not info:
            return None
        self.store.record_reputation(
            account=self.key, comment_karma=info.get("comment_karma", 0),
            link_karma=info.get("link_karma", 0))
        return info

    # ── 2. track posted comments ──────────────────────────────────────
    def track_comment(self, post_id: str, comment_id: str, subreddit: str = "") -> Dict[str, Any]:
        """Re-read a thread and find our comment → (score, visible). Logs the
        outcome. Returns {visible, score}."""
        cid = (comment_id or "").replace("comment:", "").replace("t1_", "")
        score, visible = 0, False
        try:
            _post, comments = self.reddit.read(post_id)
            for c in comments or []:
                if str(c.id).replace("t1_", "") == cid:
                    score, visible = c.score, True
                    break
        except Exception:
            pass
        self.store.log_activity(
            "comment_outcome", channel="comment", post_id=post_id, subreddit=subreddit,
            account=self.username, ref=cid,
            status=("visible" if visible else "removed"), detail=str(score))
        return {"visible": visible, "score": score}

    def track_recent(self, limit: int = 15) -> None:
        """Track outcomes for our recent posted comments."""
        sent = self.store.recent_activities(limit=limit, action="sent")
        for a in sent:
            if a.get("channel") == "comment" and a.get("ref"):
                self.track_comment(a["ref"], a["ref"], a.get("subreddit", ""))

    # ── 3. assess + gate ──────────────────────────────────────────────
    def assess(self) -> ReputationReport:
        report = ReputationReport(account=self.key)
        history = self.store.reputation_history(self.key, limit=5)
        if history:
            report.comment_karma = int(history[0].get("comment_karma") or 0)
            report.link_karma = int(history[0].get("link_karma") or 0)
            if len(history) >= 2:
                prev = int(history[1].get("comment_karma") or 0)
                report.karma_delta = report.comment_karma - prev

        outcomes = self.store.recent_activities(limit=20, action="comment_outcome")
        report.tracked = len(outcomes)
        report.removed = sum(1 for o in outcomes if o.get("status") == "removed")
        report.visible = report.tracked - report.removed
        scores = [int(o.get("detail") or 0) for o in outcomes if _is_int(o.get("detail"))]
        report.avg_comment_score = round(sum(scores) / len(scores), 1) if scores else 0.0

        self._decide(report)
        return report

    def _decide(self, r: ReputationReport) -> None:
        reasons = []
        removal_rate = (r.removed / r.tracked) if r.tracked else 0.0

        if r.tracked >= MIN_TRACKED_FOR_TRIP and removal_rate >= REMOVAL_RATE_TRIP:
            r.status = "at_risk"
            reasons.append(f"{r.removed}/{r.tracked} recent comments removed")
            self.store.trip_breaker(
                self.key,
                reason=f"reputation: {r.removed}/{r.tracked} comments removed — back off",
                resume_after=time.time() + BREAKER_COOLDOWN,
                campaign=getattr(self.campaign, "name", ""))
        elif r.karma_delta is not None and r.karma_delta < 0:
            r.status = "at_risk"
            reasons.append(f"comment karma dropped ({r.karma_delta})")
        elif r.avg_comment_score < 0:
            r.status = "at_risk"
            reasons.append(f"comments net-downvoted (avg {r.avg_comment_score})")
        elif r.tracked == 0 and r.karma_delta is None:
            r.status = "unknown"
            reasons.append("no data yet — run after some snapshots/comments")
        else:
            r.status = "healthy" if (r.karma_delta or 0) >= 0 else "building"
            reasons.append("karma stable/rising, comments landing" if r.status == "healthy"
                           else "building reputation")
        r.reasons = reasons


def _is_int(v) -> bool:
    try:
        int(v)
        return True
    except (TypeError, ValueError):
        return False
