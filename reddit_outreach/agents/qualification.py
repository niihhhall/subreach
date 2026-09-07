# -*- coding: utf-8 -*-
"""QualificationAgent — scores each lead for ICP fit and intent.

LLM path: asks the model to score fit/intent and extract pain points.
Heuristic path: keyword/intent-signal overlap scoring so it works offline.
Leads below ``campaign.min_fit_score`` are marked disqualified.
"""

from __future__ import annotations

import re

from ..models import Lead, Qualification, Stage
from .base import BaseAgent

# words that signal an active problem / buying intent
_INTENT_SIGNALS = [
    "how do", "how do you", "looking for", "recommend", "recommendation",
    "struggling", "problem", "pain", "frustrat", "any tool", "alternative",
    "best way", "help", "advice", "suggestions", "anyone use", "worth it",
    "vs ", "should i", "need a", "we're trying",
]


class QualificationAgent(BaseAgent):
    role = "qualification"

    def run(self, lead: Lead) -> Lead:
        if self.uses_llm:
            qual = self._llm_qualify(lead)
        else:
            qual = None
        if qual is None:
            qual = self._heuristic(lead)

        # Non-prospects (advice-givers, vendors, thought-pieces) are not leads,
        # no matter how on-topic — filter them out first.
        if not qual.is_prospect:
            qual.disqualified = True
            qual.disqualify_reason = (
                f"not a prospect (role={qual.poster_role or 'advice/vendor'}) — author is "
                f"discussing/advising, not expressing their own need"
            )
        elif qual.fit_score < self.campaign.min_fit_score:
            qual.disqualified = True
            qual.disqualify_reason = (
                f"fit score {qual.fit_score} below threshold {self.campaign.min_fit_score}"
            )
        lead.qualification = qual
        lead.stage = Stage.DISQUALIFIED.value if qual.disqualified else Stage.QUALIFIED.value
        return lead

    # ── LLM ───────────────────────────────────────────────────────────
    def _llm_qualify(self, lead: Lead):
        system = (
            "You are a B2B lead qualification analyst evaluating whether a Reddit "
            "post represents a good outreach target for a product.\n"
            + self._campaign_brief()
        )
        user = (
            f"Reddit post from r/{lead.post.subreddit} by u/{lead.post.author}:\n"
            f"Title: {lead.post.title}\n"
            f"Body: {lead.post.selftext[:1500]}\n\n"
            "Score this lead. Return JSON with keys: "
            "fit_score (0-100 how well the author matches the ICP), "
            "intent_score (0-100 how actively they express a related need), "
            "reasons (list of short strings), "
            "pain_points (list of short strings), "
            "poster_role (one of: 'asker' = describing THEIR OWN problem or asking "
            "for help; 'advice' = giving tips / sharing a lesson / thought-piece; "
            "'vendor' = promoting their own product/service; 'unclear'), "
            "is_prospect (true ONLY if the author is expressing their own unmet need "
            "and could plausibly buy a solution — false for advice-givers, vendors, "
            "and general discussion)."
        )
        data = self.llm.json_complete(system, user)
        if not data:
            return None
        try:
            role = str(data.get("poster_role", "asker")).lower().strip() or "asker"
            is_prospect = data.get("is_prospect")
            if is_prospect is None:
                is_prospect = role == "asker"
            return Qualification(
                fit_score=int(data.get("fit_score", 0)),
                intent_score=int(data.get("intent_score", 0)),
                reasons=[str(r) for r in data.get("reasons", [])][:5],
                pain_points=[str(p) for p in data.get("pain_points", [])][:5],
                is_prospect=bool(is_prospect),
                poster_role=role,
            )
        except (ValueError, TypeError):
            return None

    # ── heuristic fallback ────────────────────────────────────────────
    def _heuristic(self, lead: Lead) -> Qualification:
        text = f"{lead.post.title}\n{lead.post.selftext}".lower()

        # fit: token-overlap per keyword (exact-phrase match is far too strict
        # for natural post text) + a bonus for posting in a target subreddit.
        kw_score = 0.0
        matched_keywords = 0
        for kw in self.campaign.keywords:
            tokens = [t for t in re.findall(r"\w+", kw.lower()) if len(t) > 2]
            if not tokens:
                continue
            coverage = sum(1 for t in tokens if t in text) / len(tokens)
            if coverage >= 0.5:
                kw_score += 35 * coverage
                matched_keywords += 1
        kw_score = min(100.0, kw_score)
        sub_bonus = 25 if lead.post.subreddit.lower() in {
            s.lower() for s in self.campaign.subreddits
        } else 0
        fit_score = int(min(100, kw_score + sub_bonus))

        # intent: presence of question/need signals + engagement
        intent_hits = sum(1 for sig in _INTENT_SIGNALS if sig in text)
        is_question = "?" in text
        intent_score = min(100, intent_hits * 20 + (15 if is_question else 0))

        reasons = []
        if matched_keywords:
            reasons.append(f"matches {matched_keywords} campaign keyword(s)")
        if sub_bonus:
            reasons.append(f"posted in target subreddit r/{lead.post.subreddit}")
        if intent_hits:
            reasons.append(f"{intent_hits} intent signal(s) detected")
        if not reasons:
            reasons.append("no strong ICP signals found")

        pain_points = self._extract_pain(text)
        role, is_prospect = self._classify_role(text)
        if not is_prospect:
            reasons.append(f"looks like a {role} post, not someone seeking help")
        return Qualification(
            fit_score=fit_score,
            intent_score=intent_score,
            reasons=reasons,
            pain_points=pain_points,
            is_prospect=is_prospect,
            poster_role=role,
        )

    @staticmethod
    def _classify_role(text: str) -> tuple[str, bool]:
        """Heuristically decide if the author is asking for help (a prospect) or
        giving advice / selling (not a prospect)."""
        t = text.lower()
        advice_markers = [
            "here's what", "heres what", "here are", "my advice", "pro tip",
            "protip", "tip:", "lesson", "biggest mistake", "stop doing",
            "you should", "you need to", "the real problem is", "most people",
            "i've helped", "ive helped", "after years", "5 ways", "3 ways",
            "how to ", "guide to", "i built a", "we built a", "check out my",
            "dm me", "i offer", "our service", "i help ",
        ]
        asker_markers = [
            "how do you", "how do i", "anyone", "looking for", "recommend",
            "struggling", "any tool", "advice?", "suggestions", "should i",
            "need a", "need help", "we're trying", "im trying", "i'm trying",
            "does anyone", "what do you", "help me",
        ]
        advice = sum(1 for m in advice_markers if m in t)
        asker = sum(1 for m in asker_markers if m in t)
        is_question = "?" in t
        first_person_need = any(
            p in t for p in ("i need", "we need", "i can't", "i cant", "we can't",
                             "we cant", "my business", "our business", "i keep losing",
                             "we keep losing", "i'm losing", "we're losing")
        )
        if advice > asker and advice >= 2 and not first_person_need:
            return "advice", False
        if asker or is_question or first_person_need:
            return "asker", True
        if advice >= 1:
            return "advice", False
        return "unclear", True  # default to prospect when genuinely ambiguous

    @staticmethod
    def _extract_pain(text: str) -> list[str]:
        pains = []
        for sentence in re.split(r"[.!?\n]", text):
            s = sentence.strip()
            if any(w in s for w in ("struggl", "problem", "drift", "break", "hard", "frustrat", "waste", "slow")):
                if 10 < len(s) < 160:
                    pains.append(s)
        return pains[:3]
