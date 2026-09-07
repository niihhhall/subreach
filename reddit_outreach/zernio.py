# -*- coding: utf-8 -*-
"""Zernio API client — the real Reddit read + publish path.

Zernio connects your Reddit account via its own OAuth, so no Reddit API key is
needed on your side. This client wraps the endpoints the outreach system uses:

    read  : GET  /v1/reddit/search, GET /v1/reddit/feed
    setup : GET  /v1/profiles, POST /v1/profiles, GET /v1/accounts,
            GET  /v1/connect/reddit
    send  : POST /v1/posts  (publish/schedule a submission to a subreddit)
            GET  /v1/posts/{id}  (poll status)

The API key is read from the ``ZERNIO_API_KEY`` environment variable and is
never persisted by this module.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any, Dict, List, Optional

from .models import Comment, RedditPost

BASE_URL = "https://zernio.com/api/v1"


class ZernioError(RuntimeError):
    pass


class ZernioClient:
    def __init__(self, api_key: str = "", base_url: str = BASE_URL, timeout: int = 45):
        self.api_key = api_key or os.environ.get("ZERNIO_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    # ── low-level request (with 429 + transient retry/backoff) ────────
    #: how many times to retry a 429 / transient network error before giving up
    MAX_RETRIES = 3

    def _request(self, method: str, path: str, *, params=None, json=None) -> Dict[str, Any]:
        if not self.configured:
            raise ZernioError("ZERNIO_API_KEY is not set.")
        import requests

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        attempt = 0
        while True:
            try:
                resp = requests.request(
                    method, url, headers=headers, params=params, json=json,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                # transient network hiccup — retry a couple times, then fail
                if attempt < self.MAX_RETRIES:
                    time.sleep(self._backoff(attempt))
                    attempt += 1
                    continue
                raise ZernioError(f"network error calling {path}: {exc}") from exc

            # 429: respect Retry-After if given, else exponential backoff, then retry
            if resp.status_code == 429 and attempt < self.MAX_RETRIES:
                time.sleep(self._retry_after(resp) or self._backoff(attempt))
                attempt += 1
                continue

            if resp.status_code == 401:
                raise ZernioError("401 Unauthorized — the Zernio API key is invalid or revoked.")
            if resp.status_code == 429:
                raise ZernioError("429 Rate limited — retries exhausted; slow down.")
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = resp.json().get("error", "")
                except Exception:
                    detail = resp.text[:200]
                raise ZernioError(f"{resp.status_code} from {path}: {detail}")
            try:
                return resp.json()
            except ValueError:
                return {}

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential backoff with jitter, capped at 15s."""
        return min(15.0, 2.0 * (2 ** attempt)) + random.uniform(0, 0.5)

    @staticmethod
    def _retry_after(resp) -> float:
        """Seconds from a Retry-After header, or 0 if absent/unparseable."""
        val = resp.headers.get("Retry-After", "")
        try:
            return max(0.0, float(val))
        except (TypeError, ValueError):
            return 0.0

    # ── profiles & accounts ───────────────────────────────────────────
    def list_profiles(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/profiles").get("profiles", [])

    def create_profile(self, name: str, description: str = "") -> Dict[str, Any]:
        data = self._request("POST", "/profiles",
                             json={"name": name, "description": description})
        return data.get("profile", data)

    def list_accounts(self, profile_id: str = "") -> List[Dict[str, Any]]:
        params = {"profileId": profile_id} if profile_id else None
        return self._request("GET", "/accounts", params=params).get("accounts", [])

    def get_connect_url(self, platform: str, profile_id: str, redirect_url: str = "") -> Dict[str, Any]:
        params = {"profileId": profile_id}
        if redirect_url:
            params["redirect_url"] = redirect_url
        return self._request("GET", f"/connect/{platform}", params=params)

    def find_reddit_account(self, profile_id: str = "") -> Optional[Dict[str, Any]]:
        for acct in self.list_accounts(profile_id):
            if acct.get("platform") == "reddit":
                return acct
        return None

    # ── reddit read ───────────────────────────────────────────────────
    def reddit_search(self, account_id: str, query: str, subreddit: str = "",
                      sort: str = "relevance", limit: int = 25) -> List[RedditPost]:
        params = {"accountId": account_id, "q": query, "sort": sort, "limit": limit}
        if subreddit:
            params["subreddit"] = subreddit.replace("r/", "")
        data = self._request("GET", "/reddit/search", params=params)
        return _parse_zernio_posts(data)

    def reddit_feed(self, account_id: str, subreddit: str, sort: str = "hot",
                   limit: int = 25) -> List[RedditPost]:
        params = {
            "accountId": account_id,
            "subreddit": subreddit.replace("r/", ""),
            "sort": sort,
            "limit": limit,
        }
        data = self._request("GET", "/reddit/feed", params=params)
        return _parse_zernio_posts(data)

    # ── reddit publish ────────────────────────────────────────────────
    def create_reddit_post(self, account_id: str, profile_id: str, *, title: str,
                           content: str, subreddit: str, publish_now: bool = False,
                           scheduled_for: str = "", timezone: str = "UTC",
                           is_draft: bool = True) -> Dict[str, Any]:
        """Create a Reddit submission. Defaults to a DRAFT for safety.

        Reddit requires a subreddit + title; we pass the subreddit via
        platformSpecificData and set the account's target so Zernio can route it.
        """
        sub = subreddit.replace("r/", "")
        body: Dict[str, Any] = {
            "content": content,
            "title": title,
            "profileId": profile_id,
            "platforms": [{
                "platform": "reddit",
                "accountId": account_id,
                "platformSpecificData": {"subreddit": sub},
            }],
        }
        if is_draft:
            body["isDraft"] = True
        elif publish_now:
            body["publishNow"] = True
        elif scheduled_for:
            body["scheduledFor"] = scheduled_for
            body["timezone"] = timezone
        else:
            body["isDraft"] = True  # never post by accident

        data = self._request("POST", "/posts", json=body)
        return data.get("post", data)

    def get_post(self, post_id: str) -> Dict[str, Any]:
        data = self._request("GET", f"/posts/{post_id}")
        return data.get("post", data)

    # ── reddit feed ───────────────────────────────────────────────────
    # (reddit_feed defined above)

    # ── inbox: comments (read + reply) — requires Inbox add-on ─────────
    def get_post_comments(self, post_id: str, account_id: str, *, subreddit: str = "",
                          limit: int = 25, comment_id: str = "") -> List[Comment]:
        """Read a thread's comments. Reddit needs the subreddit."""
        params = {"accountId": account_id, "limit": limit}
        if subreddit:
            params["subreddit"] = subreddit.replace("r/", "")
        if comment_id:
            params["commentId"] = comment_id
        data = self._request("GET", f"/inbox/comments/{post_id}", params=params)
        return _parse_comments(data)

    def reply_to_post(self, post_id: str, account_id: str, message: str,
                      comment_id: str = "") -> Dict[str, Any]:
        """Post a reply to a thread (comment_id empty) or to a specific comment.

        This is the core Reddit outreach write. Returns {commentId, isReply}.
        """
        body: Dict[str, Any] = {"accountId": account_id, "message": message}
        if comment_id:
            body["commentId"] = comment_id
        data = self._request("POST", f"/inbox/comments/{post_id}", json=body)
        return data.get("data", data)

    # ── inbox: conversations / DMs — requires Inbox add-on ─────────────
    def list_conversations(self, *, platform: str = "reddit", account_id: str = "",
                           limit: int = 50) -> List[Dict[str, Any]]:
        params = {"platform": platform, "limit": limit}
        if account_id:
            params["accountId"] = account_id
        data = self._request("GET", "/inbox/conversations", params=params)
        return data.get("data", data.get("conversations", [])) if isinstance(data, dict) else []

    def create_conversation(self, account_id: str, *, participant_username: str = "",
                            participant_id: str = "", message: str = "") -> Dict[str, Any]:
        """Start (or add to) a DM with a Reddit user. Cold outreach — use sparingly."""
        body: Dict[str, Any] = {"accountId": account_id, "message": message}
        if participant_username:
            body["participantUsername"] = participant_username.replace("u/", "")
        if participant_id:
            body["participantId"] = participant_id
        data = self._request("POST", "/inbox/conversations", json=body)
        return data.get("data", data)

    def send_message(self, conversation_id: str, account_id: str, message: str) -> Dict[str, Any]:
        data = self._request(
            "POST", f"/inbox/conversations/{conversation_id}/messages",
            json={"accountId": account_id, "message": message},
        )
        return data.get("data", data)

    def set_default_subreddit(self, account_id: str, subreddit: str) -> Dict[str, Any]:
        sub = subreddit if subreddit.startswith("r/") else f"r/{subreddit}"
        return self._request("PUT", f"/accounts/{account_id}/reddit-subreddits",
                            json={"defaultSubreddit": sub})


# ── parsing (defensive against response shape) ────────────────────────
def _first(d: dict, *keys, default=""):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _parse_comments(data: Any) -> List[Comment]:
    items = data
    if isinstance(data, dict):
        items = _first(data, "comments", "items", "data", "results", default=[])
        if isinstance(items, dict):
            items = _first(items, "comments", "items", default=[])
    comments: List[Comment] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        # author can be a plain string, or nested under "author"/"from"
        author = it.get("author") or it.get("from") or ""
        if isinstance(author, dict):
            author = author.get("username") or author.get("name") or author.get("id") or ""
        comments.append(Comment(
            id=str(_first(it, "id", "commentId", "cid", default="")),
            author=str(author or "").replace("u/", ""),
            body=_first(it, "body", "text", "message", "content", default=""),
            score=int(_first(it, "score", "ups", "likeCount", default=0) or 0),
        ))
    return comments


def _parse_zernio_posts(data: Any) -> List[RedditPost]:
    items = data
    if isinstance(data, dict):
        items = _first(data, "items", "posts", "results", "data", "children", default=[])
    posts: List[RedditPost] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        inner = it.get("data") if isinstance(it.get("data"), dict) else it
        posts.append(RedditPost(
            id=str(_first(inner, "id", "postId", "name", default="")).replace("t3_", ""),
            title=_first(inner, "title"),
            selftext=_first(inner, "selftext", "body", "text", "content"),
            subreddit=str(_first(inner, "subreddit", "sub", default="")).replace("r/", ""),
            author=str(_first(inner, "author", "user", default="")).replace("u/", ""),
            url=_first(inner, "url", "link"),
            permalink=_first(inner, "permalink", "url"),
            score=int(_first(inner, "score", "ups", "upvotes", default=0) or 0),
            num_comments=int(_first(inner, "num_comments", "numComments", "comments", default=0) or 0),
            created_utc=float(_first(inner, "created_utc", "createdUtc", "created", default=0) or 0),
        ))
    return posts
