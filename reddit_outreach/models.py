# -*- coding: utf-8 -*-
"""Data models for the Reddit outreach pipeline.

A single :class:`Lead` object flows through every stage and accumulates the
output of each agent. This keeps persistence simple (one JSON list) and makes
the pipeline resumable — each stage only fills the fields it owns.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class Stage(str, Enum):
    """Where a lead currently sits in the pipeline."""

    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    RESEARCHED = "researched"
    DRAFTED = "drafted"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    SENT = "sent"
    SKIPPED = "skipped"
    DM_SENT = "dm_sent"          # Phase 3: a cold DM was sent to the author
    HANDED_OFF = "handed_off"    # Phase 4: handed to Markeye for the WhatsApp SDR


@dataclass
class RedditPost:
    """A Reddit post (submission) returned by search or subreddit browsing."""

    id: str
    title: str = ""
    selftext: str = ""
    subreddit: str = ""
    author: str = ""
    url: str = ""
    permalink: str = ""
    score: int = 0
    num_comments: int = 0
    created_utc: float = 0.0

    @property
    def full_url(self) -> str:
        if self.permalink:
            if self.permalink.startswith("http"):
                return self.permalink
            return f"https://www.reddit.com{self.permalink}"
        return self.url or f"https://www.reddit.com/r/{self.subreddit}/comments/{self.id}/"


@dataclass
class Comment:
    """A single comment inside a thread."""

    id: str = ""
    author: str = ""
    body: str = ""
    score: int = 0
    parent_id: str = ""      # id of the comment/post this replies to (when known)


@dataclass
class Qualification:
    """Output of the QualificationAgent."""

    fit_score: int = 0                       # 0-100 ICP fit
    intent_score: int = 0                     # 0-100 buying/need intent
    reasons: List[str] = field(default_factory=list)
    pain_points: List[str] = field(default_factory=list)
    disqualified: bool = False
    disqualify_reason: str = ""
    is_prospect: bool = True                  # author expresses own pain / asks for help
    poster_role: str = "asker"                # asker | advice | vendor | unclear

    @property
    def priority(self) -> int:
        """Combined priority score used to rank the outreach queue."""
        return round((self.fit_score * 0.6) + (self.intent_score * 0.4))


@dataclass
class Research:
    """Output of the ResearchAgent."""

    summary: str = ""
    angle: str = ""                           # the hook to lead with
    top_comments: List[Comment] = field(default_factory=list)
    author_context: str = ""


@dataclass
class Engagement:
    """Output of the EngagementAgent — is this thread worth a genuine,
    reputation-building comment (Phase 2 / CQS), NOT a sales opportunity."""

    score: int = 0                            # 0-100 composite engagement-worthiness
    value_add: int = 0                        # 0-100 can I add a specific, non-obvious help
    is_asking: bool = False                   # is the author seeking input?
    sub_fit: int = 0                          # 0-100 on-topic for the subreddit
    safe: bool = True                         # not political/drama/unwelcome
    verdict: str = "skip"                     # engage | skip
    angle: str = ""                           # the helpful point to make (no product)
    reasons: List[str] = field(default_factory=list)


@dataclass
class Draft:
    """Output of the PersonalizationAgent."""

    kind: str = "comment"                     # "comment" | "dm"
    body: str = ""
    opener: str = ""
    value: str = ""
    soft_cta: str = ""


@dataclass
class CommentQuality:
    """Output of the CommentWriterAgent's self-critique — is this engagement
    comment genuinely helpful, human, non-redundant, and mod-safe to post?"""

    helpful: int = 0                          # 0-100 does it add real value
    human: int = 0                            # 0-100 authentic, not AI-sounding
    non_redundant: bool = True                # not repeating existing comments
    mod_safe: bool = True                     # no promo/links, on-topic, won't be removed
    verdict: str = "draft"                    # ready | needs_revision
    issues: List[str] = field(default_factory=list)


@dataclass
class DMQuality:
    """Output of the DMOutreachAgent's self-critique (Phase 3) — is this cold
    DM personal, non-spammy, and low-pressure enough to send without burning
    the account or annoying the recipient?"""

    personal: int = 0                         # 0-100 references their specific post/pain
    non_spammy: int = 0                       # 0-100 not templated/salesy
    has_optout: bool = True                   # gives an easy, no-pressure out
    verdict: str = "draft"                    # ready | needs_revision
    issues: List[str] = field(default_factory=list)


@dataclass
class Compliance:
    """Output of the ComplianceAgent."""

    verdict: str = "pending"                  # approved | revise | rejected
    issues: List[str] = field(default_factory=list)
    self_promo_ratio_ok: bool = True
    revised_body: str = ""


@dataclass
class Lead:
    """A prospect flowing through the pipeline, accumulating agent output."""

    post: RedditPost
    source_query: str = ""
    stage: str = Stage.DISCOVERED.value
    discovered_at: float = field(default_factory=time.time)

    qualification: Optional[Qualification] = None
    research: Optional[Research] = None
    draft: Optional[Draft] = None
    compliance: Optional[Compliance] = None
    engagement: Optional[Engagement] = None
    comment_quality: Optional[CommentQuality] = None
    dm_quality: Optional[DMQuality] = None    # Phase 3 DM self-critique

    sent_at: float = 0.0                      # set when the user marks it sent
    sent_ref: str = ""                        # e.g. Zernio post id or "manual"
    notes: List[str] = field(default_factory=list)

    # ── serialization ────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Lead":
        post = RedditPost(**data["post"])
        qual = Qualification(**data["qualification"]) if data.get("qualification") else None
        research = None
        if data.get("research"):
            r = dict(data["research"])
            r["top_comments"] = [Comment(**c) for c in r.get("top_comments", [])]
            research = Research(**r)
        draft = Draft(**data["draft"]) if data.get("draft") else None
        comp = Compliance(**data["compliance"]) if data.get("compliance") else None
        eng = Engagement(**data["engagement"]) if data.get("engagement") else None
        cq = CommentQuality(**data["comment_quality"]) if data.get("comment_quality") else None
        dq = DMQuality(**data["dm_quality"]) if data.get("dm_quality") else None
        return cls(
            post=post,
            source_query=data.get("source_query", ""),
            stage=data.get("stage", Stage.DISCOVERED.value),
            discovered_at=data.get("discovered_at", time.time()),
            qualification=qual,
            research=research,
            draft=draft,
            compliance=comp,
            engagement=eng,
            comment_quality=cq,
            dm_quality=dq,
            sent_at=data.get("sent_at", 0.0),
            sent_ref=data.get("sent_ref", ""),
            notes=data.get("notes", []),
        )
