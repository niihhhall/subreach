# -*- coding: utf-8 -*-
"""SubredditScoutAgent — niche-mining subreddit discovery from the ICP.

Production-grade targeting engine:

  1. **Derive verticals** — from the ICP (LLM) or an explicit list, so we know
     which industries to niche into (solar, roofing, HVAC, logistics, ...).
  2. **Niche down per vertical** — brainstorm the niche subreddits *inside* each
     vertical (concurrently), not just one generic pass, so deep niches surface.
  3. **Validate** — probe every candidate's live feed; empty/nonexistent subs
     (e.g. the dead ``r/Dentistry``) are dropped.
  4. **Rank + dedup** — active, high-relevance subs float up; duplicates across
     verticals collapse to the best entry.

The caller persists results and can auto-apply them to the campaign.
Runs occasionally (e.g. weekly), not every watch cycle.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .base import BaseAgent

# fallback verticals if there's no LLM to derive them
_DEFAULT_VERTICALS = [
    "home services", "real estate", "mortgage & lending", "medical & dental clinics",
    "med spa & aesthetics", "legal", "fitness & wellness", "solar & renewables",
    "automotive", "logistics & freight", "manufacturing", "marketing agencies",
]


class SubredditScoutAgent(BaseAgent):
    role = "scout"

    def __init__(self, campaign, reddit, llm=None):
        super().__init__(campaign, llm)
        self.reddit = reddit

    def run(self, *, verticals: Optional[List[str]] = None,
            per_vertical: int = 10, validate: bool = True) -> List[Dict[str, Any]]:
        verticals = verticals or self._derive_verticals()

        # brainstorm each vertical concurrently, then a general ICP pass
        passes = [(v, v) for v in verticals] + [(None, "general")]
        merged: Dict[str, Dict[str, Any]] = {}

        def _do(pass_):
            vertical, label = pass_
            return label, self._brainstorm(per_vertical, vertical)

        with ThreadPoolExecutor(max_workers=6) as ex:
            for label, cands in ex.map(_do, passes):
                for c in cands:
                    key = c["name"].lower()
                    c["vertical"] = label
                    # keep the highest-relevance entry per subreddit
                    if key not in merged or c["relevance"] > merged[key]["relevance"]:
                        merged[key] = c

        candidates = list(merged.values())
        if not candidates:
            candidates = self._heuristic_candidates()
        if validate:
            self._validate(candidates)
        candidates.sort(
            key=lambda c: (1 if c.get("active") else 0, c.get("relevance", 0)),
            reverse=True,
        )
        return candidates

    # ── derive verticals from the ICP ─────────────────────────────────
    def _derive_verticals(self) -> List[str]:
        if not self.uses_llm:
            return _DEFAULT_VERTICALS
        system = (
            "You identify the distinct industry verticals a product's ideal "
            "customers belong to. Return concise, real industry names.\n"
            + self._campaign_brief()
        )
        user = (
            "List the 8-14 industry verticals whose businesses match this ICP and "
            'feel this pain. Return JSON: {"verticals": ["...", "..."]}'
        )
        data = self.llm.json_complete(system, user)
        vs = (data or {}).get("verticals") if isinstance(data, dict) else None
        out = [str(v).strip() for v in (vs or []) if str(v).strip()]
        return out[:14] or _DEFAULT_VERTICALS

    # ── brainstorm niche subs for one vertical ────────────────────────
    def _brainstorm(self, n: int, vertical: Optional[str]) -> List[Dict[str, Any]]:
        if not self.uses_llm:
            return []
        focus = (
            f"Focus specifically on the '{vertical}' vertical — find the niche and "
            f"sub-niche subreddits where {vertical} business owners/operators gather."
            if vertical else
            "Find broad subreddits where this ICP posts about the pain."
        )
        system = (
            "You are a Reddit growth strategist. Find subreddits where a product's "
            "ideal customers actively post about the problems it solves — prefer "
            "niche, active, practitioner communities over huge generic ones.\n"
            + self._campaign_brief()
        )
        user = (
            f"{focus}\nList up to {n} subreddits. Use exact names WITHOUT 'r/'. "
            'Return JSON: {"subreddits": [{"name": "...", "relevance": 0-100, "reason": "..."}]}'
        )
        data = self.llm.json_complete(system, user)
        raw = (data or {}).get("subreddits") if isinstance(data, dict) else None
        out: List[Dict[str, Any]] = []
        for s in raw or []:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).replace("r/", "").strip()
            if not name:
                continue
            try:
                relevance = int(s.get("relevance", 50) or 50)
            except (ValueError, TypeError):
                relevance = 50
            out.append({
                "name": name,
                "relevance": max(0, min(100, relevance)),
                "reason": str(s.get("reason", ""))[:140],
            })
        return out[:n]

    def _heuristic_candidates(self) -> List[Dict[str, Any]]:
        subs = list(dict.fromkeys(
            [*self.campaign.feed_subreddits, *self.campaign.subreddits]))
        return [{"name": s, "relevance": 50, "reason": "from campaign config",
                 "vertical": "general"} for s in subs]

    # ── validate against the live backend ─────────────────────────────
    def _validate(self, candidates: List[Dict[str, Any]], max_workers: int = 6) -> None:
        try:
            self.reddit.warm()
        except Exception:
            pass

        def probe(c: Dict[str, Any]) -> Dict[str, Any]:
            try:
                posts = self.reddit.feed(c["name"], sort="new", limit=3)
                c["active"] = len(posts) > 0
                c["sample_count"] = len(posts)
            except Exception:
                c["active"] = False
                c["sample_count"] = 0
            return c

        if len(candidates) <= 1:
            for c in candidates:
                probe(c)
            return
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(probe, candidates))
