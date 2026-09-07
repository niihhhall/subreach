# -*- coding: utf-8 -*-
"""Tests for the CommentWriterAgent (offline heuristic path + gates)."""

from reddit_outreach.agents.comment_writer import CommentWriterAgent
from reddit_outreach.reddit_client import RedditClient
from reddit_outreach.config import Campaign
from reddit_outreach.models import Lead, RedditPost, Engagement, Draft, Stage


def _campaign():
    return Campaign(name="c", product="Markeye", value_proposition="v", icp="i")


def _agent():
    # mock backend: reddit.read returns mock comments (existing-comment awareness)
    return CommentWriterAgent(_campaign(), RedditClient("mock"), llm=None)


def _lead(angle="share what worked for after-hours lead response"):
    lead = Lead(post=RedditPost(id="mock1", title="Leads after hours?",
                                selftext="how do you handle it", subreddit="devops"))
    lead.engagement = Engagement(verdict="engage", angle=angle, value_add=70)
    return lead


def test_writes_a_comment_and_quality():
    lead = _lead()
    _agent().run(lead)
    assert lead.draft and lead.draft.kind == "comment" and lead.draft.body
    assert lead.comment_quality is not None
    assert lead.stage in (Stage.DRAFTED.value, Stage.NEEDS_REVISION.value)


def test_heuristic_critique_flags_promo_and_links():
    agent = _agent()
    bad = Draft(kind="comment", body="Check out Markeye at https://markeye.com it's great")
    q = agent._heuristic_critique(bad, existing=[])
    assert q.mod_safe is False and q.verdict == "needs_revision"


def test_heuristic_critique_passes_clean_comment():
    agent = _agent()
    good = Draft(kind="comment", body=(
        "We hit this too. What helped was answering every inbound lead within a "
        "few minutes even after hours, since speed mattered more than anything else."))
    q = agent._heuristic_critique(good, existing=[])
    assert q.mod_safe and q.verdict == "ready"


def test_ai_tells_lower_human_score():
    agent = _agent()
    robotic = Draft(kind="comment", body=(
        "Moreover, it is important to note that in today's landscape you must "
        "furthermore optimize your funnel accordingly."))
    q = agent._heuristic_critique(robotic, existing=[])
    assert q.human < 60 and q.verdict == "needs_revision"
