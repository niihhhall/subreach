# -*- coding: utf-8 -*-
"""ComplianceAgent — the guardrail before anything reaches a human reviewer.

Checks the draft against spam / self-promotion / tone rules and Reddit norms:
  * banned/hypey phrases from the campaign
  * self-promotion ratio (value text should dominate the pitch)
  * link and length sanity
  * value-first ordering (product must not appear in the opener)

Verdict is one of: approved | revise | rejected. On "revise" it attempts a
light auto-fix (stripping banned phrases) and re-checks.
"""

from __future__ import annotations

import re

from ..models import Compliance, Lead, Stage
from ..rules import resolve_rule, check_content
from .base import BaseAgent


class ComplianceAgent(BaseAgent):
    role = "compliance"

    def run(self, lead: Lead) -> Lead:
        draft = lead.draft
        comp = Compliance(verdict="approved")
        if draft is None or not draft.body.strip():
            comp.verdict = "rejected"
            comp.issues.append("no draft body to review")
            lead.compliance = comp
            lead.stage = Stage.REJECTED.value
            return lead

        body = draft.body
        lower = body.lower()

        # 1. banned / hypey phrases
        banned_hits = [p for p in self.campaign.disallowed_phrases if p.lower() in lower]
        if banned_hits:
            comp.issues.append(f"contains disallowed phrase(s): {', '.join(banned_hits)}")

        # 2. self-promotion ratio — product/pitch should be the minority
        promo_mentions = lower.count(self.campaign.product.lower()) if self.campaign.product else 0
        promo_mentions += len(re.findall(r"https?://", lower))
        words = max(1, len(body.split()))
        promo_ratio = promo_mentions / (words / 100.0)  # mentions per 100 words
        comp.self_promo_ratio_ok = promo_ratio <= 2.0
        if not comp.self_promo_ratio_ok:
            comp.issues.append("self-promotion too heavy relative to helpful content")

        # 3. value-first ordering — no product mention in the opener
        if draft.opener and self.campaign.product and \
                self.campaign.product.lower() in draft.opener.lower():
            comp.issues.append("opener mentions the product (must be value-first)")

        # 4. length sanity
        if len(body) > 2500:
            comp.issues.append("draft is very long (>2500 chars); trim for Reddit")
        if len(body.split()) < 15:
            comp.issues.append("draft is too short to feel genuine")

        # 5. multiple links look spammy
        if len(re.findall(r"https?://", lower)) > 1:
            comp.issues.append("more than one link reads as spam")

        # 6. per-subreddit rules (strict-by-default floor + config overrides)
        rule = resolve_rule(self.campaign, lead.post.subreddit)
        rule_hits = check_content(rule, body, product=self.campaign.product)
        sub_hard = bool(rule_hits["reject"])
        comp.issues.extend(rule_hits["reject"])
        comp.issues.extend(rule_hits["warn"])

        # decide verdict + attempt light auto-fix for banned phrases
        if banned_hits:
            fixed = body
            for phrase in banned_hits:
                fixed = re.sub(re.escape(phrase), "", fixed, flags=re.IGNORECASE)
            fixed = re.sub(r"\s{2,}", " ", fixed).strip()
            comp.revised_body = fixed
            comp.verdict = "revise"

        hard_fail = ((not comp.self_promo_ratio_ok) or sub_hard
                     or "no draft body to review" in comp.issues)
        if hard_fail:
            comp.verdict = "rejected"
        elif comp.issues and comp.verdict != "revise":
            comp.verdict = "revise"

        lead.compliance = comp
        lead.stage = {
            "approved": Stage.APPROVED.value,
            "revise": Stage.NEEDS_REVISION.value,
            "rejected": Stage.REJECTED.value,
        }[comp.verdict]
        return lead
