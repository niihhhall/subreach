# -*- coding: utf-8 -*-
"""EngagementAgent — decides whether a thread is worth a genuine, reputation-
building comment (Phase 2 / CQS), NOT a sales opportunity.

Six signals (see the CTO framework):
  1. value_add   — do I have a specific, non-obvious helpful answer?
  2. is_asking   — is the author actually seeking input?
  3. visibility  — fresh + uncrowded? (early comment = upvotes = CQS) [from triage]
  4. thread health — implicit in visibility + safety
  5. sub_fit     — on-topic for the subreddit?
  6. safe        — not political/drama/unwelcome, no promo bait

Composite → EngagementScore + verdict (engage | skip) + the angle (the helpful
point to make, with NO product mention). LLM path + offline heuristic fallback.
"""

from __future__ import annotations

import re

from ..models import Engagement, Lead
from ..triage import visibility_multiplier
from .base import BaseAgent

ENGAGE_MIN = 55          # composite threshold to recommend engaging
MIN_VALUE_ADD = 40       # below this, don't comment (nothing useful to say)

_ASK_MARKERS = [
    "how do", "how do you", "how can", "anyone", "looking for", "recommend",
    "struggling", "any tips", "advice", "suggestions", "should i", "need help",
    "does anyone", "what do you", "help me", "any tool", "?",
]
_UNSAFE_MARKERS = [
    "politic", "election", "trump", "biden", "religion", "nsfw", "onlyfans",
    "racist", "gender war", "vaccine", "abortion",
]


class EngagementAgent(BaseAgent):
    role = "engagement"

    def run(self, lead: Lead) -> Lead:
        eng = self._llm_score(lead) if self.uses_llm else None
        if eng is None:
            eng = self._heuristic(lead)
        self._finalize(eng, lead)
        lead.engagement = eng
        return lead

    # ── composite scoring + verdict ───────────────────────────────────
    def _finalize(self, eng: Engagement, lead: Lead) -> None:
        vis = visibility_multiplier(lead.post.created_utc, lead.post.num_comments)
        base = 0.6 * eng.value_add + 0.4 * eng.sub_fit
        eng.score = max(0, min(100, round(base * vis)))
        blocked = (not eng.is_asking) or (not eng.safe) or (eng.value_add < MIN_VALUE_ADD)
        if blocked:
            eng.score = min(eng.score, 25)
            eng.verdict = "skip"
            if not eng.is_asking:
                eng.reasons.append("author isn't seeking input")
            if not eng.safe:
                eng.reasons.append("unsafe/unwelcome context")
            if eng.value_add < MIN_VALUE_ADD:
                eng.reasons.append("nothing specific/useful to add")
        else:
            eng.verdict = "engage" if eng.score >= ENGAGE_MIN else "skip"

    # ── LLM ────────────────────────────────────────────────────────────
    def _llm_score(self, lead: Lead):
        system = (
            "You decide whether commenting on a Reddit post would be a GENUINELY "
            "helpful contribution that builds account reputation — not a sales "
            "opportunity. Be honest: only recommend engaging where you can add "
            "specific, non-obvious value the thread doesn't already have.\n"
            "Your background/expertise: " + self._campaign_brief()
        )
        user = (
            f"Post from r/{lead.post.subreddit}:\n"
            f"Title: {lead.post.title}\n"
            f"Body: {lead.post.selftext[:1200]}\n\n"
            "Return JSON: value_add (0-100, do you have a specific non-obvious "
            "helpful answer?), is_asking (bool, is the author seeking input?), "
            "sub_fit (0-100, on-topic for this subreddit?), safe (bool, not "
            "political/drama/unwelcome and not a promo-bait trap), angle (one "
            "sentence: the helpful point you'd make — NO product mention)."
        )
        data = self.llm.json_complete(system, user)
        if not data:
            return None
        try:
            return Engagement(
                value_add=int(data.get("value_add", 0) or 0),
                is_asking=bool(data.get("is_asking", False)),
                sub_fit=int(data.get("sub_fit", 0) or 0),
                safe=bool(data.get("safe", True)),
                angle=str(data.get("angle", ""))[:200],
            )
        except (ValueError, TypeError):
            return None

    # ── heuristic fallback ─────────────────────────────────────────────
    def _heuristic(self, lead: Lead) -> Engagement:
        text = f"{lead.post.title}\n{lead.post.selftext}".lower()
        is_asking = any(m in text for m in _ASK_MARKERS)
        safe = not any(m in text for m in _UNSAFE_MARKERS)

        # value_add: overlap with our domain keywords
        hits = 0
        for kw in self.campaign.keywords:
            toks = [t for t in re.findall(r"\w+", kw.lower()) if len(t) > 2]
            if toks and sum(1 for t in toks if t in text) / len(toks) >= 0.5:
                hits += 1
        value_add = min(90, 40 + hits * 20) if is_asking else max(0, 20 + hits * 15)

        sub_fit = 70 if lead.post.subreddit.lower() in {
            s.lower() for s in (self.campaign.feed_subreddits + self.campaign.subreddits)
        } else 45

        pain = ""
        if lead.qualification and lead.qualification.pain_points:
            pain = lead.qualification.pain_points[0]
        angle = (f"share what worked for the '{pain[:60]}' problem" if pain
                 else "share concrete experience answering the question")
        return Engagement(value_add=value_add, is_asking=is_asking, sub_fit=sub_fit,
                          safe=safe, angle=angle)
