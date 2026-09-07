# -*- coding: utf-8 -*-
"""Tests for Zernio's 429 / transient retry-with-backoff (offline, mocked HTTP)."""

import requests

from reddit_outreach import zernio as zmod
from reddit_outreach.zernio import ZernioClient, ZernioError


class _FakeResp:
    def __init__(self, code, data=None, headers=None):
        self.status_code = code
        self._d = data or {}
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._d


def _no_sleep(monkeypatch):
    monkeypatch.setattr(zmod.time, "sleep", lambda s: None)


def test_retries_429_then_succeeds(monkeypatch):
    _no_sleep(monkeypatch)
    z = ZernioClient(api_key="k")
    calls = {"n": 0}

    def fake_request(method, url, **kw):
        calls["n"] += 1
        return _FakeResp(429) if calls["n"] == 1 else _FakeResp(200, {"ok": True})

    monkeypatch.setattr(requests, "request", fake_request)
    assert z._request("GET", "/x") == {"ok": True}
    assert calls["n"] == 2  # one retry


def test_429_exhausts_then_raises(monkeypatch):
    _no_sleep(monkeypatch)
    z = ZernioClient(api_key="k")
    calls = {"n": 0}

    def fake_request(method, url, **kw):
        calls["n"] += 1
        return _FakeResp(429)

    monkeypatch.setattr(requests, "request", fake_request)
    try:
        z._request("GET", "/x")
        assert False, "should have raised"
    except ZernioError as e:
        assert "429" in str(e)
    assert calls["n"] == ZernioClient.MAX_RETRIES + 1  # initial + retries


def test_retry_after_header_parsed(monkeypatch):
    z = ZernioClient(api_key="k")
    slept = {"secs": []}
    monkeypatch.setattr(zmod.time, "sleep", lambda s: slept["secs"].append(s))
    calls = {"n": 0}

    def fake_request(method, url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(429, headers={"Retry-After": "3"})
        return _FakeResp(200, {"ok": True})

    monkeypatch.setattr(requests, "request", fake_request)
    z._request("GET", "/x")
    assert slept["secs"] == [3.0]  # honored the Retry-After header exactly


def test_non_429_error_not_retried(monkeypatch):
    _no_sleep(monkeypatch)
    z = ZernioClient(api_key="k")
    calls = {"n": 0}

    def fake_request(method, url, **kw):
        calls["n"] += 1
        return _FakeResp(401)

    monkeypatch.setattr(requests, "request", fake_request)
    try:
        z._request("GET", "/x")
        assert False
    except ZernioError as e:
        assert "401" in str(e)
    assert calls["n"] == 1  # 401 fails fast, no retry
