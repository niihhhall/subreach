# -*- coding: utf-8 -*-
"""Tests for the EngagementAgent (Phase 2 CQS qualifier) — offline heuristic path."""

import time

from reddit_outreach.agents.engagement import EngagementAgent, ENGAGE_MIN
from reddit_outreach.triage import visibility_multiplier
from reddit_outreach.config import Campaign
from reddit_outreach.models import Lead, RedditPost


def _agent():
    return Campaign(
        name="c", product="Markeye", value_proposition="v",
        icp="businesses running ads losing leads after hours",
        keywords=["leads after hours", "speed to lead", "follow up with leads"],
        feed_subreddits=["smallbusiness"])


def _mk(title, body, subreddit="smallbusiness", age_days=1.0, num_comments=2):
    return Lead(post=RedditPost(
        id="p", title=title, selftext=body, subreddit=subreddit,
        created_utc=time.time() - age_days * 86400, num_comments=num_comments))


def test_visibility_multiplier_prefers_fresh_uncrowded():
    fresh_open = visibility_multiplier(time.time() - 1 * 86400, 2)
    old_crowded = visibility_multiplier(time.time() - 200 * 86400, 60)
    assert fresh_open > old_crowded
    assert 0.0 < old_crowded <= 1.0 and fresh_open <= 1.0


def test_engage_on_fresh_relevant_question():
    agent = EngagementAgent(_agent())
    lead = _mk("How do you handle leads after hours when you're busy?",
               "I run ads and keep missing leads that come in at night. What works?",
               age_days=1, num_comments=2)
    agent.run(lead)
    e = lead.engagement
    assert e.is_asking and e.verdict == "engage" and e.score >= ENGAGE_MIN


def test_skip_when_not_asking():
    agent = EngagementAgent(_agent())
    lead = _mk("Just sharing my monthly revenue milestone screenshot",
               "Hit 10k this month. Feels good.", age_days=1, num_comments=2)
    agent.run(lead)
    assert lead.engagement.verdict == "skip"
    assert not lead.engagement.is_asking


def test_skip_unsafe_context():
    agent = EngagementAgent(_agent())
    lead = _mk("How do you handle leads after hours? Also thoughts on the election?",
               "politics aside, how do you follow up with leads fast?")
    agent.run(lead)
    assert lead.engagement.safe is False and lead.engagement.verdict == "skip"


def test_stale_crowded_downranked():
    agent = EngagementAgent(_agent())
    fresh = _mk("How do you follow up with leads fast?", "need advice on speed to lead",
                age_days=1, num_comments=2)
    stale = _mk("How do you follow up with leads fast?", "need advice on speed to lead",
                age_days=250, num_comments=80)
    agent.run(fresh)
    agent.run(stale)
    assert fresh.engagement.score > stale.engagement.score
