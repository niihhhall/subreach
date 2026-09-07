# -*- coding: utf-8 -*-
"""DMOutreachAgent — Phase 3: drafts a cold DM to a qualified lead's author.

A DM is the most intrusive (and most ban-prone) move in the whole system, so
this agent optimizes for the opposite of spam:

  1. **Personal** — references the author's specific post/pain, not a template.
  2. **Value-first** — leads with a useful observation, not a pitch.
  3. **Low-pressure** — one soft question + an explicit opt-out line, so it reads
     like a peer reaching out, never a sales blast.
  4. **Self-critiques** (personal / non-spammy / has-optout) and revises once.

Output: a ``Draft`` (kind="dm") + a ``DMQuality`` verdict. Nothing is sent here —
sending is a separate, health-gated + capped step (and OFF unless the campaign
sets ``dm_enabled: true`` and you pass ``--confirm``).
"""

from __future__ import annotations

import re

from ..humanize import de_ai
from ..models import DMQuality, Draft, Lead, Stage
from .base import BaseAgent

READY_PERSONAL = 55
READY_NONSPAM = 60
_SPAM_TELLS = ["buy now", "limited time", "act now", "guaranteed", "cheap",
               "dear sir", "dear friend", "opportunity", "click here", "!!!"]


class DMOutreachAgent(BaseAgent):
    role = "dm_outreach"

    def run(self, lead: Lead) -> Lead:
        draft = self._write(lead) if self.uses_llm else None
        if draft is None:
            draft = self._heuristic(lead)

        draft.body = self._append_footer(draft.body)

        quality = (self._critique(lead, draft) if self.uses_llm
                   else self._heuristic_critique(draft))

        if self.uses_llm and quality.verdict != "ready":
            revised = self._write(lead, fix=quality.issues)
            if revised:
                revised.body = self._append_footer(revised.body)
                rq = self._critique(lead, revised)
                if self._score(rq) >= self._score(quality):
                    draft, quality = revised, rq

        lead.draft = draft
        lead.dm_quality = quality
        lead.stage = (Stage.DRAFTED.value if quality.verdict == "ready"
                      else Stage.NEEDS_REVISION.value)
        return lead

    @staticmethod
    def _score(q: DMQuality) -> int:
        return q.personal + q.non_spammy + (25 if q.has_optout else 0)

    def _append_footer(self, body: str) -> str:
        """Strip AI tells (em-dashes) then append opt-out + optional signature."""
        body = de_ai((body or "").strip())
        opt = (self.campaign.dm_opt_out or "").strip()
        if opt and opt.lower() not in body.lower():
            body = f"{body}\n\n{opt}"
        sig = (self.campaign.dm_signature or "").strip()
        if sig and sig not in body:
            body = f"{body}\n\n{sig}"
        return body

    # ── write ──────────────────────────────────────────────────────────
    def _write(self, lead: Lead, fix=None):
        pains = "; ".join(lead.qualification.pain_points[:3]) if (
            lead.qualification and lead.qualification.pain_points) else ""
        angle = lead.research.angle if lead.research else ""
        system = (
            "You write a SHORT, genuinely personal Reddit direct message from one "
            "peer to another. Hard rules: reference their specific post; lead with "
            "a useful, concrete observation (no pitch in the first two sentences); "
            "at most ONE soft, honest sentence about how you help; end with a single "
            "low-pressure question. 3-5 sentences total. No hype, no links, no "
            "'Dear', no exclamation spam. Sound human. " + self._campaign_brief()
        )
        user = (
            f"Their post title: {lead.post.title}\n"
            f"Their post body: {lead.post.selftext[:600]}\n"
            f"Their pain points: {pains or 'inferred from the post'}\n"
            f"Best angle: {angle}\n\n"
            "Return JSON: {\"body\": \"the DM text\"} — the message only, no subject."
        )
        if fix:
            user += f"\n\nRevise to fix: {'; '.join(fix)}"
        data = self.llm.json_complete(system, user)
        if not data or not str(data.get("body", "")).strip():
            return None
        return Draft(kind="dm", body=str(data["body"]).strip())

    # ── self-critique ───────────────────────────────────────────────────
    def _critique(self, lead: Lead, draft: Draft) -> DMQuality:
        system = (
            "You are a strict reviewer deciding whether a cold Reddit DM is safe "
            "and respectful to send. Reddit bans accounts for spammy DMs."
        )
        user = (
            f"Their post: {lead.post.title}\n"
            f"DM:\n{draft.body}\n\n"
            "Return JSON: personal (0-100 references their specific situation), "
            "non_spammy (0-100 not templated/salesy/hypey), has_optout (bool: gives "
            "an easy no-pressure out), issues (list of short strings)."
        )
        data = self.llm.json_complete(system, user)
        if not data:
            return self._heuristic_critique(draft)
        q = DMQuality(
            personal=int(data.get("personal", 0) or 0),
            non_spammy=int(data.get("non_spammy", 0) or 0),
            has_optout=bool(data.get("has_optout", True)),
            issues=[str(i) for i in data.get("issues", [])][:5],
        )
        self._decide(q)
        return q

    # ── heuristic fallbacks (offline) ────────────────────────────────────
    def _heuristic(self, lead: Lead) -> Draft:
        title = lead.post.title.strip().rstrip("?.!")
        pain = ""
        if lead.qualification and lead.qualification.pain_points:
            pain = lead.qualification.pain_points[0]
        opener = (f"Saw your post about \"{title[:90]}\" and it hit home."
                  if title else "Saw your post and it resonated.")
        value = (
            f"On the \"{pain[:70]}\" part especially, " if pain else "In our experience, "
        ) + ("the thing that moved the needle was getting a fast, consistent first "
             "response to every inbound so nothing goes cold.")
        cta = ("Curious how you're handling that right now — are you doing it "
               "manually or have you automated any of it?")
        body = f"{opener} {value}\n\n{cta}"
        return Draft(kind="dm", body=body)

    def _heuristic_critique(self, draft: Draft) -> DMQuality:
        body = (draft.body or "")
        lower = body.lower()
        has_link = bool(re.search(r"https?://", lower))
        spammy = any(t in lower for t in _SPAM_TELLS) or has_link
        references = bool(re.search(r'"[^"]+"', body)) or "your post" in lower or "saw your" in lower
        opt = (self.campaign.dm_opt_out or "").strip().lower()
        has_optout = bool(opt) and opt[:20] in lower if opt else True
        q = DMQuality(
            personal=65 if references else 35,
            non_spammy=30 if spammy else 70,
            has_optout=has_optout,
        )
        if spammy:
            q.issues.append("spam tell or link present")
        if not references:
            q.issues.append("not clearly personalized to their post")
        self._decide(q)
        return q

    @staticmethod
    def _decide(q: DMQuality) -> None:
        q.verdict = ("ready" if (q.has_optout and q.personal >= READY_PERSONAL
                                 and q.non_spammy >= READY_NONSPAM)
                     else "needs_revision")
