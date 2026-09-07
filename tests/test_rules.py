# -*- coding: utf-8 -*-
"""Tests for per-subreddit rule awareness: resolution, content enforcement in
ComplianceAgent, and behavioral enforcement (cap override, auto-bench, karma/age
gates) in the send gate. Fully offline."""

import time

import pytest

from reddit_outreach.config import Campaign
from reddit_outreach.rules import resolve_rule, check_content, should_bench, SubredditRule
from reddit_outreach.store import LeadStore
from reddit_outreach.health import HealthMonitor
from reddit_outreach.agents.compliance import ComplianceAgent
from reddit_outreach.models import Lead, RedditPost, Draft, Stage


@pytest.fixture
def st(tmp_path):
    s = LeadStore(str(tmp_path), "camp")
    try:
        yield s
    finally:
        s.close()


def _campaign(**kw):
    base = dict(name="camp", product="DocSync", value_proposition="v", icp="i")
    base.update(kw)
    return Campaign(**base)


# ── resolution ────────────────────────────────────────────────────────
def test_strict_by_default_floor():
    rule = resolve_rule(_campaign(), "SomeUnknownSub")
    assert rule.source == "default"
    assert rule.allow_links is False and rule.allow_self_promo is False


def test_lenient_default_when_disabled():
    rule = resolve_rule(_campaign(strict_by_default=False), "AnySub")
    assert rule.allow_links is True and rule.allow_self_promo is True


def test_config_override_wins_and_is_case_insensitive():
    c = _campaign(subreddit_rules={"ExperiencedDevs": {"allow_links": False,
                                                       "min_comment_karma": 100,
                                                       "max_sends_per_day": 1}},
                  strict_by_default=False)
    rule = resolve_rule(c, "r/experienceddevs")
    assert rule.source == "config"
    assert rule.allow_links is False           # override tightened the lenient floor
    assert rule.min_comment_karma == 100 and rule.max_sends_per_day == 1


def test_fetched_rules_below_config():
    c = _campaign(subreddit_rules={"devops": {"allow_links": True}})
    rule = resolve_rule(c, "devops", fetched={"allow_links": False, "requires_flair": True})
    assert rule.allow_links is True            # config beats fetched
    assert rule.requires_flair is True         # fetched-only field survives


# ── content checks ────────────────────────────────────────────────────
def test_check_content_rejects_links_and_promo():
    rule = SubredditRule(subreddit="x", allow_links=False, allow_self_promo=False)
    hits = check_content(rule, "great tool, see https://foo.com — try DocSync", product="DocSync")
    assert any("links" in r for r in hits["reject"])
    assert any("self-promotion" in r for r in hits["reject"])


def test_check_content_allows_when_permitted():
    rule = SubredditRule(subreddit="x", allow_links=True, allow_self_promo=True)
    hits = check_content(rule, "here is https://foo.com about DocSync", product="DocSync")
    assert hits["reject"] == []


def test_check_content_flair_is_warn_not_reject():
    rule = SubredditRule(subreddit="x", allow_links=True, allow_self_promo=True,
                         requires_flair=True)
    hits = check_content(rule, "a helpful comment", product="DocSync")
    assert hits["reject"] == [] and any("flair" in w for w in hits["warn"])


def test_should_bench():
    assert should_bench(3, 5, rate=0.5, min_samples=4) is True
    assert should_bench(1, 5, rate=0.5, min_samples=4) is False
    assert should_bench(3, 3, rate=0.5, min_samples=4) is False  # not enough samples


# ── compliance integration ────────────────────────────────────────────
def _drafted_lead(subreddit, body):
    lead = Lead(post=RedditPost(id="p", title="t", subreddit=subreddit))
    lead.draft = Draft(kind="comment", opener="Helpful opener about your workflow issue here.",
                       body=body)
    return lead


def test_compliance_rejects_link_in_strict_sub():
    agent = ComplianceAgent(_campaign())  # strict by default: no links anywhere
    body = ("Here is a genuinely helpful and specific answer to your problem that "
            "should help a good deal. More context at https://example.com/guide")
    lead = _drafted_lead("SomeStrictSub", body)
    agent.run(lead)
    assert lead.stage == Stage.REJECTED.value
    assert any("links are not allowed" in i for i in lead.compliance.issues)


def test_compliance_allows_link_where_config_permits():
    c = _campaign(subreddit_rules={"devops": {"allow_links": True, "allow_self_promo": True}})
    agent = ComplianceAgent(c)
    # long, low-promo body with a single link -> passes the global self-promo ratio,
    # so the only thing that could reject it is the per-sub link rule (which allows links here)
    body = (
        "We hit this exact problem last year and what finally helped was writing a "
        "small contract test that fails the build whenever the response shape drifts "
        "from the documented schema. It caught the mismatches before they ever reached "
        "our integration partners, and it forced the docs and the code to stay honest "
        "with each other over time. A short write-up of how we wired it into CI is here "
        "https://example.com/guide if it is useful to anyone facing the same drift."
    )
    lead = _drafted_lead("devops", body)
    agent.run(lead)
    assert not any("links are not allowed" in i for i in lead.compliance.issues)
    assert lead.stage != Stage.REJECTED.value  # link allowed in this sub


# ── gate integration ──────────────────────────────────────────────────
def _monitor(store, **kw):
    return HealthMonitor(_campaign(**kw), store, username="u", account_id="a1")


def test_gate_auto_benches_high_removal_sub(st):
    m = _monitor(st, min_seconds_between_sends=0)
    # 3 removed of 4 verified in r/spammy -> above default 0.5 rate, >= 4 samples
    for _ in range(3):
        st.log_activity("verify", channel="comment", subreddit="spammy", status="removed")
    st.log_activity("verify", channel="comment", subreddit="spammy", status="visible")
    g = m.guard_send(subreddit="spammy")
    assert not g.allowed and "benched" in g.reason.lower()
    # a clean sub is unaffected
    assert m.guard_send(subreddit="cleanplace").allowed


def test_gate_per_sub_cap_override(st):
    c_kw = {"max_sends_per_day": 100, "min_seconds_between_sends": 0,
            "subreddit_rules": {"strictsub": {"max_sends_per_day": 1}}}
    m = _monitor(st, **c_kw)
    st.log_activity("sent", channel="comment", subreddit="strictsub", status="posted")
    st.conn.execute("UPDATE activities SET ts = ?", (time.time() - 1000,))
    st.conn.commit()
    assert not m.guard_send(subreddit="strictsub").allowed  # 1/1 override cap hit


def test_gate_karma_gate_blocks_when_probe_known(st):
    c_kw = {"min_seconds_between_sends": 0,
            "subreddit_rules": {"prosub": {"min_comment_karma": 100}}}
    m = _monitor(st, **c_kw)
    # a health snapshot with low karma
    st.record_health_snapshot(account=m.key, username="u", score=80, status="healthy",
                              shadowbanned=0, signals={"comment_karma": 5})
    g = m.guard_send(subreddit="prosub")
    assert not g.allowed and "karma" in g.reason.lower()


def test_gate_karma_gate_fails_open_when_probe_unknown(st):
    c_kw = {"min_seconds_between_sends": 0,
            "subreddit_rules": {"prosub": {"min_comment_karma": 100}}}
    m = _monitor(st, **c_kw)
    # no health snapshot at all -> karma unknown -> must NOT block
    assert m.guard_send(subreddit="prosub").allowed


# ── store methods ─────────────────────────────────────────────────────
def test_store_subreddit_removal_stats(st):
    for _ in range(2):
        st.log_activity("verify", channel="comment", subreddit="devops", status="removed")
    st.log_activity("verify", channel="comment", subreddit="devops", status="visible")
    st.log_activity("verify", channel="comment", subreddit="devops", status="unverified")
    removed, total = st.subreddit_removal_stats("devops")
    assert removed == 2 and total == 3  # 'unverified' excluded


def test_store_subreddit_rules_cache_roundtrip(st):
    st.record_subreddit_rules("devops", {"allow_links": True, "rules_text": "no spam"})
    got = st.get_subreddit_rules("r/devops")
    assert got["allow_links"] is True and got["rules_text"] == "no spam"
    assert st.get_subreddit_rules("neverseen") is None
