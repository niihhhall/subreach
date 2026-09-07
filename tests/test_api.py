# -*- coding: utf-8 -*-
"""Tests for the read-only JSON API consumed by the Next.js dashboard."""

import os

import pytest
from fastapi.testclient import TestClient

from reddit_outreach import web
from reddit_outreach.store import LeadStore
from reddit_outreach.models import (Lead, RedditPost, Qualification, Draft,
                                    Compliance, Engagement, CommentQuality, Stage)

CAMPAIGN_YAML = ("name: Test Campaign\nproduct: A test product.\n"
                 "value_proposition: helps.\nicp: smb owners\n")


def _seed(data_dir):
    s = LeadStore(data_dir, "Test Campaign")
    lead = Lead(post=RedditPost(id="p1", title="need help with leads",
                                subreddit="smallbusiness", author="alice",
                                num_comments=3, created_utc=0.0))
    lead.qualification = Qualification(fit_score=90, intent_score=80,
                                       pain_points=["missing calls"])
    lead.draft = Draft(kind="comment", body="helpful reply")
    lead.compliance = Compliance(verdict="approved")
    lead.stage = Stage.APPROVED.value
    s.upsert(lead)
    eng = Lead(post=RedditPost(id="p2", title="after hours?", subreddit="Entrepreneur",
                               author="bob", num_comments=1))
    eng.qualification = Qualification(fit_score=70, intent_score=60)
    eng.engagement = Engagement(score=82, verdict="engage", angle="tip")
    eng.comment_quality = CommentQuality(helpful=88, human=90, verdict="ready")
    s.upsert(eng)
    s.record_account("acc1", "reddit", "tester", "prof1")
    s.record_reputation(account="acc1", comment_karma=100, link_karma=20)
    s.record_health_snapshot(account="acc1", username="tester", score=95,
                             status="healthy", shadowbanned=0, signals={})
    s.save()
    s.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir)
    (tmp_path / "campaigns").mkdir()
    (tmp_path / "campaigns" / "t.yaml").write_text(CAMPAIGN_YAML, encoding="utf-8")
    _seed(data_dir)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OUTREACH_DATA_DIR", data_dir)
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("CLIENT_TOKEN", "client-secret")
    return TestClient(web.app)


def test_api_requires_token(client):
    assert client.get("/api/overview").status_code == 401


def test_api_campaigns(client):
    r = client.get("/api/campaigns?token=client-secret")
    assert r.status_code == 200
    assert "Test Campaign" in r.json()["campaigns"]


def test_api_overview(client):
    r = client.get("/api/overview?token=client-secret")
    assert r.status_code == 200
    d = r.json()
    assert d["campaign"] == "Test Campaign"
    assert d["total"] >= 2 and "funnel" in d


def test_api_leads_and_engagement(client):
    leads = client.get("/api/leads?token=client-secret").json()["leads"]
    assert any(l["title"] == "need help with leads" for l in leads)
    eng = client.get("/api/engagement?token=client-secret").json()["items"]
    assert any(e["angle"] == "tip" for e in eng)


def test_api_bearer_header_auth(client):
    r = client.get("/api/overview", headers={"Authorization": "Bearer client-secret"})
    assert r.status_code == 200
