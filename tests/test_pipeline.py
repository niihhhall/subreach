# -*- coding: utf-8 -*-
"""End-to-end pipeline tests using the mock Reddit backend + heuristic agents.

These run fully offline (no network, no API keys, no rdt/opencli).
"""

import os
import tempfile

import pytest

from reddit_outreach.config import Campaign, Settings
from reddit_outreach.models import Lead, RedditPost, Stage
from reddit_outreach.orchestrator import Orchestrator
from reddit_outreach.reddit_client import RedditClient
from reddit_outreach.store import LeadStore
from reddit_outreach.agents import (
    QualificationAgent,
    PersonalizationAgent,
    ComplianceAgent,
)


def make_campaign(**overrides):
    base = dict(
        name="test-campaign",
        product="DocSync",
        value_proposition="Keeps API docs in sync with code.",
        icp="Engineering leads who own a public API and struggle with stale docs.",
        keywords=["api documentation", "docs in sync", "onboard"],
        subreddits=["devops", "ExperiencedDevs"],
        min_fit_score=40,
    )
    base.update(overrides)
    return Campaign(**base)


def make_settings(data_dir):
    return Settings(reddit_backend="mock", llm_provider="mock", data_dir=data_dir)


def test_mock_backend_selected_when_no_tools():
    client = RedditClient("auto")
    # in CI there is no rdt/opencli, so it must fall back to mock
    assert client.backend in ("mock", "opencli", "rdt")


def test_mock_search_matches_keywords():
    client = RedditClient("mock")
    posts = client.search("api docs sync", limit=10)
    assert posts
    assert all(isinstance(p, RedditPost) for p in posts)


def test_qualification_disqualifies_off_topic():
    campaign = make_campaign(min_fit_score=55)
    agent = QualificationAgent(campaign)
    off_topic = Lead(post=RedditPost(
        id="x", title="Favorite keyboard switch?",
        selftext="Just curious what people like.",
        subreddit="MechanicalKeyboards",
    ))
    agent.run(off_topic)
    assert off_topic.qualification is not None
    assert off_topic.stage == Stage.DISQUALIFIED.value


def test_qualification_qualifies_on_topic():
    campaign = make_campaign(min_fit_score=40)
    agent = QualificationAgent(campaign)
    lead = Lead(post=RedditPost(
        id="y",
        title="Struggling to keep our api documentation in sync with code",
        selftext="Every release breaks docs for partners. How do you keep docs accurate?",
        subreddit="devops",
    ))
    agent.run(lead)
    assert lead.stage == Stage.QUALIFIED.value
    assert lead.qualification.fit_score >= 40


def test_compliance_flags_banned_phrase():
    campaign = make_campaign()
    agent = ComplianceAgent(campaign)
    lead = Lead(post=RedditPost(id="z", title="t", subreddit="devops"))
    from reddit_outreach.models import Draft
    lead.draft = Draft(
        kind="comment",
        opener="Here is a genuinely helpful tip about your workflow problem here.",
        body=("Here is a genuinely helpful tip about your workflow problem that should "
              "help a lot. Buy now before it is gone forever and ever."),
    )
    agent.run(lead)
    assert lead.compliance.verdict in ("revise", "rejected")
    assert any("disallowed" in i for i in lead.compliance.issues)


def test_full_pipeline_produces_queue():
    with tempfile.TemporaryDirectory() as d:
        campaign = make_campaign(min_fit_score=40)
        settings = make_settings(d)
        orch = Orchestrator(campaign, settings)
        report = orch.run(limit_per_query=10)

        assert report.discovered > 0
        # at least one on-topic mock post should qualify and produce a draft
        assert report.qualified >= 1
        assert report.drafted >= 1
        orch.close()

        store = LeadStore(d, campaign.name)
        reviewed = store.by_stage(
            Stage.APPROVED.value, Stage.NEEDS_REVISION.value, Stage.REJECTED.value
        )
        assert reviewed, "pipeline should produce at least one reviewed lead"
        store.close()


def test_pipeline_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        campaign = make_campaign(min_fit_score=40)
        settings = make_settings(d)

        o1 = Orchestrator(campaign, settings)
        o1.run()
        o1.close()
        store1 = LeadStore(d, campaign.name)
        count1 = len(store1.all())
        store1.close()

        # second run should not duplicate leads (keyed by post id)
        o2 = Orchestrator(campaign, settings)
        o2.run()
        o2.close()
        store2 = LeadStore(d, campaign.name)
        count2 = len(store2.all())
        store2.close()

        assert count1 == count2


def test_personalization_value_first():
    campaign = make_campaign()
    agent = PersonalizationAgent(campaign)
    lead = Lead(post=RedditPost(
        id="p", title="Docs keep drifting out of sync", subreddit="devops",
    ))
    agent.run(lead)
    assert lead.draft is not None
    # opener must not lead with the product name (value-first rule)
    assert campaign.product.lower() not in lead.draft.opener.lower()


def test_parse_thread_handles_opencli_list_format():
    # OpenCLI returns a flat list: post first (type POST), then comments (type COMMENT).
    import json
    from reddit_outreach.reddit_client import _parse_thread

    raw = json.dumps([
        {"type": "POST", "author": "op", "title": "Leads after hours?",
         "text": "I run a small business and lose leads at night.", "score": 3},
        {"type": "COMMENT", "author": "helper1", "text": "Use an answering service.", "score": 5},
        {"type": "COMMENT", "author": "helper2", "text": "We built a bot for this.", "score": 2},
    ])
    post, comments = _parse_thread(raw)
    assert post is not None and post.title == "Leads after hours?"
    assert len(comments) == 2
    assert comments[0].author == "helper1"
    assert "answering service" in comments[0].body
