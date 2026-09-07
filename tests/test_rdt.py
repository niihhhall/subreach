# -*- coding: utf-8 -*-
"""Tests for the rdt-cli backend: envelope unwrap, listing/thread parsing,
whoami, and write ops. Offline — self._run is monkeypatched (no subprocess)."""

import json

import pytest

from reddit_outreach.reddit_client import (
    RedditClient, RedditClientError, _rdt_posts, _rdt_thread,
)


def _client(run_return):
    c = RedditClient("rdt")  # backend set directly, no subprocess at init
    c._run = lambda args: run_return  # type: ignore
    return c


# ── pure parsers ──────────────────────────────────────────────────────
def test_rdt_posts_parses_listing():
    data = {"items": [
        {"id": "a1", "title": "T", "subreddit": "solar", "author": "bob",
         "score": 5, "num_comments": 3, "created_utc": 123, "selftext": "body"}]}
    posts = _rdt_posts(data)
    assert len(posts) == 1
    p = posts[0]
    assert p.id == "a1" and p.subreddit == "solar" and p.num_comments == 3 and p.score == 5


def test_rdt_thread_flattens_nested_comments():
    data = {
        "post": {"id": "p1", "title": "T", "subreddit": "s", "author": "op", "selftext": "b"},
        "comments": [
            {"id": "c1", "author": "a", "body": "top", "score": 2,
             "replies": [{"id": "c2", "author": "b", "body": "nested", "score": 1, "replies": []}]}
        ],
    }
    post, comments = _rdt_thread(data)
    assert post.id == "p1"
    assert len(comments) == 2                 # top + nested flattened
    assert comments[1].body == "nested"


# ── envelope handling via the client ───────────────────────────────────
def test_search_unwraps_ok_envelope():
    env = json.dumps({"ok": True, "schema_version": "1",
                      "data": {"items": [{"id": "x", "title": "t", "subreddit": "r",
                                          "author": "u", "num_comments": 1}]}})
    c = _client(env)
    posts = c.search("query", limit=5)
    assert len(posts) == 1 and posts[0].id == "x"


def test_error_envelope_raises():
    env = json.dumps({"ok": False, "schema_version": "1",
                      "error": {"code": "not_authenticated", "message": "need login"}})
    c = _client(env)
    with pytest.raises(RedditClientError) as e:
        c.search("query")
    assert "not_authenticated" in str(e.value)


def test_read_parses_thread():
    env = json.dumps({"ok": True, "data": {
        "post": {"id": "p1", "title": "T", "subreddit": "s", "author": "op", "selftext": "b"},
        "comments": [{"id": "c1", "author": "a", "body": "hi", "score": 3, "replies": []}]}})
    c = _client(env)
    post, comments = c.read("p1")
    assert post.id == "p1" and len(comments) == 1 and comments[0].body == "hi"


def test_account_info_from_whoami():
    env = json.dumps({"ok": True, "data": {"user": {
        "name": "me", "comment_karma": 50, "link_karma": 10, "created_utc": 100.0}}})
    c = _client(env)
    info = c.account_info()
    assert info["username"] == "me" and info["comment_karma"] == 50 and info["link_karma"] == 10


def test_write_ops_require_rdt_backend():
    from reddit_outreach.reddit_client import RedditClient as RC
    mock = RC("mock")
    for call in (lambda: mock.comment("id", "hi"), lambda: mock.vote("id"),
                 lambda: mock.save_post("id"), lambda: mock.subscribe("solar")):
        with pytest.raises(RedditClientError):
            call()


def test_comment_passes_args_as_list(monkeypatch):
    c = RedditClient("rdt")
    captured = {}
    c._run = lambda args: captured.update(args=args) or ""  # type: ignore
    c.comment("1abc", 'text with "quotes" and $shell')
    # args passed as a list (no shell) → injection-safe
    assert captured["args"][:2] == ["rdt", "comment"]
    assert captured["args"][3] == 'text with "quotes" and $shell'
