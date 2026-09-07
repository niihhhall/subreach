# -*- coding: utf-8 -*-
"""Tests for the SubredditScoutAgent (offline via the mock Reddit backend)."""

from reddit_outreach.agents.scout import SubredditScoutAgent
from reddit_outreach.reddit_client import RedditClient
from reddit_outreach.config import Campaign


def _campaign(**kw):
    base = dict(name="c", product="Markeye", value_proposition="v", icp="i",
                feed_subreddits=["devops", "webdev"], subreddits=["programming"])
    base.update(kw)
    return Campaign(**base)


def test_scout_heuristic_fallback_validates_via_feed():
    # no LLM -> heuristic candidates from campaign; mock feed returns posts -> active
    reddit = RedditClient("mock")
    agent = SubredditScoutAgent(_campaign(), reddit, llm=None)
    results = agent.run()  # no LLM -> heuristic candidates from campaign
    names = {c["name"] for c in results}
    assert {"devops", "webdev", "programming"} <= names
    assert all("active" in c for c in results)
    # mock backend returns posts for any sub, so all validate active
    assert all(c["active"] for c in results)


def test_scout_ranks_active_first():
    reddit = RedditClient("mock")
    agent = SubredditScoutAgent(_campaign(), reddit, llm=None)
    candidates = [
        {"name": "a", "relevance": 90},
        {"name": "b", "relevance": 40},
    ]
    # manually validate then sort via run()'s logic
    agent._validate(candidates)
    candidates.sort(key=lambda c: (1 if c.get("active") else 0, c.get("relevance", 0)),
                    reverse=True)
    assert candidates[0]["name"] == "a"  # higher relevance, both active


def test_orchestrator_merges_scouted_subs_from_db():
    # The two-agent coordination: Scout writes subs to the DB, the watch/find
    # path (_refresh_feeds) unions them into discovery on every cycle.
    import tempfile
    from reddit_outreach.orchestrator import Orchestrator
    from reddit_outreach.config import Settings

    with tempfile.TemporaryDirectory() as d:
        campaign = Campaign(name="camp2", product="Markeye", value_proposition="v",
                            icp="i", feed_subreddits=["smallbusiness"],
                            use_scouted_subreddits=True)
        settings = Settings(reddit_backend="mock", llm_provider="mock", data_dir=d)
        orch = Orchestrator(campaign, settings)
        try:
            orch.store.record_scouted_subreddit(subreddit="solarbusiness",
                                                vertical="solar", relevance=90,
                                                active=True, sample_count=3)
            orch.store.record_scouted_subreddit(subreddit="deadsub", active=False)
            orch._refresh_feeds()
            feeds = {s.lower() for s in orch.campaign.feed_subreddits}
            assert "smallbusiness" in feeds        # base feed kept
            assert "solarbusiness" in feeds        # active scouted merged in
            assert "deadsub" not in feeds          # inactive scouted excluded
        finally:
            orch.close()
