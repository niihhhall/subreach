# -*- coding: utf-8 -*-
"""Reddit read layer — wraps Agent-Reach's upstream tools.

Backends (in Agent-Reach's honest tiering, login is mandatory for the real
ones):
    * ``opencli`` — desktop, reuses the browser's reddit.com session
    * ``rdt``     — headless/VPS (rdt-cli): cookie auth, reads comments, and can
                    comment / upvote / save / subscribe + report karma via whoami
    * ``mock``    — offline fixtures, so the pipeline runs with zero setup

Both real backends expose ``search`` and ``read``; we shell out and parse the
YAML/JSON they emit. Output schemas vary slightly between tool versions, so the
parser is defensive and pulls fields by common aliases.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import List, Optional

from .models import Comment, RedditPost


class RedditClientError(RuntimeError):
    pass


class RedditClient:
    """Reddit read layer with pluggable backends.

    Auto-resolution order: opencli > rdt > zernio > mock. opencli/rdt are
    preferred when installed because they can also read a thread's *comments*
    (used by the research stage). Zernio gives real search data using only the
    Zernio key but has no comment-read endpoint, so research degrades to a
    heuristic angle from the post body. mock is the offline fallback.
    """

    def __init__(self, backend: str = "auto", proxy: str = "", zernio=None,
                 fallback: str = "", _is_fallback: bool = False):
        import threading
        self.proxy = proxy
        self._zernio = zernio
        self._z_account_id = ""
        self._z_profile_id = ""
        self._cache: dict[str, RedditPost] = {}
        self._account_lock = threading.Lock()  # guards account init under parallel discovery
        self.backend = self._resolve_backend(backend)

        # Optional read-fallback: if the primary read path errors or comes back
        # empty, retry the same read through a second backend (e.g. Zernio primary
        # with rdt fallback). Reads only — writes stay on the primary/account key.
        self._fb: Optional["RedditClient"] = None
        if not _is_fallback:
            fb = fallback or os.environ.get("REDDIT_FALLBACK", "")
            fb = (fb or "").strip().lower()
            if fb and fb != self.backend and self._backend_available(fb):
                self._fb = RedditClient(fb, proxy=proxy, zernio=zernio,
                                        _is_fallback=True)

    def _backend_available(self, name: str) -> bool:
        if name in ("opencli", "rdt"):
            return shutil.which(name) is not None
        if name == "zernio":
            return self._zernio is not None and self._zernio.configured
        return name == "mock"

    def _resolve_backend(self, backend: str) -> str:
        if backend != "auto":
            return backend
        if shutil.which("opencli"):
            return "opencli"
        if shutil.which("rdt"):
            return "rdt"
        if self._zernio is not None and self._zernio.configured:
            return "zernio"
        return "mock"

    @property
    def is_live(self) -> bool:
        return self.backend in ("opencli", "rdt", "zernio")

    def _ensure_zernio_account(self) -> None:
        if self._z_account_id:
            return
        with self._account_lock:  # only the first parallel caller resolves the account
            if self._z_account_id:
                return
            if self._zernio is None or not self._zernio.configured:
                raise RedditClientError("Zernio backend selected but ZERNIO_API_KEY is not set.")
            acct = self._zernio.find_reddit_account()
            if not acct:
                raise RedditClientError(
                    "No Reddit account connected in Zernio. Connect one first:\n"
                    "  python -m reddit_outreach.cli zernio-setup"
                )
            self._z_account_id = acct.get("_id", "")
            self._z_profile_id = acct.get("profileId", "")

    def warm(self) -> None:
        """Pre-resolve backend state (e.g. Zernio account) before parallel use."""
        if self.backend == "zernio":
            try:
                self._ensure_zernio_account()
            except RedditClientError:
                pass

    # ── public API (fallback-aware) ───────────────────────────────────
    def search(self, query: str, limit: int = 10, subreddit: str = "") -> List[RedditPost]:
        if self._fb is None:
            return self._search_once(query, limit, subreddit)   # no fallback: raise as before
        try:
            posts = self._search_once(query, limit, subreddit)
        except Exception:
            posts = []
        if not posts:
            try:
                posts = self._fb.search(query, limit, subreddit)
            except Exception:
                posts = []
        return posts

    def feed(self, subreddit: str, sort: str = "hot", limit: int = 10) -> List[RedditPost]:
        if self._fb is None:
            return self._feed_once(subreddit, sort, limit)
        try:
            posts = self._feed_once(subreddit, sort, limit)
        except Exception:
            posts = []
        if not posts:
            try:
                posts = self._fb.feed(subreddit, sort, limit)
            except Exception:
                posts = []
        return posts

    def read(self, post_id: str) -> tuple[Optional[RedditPost], List[Comment]]:
        if self._fb is None:
            return self._read_once(post_id)
        try:
            post, comments = self._read_once(post_id)
        except Exception:
            post, comments = None, []
        if not comments:
            try:
                fb_post, fb_comments = self._fb.read(post_id)
                if fb_comments:
                    return (post or fb_post), fb_comments
            except Exception:
                pass
        return post, comments

    # ── per-backend implementations ───────────────────────────────────
    def _search_once(self, query: str, limit: int = 10, subreddit: str = "") -> List[RedditPost]:
        if self.backend == "mock":
            posts = _mock_search(query, limit, subreddit)
        elif self.backend == "zernio":
            self._ensure_zernio_account()
            posts = self._zernio.reddit_search(
                self._z_account_id, query, subreddit=subreddit, limit=limit,
            )
        elif self.backend == "rdt":
            args = ["rdt", "search", query, "-n", str(limit)]
            if subreddit:
                args += ["-r", subreddit.replace("r/", "")]
            posts = _rdt_posts(self._run_rdt(args))
        else:  # opencli
            raw = self._run(["opencli", "reddit", "search", query, "-f", "json"])
            posts = _parse_posts(raw)
            if subreddit:
                posts = [p for p in posts if p.subreddit.lower() == subreddit.lower()]
        posts = posts[:limit]
        for p in posts:
            if p.id:
                self._cache[p.id] = p
        return posts

    def _feed_once(self, subreddit: str, sort: str = "hot", limit: int = 10) -> List[RedditPost]:
        """Browse a subreddit's feed (hot/new/top/rising)."""
        sub = subreddit.replace("r/", "")
        if self.backend == "mock":
            posts = [p for p in _MOCK_POSTS if p.subreddit.lower() == sub.lower()] or list(_MOCK_POSTS)
        elif self.backend == "zernio":
            self._ensure_zernio_account()
            posts = self._zernio.reddit_feed(self._z_account_id, sub, sort=sort, limit=limit)
        elif self.backend == "opencli":
            posts = _parse_posts(self._run(["opencli", "reddit", "subreddit", sub, "-f", "json"]))
        else:  # rdt
            posts = _rdt_posts(self._run_rdt(["rdt", "sub", sub, "-s", sort, "-n", str(limit)]))
        posts = posts[:limit]
        for p in posts:
            if p.id:
                self._cache[p.id] = p
        return posts

    def _read_once(self, post_id: str) -> tuple[Optional[RedditPost], List[Comment]]:
        if self.backend == "mock":
            return _mock_read(post_id)
        if self.backend == "zernio":
            post = self._cache.get(post_id)
            comments: List[Comment] = []
            # Reading comments needs the Inbox add-on; degrade quietly if absent.
            try:
                self._ensure_zernio_account()
                sub = post.subreddit if post else ""
                comments = self._zernio.get_post_comments(
                    post_id, self._z_account_id, subreddit=sub, limit=25,
                )
            except Exception:
                comments = []
            return post, comments
        if self.backend == "rdt":
            return _rdt_thread(self._run_rdt(["rdt", "read", post_id, "-n", "50"]))
        raw = self._run(["opencli", "reddit", "read", post_id, "-f", "json"])
        return _parse_thread(raw)

    # ── rdt: authenticated profile + engagement writes (Phase 2) ──────
    def account_info(self) -> Optional[dict]:
        """Authenticated karma + account age via ``rdt whoami``. None if the
        backend isn't rdt or the call fails. This is the real (non-403) source
        for account-health / CQS signals."""
        if self.backend != "rdt":
            return None
        try:
            data = self._run_rdt(["rdt", "whoami"])
        except RedditClientError:
            return None
        user = (data or {}).get("user", data) if isinstance(data, dict) else {}
        if not isinstance(user, dict):
            return None
        return {
            "username": user.get("name", ""),
            "comment_karma": int(user.get("comment_karma", 0) or 0),
            "link_karma": int(user.get("link_karma", 0) or 0),
            "created_utc": float(user.get("created_utc", 0) or 0),
        }

    def comment(self, post_id: str, text: str) -> dict:
        """Post a comment (rdt only). Args passed as a list — no shell, no injection."""
        if self.backend != "rdt":
            raise RedditClientError("commenting requires the rdt backend")
        out = self._run(["rdt", "comment", post_id, text])
        return {"ok": True, "raw": (out or "")[:200]}

    def vote(self, post_id: str, down: bool = False) -> dict:
        if self.backend != "rdt":
            raise RedditClientError("voting requires the rdt backend")
        self._run(["rdt", "upvote", post_id] + (["--down"] if down else []))
        return {"ok": True}

    def save_post(self, post_id: str) -> dict:
        if self.backend != "rdt":
            raise RedditClientError("save requires the rdt backend")
        self._run(["rdt", "save", post_id])
        return {"ok": True}

    def subscribe(self, subreddit: str) -> dict:
        if self.backend != "rdt":
            raise RedditClientError("subscribe requires the rdt backend")
        self._run(["rdt", "subscribe", subreddit.replace("r/", "")])
        return {"ok": True}

    # ── internals ─────────────────────────────────────────────────────
    def _run(self, args: List[str]) -> str:
        env = None
        if self.proxy:
            import os
            env = dict(os.environ)
            env["HTTPS_PROXY"] = self.proxy
            env["HTTP_PROXY"] = self.proxy
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                env=env,
            )
        except FileNotFoundError:
            raise RedditClientError(f"Backend tool not found: {args[0]}")
        except subprocess.TimeoutExpired:
            raise RedditClientError(f"{args[0]} timed out. Check network/proxy and login state.")
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()
            hint = tail[-1] if tail else "no output"
            raise RedditClientError(
                f"{args[0]} failed (exit {result.returncode}): {hint}. "
                f"Run `agent-reach doctor --json` and confirm you are logged in."
            )
        return result.stdout or ""

    def _run_rdt(self, args: List[str]):
        """Run an rdt-cli command with --json and unwrap its {ok,data,error}
        envelope. rdt exits 0 even on logical errors, so we check ``ok`` here."""
        raw = self._run(args + ["--json"])
        data = _load(raw)
        if not isinstance(data, dict):
            raise RedditClientError(f"rdt returned unexpected output: {(raw or '')[:200]}")
        if not data.get("ok", False):
            err = data.get("error") or {}
            raise RedditClientError(
                f"rdt {args[1] if len(args) > 1 else ''} failed: "
                f"{err.get('code', '')}: {err.get('message', 'unknown error')} "
                f"(is the account logged in? cookies valid?)"
            )
        return data.get("data")


# ── parsers (defensive against schema drift) ──────────────────────────
def _first(d: dict, *keys, default=""):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _to_post(d: dict) -> RedditPost:
    return RedditPost(
        id=str(_first(d, "id", "post_id", "name", default="")).replace("t3_", ""),
        title=_first(d, "title"),
        selftext=_first(d, "selftext", "body", "text", "content"),
        subreddit=str(_first(d, "subreddit", "sub", "subreddit_name")).replace("r/", ""),
        author=str(_first(d, "author", "user", "username")).replace("u/", ""),
        url=_first(d, "url", "link"),
        permalink=_first(d, "permalink", "url"),
        score=int(_first(d, "score", "ups", "upvotes", default=0) or 0),
        num_comments=int(_first(d, "num_comments", "comments", "comment_count", default=0) or 0),
        created_utc=float(_first(d, "created_utc", "created", "timestamp", default=0) or 0),
    )


def _load(raw: str):
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # type: ignore
        return yaml.safe_load(raw)
    except Exception:
        return None


def _parse_posts(raw: str) -> List[RedditPost]:
    data = _load(raw)
    if data is None:
        return []
    items = data
    if isinstance(data, dict):
        items = _first(data, "results", "posts", "data", "children", default=[])
        if isinstance(items, dict):
            items = items.get("children", []) or list(items.values())
    posts: List[RedditPost] = []
    for it in items or []:
        if isinstance(it, dict):
            # reddit-style {"data": {...}} envelopes
            inner = it.get("data") if isinstance(it.get("data"), dict) else it
            posts.append(_to_post(inner))
    return posts


def _parse_thread(raw: str) -> tuple[Optional[RedditPost], List[Comment]]:
    data = _load(raw)
    if data is None:
        return None, []
    # OpenCLI returns a flat list: [post (type POST), comment (type COMMENT), ...]
    if isinstance(data, list):
        post = None
        raw_comments = []
        for item in data:
            if not isinstance(item, dict):
                continue
            itype = str(item.get("type", "")).upper()
            if post is None and (itype == "POST" or "title" in item):
                post = _to_post(item)
            else:
                raw_comments.append(item)
        if post is None and data and isinstance(data[0], dict):
            post = _to_post(data[0])
            raw_comments = [x for x in data[1:] if isinstance(x, dict)]
        comments: List[Comment] = []
        for inner in raw_comments:
            comments.append(Comment(
                id=str(_first(inner, "id", default="")),
                author=str(_first(inner, "author", "user", default="")).replace("u/", ""),
                body=_first(inner, "body", "text", default=""),
                score=int(_first(inner, "score", "ups", default=0) or 0),
            ))
        return post, comments

    node = data
    if isinstance(data, dict):
        node = _first(data, "post", "submission", "data", default=data)
        if isinstance(node, dict) and "post" in node:
            node = node["post"]
    post = _to_post(node) if isinstance(node, dict) else None

    raw_comments = []
    if isinstance(data, dict):
        raw_comments = _first(data, "comments", "replies", "children", default=[])
    comments: List[Comment] = []
    for c in raw_comments or []:
        if isinstance(c, dict):
            inner = c.get("data") if isinstance(c.get("data"), dict) else c
            comments.append(Comment(
                id=str(_first(inner, "id", default="")),
                author=str(_first(inner, "author", "user", default="")).replace("u/", ""),
                body=_first(inner, "body", "text", default=""),
                score=int(_first(inner, "score", "ups", default=0) or 0),
            ))
    return post, comments


# ── rdt-cli parsers (envelope already unwrapped to `data`) ────────────
def _rdt_posts(data) -> List[RedditPost]:
    """Parse a rdt ListingPage payload ({items:[Post...]}) into RedditPosts."""
    items = data.get("items", []) if isinstance(data, dict) else (data or [])
    return [_to_post(x) for x in items if isinstance(x, dict)]


def _rdt_thread(data) -> tuple[Optional[RedditPost], List[Comment]]:
    """Parse a rdt PostDetail payload ({post, comments:[nested replies]})."""
    if not isinstance(data, dict):
        return None, []
    post = _to_post(data["post"]) if isinstance(data.get("post"), dict) else None
    comments: List[Comment] = []
    _flatten_rdt_comments(data.get("comments", []), comments)
    return post, comments


def _flatten_rdt_comments(nodes, out: List[Comment], parent_id: str = "") -> None:
    """Flatten rdt's nested comment tree (replies) into a flat list, keeping the
    parent id so we can tell which comments are replies to ours."""
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        cid = str(n.get("id", ""))
        out.append(Comment(
            id=cid,
            author=str(n.get("author", "")).replace("u/", ""),
            body=n.get("body", "") or "",
            score=int(n.get("score", 0) or 0),
            parent_id=parent_id,
        ))
        _flatten_rdt_comments(n.get("replies", []), out, parent_id=cid)


# ── mock fixtures for offline development ─────────────────────────────
_MOCK_POSTS = [
    RedditPost(
        id="mock1",
        title="Struggling to keep our team's API docs in sync with the code",
        selftext=(
            "We're a 12-person startup and our REST API docs drift out of date "
            "constantly. Every release something breaks for integration partners. "
            "How do you all keep docs accurate without a dedicated writer?"
        ),
        subreddit="devops",
        author="tired_founder",
        permalink="/r/devops/comments/mock1/struggling_api_docs/",
        score=87, num_comments=34, created_utc=1_760_000_000,
    ),
    RedditPost(
        id="mock2",
        title="Best way to onboard new engineers into a messy codebase?",
        selftext=(
            "Inherited a 6-year-old monolith. New hires take ~6 weeks to be "
            "productive. Looking for tools or processes that actually help."
        ),
        subreddit="ExperiencedDevs",
        author="eng_lead_99",
        permalink="/r/ExperiencedDevs/comments/mock2/onboard_messy_codebase/",
        score=142, num_comments=61, created_utc=1_760_100_000,
    ),
    RedditPost(
        id="mock3",
        title="What's your favorite mechanical keyboard switch?",
        selftext="Just curious what everyone likes. I'm on browns right now.",
        subreddit="MechanicalKeyboards",
        author="clackfan",
        permalink="/r/MechanicalKeyboards/comments/mock3/fav_switch/",
        score=210, num_comments=180, created_utc=1_760_200_000,
    ),
]

_MOCK_COMMENTS = {
    "mock1": [
        Comment(id="c1", author="devops_dan", body="We tried Swagger but nobody updates it.", score=22),
        Comment(id="c2", author="apiqueen", body="Contract testing helped us catch drift early.", score=15),
    ],
    "mock2": [
        Comment(id="c3", author="senior_sam", body="Good onboarding docs + a buddy system cut ours in half.", score=40),
    ],
}


def _mock_search(query: str, limit: int, subreddit: str) -> List[RedditPost]:
    q = query.lower()
    scored = []
    for p in _MOCK_POSTS:
        hay = f"{p.title} {p.selftext} {p.subreddit}".lower()
        hits = sum(1 for term in q.split() if term in hay)
        if hits:
            scored.append((hits, p))
    scored.sort(key=lambda t: t[0], reverse=True)
    posts = [p for _, p in scored] or list(_MOCK_POSTS)
    if subreddit:
        posts = [p for p in posts if p.subreddit.lower() == subreddit.lower()]
    return posts[:limit]


def _mock_read(post_id: str) -> tuple[Optional[RedditPost], List[Comment]]:
    post = next((p for p in _MOCK_POSTS if p.id == post_id), None)
    return post, _MOCK_COMMENTS.get(post_id, [])
