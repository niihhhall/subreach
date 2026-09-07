# -*- coding: utf-8 -*-
"""Tests for the account-health / shadowban defense layer.

Fully offline: the single network seam (``health._reddit_get``) is monkeypatched
so no real reddit.com calls happen. Covers the pure parsers, the pre-send gate,
the circuit breaker, scoring, post-send verification, and the store methods that
back all of it.
"""

import time

import pytest

from reddit_outreach import health
from reddit_outreach.health import (
    HealthMonitor,
    ProfileProbe,
    probe_public_profile,
    verify_comment_visible,
    _collect_comment_ids,
    _status_for,
)
from reddit_outreach.config import Campaign
from reddit_outreach.store import LeadStore
from reddit_outreach.models import Lead, RedditPost, Draft


# ── fixtures / helpers ────────────────────────────────────────────────
@pytest.fixture
def st(tmp_path):
    """A fresh SQLite store, closed on teardown (avoids Windows file locks)."""
    s = LeadStore(str(tmp_path), "camp")
    try:
        yield s
    finally:
        s.close()


def _campaign(**overrides):
    base = dict(name="camp", product="DocSync",
                value_proposition="keeps docs in sync", icp="eng leads")
    base.update(overrides)
    return Campaign(**base)


def _monitor(store, *, campaign_kw=None, username="u", account_id="acct1"):
    return HealthMonitor(_campaign(**(campaign_kw or {})), store,
                         username=username, account_id=account_id)


def _comment_node(cid, author="bob", body="", replies=None):
    node = {"kind": "t1", "data": {"id": cid, "author": author, "body": body}}
    node["data"]["replies"] = {"data": {"children": replies}} if replies else ""
    return node


def _thread_json(children):
    """Shape reddit's /comments/<id>.json returns: [postListing, commentListing]."""
    return [
        {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {"id": "p1"}}]}},
        {"kind": "Listing", "data": {"children": children}},
    ]


def _lead(body="a genuinely helpful and specific reply about the problem"):
    lead = Lead(post=RedditPost(id="p1", title="t", subreddit="devops", author="bob"))
    lead.draft = Draft(kind="comment", body=body)
    return lead


class _Result:
    def __init__(self, ref="", status="posted", ok=True):
        self.ref, self.status, self.ok, self.message = ref, status, ok, ""


# ── pure parsers ──────────────────────────────────────────────────────
def test_collect_comment_ids_recursive():
    children = [
        _comment_node("c1", body="top level", replies=[_comment_node("c2", body="nested")]),
        _comment_node("c3", body="another"),
    ]
    assert {c["id"] for c in _collect_comment_ids(children)} == {"c1", "c2", "c3"}


def test_status_for_thresholds():
    p = ProfileProbe(username="u", ok=True)
    assert _status_for(90, p) == "healthy"
    assert _status_for(60, p) == "degraded"
    assert _status_for(30, p) == "at_risk"
    assert _status_for(10, p) == "banned"
    assert _status_for(100, ProfileProbe(username="u", ok=True, shadowbanned=True)) == "banned"


# ── profile probe (monkeypatched network) ─────────────────────────────
def test_probe_shadowban_on_404(monkeypatch):
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (404, None))
    p = probe_public_profile("ghost")
    assert p.ok and p.shadowbanned and "shadowban" in p.note.lower()


def test_probe_suspended(monkeypatch):
    monkeypatch.setattr(health, "_reddit_get",
                        lambda *a, **k: (200, {"data": {"is_suspended": True}}))
    p = probe_public_profile("bad")
    assert p.ok and p.suspended and not p.shadowbanned


def test_probe_healthy_captures_karma_and_age(monkeypatch):
    created = time.time() - 400 * 86400
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (
        200, {"data": {"comment_karma": 500, "link_karma": 50, "created_utc": created}}))
    p = probe_public_profile("good")
    assert p.ok and not p.shadowbanned and not p.suspended
    assert p.comment_karma == 500 and p.link_karma == 50 and p.account_age_days > 300


def test_probe_fails_open_on_403(monkeypatch):
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (403, None))
    p = probe_public_profile("blocked")
    assert p.ok is False and p.shadowbanned is False  # unknown, never a false ban


def test_probe_fails_open_on_network_error(monkeypatch):
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (0, None))
    p = probe_public_profile("x")
    assert p.ok is False and p.shadowbanned is False


# ── comment verification ──────────────────────────────────────────────
def test_verify_visible_by_id(monkeypatch):
    monkeypatch.setattr(health, "_reddit_get",
                        lambda *a, **k: (200, _thread_json([_comment_node("abc", body="hi")])))
    chk = verify_comment_visible("p1", subreddit="devops", comment_id="t1_abc")
    assert chk.ok and chk.visible


def test_verify_visible_by_body_snippet(monkeypatch):
    body = "this exact helpful sentence lives on the thread"
    monkeypatch.setattr(health, "_reddit_get",
                        lambda *a, **k: (200, _thread_json([_comment_node("zzz", body=body)])))
    chk = verify_comment_visible("p1", comment_id="", body_snippet=body)
    assert chk.ok and chk.visible


def test_verify_not_visible(monkeypatch):
    monkeypatch.setattr(health, "_reddit_get",
                        lambda *a, **k: (200, _thread_json([_comment_node("other", body="nope")])))
    chk = verify_comment_visible("p1", comment_id="t1_mine", body_snippet="my missing text")
    assert chk.ok and not chk.visible and "not visible" in chk.note.lower()


def test_verify_fetch_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (0, None))
    chk = verify_comment_visible("p1", comment_id="t1_mine")
    assert chk.ok is False and chk.visible is False  # unknown, not "removed"


# ── pre-send gate ─────────────────────────────────────────────────────
def test_gate_allows_when_fresh(st):
    assert _monitor(st).guard_send(subreddit="devops").allowed


def test_gate_blocks_when_breaker_open(st):
    m = _monitor(st)
    st.trip_breaker(m.key, reason="shadowban", resume_after=time.time() + 3600)
    g = m.guard_send(subreddit="devops")
    assert not g.allowed and "breaker" in g.reason.lower()


def test_gate_auto_resumes_after_cooldown(st):
    m = _monitor(st)
    st.trip_breaker(m.key, reason="removals", resume_after=time.time() - 1)  # elapsed
    assert m.guard_send(subreddit="devops").allowed
    assert not (st.breaker_state(m.key) or {}).get("breaker_tripped")


def test_gate_daily_cap(st):
    m = _monitor(st, campaign_kw={"max_sends_per_day": 2, "warmup_days": 0,
                                  "min_seconds_between_sends": 0})
    for _ in range(2):
        st.log_activity("sent", channel="comment", subreddit="devops", status="posted")
    g = m.guard_send(subreddit="devops")
    assert not g.allowed and "daily send cap" in g.reason.lower()


def test_gate_per_subreddit_cap(st):
    m = _monitor(st, campaign_kw={"max_sends_per_day": 100,
                                  "max_sends_per_subreddit_per_day": 1, "warmup_days": 0})
    st.log_activity("sent", channel="comment", subreddit="devops", status="posted")
    # backdate the send so the pacing gap has elapsed and only the sub cap is in play
    st.conn.execute("UPDATE activities SET ts = ?", (time.time() - 1000,))
    st.conn.commit()
    assert not m.guard_send(subreddit="devops").allowed   # 1/1 in devops -> blocked
    assert m.guard_send(subreddit="webdev").allowed        # different sub is fine


def test_gate_pacing_gap_returns_wait(st):
    m = _monitor(st, campaign_kw={"max_sends_per_day": 100,
                                  "min_seconds_between_sends": 300, "warmup_days": 0})
    st.log_activity("sent", channel="comment", subreddit="devops", status="posted")
    g = m.guard_send(subreddit="devops")
    assert not g.allowed and g.wait_seconds > 0


def test_gate_ignores_errored_sends_in_counts(st):
    m = _monitor(st, campaign_kw={"max_sends_per_day": 1, "warmup_days": 0,
                                  "min_seconds_between_sends": 0})
    st.log_activity("sent", channel="comment", subreddit="devops", status="error")
    assert m.guard_send(subreddit="devops").allowed  # error doesn't count against cap


# ── scoring / probe integration ───────────────────────────────────────
def test_monitor_probe_shadowban_zeroes_and_trips(st, monkeypatch):
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (404, None))
    m = _monitor(st)
    report = m.probe()
    assert report.score == 0 and report.status == "banned"
    assert (st.breaker_state(m.key) or {}).get("breaker_tripped")
    assert st.latest_health(m.key)["score"] == 0  # snapshot persisted


def test_monitor_probe_healthy(st, monkeypatch):
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (
        200, {"data": {"comment_karma": 800, "link_karma": 100,
                       "created_utc": time.time() - 500 * 86400}}))
    report = _monitor(st).probe()
    assert report.status == "healthy" and report.score >= 75


def test_monitor_probe_fail_open_keeps_last_score(st, monkeypatch):
    m = _monitor(st)
    st.record_health_snapshot(account=m.key, username="u", score=70,
                              status="degraded", shadowbanned=0, signals={})
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (0, None))
    report = m.probe()
    assert report.status == "unknown" and report.score == 70
    assert not (st.breaker_state(m.key) or {}).get("breaker_tripped")


def test_monitor_probe_penalizes_removal_rate(st, monkeypatch):
    monkeypatch.setattr(health, "_reddit_get", lambda *a, **k: (
        200, {"data": {"comment_karma": 800, "link_karma": 100,
                       "created_utc": time.time() - 500 * 86400}}))
    m = _monitor(st)
    for _ in range(4):
        st.log_activity("verify", channel="comment", status="removed")
    st.log_activity("verify", channel="comment", status="visible")
    assert m.probe().score < 75  # high removal rate drags it down


# ── post-send verification ────────────────────────────────────────────
def test_verify_after_send_logs_and_trips_on_spike(st, monkeypatch):
    monkeypatch.setattr(health, "_reddit_get",
                        lambda *a, **k: (200, _thread_json([_comment_node("other", body="x")])))
    m = _monitor(st)
    for _ in range(3):
        m.verify_after_send(_lead(body="unique body text that is absent"),
                            _Result(ref="comment:mine"), grace_seconds=0)
    verifs = st.recent_verifications(limit=5)
    assert verifs and all(v["status"] == "removed" for v in verifs)
    assert (st.breaker_state(m.key) or {}).get("breaker_tripped")


def test_verify_after_send_visible_does_not_trip(st, monkeypatch):
    body = "the specific helpful body that will match"
    monkeypatch.setattr(health, "_reddit_get",
                        lambda *a, **k: (200, _thread_json([_comment_node("c", body=body)])))
    m = _monitor(st)
    chk = m.verify_after_send(_lead(body=body), _Result(ref="comment:c"), grace_seconds=0)
    assert chk.visible
    assert not (st.breaker_state(m.key) or {}).get("breaker_tripped")


# ── store health methods ──────────────────────────────────────────────
def test_store_health_snapshot_roundtrip(st):
    st.record_health_snapshot(account="a1", username="u", score=55, status="degraded",
                              shadowbanned=0, signals={"karma": 5}, detail="low karma")
    latest = st.latest_health("a1")
    assert latest["score"] == 55 and latest["signals"]["karma"] == 5
    assert len(st.health_history("a1")) == 1


def test_store_breaker_lifecycle(st):
    assert st.breaker_state("a1") is None
    st.trip_breaker("a1", reason="r", resume_after=time.time() + 10)
    assert st.breaker_state("a1")["breaker_tripped"]
    st.reset_breaker("a1")
    assert not st.breaker_state("a1")["breaker_tripped"]


def test_store_send_counts_and_rate_limits(st):
    st.log_activity("sent", channel="comment", subreddit="devops", status="posted")
    st.log_activity("sent", channel="comment", subreddit="webdev", status="posted")
    st.log_activity("sent", channel="comment", subreddit="devops", status="error")
    assert st.count_sends() == 2  # error excluded
    assert st.count_sends(subreddit="devops") == 1
    assert st.last_send_ts() > 0
    st.log_activity("sent", channel="comment", status="error", detail="429 Rate limited")
    assert st.count_rate_limit_events() == 1
