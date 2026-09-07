# -*- coding: utf-8 -*-
"""Tests for the ReputationTracker (offline): karma snapshot, comment outcome
tracking, and the assess()/breaker feedback logic."""

import tempfile

import pytest

from reddit_outreach.reputation import ReputationTracker, REMOVAL_RATE_TRIP
from reddit_outreach.store import LeadStore
from reddit_outreach.config import Campaign
from reddit_outreach.models import Comment


class _FakeReddit:
    """Stands in for a rdt-backed RedditClient."""
    def __init__(self, karma=100, thread_comments=None):
        self._karma = karma
        self._comments = thread_comments or {}

    def account_info(self):
        return {"username": "me", "comment_karma": self._karma, "link_karma": 5,
                "created_utc": 100.0}

    def read(self, post_id):
        return None, self._comments.get(post_id, [])


@pytest.fixture
def st(tmp_path):
    s = LeadStore(str(tmp_path), "camp")
    try:
        yield s
    finally:
        s.close()


def _tracker(store, reddit):
    return ReputationTracker(Campaign(name="camp", product="p", value_proposition="v",
                                      icp="i"), store, reddit, account_id="a1", username="me")


def test_snapshot_records_karma(st):
    t = _tracker(st, _FakeReddit(karma=120))
    snap = t.snapshot()
    assert snap["comment_karma"] == 120
    hist = st.reputation_history("a1")
    assert len(hist) == 1 and hist[0]["comment_karma"] == 120


def test_track_comment_visible_and_removed(st):
    reddit = _FakeReddit(thread_comments={"p1": [Comment(id="c1", author="me", body="hi", score=7)]})
    t = _tracker(st, reddit)
    assert t.track_comment("p1", "c1")["visible"] is True
    assert t.track_comment("p1", "missing")["visible"] is False
    outcomes = st.recent_activities(action="comment_outcome")
    assert len(outcomes) == 2


def test_assess_trips_breaker_on_removal_spike(st):
    t = _tracker(st, _FakeReddit())
    # 3 removed of 4 tracked → above trip threshold
    for _ in range(3):
        st.log_activity("comment_outcome", channel="comment", status="removed", detail="0")
    st.log_activity("comment_outcome", channel="comment", status="visible", detail="2")
    r = t.assess()
    assert r.status == "at_risk" and r.removed == 3
    assert (st.breaker_state("a1") or {}).get("breaker_tripped")


def test_assess_healthy_when_karma_rising(st):
    t = _tracker(st, _FakeReddit())
    st.record_reputation(account="a1", comment_karma=100, link_karma=5)
    st.record_reputation(account="a1", comment_karma=110, link_karma=5)  # newer, higher
    r = t.assess()
    assert r.karma_delta == 10 and r.status == "healthy"
    assert not (st.breaker_state("a1") or {}).get("breaker_tripped")


def test_assess_at_risk_when_karma_drops(st):
    t = _tracker(st, _FakeReddit())
    st.record_reputation(account="a1", comment_karma=100, link_karma=5)
    st.record_reputation(account="a1", comment_karma=92, link_karma=5)  # newer, lower
    r = t.assess()
    assert r.karma_delta == -8 and r.status == "at_risk"
