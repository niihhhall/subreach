# -*- coding: utf-8 -*-
"""Offline tests for the Zernio client parsing, backend selection, and sender.

No network calls: we test the pure parsing/logic and the graceful-degradation
paths (unconfigured key, missing draft).
"""

from reddit_outreach.zernio import ZernioClient, _parse_zernio_posts, _parse_comments
from reddit_outreach.reddit_client import RedditClient
from reddit_outreach.models import Draft, Lead, RedditPost, Stage
from reddit_outreach.sender import manual_send, zernio_publish, zernio_comment, zernio_dm


def test_parse_zernio_items_shape():
    # mirrors the real /reddit/search response ("items" envelope)
    data = {
        "items": [
            {
                "id": "1terlq7",
                "fullname": "t3_1terlq7",
                "title": "I hate the API docs",
                "author": "someone",
                "subreddit": "dev",
                "permalink": "https://www.reddit.com/r/dev/comments/1terlq7/x/",
                "selftext": "docs are stale",
            }
        ]
    }
    posts = _parse_zernio_posts(data)
    assert len(posts) == 1
    p = posts[0]
    assert p.id == "1terlq7"
    assert p.subreddit == "dev"
    assert p.author == "someone"
    assert "stale" in p.selftext


def test_unconfigured_client_is_not_configured(monkeypatch):
    monkeypatch.delenv("ZERNIO_API_KEY", raising=False)
    c = ZernioClient(api_key="")
    assert not c.configured


def test_reddit_client_prefers_zernio_when_no_cli(monkeypatch):
    # simulate no rdt/opencli on PATH
    monkeypatch.setattr("reddit_outreach.reddit_client.shutil.which", lambda name: None)
    zern = ZernioClient(api_key="sk_test")  # configured (won't be called)
    client = RedditClient("auto", zernio=zern)
    assert client.backend == "zernio"
    assert client.is_live


def test_reddit_client_falls_back_to_mock(monkeypatch):
    monkeypatch.delenv("ZERNIO_API_KEY", raising=False)
    monkeypatch.setattr("reddit_outreach.reddit_client.shutil.which", lambda name: None)
    client = RedditClient("auto", zernio=ZernioClient(api_key=""))
    assert client.backend == "mock"


def test_manual_send_requires_draft():
    lead = Lead(post=RedditPost(id="a", title="t", subreddit="devops"))
    result = manual_send(lead, open_browser=False)
    assert not result.ok


def test_manual_send_with_draft(monkeypatch):
    # avoid touching the real clipboard/browser in CI
    monkeypatch.setattr("reddit_outreach.sender.copy_to_clipboard", lambda t: True)
    monkeypatch.setattr("reddit_outreach.sender.open_in_browser", lambda u: True)
    lead = Lead(post=RedditPost(id="b", title="t", subreddit="devops"))
    lead.draft = Draft(kind="comment", body="a genuinely helpful reply about the problem")
    result = manual_send(lead, open_browser=True)
    assert result.ok
    assert result.ref == "manual"


def test_zernio_publish_without_key(monkeypatch):
    monkeypatch.delenv("ZERNIO_API_KEY", raising=False)
    lead = Lead(post=RedditPost(id="c", title="t", subreddit="devops"))
    lead.draft = Draft(kind="comment", body="hello there this is a draft body")
    result = zernio_publish(lead, ZernioClient(api_key=""))
    assert not result.ok
    assert "ZERNIO_API_KEY" in result.message


def test_parse_comments_handles_author_shapes():
    data = {"comments": [
        {"id": "t1_a", "author": {"username": "alice"}, "body": "hi", "score": 3},
        {"id": "t1_b", "author": "u/bob", "text": "yo", "ups": 1},
        {"id": "t1_c", "from": {"name": "carol"}, "message": "hey", "createdTime": "2025-01-01"},
    ]}
    comments = _parse_comments(data)
    assert [c.author for c in comments] == ["alice", "bob", "carol"]
    assert comments[0].body == "hi"
    assert comments[2].body == "hey"


def test_mock_feed_returns_posts():
    client = RedditClient("mock")
    posts = client.feed("devops", sort="hot", limit=5)
    assert posts
    assert all(isinstance(p, RedditPost) for p in posts)


def test_zernio_comment_dry_run_by_default(monkeypatch):
    class FakeZernio(ZernioClient):
        @property
        def configured(self):
            return True

        def find_reddit_account(self, profile_id=""):
            return {"_id": "acc1", "profileId": "prof1"}

        def reply_to_post(self, *a, **k):
            raise AssertionError("must not post without confirm=True")

    lead = Lead(post=RedditPost(id="e", title="t", subreddit="devops"))
    lead.draft = Draft(kind="comment", body="a helpful reply body about the problem")
    result = zernio_comment(lead, FakeZernio(api_key="sk_x"), confirm=False)
    assert result.ok
    assert result.status == "dry-run"
    assert lead.stage != Stage.SENT.value


def test_zernio_comment_posts_with_confirm(monkeypatch):
    captured = {}

    class FakeZernio(ZernioClient):
        @property
        def configured(self):
            return True

        def find_reddit_account(self, profile_id=""):
            return {"_id": "acc1", "profileId": "prof1"}

        def reply_to_post(self, post_id, account_id, message, comment_id=""):
            captured.update(post_id=post_id, account_id=account_id, message=message)
            return {"commentId": "t1_new", "isReply": True}

    lead = Lead(post=RedditPost(id="f", title="t", subreddit="devops"))
    lead.draft = Draft(kind="comment", body="a helpful reply body about the problem")
    result = zernio_comment(lead, FakeZernio(api_key="sk_x"), confirm=True)
    assert result.ok and result.status == "posted"
    assert captured["post_id"] == "f"
    assert lead.stage == Stage.SENT.value
    assert lead.sent_ref == "comment:t1_new"


def test_zernio_dm_dry_run(monkeypatch):
    class FakeZernio(ZernioClient):
        @property
        def configured(self):
            return True

        def find_reddit_account(self, profile_id=""):
            return {"_id": "acc1", "profileId": "prof1"}

    lead = Lead(post=RedditPost(id="g", title="t", subreddit="devops", author="carol"))
    lead.draft = Draft(kind="dm", body="hey, saw your post about stale docs")
    result = zernio_dm(lead, FakeZernio(api_key="sk_x"), confirm=False)
    assert result.ok and result.status == "dry-run"
    assert "carol" in result.message


def test_zernio_publish_defaults_to_draft_mode(monkeypatch):
    """create_reddit_post must be called with is_draft=True by default."""
    captured = {}

    class FakeZernio(ZernioClient):
        @property
        def configured(self):
            return True

        def find_reddit_account(self, profile_id=""):
            return {"_id": "acc1", "profileId": "prof1"}

        def create_reddit_post(self, **kwargs):
            captured.update(kwargs)
            return {"_id": "zpost1", "status": "draft"}

    lead = Lead(post=RedditPost(id="d", title="Stale docs", subreddit="devops"))
    lead.draft = Draft(kind="comment", body="helpful body content here for the reply")
    result = zernio_publish(lead, FakeZernio(api_key="sk_x"), mode="draft")

    assert result.ok
    assert captured["is_draft"] is True
    assert captured["publish_now"] is False
    assert lead.stage == Stage.SENT.value
    assert lead.sent_ref == "zpost1"
