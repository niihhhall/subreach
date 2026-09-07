# -*- coding: utf-8 -*-
"""Tests for the warm-up ramp + reply-back monitor (offline)."""

import tempfile

from reddit_outreach.config import Campaign, Settings
from reddit_outreach.models import Comment, Lead, RedditPost
from reddit_outreach.humanize import has_em_dash
from reddit_outreach.personas import resolve_persona
from reddit_outreach.pacing import HumanPacer
from reddit_outreach.agents.reply_writer import ReplyWriterAgent
from reddit_outreach.swarm import SwarmRunner, WarmAccount, ramp_cap, find_reply_targets


def _campaign():
    return Campaign(name="t", product="P", value_proposition="v", icp="smb")


def _settings(d):
    return Settings(reddit_backend="mock", llm_provider="mock", data_dir=d, database_url="")


class _FakeReddit:
    def __init__(self, comments):
        self._c = comments

    def read(self, post_id):
        return (None, self._c)


def test_ramp_climbs_with_age():
    assert ramp_cap(15, 0) == 4
    assert ramp_cap(15, 5) == 6
    assert ramp_cap(15, 10) == 10
    assert ramp_cap(15, 30) == 15
    assert ramp_cap(6, 30) == 6            # never exceeds the ceiling


def test_find_reply_targets_prioritizes_direct_replies():
    cs = [
        Comment(id="a", author="me", body="my own comment"),          # ours -> skip
        Comment(id="b", author="op", body="a reply to us", parent_id="c1"),
        Comment(id="c", author="op", body="op re-engaged elsewhere"),
        Comment(id="d", author="rando", body="unrelated chatter"),    # ignore
        Comment(id="e", author="op", body="already answered"),        # answered -> skip
    ]
    targets = find_reply_targets(cs, our_username="me", our_comment_ids={"c1"},
                                 op_author="op", answered_ids={"e"})
    ids = [c.id for c in targets]
    assert ids[0] == "b"                    # direct reply first
    assert "c" in ids
    assert "a" not in ids and "d" not in ids and "e" not in ids


def test_reply_writer_heuristic_is_clean():
    rw = ReplyWriterAgent(_campaign())      # mock llm -> heuristic
    for body in ("thanks so much, super helpful!", "ok but how do i start?",
                 "makes sense i guess"):
        d = rw.run(thread_title="t", our_comment="x", reply_author="op",
                   reply_body=body, persona=resolve_persona("tradesman"))
        assert d.body and not has_em_dash(d.body)


def test_reply_pass_detects_op_reengagement_dryrun():
    with tempfile.TemporaryDirectory() as d:
        runner = SwarmRunner(_campaign(), _settings(d))
        # we previously commented on p1
        runner.store.log_activity("sent", channel="comment", post_id="p1",
                                  account="rid1", ref="c1", status="posted")
        runner.store.upsert(Lead(post=RedditPost(id="p1", title="how do i do X",
                                                 author="op_user",
                                                 subreddit="smallbusiness")))
        runner.store.save()
        acct = WarmAccount("a1", reddit_id="rid1", api_key="k",
                           subreddits=["smallbusiness"])
        fake = _FakeReddit([Comment(id="r1", author="op_user",
                                    body="thanks, but how do i actually start?")])
        res = {"reply_posted": 0, "reply_dryrun": 0, "notes": []}
        n = runner._reply_pass(
            acct=acct, zernio=None, reddit=fake, account_id="acc", username="myuser",
            persona=resolve_persona("operator"), reply_writer=ReplyWriterAgent(_campaign()),
            pacer=HumanPacer(enabled=False), budget=5, confirm=False, res=res)
        runner.close()
        assert n == 1 and res["reply_dryrun"] == 1


class _FakeZernio:
    """Returns replies sitting under a given comment_id (precise Inbox path)."""
    configured = True

    def __init__(self, by_comment):
        self._by = by_comment          # {comment_id: [Comment, ...]}

    def get_post_comments(self, post_id, account_id, *, subreddit="",
                          comment_id="", limit=25):
        return self._by.get(comment_id, [])


def test_reply_pass_precise_path_uses_comment_id_replies():
    with tempfile.TemporaryDirectory() as d:
        runner = SwarmRunner(_campaign(), _settings(d))
        runner.store.log_activity("sent", channel="comment", post_id="p1",
                                  account="rid1", ref="c1", status="posted")
        runner.store.upsert(Lead(post=RedditPost(id="p1", title="how do i do X",
                                                 author="op_user",
                                                 subreddit="smallbusiness")))
        runner.store.save()
        acct = WarmAccount("a1", reddit_id="rid1", api_key="k",
                           subreddits=["smallbusiness"])
        # a reply sitting under OUR comment c1, from a non-OP user (precise match)
        zern = _FakeZernio({"c1": [Comment(id="rr", author="curious_dev",
                                           body="wait how did you automate that?")]})
        res = {"reply_posted": 0, "reply_dryrun": 0, "notes": []}
        n = runner._reply_pass(
            acct=acct, zernio=zern, reddit=_FakeReddit([]), account_id="acc",
            username="myuser", persona=resolve_persona("marketer"),
            reply_writer=ReplyWriterAgent(_campaign()),
            pacer=HumanPacer(enabled=False), budget=5, confirm=False, res=res)
        runner.close()
        assert n == 1 and res["reply_dryrun"] == 1


def test_reply_pass_skips_when_no_prior_comments():
    with tempfile.TemporaryDirectory() as d:
        runner = SwarmRunner(_campaign(), _settings(d))
        acct = WarmAccount("a1", reddit_id="rid1", api_key="k",
                           subreddits=["smallbusiness"])
        res = {"reply_posted": 0, "reply_dryrun": 0, "notes": []}
        n = runner._reply_pass(
            acct=acct, zernio=None, reddit=_FakeReddit([]), account_id="acc",
            username="myuser", persona=resolve_persona("operator"),
            reply_writer=ReplyWriterAgent(_campaign()),
            pacer=HumanPacer(enabled=False), budget=5, confirm=False, res=res)
        runner.close()
        assert n == 0
