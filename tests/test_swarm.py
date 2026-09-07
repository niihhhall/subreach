# -*- coding: utf-8 -*-
"""Tests for the warm-up swarm — roster loading + per-account safety gates.

Offline: the daily-cap and breaker gates short-circuit before any network/LLM,
so these assert the guardrails that keep the accounts alive.
"""

import os
import tempfile
import time

from reddit_outreach.config import Campaign, Settings
from reddit_outreach.swarm import (
    WarmAccount, SwarmRunner, load_accounts, overlap_warnings,
)

ROSTER = """\
accounts:
  - label: a1
    email: a1@example.com
    zernio_reddit_id: rid1
    api_key_env: SWARM_TEST_KEY_1
    max_comments_per_day: 2
    subreddits: [smallbusiness, Entrepreneur]
  - label: a2
    email: a2@example.com
    zernio_reddit_id: rid2
    api_key_env: SWARM_TEST_KEY_MISSING
    subreddits: [PPC]
  - label: a3
    email: a3@example.com
    zernio_reddit_id: rid3
    api_key_env: SWARM_TEST_KEY_1
    subreddits: [smallbusiness]
"""


def _campaign():
    return Campaign(name="t", product="P", value_proposition="v", icp="smb")


def _settings(d):
    return Settings(reddit_backend="mock", llm_provider="mock", data_dir=d, database_url="")


def test_overlap_warnings_flags_shared_subs():
    accts = [WarmAccount("a", subreddits=["x", "y"]),
             WarmAccount("b", subreddits=["y", "z"])]
    warns = overlap_warnings(accts)
    assert any("r/y" in w for w in warns)
    assert not any("r/x" in w for w in warns)


def test_load_accounts_resolves_keys_and_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_TEST_KEY_1", "sk_live_1")
    monkeypatch.delenv("SWARM_TEST_KEY_MISSING", raising=False)
    p = tmp_path / "accounts.yaml"
    p.write_text(ROSTER, encoding="utf-8")

    accounts, warnings = load_accounts(str(p))
    by = {a.label: a for a in accounts}
    assert by["a1"].api_key == "sk_live_1" and by["a1"].usable
    assert by["a2"].api_key == "" and not by["a2"].usable      # missing key
    # a2 missing-key warning + overlap on smallbusiness (a1 & a3)
    assert any("a2" in w and "no API key" in w for w in warnings)
    assert any("smallbusiness" in w.lower() for w in warnings)


def test_warm_account_respects_per_account_daily_cap():
    with tempfile.TemporaryDirectory() as d:
        runner = SwarmRunner(_campaign(), _settings(d))
        acct = WarmAccount("a1", reddit_id="rid1", api_key="sk_fake",
                           subreddits=["smallbusiness"], max_comments_per_day=2)
        # pre-log 2 comment sends for this account -> cap reached
        for pid in ("p1", "p2"):
            runner.store.log_activity("sent", channel="comment", post_id=pid,
                                      account="rid1", status="posted")
        res = runner.warm_account(acct, confirm=True)
        runner.close()
        assert res["posted"] == 0 and res["drafted"] == 0
        assert any("cap reached" in n for n in res["notes"])


def test_warm_account_skips_when_breaker_open():
    with tempfile.TemporaryDirectory() as d:
        runner = SwarmRunner(_campaign(), _settings(d))
        runner.store.trip_breaker("rid1", reason="shadowban suspected",
                                  resume_after=time.time() + 3600)
        acct = WarmAccount("a1", reddit_id="rid1", api_key="sk_fake",
                           subreddits=["smallbusiness"])
        res = runner.warm_account(acct, confirm=True)
        runner.close()
        assert res["posted"] == 0
        assert any("breaker OPEN" in n for n in res["notes"])


def test_load_accounts_from_env_roster(monkeypatch):
    monkeypatch.setenv("SWARM_TEST_KEY_1", "sk_env_1")
    monkeypatch.setenv("SWARM_ACCOUNTS",
                       '{"accounts": [{"label": "envacct", "zernio_reddit_id": "rid9", '
                       '"api_key_env": "SWARM_TEST_KEY_1", "active_hours": "8-23", '
                       '"tz_offset": -5, "subreddits": ["smallbusiness"]}]}')
    accounts, _ = load_accounts("does-not-exist.yaml")
    assert len(accounts) == 1
    a = accounts[0]
    assert a.label == "envacct" and a.api_key == "sk_env_1" and a.usable
    assert a.active_start == 8 and a.active_end == 23 and a.tz_offset == -5


def test_warm_account_skips_outside_active_hours():
    with tempfile.TemporaryDirectory() as d:
        runner = SwarmRunner(_campaign(), _settings(d))
        # window that excludes "now": start == end+1 trick -> use a 1-hour window far off
        cur = time.gmtime().tm_hour
        start = (cur + 2) % 24
        end = (cur + 3) % 24
        acct = WarmAccount("a1", reddit_id="rid1", api_key="sk_fake",
                           subreddits=["smallbusiness"],
                           active_start=start, active_end=end, tz_offset=0)
        res = runner.warm_account(acct, confirm=True)
        runner.close()
        assert res["posted"] == 0
        assert any("outside active hours" in n for n in res["notes"])


def test_unusable_account_is_reported_not_run():
    with tempfile.TemporaryDirectory() as d:
        runner = SwarmRunner(_campaign(), _settings(d))
        acct = WarmAccount("a2", reddit_id="rid2", api_key="", subreddits=["PPC"])
        res = runner.warm_account(acct, confirm=True)
        runner.close()
        assert res["posted"] == 0
        assert any("not usable" in n for n in res["notes"])

