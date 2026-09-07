# -*- coding: utf-8 -*-
"""ReplyWriterAgent — writes a natural follow-up when someone replies to us.

Holding a short back-and-forth is the most human, most karma-positive thing a
warm-up account can do. Given our original comment and the reply we got, this
writes one genuine follow-up in the account's persona voice: acknowledge, add a
little more value or answer their question, no product, no links, no em-dash.

Kept short on purpose. Real follow-ups are a sentence or two, not an essay.
"""

from __future__ import annotations

from ..humanize import humanize
from ..models import Draft
from ..personas import Persona
from .base import BaseAgent


class ReplyWriterAgent(BaseAgent):
    role = "reply_writer"

    def __init__(self, campaign, reddit=None, llm=None):
        super().__init__(campaign, llm)
        self.reddit = reddit

    def run(self, *, thread_title: str, our_comment: str, reply_author: str,
            reply_body: str, persona: Persona = None) -> Draft:
        draft = (self._write(thread_title, our_comment, reply_author, reply_body, persona)
                 if self.uses_llm else None)
        if draft is None:
            draft = self._heuristic(reply_body)
        casual = persona.casual if persona else True
        rate = persona.typo_rate if persona else 0.2
        if not getattr(self.campaign, "humanize_comments", True):
            casual, rate = False, 0.0
        draft.body = humanize(draft.body, casual=casual, typo_rate=rate)
        return draft

    def _write(self, thread_title, our_comment, reply_author, reply_body, persona):
        voice = persona.voice if persona else "a helpful peer"
        pstyle = persona.style if persona else "casual and direct"
        system = (
            f"You are {voice} continuing a Reddit conversation you started. Someone "
            "replied to your comment; write ONE short, natural follow-up.\n"
            "Hard rules:\n"
            "- NEVER use an em-dash (—). Use commas or periods.\n"
            "- NO product/tool/company mention, NO links, no self-promotion.\n"
            "- 1-3 sentences. Answer their question or add one more useful bit. If "
            "they just thanked you, a brief warm reply is fine.\n"
            "- No AI tells, no wind-up, no summary line.\n"
            f"Your style: {pstyle}. Contractions fine. Sound like a real person."
        )
        user = (
            f"Thread: {thread_title}\n"
            f"Your original comment: {our_comment[:600]}\n"
            f"u/{reply_author} replied: {reply_body[:600]}\n\n"
            "Return JSON: {\"body\": \"your follow-up\"}"
        )
        data = self.llm.json_complete(system, user)
        if not data or not str(data.get("body", "")).strip():
            return None
        return Draft(kind="comment", body=str(data["body"]).strip())

    def _heuristic(self, reply_body: str) -> Draft:
        low = (reply_body or "").lower()
        if any(w in low for w in ("thanks", "thank you", "appreciate", "helpful")):
            body = "np, glad it helped. happy to expand on any of it if useful"
        elif "?" in (reply_body or ""):
            body = ("good question. depends a bit on your setup, but in most cases "
                    "the simple version works before you overthink it. what does yours look like?")
        else:
            body = "yeah exactly. the main thing is just staying consistent with it, that's what made the difference for us"
        return Draft(kind="comment", body=body)
