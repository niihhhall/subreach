# -*- coding: utf-8 -*-
"""Campaign and runtime configuration.

A campaign describes *who* you want to reach and *what* value you offer. It is
the single source of truth every agent reads — the ICP, the keywords to search,
the target subreddits, the value proposition, and the guardrails.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def _load_yaml_or_json(path: str) -> Dict[str, Any]:
    """Load a campaign file. Uses PyYAML if available, else falls back to JSON."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
            return yaml.safe_load(text) or {}
        except ImportError:
            raise SystemExit(
                "This campaign is YAML but PyYAML is not installed.\n"
                "Install it with `pip install pyyaml`, or convert the file to JSON."
            )
    return json.loads(text)


@dataclass
class Campaign:
    """Everything the agents need to know about a single outreach campaign."""

    name: str
    product: str                              # what you're offering, one line
    value_proposition: str                    # why it helps the target
    icp: str                                   # ideal customer profile, prose
    keywords: List[str] = field(default_factory=list)
    subreddits: List[str] = field(default_factory=list)

    # feed-based discovery: browse these subreddits' feeds directly
    feed_subreddits: List[str] = field(default_factory=list)
    feed_sort: str = "hot"                     # hot | new | top | rising

    # guardrails
    min_fit_score: int = 55                    # below this = disqualified
    max_leads_per_run: int = 25
    tone: str = "helpful, peer-to-peer, no hard selling"
    disallowed_phrases: List[str] = field(default_factory=lambda: [
        "buy now", "limited time", "act now", "guaranteed", "cheap",
    ])
    outreach_kind: str = "comment"             # "comment" | "dm"
    signature: str = ""                        # optional, appended to drafts

    # human "brain" for comments: em-dashes are ALWAYS stripped; these tune the
    # casual style + occasional harmless typo so comments read like a real person.
    humanize_comments: bool = True             # lowercase starts, dropped periods, casual
    humanize_typo_rate: float = 0.2            # 0 = pristine; ~0.2 = the odd human slip

    # account-health / anti-shadowban guardrails (see health.py for defaults)
    max_sends_per_day: int = 0                 # 0 -> use health.py default
    max_sends_per_subreddit_per_day: int = 0   # 0 -> use health.py default
    min_seconds_between_sends: int = 0          # 0 -> use health.py default
    warmup_days: int = 0                        # 0 -> use health.py default
    warmup_max_sends_per_day: int = 0           # 0 -> use health.py default
    verify_sends: bool = True                  # re-fetch thread to confirm a comment landed

    # per-subreddit rule awareness (see rules.py)
    strict_by_default: bool = True             # unknown subs -> strictest policy (no links/promo)
    subreddit_rules: Dict[str, Any] = field(default_factory=dict)  # sub -> rule overrides
    use_scouted_subreddits: bool = True        # discovery also reads active subs the Scout found
    auto_bench_removal_rate: float = 0.5       # bench a sub above this removal rate
    auto_bench_min_samples: int = 4            # ...once we have at least this many verified sends

    # ── Phase 3: DM outreach (HIGH ban-risk — OFF by default) ──
    dm_enabled: bool = False                   # must be true AND --confirm to actually DM
    max_dms_per_day: int = 5                   # hard daily cap on cold DMs (very conservative)
    dm_opt_out: str = ("No worries at all if this isn't relevant — just ignore this "
                       "and I won't follow up.")  # low-pressure out, appended to every DM
    dm_signature: str = ""                     # optional disclosure line for DMs

    # ── Phase 4: handoff to Markeye (the WhatsApp AI SDR) ──
    # We do NOT run the SDR sequence here — we POST a signed payload to Markeye's
    # webhook and it takes over (BANT/Calendly/5-msg live in Markeye).
    handoff_enabled: bool = True
    handoff_webhook_url: str = ""              # blank -> env MARKEYE_WEBHOOK_URL -> dry-run
    handoff_secret: str = ""                   # blank -> env MARKEYE_WEBHOOK_SECRET (HMAC sign)

    @classmethod
    def load(cls, path: str) -> "Campaign":
        if not os.path.exists(path):
            raise SystemExit(f"Campaign file not found: {path}")
        data = _load_yaml_or_json(path)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(data) - known
        if unknown:
            raise SystemExit(f"Unknown campaign keys: {', '.join(sorted(unknown))}")
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Settings:
    """Runtime settings resolved from env vars with sensible defaults."""

    reddit_backend: str = "auto"               # auto | rdt | opencli | mock
    llm_provider: str = "auto"                 # auto | openai | groq | anthropic | mock
    llm_model: str = ""
    data_dir: str = "data"
    proxy: str = ""
    database_url: str = ""                     # set -> use Supabase/Postgres instead of SQLite

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            reddit_backend=os.environ.get("REDDIT_BACKEND", "auto"),
            llm_provider=os.environ.get("OUTREACH_LLM_PROVIDER", "auto"),
            llm_model=os.environ.get("OUTREACH_LLM_MODEL", ""),
            data_dir=os.environ.get("OUTREACH_DATA_DIR", "data"),
            proxy=os.environ.get("REDDIT_PROXY", os.environ.get("HTTPS_PROXY", "")),
            # Supabase gives you a Postgres connection string (Settings → Database).
            database_url=os.environ.get("DATABASE_URL",
                                        os.environ.get("SUPABASE_DB_URL", "")),
        )
