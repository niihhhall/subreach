# -*- coding: utf-8 -*-
"""CommentWriterAgent — the "brain" that writes a genuine engagement comment.

For a thread the EngagementAgent marked ``engage``, it:
  1. **Reads the existing comments** (via the backend) so the draft adds
     something new instead of repeating what's already said.
  2. **Writes** a helpful, human, sub-matched comment — NO product, NO links.
  3. **Self-critiques** (helpful / human / non-redundant / mod-safe) and
     revises once if it falls short.

Output: a ``Draft`` (kind="comment") + a ``CommentQuality`` verdict. Nothing is
posted here — that's a separate, health-gated step (and held during shadowban).
"""

from __future__ import annotations

import random
import re

from ..humanize import de_ai, humanize, has_em_dash
from ..models import CommentQuality, Draft, Lead, Stage
from ..personas import ANGLE_INSTRUCTIONS, Persona, choose_angle, resolve_persona
from .base import BaseAgent

READY_HELPFUL = 60
READY_HUMAN = 60
_AI_TELLS = ["moreover", "furthermore", "in today's", "in conclusion", "delve",
             "it's important to note", "as an ai", "—"]


class CommentWriterAgent(BaseAgent):
    role = "comment_writer"

    def __init__(self, campaign, reddit, llm=None):
        super().__init__(campaign, llm)
        self.reddit = reddit

    def run(self, lead: Lead, style_history=None, persona: Persona = None) -> Lead:
        existing = self._existing_comments(lead)
        style_history = style_history or []
        persona = persona or resolve_persona("")
        # pick the reply move (direct / question / reframe / short) from the thread
        angle = choose_angle(
            is_asking=(lead.engagement.is_asking if lead.engagement else True),
            num_comments=lead.post.num_comments,
            text=f"{lead.post.title}\n{lead.post.selftext}",
            persona=persona)

        draft = self._write(lead, existing, style_history, persona, angle) \
            if self.uses_llm else None
        if draft is None:
            draft = self._heuristic(lead)
        self._humanize(draft, persona)             # strip em-dashes + human texture
        quality = (self._critique(lead, draft, existing) if self.uses_llm
                   else self._heuristic_critique(draft, existing))

        # one revision pass if the LLM judged it not ready
        if self.uses_llm and quality.verdict != "ready":
            revised = self._write(lead, existing, style_history, persona, angle,
                                  fix=quality.issues)
            if revised:
                self._humanize(revised, persona)
                rq = self._critique(lead, revised, existing)
                if self._score(rq) >= self._score(quality):
                    draft, quality = revised, rq

        lead.draft = draft
        lead.comment_quality = quality
        lead.stage = (Stage.DRAFTED.value if quality.verdict == "ready"
                      else Stage.NEEDS_REVISION.value)
        return lead

    @staticmethod
    def _score(q: CommentQuality) -> int:
        return q.helpful + q.human + (20 if q.non_redundant else 0) + (20 if q.mod_safe else 0)

    def _humanize(self, draft: Draft, persona: Persona = None) -> None:
        """Final pass: em-dashes always removed; casual style + occasional slip.
        Persona overrides the campaign defaults so each account reads distinct.
        Runs before critique so the verdict judges what actually posts."""
        if not (draft and draft.body):
            return
        campaign_casual = getattr(self.campaign, "humanize_comments", True)
        campaign_rate = float(getattr(self.campaign, "humanize_typo_rate", 0.2) or 0.0)
        casual = persona.casual if persona else campaign_casual
        rate = persona.typo_rate if persona else campaign_rate
        if not campaign_casual:          # campaign can hard-disable texture
            casual, rate = False, 0.0
        draft.body = humanize(draft.body, casual=casual, typo_rate=rate)

    # ── read the thread's existing comments (avoid redundancy) ────────
    def _existing_comments(self, lead: Lead, limit: int = 8):
        try:
            _post, comments = self.reddit.read(lead.post.id)
        except Exception:
            return []
        return [c.body.strip() for c in (comments or []) if c.body][:limit]

    # ── write ──────────────────────────────────────────────────────────
    def _write(self, lead: Lead, existing, style_history, persona=None, angle="direct",
               fix=None):
        point = lead.engagement.angle if lead.engagement else ""
        angle_note = ANGLE_INSTRUCTIONS.get(angle, ANGLE_INSTRUCTIONS["direct"])
        voice = persona.voice if persona else "someone who has actually done this"
        pstyle = persona.style if persona else "casual and direct"
        existing_block = "\n".join(f"- {c[:160]}" for c in existing[:6]) or "(none visible)"
        hist_block = "\n".join(f"- {h[:120]}" for h in style_history[:5])
        system = (
            f"You are {voice}, leaving one genuinely helpful Reddit comment to build "
            "a real reputation. Write EXACTLY like that person talks, not like an "
            "essay or an AI.\n"
            "Hard rules:\n"
            "- NEVER use an em-dash (—) or en-dash. Use commas, periods, or start "
            "a new sentence. This is critical.\n"
            "- NO product/tool/company mention, NO links, no self-promotion.\n"
            "- Don't repeat points already made in the existing comments.\n"
            "- No AI tells: no 'Moreover', 'Furthermore', 'It's important to note', "
            "no wind-up intros, no bulleted lists, no summary sentence at the end.\n"
            f"Your writing style: {pstyle}. Contractions are fine (dont, youre, its). "
            "Short sentences, sometimes a fragment. It's okay to sound a little rough, "
            "that's how real people type.\n"
            f"Reply approach for THIS thread: {angle_note}\n"
            f"Match the voice of r/{lead.post.subreddit}."
        )
        user = (
            f"Post title: {lead.post.title}\n"
            f"Post body: {lead.post.selftext[:800]}\n"
            f"Useful point you could make: {point}\n\n"
            f"Existing comments (do not repeat these):\n{existing_block}\n"
        )
        if hist_block:
            user += f"\nYour recent comments (vary your opener/structure from these):\n{hist_block}\n"
        if fix:
            user += f"\nRevise to fix: {'; '.join(fix)}\n"
        user += "\nReturn JSON: {\"body\": \"the comment text\"}"
        data = self.llm.json_complete(system, user)
        if not data or not str(data.get("body", "")).strip():
            return None
        return Draft(kind="comment", body=str(data["body"]).strip())

    # ── self-critique ───────────────────────────────────────────────────
    def _critique(self, lead: Lead, draft: Draft, existing) -> CommentQuality:
        existing_block = "\n".join(f"- {c[:160]}" for c in existing[:6]) or "(none)"
        system = (
            "You are a strict Reddit moderator + editor. Judge whether this comment "
            "should be posted from a reputation-building account."
        )
        user = (
            f"Subreddit: r/{lead.post.subreddit}\n"
            f"Comment:\n{draft.body}\n\n"
            f"Existing comments:\n{existing_block}\n\n"
            "Return JSON: helpful (0-100), human (0-100 authentic not AI), "
            "non_redundant (bool vs existing), mod_safe (bool: no promo/links, "
            "on-topic, wouldn't be removed), issues (list of short strings)."
        )
        data = self.llm.json_complete(system, user)
        if not data:
            return self._heuristic_critique(draft, existing)
        q = CommentQuality(
            helpful=int(data.get("helpful", 0) or 0),
            human=int(data.get("human", 0) or 0),
            non_redundant=bool(data.get("non_redundant", True)),
            mod_safe=bool(data.get("mod_safe", True)),
            issues=[str(i) for i in data.get("issues", [])][:5],
        )
        self._decide(q)
        return q

    # ── heuristic fallbacks (offline) ────────────────────────────────────
    def _heuristic(self, lead: Lead) -> Draft:
        angle = (lead.engagement.angle if lead.engagement else "") or \
            "share what actually worked when we hit this"
        body = (f"Been through this. {angle.capitalize()}. "
                "Happy to go deeper if it helps.")
        return Draft(kind="comment", body=body)

    def _heuristic_critique(self, draft: Draft, existing) -> CommentQuality:
        body = draft.body or ""
        lower = body.lower()
        has_link = bool(re.search(r"https?://", lower))
        promo = self.campaign.product and self.campaign.product.lower() in lower
        mod_safe = not has_link and not promo
        human = 40 if any(t in lower for t in _AI_TELLS) else 70
        helpful = 60 if len(body.split()) >= 12 else 35
        non_redundant = not any(body.strip()[:40].lower() in (e.lower()) for e in existing)
        q = CommentQuality(helpful=helpful, human=human, non_redundant=non_redundant,
                           mod_safe=mod_safe)
        if not mod_safe:
            q.issues.append("contains link or product mention")
        self._decide(q)
        return q

    @staticmethod
    def _decide(q: CommentQuality) -> None:
        q.verdict = ("ready" if (q.mod_safe and q.non_redundant
                                 and q.helpful >= READY_HELPFUL and q.human >= READY_HUMAN)
                     else "needs_revision")
