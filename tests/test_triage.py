# -*- coding: utf-8 -*-
"""Tests for lead triage (recency / saturation / sendability) and the
asker-vs-advice-giver classification in qualification. Fully offline."""

import time

from reddit_outreach.triage import (
    triage_lead, age_tag, saturation_tag, post_age_days,
    FRESH_DAYS, RECENT_DAYS,
)
from reddit_outreach.models import Lead, RedditPost, Qualification
from reddit_outreach.agents.qualification import QualificationAgent
from reddit_outreach.config import Campaign


def _lead(*, age_days=1.0, num_comments=2, fit=90, intent=90, is_prospect=True):
    created = time.time() - age_days * 86400
    lead = Lead(post=RedditPost(id="p", title="t", subreddit="smallbusiness",
                                created_utc=created, num_comments=num_comments))
    lead.qualification = Qualification(fit_score=fit, intent_score=intent,
                                       is_prospect=is_prospect)
    return lead


# ── age / saturation tags ─────────────────────────────────────────────
def test_age_tags():
    assert age_tag(-1) == "unknown"
    assert age_tag(3) == "fresh"
    assert age_tag(FRESH_DAYS) == "fresh"
    assert age_tag(20) == "recent"
    assert age_tag(RECENT_DAYS + 1) == "stale"


def test_saturation_tags():
    assert saturation_tag(0) == "open"
    assert saturation_tag(9) == "open"
    assert saturation_tag(15) == "busy"
    assert saturation_tag(40) == "saturated"


def test_post_age_days_unknown_when_no_timestamp():
    assert post_age_days(0) == -1.0


# ── sendability tiers ─────────────────────────────────────────────────
def test_fresh_open_prospect_is_hot():
    t = triage_lead(_lead(age_days=2, num_comments=3, fit=95, intent=95))
    assert t.tier == "hot" and t.score >= 65
    assert "comment now" in t.channel_hint


def test_stale_prospect_is_cold_but_kept():
    # 200d old, modest priority -> heavily discounted but NOT dropped
    t = triage_lead(_lead(age_days=200, num_comments=5, fit=50, intent=50))
    assert t.tier == "cold" and t.score > 0        # kept, not dropped
    assert "old thread" in t.channel_hint


def test_saturated_fresh_routes_to_dm():
    t = triage_lead(_lead(age_days=3, num_comments=40, fit=90, intent=90))
    assert "DM" in t.channel_hint


def test_non_prospect_is_skip_zero():
    t = triage_lead(_lead(is_prospect=False))
    assert t.tier == "skip" and t.score == 0
    assert "not a prospect" in t.channel_hint


def test_recency_downranks_old_over_fresh():
    fresh = triage_lead(_lead(age_days=2, num_comments=3))
    old = triage_lead(_lead(age_days=200, num_comments=3))
    assert fresh.score > old.score


# ── asker vs advice-giver classification ──────────────────────────────
def _agent():
    return QualificationAgent(Campaign(name="c", product="Markeye",
                                       value_proposition="v", icp="i", min_fit_score=40))


def test_classify_asker():
    role, is_prospect = _agent()._classify_role(
        "i run a small business and i keep losing leads after hours. how do you handle this?")
    assert role == "asker" and is_prospect is True


def test_classify_advice_giver():
    role, is_prospect = _agent()._classify_role(
        "here's what i learned after years: the biggest mistake is slow follow up. "
        "pro tip: you should answer fast. most people ignore this.")
    assert role == "advice" and is_prospect is False


def test_qualification_disqualifies_advice_post():
    agent = _agent()
    lead = Lead(post=RedditPost(
        id="a", subreddit="smallbusiness",
        title="Most businesses don't have a marketing problem, they have this",
        selftext=("here's what i learned: the biggest mistake is no follow up system. "
                  "pro tip, you should answer leads fast. most people get this wrong.")))
    agent.run(lead)
    assert lead.qualification.is_prospect is False
    assert lead.stage.endswith("disqualified") or lead.qualification.disqualified
