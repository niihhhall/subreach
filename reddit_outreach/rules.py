# -*- coding: utf-8 -*-
"""Per-subreddit rule awareness.

ICP-targeted outreach touches *many* subreddits, and each one has its own rules
(no links, no self-promotion, karma/age gates, required flair, ...). Hand-writing
a rulebook per subreddit does not scale, and breaking a sub's rules is the #1
cause of the AutoMod removals the health layer detects. So this module takes a
scalable stance:

1. **Strict-by-default floor** — for any subreddit we don't have explicit rules
   for, assume the strictest common policy: no links, no self-promotion, no
   required-flair claims. A genuinely value-first comment passes almost every
   subreddit under this floor, so we're safe everywhere by default.

2. **Config overrides** — the operator can *relax* specific subs (or tighten
   them) via ``campaign.subreddit_rules``. You only special-case the handful of
   subs that need it, not all of them.

3. **Fetched rules (seam)** — a cache slot for rules pulled from Reddit's
   ``/r/<sub>/about/rules.json`` via an authenticated backend. That live fetch
   is deferred until the authenticated read path lands (anonymous reddit JSON is
   403-blocked), but the resolver and cache are ready for it.

Enforcement lives in two places that mirror the health split:
  * :class:`ComplianceAgent` applies the *content* rules (links / self-promo /
    phrases / flair) to each draft.
  * :meth:`HealthMonitor.guard_send` applies the *behavioral* rules (per-sub
    send cap, karma/age gates) and the auto-bench closed loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Tuple


@dataclass
class SubredditRule:
    """Effective rule for one subreddit. Dataclass defaults *are* the strict floor."""

    subreddit: str = ""
    allow_links: bool = False
    allow_self_promo: bool = False
    requires_flair: bool = False
    min_comment_karma: int = 0
    min_account_age_days: int = 0
    max_sends_per_day: int = 0            # 0 => no per-sub override
    extra_disallowed_phrases: List[str] = field(default_factory=list)
    rules_text: str = ""                  # raw rules (for LLM adaptation); filled by fetch later
    source: str = "default"               # default | config | fetched
    notes: str = ""

    def constraints_prompt(self) -> str:
        """A short natural-language constraint string for LLM-adapted drafting."""
        bits = []
        if not self.allow_links:
            bits.append("do NOT include any links")
        if not self.allow_self_promo:
            bits.append("do NOT mention or promote any product/tool")
        if self.requires_flair:
            bits.append("this subreddit requires post flair")
        if self.extra_disallowed_phrases:
            bits.append("avoid these phrases: " + ", ".join(self.extra_disallowed_phrases))
        base = f"Subreddit r/{self.subreddit} rules — " + "; ".join(bits) if bits else ""
        if self.rules_text:
            base += f"\nSubreddit rules text:\n{self.rules_text.strip()}"
        return base


# fields that a config/fetched override may set on a rule
_OVERRIDABLE = {f.name for f in fields(SubredditRule)} - {"subreddit", "source"}


def _norm(sub: str) -> str:
    return (sub or "").replace("r/", "").strip()


def resolve_rule(campaign, subreddit: str, *, fetched: Dict[str, Any] | None = None) -> SubredditRule:
    """Resolve the effective rule for a subreddit.

    Precedence (lowest to highest): strict-by-default floor -> fetched rules
    (from cache) -> explicit ``campaign.subreddit_rules`` override.
    """
    sub = _norm(subreddit)
    strict = getattr(campaign, "strict_by_default", True)

    # floor: strict = defaults; lenient = links/promo allowed unless a rule says no
    rule = SubredditRule(subreddit=sub)
    if not strict:
        rule.allow_links = True
        rule.allow_self_promo = True

    if fetched:
        _apply(rule, fetched)
        rule.source = "fetched"

    override = _match_override(getattr(campaign, "subreddit_rules", {}) or {}, sub)
    if override:
        _apply(rule, override)
        rule.source = "config"

    return rule


def _match_override(overrides: Dict[str, Any], sub: str) -> Dict[str, Any] | None:
    for key, val in overrides.items():
        if _norm(key).lower() == sub.lower() and isinstance(val, dict):
            return val
    return None


def _apply(rule: SubredditRule, data: Dict[str, Any]) -> None:
    for key, val in data.items():
        if key in _OVERRIDABLE and val is not None:
            setattr(rule, key, val)


def check_content(rule: SubredditRule, draft_body: str, product: str = "") -> Dict[str, List[str]]:
    """Check a draft against a subreddit's content rules.

    Returns ``{"reject": [...], "warn": [...]}``. ``reject`` issues are hard
    violations (the draft would almost certainly be removed); ``warn`` issues
    need a human's attention but don't auto-reject.
    """
    reject: List[str] = []
    warn: List[str] = []
    body = draft_body or ""
    lower = body.lower()

    links = len(re.findall(r"https?://", lower))
    if links and not rule.allow_links:
        reject.append(f"r/{rule.subreddit}: links are not allowed here")

    if not rule.allow_self_promo and product and product.lower() in lower:
        reject.append(f"r/{rule.subreddit}: self-promotion not allowed (mentions the product)")

    for phrase in rule.extra_disallowed_phrases:
        if phrase and phrase.lower() in lower:
            reject.append(f"r/{rule.subreddit}: contains disallowed phrase '{phrase}'")

    if rule.requires_flair:
        warn.append(f"r/{rule.subreddit}: requires post flair — set it before sending")

    return {"reject": reject, "warn": warn}


def should_bench(removed: int, total: int, *, rate: float = 0.5, min_samples: int = 4) -> bool:
    """Closed loop: has this subreddit removed enough of our sends to bench it?"""
    if total < min_samples:
        return False
    return (removed / total) >= rate
