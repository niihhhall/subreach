# -*- coding: utf-8 -*-
"""Tests for per-account personas + reply-angle selection."""

import random

from reddit_outreach.personas import resolve_persona, choose_angle, ANGLES
from reddit_outreach.humanize import has_em_dash
from reddit_outreach.config import Campaign
from reddit_outreach.models import Lead, RedditPost, Engagement
from reddit_outreach.agents.comment_writer import CommentWriterAgent


def test_resolve_persona_presets_and_default():
    assert resolve_persona("operator").name == "operator"
    assert resolve_persona("MARKETER").name == "marketer"
    assert resolve_persona("tradesman").name == "tradesman"
    assert resolve_persona("nope").name == "default"
    assert resolve_persona("").name == "default"


def test_personas_have_distinct_voice_and_typo_rate():
    op, mk, tr = (resolve_persona("operator"), resolve_persona("marketer"),
                  resolve_persona("tradesman"))
    assert op.voice != mk.voice != tr.voice
    # tradesman is roughest, marketer cleanest
    assert tr.typo_rate > op.typo_rate > mk.typo_rate
    assert mk.casual is False and tr.casual is True


def test_choose_angle_returns_valid_angle():
    op = resolve_persona("operator")
    a = choose_angle(is_asking=False, num_comments=2,
                     text="im burning money and frustrated", persona=op,
                     rng=random.Random(0))
    assert a in ANGLES


def test_marketer_leans_question_on_asking_threads():
    mk = resolve_persona("marketer")
    picks = {choose_angle(is_asking=True, num_comments=1,
                          text="how do you handle leads?", persona=mk,
                          rng=random.Random(i)) for i in range(25)}
    assert "question" in picks          # marketer's top preference surfaces


def test_tradesman_leans_short_on_crowded_threads():
    tr = resolve_persona("tradesman")
    picks = [choose_angle(is_asking=True, num_comments=90,
                          text="how do i do this", persona=tr,
                          rng=random.Random(i)) for i in range(25)]
    assert picks.count("short") >= 10   # crowded + short-preferring persona


def test_comment_writer_accepts_persona_and_stays_clean():
    camp = Campaign(name="t", product="P", value_proposition="v", icp="smb")
    agent = CommentWriterAgent(camp, reddit=None)      # heuristic path, no network
    lead = Lead(post=RedditPost(id="p1", subreddit="smallbusiness", num_comments=3,
                                title="how do i handle leads after hours?"))
    lead.engagement = Engagement(score=80, is_asking=True, angle="respond fast",
                                 verdict="engage")
    out = agent.run(lead, persona=resolve_persona("tradesman"))
    assert out.draft and out.draft.body
    assert not has_em_dash(out.draft.body)
