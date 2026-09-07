# -*- coding: utf-8 -*-
"""Tests for the human-comment brain: em-dashes always die, texture is safe."""

import random

from reddit_outreach.humanize import de_ai, humanize, has_em_dash
from reddit_outreach.config import Campaign
from reddit_outreach.models import Draft
from reddit_outreach.agents.comment_writer import CommentWriterAgent


def test_de_ai_removes_em_and_en_dashes():
    out = de_ai("the fix — a fast response — really helped us")
    assert "—" not in out and "–" not in out
    assert "a fast response" in out


def test_de_ai_strips_ai_phrases_and_recapitalizes():
    out = de_ai("Moreover, this actually works for most shops.")
    assert not out.lower().startswith("moreover")
    assert out.startswith("This")


def test_humanize_never_leaves_em_dash():
    txt = "speed to lead matters — respond fast — and you win more deals"
    out = humanize(txt, casual=True, typo_rate=0.5, rng=random.Random(1))
    assert not has_em_dash(out)


def test_humanize_is_clean_when_disabled():
    txt = "Respond to leads fast and you will win more of them."
    # casual off + no typos => only de_ai applied (which changes nothing here)
    out = humanize(txt, casual=False, typo_rate=0.0, rng=random.Random(0))
    assert out == txt


def test_typo_rate_one_introduces_single_slip():
    txt = "I don't think you're handling this the wrong way honestly"
    out = humanize(txt, casual=False, typo_rate=1.0, rng=random.Random(3))
    # a slip happened (dropped apostrophe or lowercased I), text still readable
    assert out != txt
    assert not has_em_dash(out)


def test_comment_writer_humanize_strips_em_dash():
    camp = Campaign(name="t", product="P", value_proposition="v", icp="smb")
    agent = CommentWriterAgent(camp, reddit=None)      # heuristic path, no network
    draft = Draft(kind="comment", body="do this — then that — it works")
    agent._humanize(draft)
    assert not has_em_dash(draft.body)


def test_comment_writer_respects_disabled_humanize():
    camp = Campaign(name="t", product="P", value_proposition="v", icp="smb",
                    humanize_comments=False, humanize_typo_rate=0.0)
    agent = CommentWriterAgent(camp, reddit=None)
    draft = Draft(kind="comment", body="Great point — here is the fix.")
    agent._humanize(draft)
    assert not has_em_dash(draft.body)                 # em-dash still removed
    assert draft.body[0].isupper()                     # but no casual lowercasing
