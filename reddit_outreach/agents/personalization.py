# -*- coding: utf-8 -*-
"""PersonalizationAgent — drafts a value-first reply or DM.

Structure enforced: lead with a genuinely useful point (the researched angle),
then optionally a soft, transparent mention of the product. Never opens with a
pitch. The signature (with disclosure) is appended if the campaign sets one.
"""

from __future__ import annotations

from ..models import Draft, Lead, Stage
from ..rules import resolve_rule
from .base import BaseAgent


class PersonalizationAgent(BaseAgent):
    role = "personalization"

    def run(self, lead: Lead) -> Lead:
        # Respect the subreddit's rules while drafting: where self-promotion is
        # banned, write a purely helpful reply with NO product mention (so it
        # passes compliance and doesn't get removed). Only mention the product
        # where the sub allows it.
        rule = resolve_rule(self.campaign, lead.post.subreddit)
        allow_promo = rule.allow_self_promo

        if self.uses_llm:
            draft = self._llm_draft(lead, allow_promo)
        else:
            draft = None
        if draft is None:
            draft = self._heuristic(lead, allow_promo)

        # append the disclosure signature ONLY where self-promo is allowed
        if allow_promo and self.campaign.signature \
                and self.campaign.signature not in draft.body:
            draft.body = f"{draft.body}\n\n{self.campaign.signature}"

        lead.draft = draft
        lead.stage = Stage.DRAFTED.value
        return lead

    def _llm_draft(self, lead: Lead, allow_promo: bool):
        angle = lead.research.angle if lead.research else ""
        summary = lead.research.summary if lead.research else ""
        if allow_promo:
            promo_rule = (
                "The first paragraph must help the author with NO product mention. "
                "Only after that may you add ONE soft, honest sentence about the "
                "product, and only if genuinely relevant."
            )
        else:
            promo_rule = (
                "IMPORTANT: this subreddit forbids self-promotion. Do NOT mention any "
                "product, tool, company, or link anywhere. Write a purely helpful reply "
                "and END with one genuine, low-pressure question about how they "
                "currently handle the problem. soft_cta MUST be empty."
            )
        system = (
            "You write Reddit outreach that redditors actually appreciate: helpful "
            "first, human, never spammy. " + promo_rule + " Match the tone: "
            + self.campaign.tone + ".\n" + self._campaign_brief()
        )
        user = (
            f"Post title: {lead.post.title}\n"
            f"Author need: {summary}\n"
            f"Best angle: {angle}\n"
            f"Outreach kind: {self.campaign.outreach_kind}\n"
            f"Self-promotion allowed here: {'yes' if allow_promo else 'NO'}\n\n"
            "Return JSON with keys: opener (the helpful first paragraph, no product), "
            "value (the useful substance), soft_cta (one soft line if promo allowed, "
            "else empty), body (the full message combining the above naturally)."
        )
        data = self.llm.json_complete(system, user)
        if not data:
            return None
        return Draft(
            kind=self.campaign.outreach_kind,
            opener=str(data.get("opener", "")),
            value=str(data.get("value", "")),
            soft_cta=str(data.get("soft_cta", "")),
            body=str(data.get("body", "")).strip(),
        )

    def _heuristic(self, lead: Lead, allow_promo: bool = True) -> Draft:
        title = lead.post.title.strip().rstrip("?.")
        pain = ""
        if lead.qualification and lead.qualification.pain_points:
            pain = lead.qualification.pain_points[0]

        opener = (
            f"Hit this exact wall with \"{title}\" a while back, so I feel you."
            if title else "Been in this exact spot before."
        )
        value = (
            "What worked for us was treating speed-to-lead as the priority — the leads "
            "you already paid for are worth more than new ones, so anything that gets a "
            "fast, consistent first response (even after hours) usually moves the needle "
            "more than spending more on ads."
        )
        if pain:
            value = (
                f"On the \"{pain[:80]}\" part specifically: the fix that helped us was "
                "making sure every inbound lead got an instant first response and a few "
                "qualifying questions, so nothing goes cold while you're busy or offline."
            )

        if allow_promo:
            close = (
                f"We ended up building {self.campaign.product} around this — happy to "
                "share how it works if useful, but the workflow change matters more than any tool."
            )
        else:
            # pure-value: end with a genuine qualifying question, no product mention
            close = (
                "How are you handling leads that come in after hours or when you're "
                "slammed right now — manual follow-up, a VA, or something automated?"
            )
        body = f"{opener}\n\n{value}\n\n{close}"
        return Draft(
            kind=self.campaign.outreach_kind,
            opener=opener,
            value=value,
            soft_cta=(close if allow_promo else ""),
            body=body,
        )
