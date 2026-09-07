# -*- coding: utf-8 -*-
"""Tests for health-gated engagement comment posting (offline)."""

import tempfile
import time

from reddit_outreach.orchestrator import Orchestrator
from reddit_outreach.config import Campaign, Settings
from reddit_outreach.models import Lead, RedditPost, Draft, Engagement, CommentQuality, Stage


def _ready_lead(pid="p1", sub="devops"):
    lead = Lead(post=RedditPost(id=pid, title="t", subreddit=sub, author="op",
                                created_utc=time.time() - 86400, num_comments=2))
    lead.engagement = Engagement(verdict="engage", score=80, angle="help")
    lead.draft = Draft(kind="comment", body="a genuinely helpful specific comment about the topic")
    lead.comment_quality = CommentQuality(verdict="ready", helpful=80, human=80)
    return lead


def _orch(d):
    campaign = Campaign(name="camp", product="p", value_proposition="v", icp="i",
                        min_seconds_between_sends=0, warmup_days=0)
    settings = Settings(reddit_backend="mock", llm_provider="mock", data_dir=d)
    return Orchestrator(campaign, settings)


def test_dry_run_does_not_post():
    with tempfile.TemporaryDirectory() as d:
        orch = _orch(d)
        posted = {"n": 0}
        orch.reddit.comment = lambda pid, body: posted.update(n=posted["n"] + 1)  # type: ignore
        results = orch.post_engagement_comments([_ready_lead()], budget=3, confirm=False)
        assert posted["n"] == 0
        assert results and results[0][1] == "dry-run"
        orch.close()


def test_confirm_posts_through_gate():
    with tempfile.TemporaryDirectory() as d:
        orch = _orch(d)
        calls = {"comment": []}
        orch.reddit.comment = lambda pid, body: calls["comment"].append((pid, body)) or {"ok": True}  # type: ignore
        # avoid the post-send verify doing a network read
        orch.reddit.read = lambda pid: (None, [])  # type: ignore
        results = orch.post_engagement_comments([_ready_lead()], budget=3, confirm=True)
        assert len(calls["comment"]) == 1
        assert results[0][1] == "posted"

        # the lead is marked sent + a 'sent' activity logged
        sent = orch.store.recent_activities(action="sent")
        assert any(a["channel"] == "comment" for a in sent)
        orch.close()


def test_breaker_blocks_posting():
    with tempfile.TemporaryDirectory() as d:
        orch = _orch(d)
        calls = {"n": 0}
        orch.reddit.comment = lambda pid, body: calls.update(n=calls["n"] + 1)  # type: ignore
        # trip the breaker for the account key (username empty in mock -> 'default')
        orch.store.trip_breaker("default", reason="test", resume_after=time.time() + 3600)
        results = orch.post_engagement_comments([_ready_lead()], budget=3, confirm=True)
        assert calls["n"] == 0                      # nothing posted
        assert results[0][1] == "blocked"
        orch.close()


def test_only_ready_comments_posted():
    with tempfile.TemporaryDirectory() as d:
        orch = _orch(d)
        orch.reddit.comment = lambda pid, body: {"ok": True}  # type: ignore
        orch.reddit.read = lambda pid: (None, [])  # type: ignore
        not_ready = _ready_lead("p2")
        not_ready.comment_quality.verdict = "needs_revision"
        results = orch.post_engagement_comments([not_ready], budget=3, confirm=True)
        assert results == []                        # skipped, not ready
        orch.close()
