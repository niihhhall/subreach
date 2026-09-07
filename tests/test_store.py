# -*- coding: utf-8 -*-
"""Tests for the SQLite store: leads, activity log, accounts, analytics."""

import tempfile

from reddit_outreach.store import LeadStore
from reddit_outreach.models import Lead, RedditPost, Qualification, Draft, Compliance, Stage


def _lead(post_id, subreddit, author, fit=90, stage=Stage.APPROVED.value):
    lead = Lead(post=RedditPost(id=post_id, title="t", subreddit=subreddit, author=author))
    lead.qualification = Qualification(fit_score=fit, intent_score=fit)
    lead.draft = Draft(kind="comment", body="helpful reply body about the problem here")
    lead.compliance = Compliance(verdict="approved")
    lead.stage = stage
    return lead


def test_leads_persist_and_dedup():
    with tempfile.TemporaryDirectory() as d:
        s = LeadStore(d, "camp")
        s.upsert(_lead("p1", "devops", "alice"))
        s.upsert(_lead("p1", "devops", "alice"))  # dup id — ignored
        s.upsert(_lead("p2", "webdev", "bob"))
        s.save()
        s.close()

        # reopen -> data survived
        s2 = LeadStore(d, "camp")
        assert len(s2.all()) == 2
        funnel = s2.funnel()
        assert funnel.get(Stage.APPROVED.value) == 2
        s2.close()


def test_activity_log_and_sends_analytics():
    with tempfile.TemporaryDirectory() as d:
        s = LeadStore(d, "camp")
        s.log_activity("sent", channel="comment", post_id="p1", subreddit="devops",
                       author="alice", account="me", ref="t1_x", status="posted")
        s.log_activity("sent", channel="dm", post_id="p2", subreddit="webdev",
                       author="bob", account="me", ref="bob", status="posted")
        s.log_activity("sent", channel="comment", post_id="p3", subreddit="devops",
                       author="carol", account="me", ref="", status="error")

        sends = {(r["channel"], r["status"]): r["n"] for r in s.sends_by_channel()}
        assert sends[("comment", "posted")] == 1
        assert sends[("dm", "posted")] == 1
        assert sends[("comment", "error")] == 1

        recent = s.recent_activities(limit=10)
        assert len(recent) == 3

        authors = s.top_authors_contacted()
        names = {a["author"] for a in authors}
        assert {"alice", "bob", "carol"} <= names
        s.close()


def test_subreddit_breakdown_and_accounts():
    with tempfile.TemporaryDirectory() as d:
        s = LeadStore(d, "camp")
        a = _lead("p1", "devops", "alice"); a.sent_at = 123.0
        s.upsert(a)
        s.upsert(_lead("p2", "devops", "bob"))
        s.upsert(_lead("p3", "webdev", "carol"))
        s.save()

        breakdown = {r["subreddit"]: r for r in s.subreddit_breakdown()}
        assert breakdown["devops"]["leads"] == 2
        assert breakdown["devops"]["sent"] == 1
        assert breakdown["webdev"]["leads"] == 1

        s.record_account("acc1", "reddit", "myuser", "prof1")
        s.record_account("acc1", "reddit", "myuser", "prof1")  # upsert, no dup
        accts = s.accounts()
        assert len(accts) == 1 and accts[0]["username"] == "myuser"
        s.close()


def test_record_account_coerces_nested_ids():
    # Zernio can return profileId as a nested object; must not crash the bind.
    with tempfile.TemporaryDirectory() as d:
        s = LeadStore(d, "camp")
        s.record_account("acc2", "reddit", "u2", {"_id": "prof-xyz", "name": "P"})
        accts = {a["account_id"]: a for a in s.accounts()}
        assert accts["acc2"]["profile_id"] == "prof-xyz"
        s.close()
