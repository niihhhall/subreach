# -*- coding: utf-8 -*-
"""Lead triage: recency, saturation, and a combined 'sendability' score.

Topic-fit alone ranked 9-month-old advice posts above fresh cries for help.
This module adds the missing dimensions so the queue reflects what's actually
worth acting on *now*:

  * **Recency**   — how old is the post? A dead thread isn't worth a comment.
  * **Saturation**— how many comments already? 30+ means you're buried / late.
  * **Sendability** — priority, discounted for age and crowding, gated on the
    author actually being a prospect (asker), producing a hot/warm/cold tier
    and a channel hint (comment / dm / skip).

Nothing is deleted: an old post from someone genuinely asking is kept as a
*cold* lead — the founder may still be unsolved — just ranked below the fresh,
uncrowded ones. Only non-prospects (advice-givers, vendors) are filtered out
upstream in qualification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# recency thresholds (days)
FRESH_DAYS = 7
RECENT_DAYS = 30

# saturation thresholds (comment counts)
OPEN_MAX = 10
BUSY_MAX = 25

# sendability tier cutoffs
HOT_MIN = 65
WARM_MIN = 35


@dataclass
class Triage:
    age_days: float                 # -1 if unknown
    age_tag: str                    # fresh | recent | stale | unknown
    saturation_tag: str             # open | busy | saturated
    num_comments: int
    score: int                      # 0-100 sendability
    tier: str                       # hot | warm | cold | skip
    channel_hint: str               # what to do about it


def post_age_days(created_utc: float, *, now: float | None = None) -> float:
    if not created_utc:
        return -1.0
    now = now if now is not None else time.time()
    return max(0.0, (now - created_utc) / 86400.0)


def age_tag(age_days: float) -> str:
    if age_days < 0:
        return "unknown"
    if age_days <= FRESH_DAYS:
        return "fresh"
    if age_days <= RECENT_DAYS:
        return "recent"
    return "stale"


def saturation_tag(num_comments: int) -> str:
    n = num_comments or 0
    if n < OPEN_MAX:
        return "open"
    if n <= BUSY_MAX:
        return "busy"
    return "saturated"


def _recency_mult(tag: str) -> float:
    return {"fresh": 1.0, "recent": 0.8, "stale": 0.5, "unknown": 0.7}[tag]


def _saturation_mult(tag: str) -> float:
    return {"open": 1.0, "busy": 0.85, "saturated": 0.6}[tag]


def visibility_multiplier(created_utc: float, num_comments: int,
                          *, now: float | None = None) -> float:
    """0.3-1.0 multiplier for how *visible* a comment here would be — fresh +
    uncrowded threads score high. Reused by engagement scoring (early comments
    on fresh, open threads earn the upvotes that build CQS)."""
    return (_recency_mult(age_tag(post_age_days(created_utc, now=now)))
            * _saturation_mult(saturation_tag(num_comments)))


def _channel_hint(is_prospect: bool, atag: str, stag: str) -> str:
    if not is_prospect:
        return "skip — author is not a prospect (advice/vendor)"
    if atag == "stale":
        return "low-priority comment — old thread, but may still be unsolved"
    if stag == "saturated":
        return "DM the author — in-market but the thread is crowded"
    if atag == "fresh" and stag == "open":
        return "comment now — fresh and uncrowded, best odds"
    return "comment — reply on the thread"


def triage_lead(lead, *, now: float | None = None) -> Triage:
    """Compute the triage view for a lead. Pure — no I/O."""
    post = lead.post
    q = lead.qualification
    priority = q.priority if q else 0
    is_prospect = q.is_prospect if q else True

    age = post_age_days(post.created_utc, now=now)
    atag = age_tag(age)
    stag = saturation_tag(post.num_comments)

    if not is_prospect:
        return Triage(age, atag, stag, post.num_comments or 0, 0, "skip",
                      _channel_hint(False, atag, stag))

    score = int(round(priority * _recency_mult(atag) * _saturation_mult(stag)))
    score = max(0, min(100, score))
    if score >= HOT_MIN:
        tier = "hot"
    elif score >= WARM_MIN:
        tier = "warm"
    else:
        tier = "cold"

    return Triage(age, atag, stag, post.num_comments or 0, score, tier,
                  _channel_hint(True, atag, stag))
