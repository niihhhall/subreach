# -*- coding: utf-8 -*-
"""Tests for Phase 3 — DM outreach (offline: heuristic agent, no network/LLM)."""

import tempfile

from reddit_outreach.config import Campaign, Settings
from reddit_outreach.models import Lead, RedditPost, Qualification, Stage
from reddit_outreach.agents.dm_outreach import DMOutreachAgent
from reddit_outreach.orchestrator import Orchestrator


def _campaign(**kw):
    base = dict(name="t", product="Markeye", value_proposition="v", icp="smb owners")
    base.update(kw)
    return Campaign(**base)


def _lead(pid="p1", author="alice", pri=90):
    lead = Lead(post=RedditPost(id=pid, title="losing leads after hours",
                                author=author, subreddit="smallbusiness",
                                selftext="we keep missing calls when the shop is busy"))
    lead.qualification = Qualification(fit_score=pri, intent_score=pri,
                                       pain_points=["missing calls after hours"],
                                       is_prospect=True)
    lead.stage = Stage.QUALIFIED.value
    return lead


def _settings(d):
    return Settings(reddit_backend="mock", llm_provider="mock", data_dir=d, database_url="")


def test_dm_agent_drafts_personal_dm_with_optout():
    c = _campaign()
    lead = _lead()
    DMOutreachAgent(c).run(lead)              # mock LLM -> heuristic path
    assert lead.draft and lead.draft.kind == "dm"
    assert "ignore this" in lead.draft.body.lower()      # opt-out line appended
    assert lead.dm_quality is not None
    assert lead.dm_quality.verdict in ("ready", "needs_revision")


def test_dm_targets_ranks_prospects_and_excludes_sent():
    with tempfile.TemporaryDirectory() as d:
        orch = Orchestrator(_campaign(), _settings(d))
        orch.store.upsert(_lead("p1", "alice", 90))
        orch.store.upsert(_lead("p2", "bob", 50))
        already = _lead("p3", "carol", 99)
        already.stage = Stage.DM_SENT.value
        orch.store.upsert(already)
        orch.store.save()
        targets = orch.dm_targets(budget=10)
        ids = [l.post.id for l in targets]
        orch.close()
        assert ids == ["p1", "p2"]           # p3 excluded (already DM'd), sorted by priority


def test_dm_send_blocked_when_disabled():
    with tempfile.TemporaryDirectory() as d:
        orch = Orchestrator(_campaign(dm_enabled=False), _settings(d))
        lead = _lead()
        orch.store.upsert(lead)
        orch.store.save()
        targets = orch.dm_targets()
        orch.write_dms(targets)
        results = orch.send_dms(targets, confirm=True)
        orch.close()
        assert results and all(status == "blocked" for _, status, _ in results)


def test_dm_send_is_dryrun_when_not_confirmed():
    with tempfile.TemporaryDirectory() as d:
        orch = Orchestrator(_campaign(dm_enabled=True), _settings(d))
        lead = _lead()
        orch.store.upsert(lead)
        orch.store.save()
        targets = orch.dm_targets()
        orch.write_dms(targets)
        results = orch.send_dms(targets, confirm=False)
        orch.close()
        statuses = {status for _, status, _ in results}
        assert "dry-run" in statuses            # ready draft, but nothing sent
