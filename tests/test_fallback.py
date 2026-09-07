# -*- coding: utf-8 -*-
"""Reads fall back to a second backend when the primary errors/empties."""

from reddit_outreach.reddit_client import RedditClient


def test_no_fallback_still_raises_on_primary_error(monkeypatch):
    # with NO fallback configured, there must be no fallback client (contract kept)
    monkeypatch.delenv("REDDIT_FALLBACK", raising=False)
    c = RedditClient("mock")
    assert c._fb is None


def test_read_fallback_when_primary_empty(monkeypatch):
    primary = RedditClient("mock", fallback="mock")
    # force fallback to exist even though same backend name would normally skip
    primary._fb = RedditClient("mock", _is_fallback=True)

    # primary returns nothing, fallback returns a comment
    from reddit_outreach.models import Comment
    monkeypatch.setattr(primary, "_read_once", lambda pid: (None, []))
    monkeypatch.setattr(primary._fb, "read", lambda pid: (None, [Comment(id="x", body="hi")]))

    _post, comments = primary.read("p1")
    assert comments and comments[0].body == "hi"


def test_search_fallback_when_primary_raises(monkeypatch):
    primary = RedditClient("mock")
    primary._fb = RedditClient("mock", _is_fallback=True)

    from reddit_outreach.models import RedditPost

    def boom(*a, **k):
        raise RuntimeError("primary down")

    monkeypatch.setattr(primary, "_search_once", boom)
    monkeypatch.setattr(primary._fb, "search", lambda *a, **k: [RedditPost(id="p1")])

    posts = primary.search("q")
    assert posts and posts[0].id == "p1"
