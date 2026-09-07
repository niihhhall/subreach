# -*- coding: utf-8 -*-
"""Tests for the read-only FastAPI dashboard (offline, via TestClient).

Covers the security gate (unset / wrong / valid token + cookie) and that each
page renders seeded store data without touching the network.
"""

import os

import pytest
from fastapi.testclient import TestClient

from reddit_outreach import web
from reddit_outreach.store import LeadStore
from reddit_outreach.models import (
    Lead, RedditPost, Qualification, Draft, Compliance, Engagement,
    CommentQuality, DMQuality, Stage,
)

CAMPAIGN_YAML = """\
name: Test Campaign
product: A test product.
value_proposition: It helps.
icp: small business owners
feed_subreddits:
  - smallbusiness
"""


def _seed_store(data_dir):
    s = LeadStore(data_dir, "Test Campaign")
    # an approved lead (shows in leads + queue)
    lead = Lead(post=RedditPost(id="p1", title="need help with leads",
                                subreddit="smallbusiness", author="alice",
                                num_comments=3, created_utc=0.0))
    lead.qualification = Qualification(fit_score=90, intent_score=80,
                                       pain_points=["missing calls"])
    lead.draft = Draft(kind="comment", body="here is a genuinely helpful reply")
    lead.compliance = Compliance(verdict="approved")
    lead.stage = Stage.APPROVED.value
    s.upsert(lead)

    # an engagement lead (shows in engagement page)
    eng = Lead(post=RedditPost(id="p2", title="how do you handle after-hours?",
                               subreddit="Entrepreneur", author="bob",
                               num_comments=1, created_utc=0.0))
    eng.qualification = Qualification(fit_score=70, intent_score=60)
    eng.engagement = Engagement(score=82, value_add=80, sub_fit=85,
                                verdict="engage", angle="share a workflow tip")
    eng.draft = Draft(kind="comment", body="a helpful non-promo comment")
    eng.comment_quality = CommentQuality(helpful=88, human=90, verdict="ready")
    eng.stage = Stage.QUALIFIED.value
    s.upsert(eng)

    # a DM-drafted lead (Phase 3) + a handoff (Phase 4)
    dm = Lead(post=RedditPost(id="p4", title="ads leads going cold overnight",
                              subreddit="PPC", author="dana", num_comments=0))
    dm.qualification = Qualification(fit_score=85, intent_score=80, is_prospect=True,
                                     pain_points=["after-hours leads"])
    dm.draft = Draft(kind="dm", body="Saw your post about after-hours leads...")
    dm.dm_quality = DMQuality(personal=80, non_spammy=75, has_optout=True, verdict="ready")
    dm.stage = Stage.QUALIFIED.value
    s.upsert(dm)
    s.log_activity("handoff", channel="webhook", post_id="p1", author="alice",
                   status="sent", detail="handoff accepted (200)")

    # account + activity + reputation + health
    s.record_account("acc1", "reddit", "tester", "prof1")
    s.log_activity("run", detail="cycle done")
    s.record_reputation(account="acc1", comment_karma=100, link_karma=20)
    s.record_reputation(account="acc1", comment_karma=110, link_karma=25)
    s.record_health_snapshot(account="acc1", username="tester", score=95,
                             status="healthy", shadowbanned=0,
                             signals={"comment_karma": 110, "link_karma": 25,
                                      "account_age_days": 30})
    s.record_scouted_subreddit(subreddit="solar", vertical="home-services",
                               relevance=88, active=True, sample_count=5)
    s.save()
    s.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)
    (tmp_path / "campaigns").mkdir()
    (tmp_path / "campaigns" / "test.yaml").write_text(CAMPAIGN_YAML, encoding="utf-8")
    _seed_store(data_dir)

    monkeypatch.chdir(tmp_path)                 # so campaigns/*.yaml is discoverable
    monkeypatch.setenv("OUTREACH_DATA_DIR", data_dir)
    monkeypatch.setenv("DATABASE_URL", "")      # force local SQLite
    monkeypatch.setenv("DASHBOARD_TOKEN", "secret")
    return TestClient(app_or_web())


def app_or_web():
    return web.app


def test_liveness_is_unauthenticated(client):
    r = client.get("/health-check")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_setup_notice_when_token_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    c = TestClient(web.app)
    r = c.get("/")
    assert r.status_code == 503
    assert "Setup required" in r.text or "locked" in r.text


def test_wrong_token_is_rejected(client):
    r = client.get("/?token=nope")
    assert r.status_code == 401
    assert "Sign in" in r.text


def test_valid_token_sets_cookie_and_grants_access(client):
    r = client.get("/?token=secret")
    assert r.status_code == 200
    assert "dash_token" in r.headers.get("set-cookie", "")
    # cookie now persisted on the client -> next request needs no query token
    assert client.get("/leads").status_code == 200


@pytest.mark.parametrize("path", ["/", "/leads", "/queue", "/engagement", "/outreach",
                                  "/threads", "/swarm", "/health", "/scout", "/activity"])
def test_pages_render_with_token(client, path):
    r = client.get(path + "?token=secret")
    assert r.status_code == 200
    assert "reddit-outreach" in r.text


def test_leads_page_shows_seeded_lead(client):
    r = client.get("/leads?token=secret")
    assert "need help with leads" in r.text
    assert "smallbusiness" in r.text


def test_queue_shows_approved_draft(client):
    r = client.get("/queue?token=secret")
    assert "genuinely helpful reply" in r.text


def test_engagement_shows_scored_thread(client):
    r = client.get("/engagement?token=secret")
    assert "after-hours" in r.text
    assert "share a workflow tip" in r.text


def test_health_page_shows_account_and_karma(client):
    r = client.get("/health?token=secret")
    assert "tester" in r.text
    assert "Karma trend" in r.text          # two reputation points -> chart renders


def test_scout_page_groups_by_vertical(client):
    r = client.get("/scout?token=secret")
    assert "home-services" in r.text
    assert "solar" in r.text


def test_outreach_page_shows_dm_and_handoff(client):
    r = client.get("/outreach?token=secret")
    assert "dana" in r.text                 # DM draft recipient
    assert "handoff accepted" in r.text      # Phase 4 handoff log entry


def test_swarm_page_lists_roster_accounts(client):
    os.environ["SWARM_ACCOUNTS"] = (
        '{"accounts": [{"label": "swarm-a1", "zernio_reddit_id": "rid1", '
        '"api_key_env": "X", "subreddits": ["smallbusiness"]}]}')
    os.environ["X"] = "sk_fake"
    try:
        r = client.get("/swarm?token=secret")
    finally:
        os.environ.pop("SWARM_ACCOUNTS", None)
        os.environ.pop("X", None)
    assert r.status_code == 200
    assert "swarm-a1" in r.text
