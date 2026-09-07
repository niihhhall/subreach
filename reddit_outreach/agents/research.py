# -*- coding: utf-8 -*-
"""ResearchAgent — reads the full thread to build context and find an angle.

Pulls the top comments and summarizes what the author actually needs, then
picks the single best "angle" (hook) for a value-first reply. This is what
makes the later draft feel personal instead of templated.
"""

from __future__ import annotations

from ..models import Comment, Lead, Research, Stage
from ..reddit_client import RedditClient, RedditClientError
from .base import BaseAgent


class ResearchAgent(BaseAgent):
    role = "research"

    def __init__(self, campaign, reddit: RedditClient, llm=None):
        super().__init__(campaign, llm)
        self.reddit = reddit

    def run(self, lead: Lead) -> Lead:
        comments: list[Comment] = []
        try:
            _post, comments = self.reddit.read(lead.post.id)
        except RedditClientError as exc:
            lead.notes.append(f"research: could not read thread ({exc})")

        top = sorted(comments, key=lambda c: c.score, reverse=True)[:5]

        if self.uses_llm:
            research = self._llm_research(lead, top)
        else:
            research = None
        if research is None:
            research = self._heuristic(lead, top)

        research.top_comments = top
        lead.research = research
        lead.stage = Stage.RESEARCHED.value
        return lead

    def _llm_research(self, lead: Lead, comments: list[Comment]):
        system = (
            "You research a Reddit thread to prepare a helpful, non-salesy reply.\n"
            + self._campaign_brief()
        )
        comment_block = "\n".join(f"- u/{c.author}: {c.body[:200]}" for c in comments) or "(none)"
        user = (
            f"Thread r/{lead.post.subreddit} — {lead.post.title}\n"
            f"Body: {lead.post.selftext[:1200]}\n"
            f"Top comments:\n{comment_block}\n\n"
            "Return JSON with keys: summary (1-2 sentences on what the author needs), "
            "angle (the single best hook to lead with — a genuinely useful point, "
            "not a pitch), author_context (what we can infer about the author)."
        )
        data = self.llm.json_complete(system, user)
        if not data:
            return None
        return Research(
            summary=str(data.get("summary", "")),
            angle=str(data.get("angle", "")),
            author_context=str(data.get("author_context", "")),
        )

    def _heuristic(self, lead: Lead, comments: list[Comment]) -> Research:
        pains = lead.qualification.pain_points if lead.qualification else []
        summary = pains[0] if pains else (lead.post.title.strip())
        angle = (
            f"Address the core problem in \"{lead.post.title.strip()}\" with a concrete, "
            "experience-based tip before mentioning anything about the product."
        )
        author_context = (
            f"u/{lead.post.author} in r/{lead.post.subreddit}; "
            f"post has {lead.post.score} upvotes and {lead.post.num_comments} comments."
        )
        return Research(summary=summary, angle=angle, author_context=author_context)
