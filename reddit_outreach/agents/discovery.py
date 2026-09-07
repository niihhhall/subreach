# -*- coding: utf-8 -*-
"""DiscoveryAgent — finds candidate posts across keywords and subreddits.

Uses the Reddit read client (rdt / opencli / mock) to search. Deduplicates by
post id and returns fresh Lead objects. This agent does not judge fit — that's
the QualificationAgent's job.
"""

from __future__ import annotations

from typing import List

from ..models import Lead, RedditPost, Stage
from ..reddit_client import RedditClient, RedditClientError
from .base import BaseAgent


class DiscoveryAgent(BaseAgent):
    role = "discovery"

    def __init__(self, campaign, reddit: RedditClient, llm=None):
        super().__init__(campaign, llm)
        self.reddit = reddit

    def run(self, limit_per_query: int = 10) -> List[Lead]:
        seen: dict[str, Lead] = {}

        # Build every fetch as a (source, callable) task, then run them
        # concurrently — 15 feeds + keyword searches sequentially is minutes;
        # in parallel it's seconds. Results are merged sequentially (thread-safe).
        tasks = []
        for query, subreddit in self._build_queries():
            src = f"search:{query}" + (f" r/{subreddit}" if subreddit else "")
            tasks.append((src, lambda q=query, s=subreddit: self.reddit.search(
                q, limit=limit_per_query, subreddit=s)))
        for subreddit in self.campaign.feed_subreddits:
            src = f"feed:{self.campaign.feed_sort} r/{subreddit}"
            tasks.append((src, lambda s=subreddit: self.reddit.feed(
                s, sort=self.campaign.feed_sort, limit=limit_per_query)))

        # warm the backend once so parallel workers don't race on account init
        try:
            self.reddit.warm()
        except Exception:
            pass

        results = self._run_tasks(tasks)
        for src, posts in results:
            self._collect(seen, posts, src)

        leads = list(seen.values())
        return leads[: self.campaign.max_leads_per_run]

    def _run_tasks(self, tasks, max_workers: int = 5):
        """Run fetch tasks concurrently; failures are logged, not fatal."""
        from concurrent.futures import ThreadPoolExecutor

        def _one(task):
            src, fn = task
            try:
                return src, fn()
            except RedditClientError as exc:
                print(f"  [discovery] {src} failed: {exc}")
                return src, []
            except Exception as exc:  # never let one fetch kill discovery
                print(f"  [discovery] {src} error: {exc}")
                return src, []

        if len(tasks) <= 1:
            return [_one(t) for t in tasks]
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(_one, tasks))

    @staticmethod
    def _collect(seen: dict, posts: List[RedditPost], source: str) -> None:
        for post in posts:
            if post.id and post.id not in seen:
                seen[post.id] = Lead(post=post, source_query=source,
                                     stage=Stage.DISCOVERED.value)

    def _build_queries(self) -> List[tuple[str, str]]:
        """Cross keywords with target subreddits (or global search if none)."""
        keywords = self.campaign.keywords or [self.campaign.product]
        subreddits = self.campaign.subreddits or [""]
        pairs: List[tuple[str, str]] = []
        for kw in keywords:
            for sub in subreddits:
                pairs.append((kw, sub))
        return pairs
