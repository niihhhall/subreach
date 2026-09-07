# -*- coding: utf-8 -*-
"""Tests for Phase 4 — Markeye handoff webhook (offline via an injected transport)."""

import hashlib
import hmac
import json
import tempfile

from reddit_outreach.config import Campaign
from reddit_outreach.models import Lead, RedditPost, Qualification, Stage
from reddit_outreach.store import LeadStore
from reddit_outreach.handoff import HandoffClient


def _campaign(**kw):
    base = dict(name="t", product="Markeye", value_proposition="v", icp="smb")
    base.update(kw)
    return Campaign(**base)


def _lead(pid="p1"):
    lead = Lead(post=RedditPost(id=pid, title="need after-hours help",
                                author="alice", subreddit="smallbusiness"))
    lead.qualification = Qualification(fit_score=80, intent_score=70,
                                       pain_points=["missing calls"])
    return lead


def test_handoff_dryrun_without_url():
    with tempfile.TemporaryDirectory() as d:
        store = LeadStore(d, "t")
        r = HandoffClient(_campaign(), store).emit(_lead())
        store.close()
    assert r.ok and r.status == "dry-run"
    assert r.payload["event"] == "lead.handoff"
    assert r.payload["contact"]["username"] == "alice"


def test_handoff_posts_signs_and_is_idempotent():
    calls = []

    def fake_post(url, body, headers, timeout):
        calls.append((url, body, headers))
        return 200, '{"id": "conv_123"}'

    with tempfile.TemporaryDirectory() as d:
        store = LeadStore(d, "t")
        c = _campaign(handoff_webhook_url="https://example.com/hook",
                      handoff_secret="s3cr3t")
        client = HandoffClient(c, store, post_fn=fake_post)
        lead = _lead()
        r = client.emit(lead, whatsapp="+1555", reason="replied yes", confirm=True)

        assert r.ok and r.status == "sent" and r.ref == "conv_123"
        assert lead.stage == Stage.HANDED_OFF.value

        _url, body, headers = calls[0]
        expect = "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
        assert headers["X-Markeye-Signature"] == expect
        assert headers["X-Idempotency-Key"] == "p1"
        payload = json.loads(body.decode("utf-8"))
        assert payload["contact"]["whatsapp"] == "+1555"

        # second emit for the same lead -> duplicate, no second POST
        r2 = client.emit(lead, confirm=True)
        store.close()
    assert r2.status == "duplicate"
    assert len(calls) == 1


def test_handoff_disabled_campaign():
    with tempfile.TemporaryDirectory() as d:
        store = LeadStore(d, "t")
        c = _campaign(handoff_enabled=False, handoff_webhook_url="https://x/y")
        r = HandoffClient(c, store).emit(_lead(), confirm=True)
        store.close()
    assert not r.ok and r.status == "disabled"


def test_handoff_4xx_does_not_retry():
    calls = []

    def fake_post(url, body, headers, timeout):
        calls.append(1)
        return 400, "bad request"

    with tempfile.TemporaryDirectory() as d:
        store = LeadStore(d, "t")
        c = _campaign(handoff_webhook_url="https://x/y")
        r = HandoffClient(c, store, post_fn=fake_post).emit(_lead(), confirm=True)
        store.close()
    assert not r.ok and r.status == "error"
    assert len(calls) == 1        # 4xx (non-429) is not retried
