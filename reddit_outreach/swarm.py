# -*- coding: utf-8 -*-
"""Warm-up swarm — rotate several Reddit accounts to build genuine karma/CQS.

The goal is *legitimate* account warm-up: each account posts a few genuinely
helpful, on-topic, NON-promotional comments per day in its OWN set of
subreddits, so it accrues real karma before you ever use it for outreach.

What this is NOT (and will not do), because it's what gets accounts nuked:
  * no cross-account voting or commenting on each other's posts (vote
    manipulation / ban-evasion — Reddit links and bans the whole cluster);
  * no product mentions or links during warm-up (pure reputation building);
  * no synchronized bursts — actions are jittered and per-account capped.

Each account:
  * uses its OWN Zernio key (``ZernioClient(api_key=...)``);
  * is scoped to its OWN subreddits (overlap is flagged);
  * is gated by its OWN circuit breaker + OWN daily comment cap (the activity
    log is namespaced by account id);
  * has every posted comment verified for visibility, so a silent removal spike
    trips that account's breaker instead of burning it for days.

Dry-run by default. Real posting needs ``confirm=True`` (the CLI's ``--confirm``).
"""

from __future__ import annotations

import dataclasses
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .agents import (CommentWriterAgent, DiscoveryAgent, EngagementAgent,
                     ReplyWriterAgent)
from .config import Campaign, Settings
from .health import HealthMonitor
from .llm import LLM
from .models import Stage
from .pacing import HumanPacer, parse_active_hours, within_active_hours
from .personas import resolve_persona
from .reddit_client import RedditClient
from .sender import zernio_comment
from .store import open_store
from .zernio import ZernioClient


@dataclass
class WarmAccount:
    label: str
    email: str = ""
    reddit_id: str = ""
    api_key: str = ""
    api_key_env: str = ""
    subreddits: List[str] = field(default_factory=list)
    max_comments_per_day: int = 4
    active_start: Optional[int] = None   # local hour the account "wakes up"
    active_end: Optional[int] = None     # local hour it "sleeps"
    tz_offset: float = 0.0               # hours from UTC for this persona
    persona: str = ""                    # persona preset name (operator/marketer/tradesman)

    @property
    def key(self) -> str:
        """Store key for health/reputation/send-count — matches HealthMonitor."""
        return self.reddit_id or self.label or "default"

    @property
    def usable(self) -> bool:
        return bool(self.api_key and self.subreddits)

    def awake(self, now: Optional[float] = None) -> bool:
        return within_active_hours(self.active_start, self.active_end,
                                   now=now, tz_offset_hours=self.tz_offset)


def load_accounts(path: str = "accounts.yaml") -> Tuple[List[WarmAccount], List[str]]:
    """Load the roster; resolve each key from the env var named by api_key_env.

    Source precedence (cloud-friendly): the ``SWARM_ACCOUNTS`` env var (JSON or
    YAML string) wins over the file, so PaaS deploys (Heroku/Render) can carry
    the roster without a committed file. Never raises for a bad/missing key —
    the swarm runs the accounts that ARE configured and reports the rest.
    """
    warnings: List[str] = []
    import yaml  # pyyaml is a hard dep of this project

    # SWARM_ACCOUNTS_B64 (base64 of the JSON/YAML roster) is the cloud-safe path:
    # multi-line env vars get mangled by some shells, base64 is a single clean token.
    env_roster = ""
    b64 = os.environ.get("SWARM_ACCOUNTS_B64", "").strip()
    if b64:
        import base64
        try:
            env_roster = base64.b64decode(b64).decode("utf-8")
        except Exception as exc:
            return [], [f"SWARM_ACCOUNTS_B64 could not be decoded: {exc}"]
    env_roster = env_roster or os.environ.get("SWARM_ACCOUNTS", "").strip()
    if env_roster:
        try:
            data = yaml.safe_load(env_roster) or {}   # yaml.safe_load also parses JSON
        except Exception as exc:
            return [], [f"SWARM_ACCOUNTS could not be parsed: {exc}"]
    elif os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        return [], [f"roster not found: {path} (copy accounts.example.yaml, "
                    f"or set the SWARM_ACCOUNTS env var)"]

    accounts: List[WarmAccount] = []
    for raw in data.get("accounts", []):
        env_name = raw.get("api_key_env", "")
        api_key = os.environ.get(env_name, "") if env_name else raw.get("api_key", "")
        start, end = parse_active_hours(raw.get("active_hours"))
        acct = WarmAccount(
            label=str(raw.get("label", "") or raw.get("email", "acct")),
            email=str(raw.get("email", "")),
            reddit_id=str(raw.get("zernio_reddit_id", "") or raw.get("reddit_id", "")),
            api_key=api_key,
            api_key_env=env_name,
            subreddits=[s.replace("r/", "").strip()
                        for s in (raw.get("subreddits") or []) if s.strip()],
            max_comments_per_day=int(raw.get("max_comments_per_day", 4) or 4),
            active_start=start,
            active_end=end,
            tz_offset=float(raw.get("tz_offset", 0) or 0),
            persona=str(raw.get("persona", "")),
        )
        if not api_key:
            warnings.append(f"{acct.label}: no API key (env {env_name!r} is unset) — skipped")
        if not acct.subreddits:
            warnings.append(f"{acct.label}: no subreddits assigned — skipped")
        accounts.append(acct)

    warnings.extend(overlap_warnings(accounts))
    return accounts, warnings


def overlap_warnings(accounts: List[WarmAccount]) -> List[str]:
    """Flag subreddits assigned to more than one account (cluster risk)."""
    seen: Dict[str, List[str]] = {}
    for a in accounts:
        for s in a.subreddits:
            seen.setdefault(s.lower(), []).append(a.label)
    out = []
    for sub, labels in seen.items():
        if len(labels) > 1:
            out.append(f"OVERLAP: r/{sub} shared by {', '.join(labels)} — give each "
                       f"account distinct subs to avoid looking like a cluster")
    return out


def ramp_cap(max_cap: int, age_days: float) -> int:
    """Warm-up ramp: don't let a brand-new account post at full volume. Start
    low and grow to the ceiling as the account ages and proves healthy."""
    if age_days < 3:
        return min(max_cap, 4)
    if age_days < 7:
        return min(max_cap, 6)
    if age_days < 14:
        return min(max_cap, 10)
    return max_cap


def find_reply_targets(comments, *, our_username: str, our_comment_ids,
                       op_author: str, answered_ids) -> list:
    """Which comments deserve a follow-up: true replies to our comment (when the
    backend gives parent ids) first, then the OP re-engaging in the thread. Skips
    our own comments and ones we've already answered."""
    uname = (our_username or "").lower()
    ours = {x for x in (our_comment_ids or []) if x}
    answered = set(answered_ids or [])
    op = (op_author or "").lower()
    direct, op_hits = [], []
    for c in comments or []:
        if not getattr(c, "body", ""):
            continue
        author = (getattr(c, "author", "") or "").lower()
        if author and author == uname:
            continue                                  # our own comment
        if getattr(c, "id", "") and c.id in answered:
            continue                                  # already followed up
        if getattr(c, "parent_id", "") and c.parent_id in ours:
            direct.append(c)                          # a real reply to us
        elif op and author == op:
            op_hits.append(c)                         # OP re-engaged the thread
    return direct + op_hits


class SwarmRunner:
    """Runs the warm-up cycle across a roster of accounts (one shared store,
    namespaced per account)."""

    def __init__(self, campaign: Campaign, settings: Settings):
        self.campaign = campaign
        self.settings = settings
        self.llm = LLM(settings.llm_provider, settings.llm_model)
        self.store = open_store(settings, campaign.name)

    def close(self) -> None:
        self.store.close()

    def _scoped(self, subs: List[str]) -> Campaign:
        """A campaign copy scoped to one account's subs, warm-up-safe (no promo,
        no keyword sprawl, no scouted-sub union)."""
        return dataclasses.replace(
            self.campaign,
            subreddits=list(subs),
            feed_subreddits=list(subs),
            keywords=[],                     # feed-only within the assigned subs
            use_scouted_subreddits=False,
            signature="",                    # warm-up = zero self-promo
            strict_by_default=True,
        )

    def _account_age_days(self, acct: WarmAccount) -> float:
        """How long we've been warming this account (proxy: first_seen locally)."""
        for a in self.store.accounts():
            if a.get("account_id") == acct.reddit_id:
                fs = a.get("first_seen") or 0
                if fs:
                    return max(0.0, (time.time() - float(fs)) / 86400.0)
        return 0.0

    def _reply_targets_for_post(self, *, zernio, reddit, post_id, subreddit,
                                account_id, our_ids, username, op_author, answered):
        """Replies worth answering. PRECISE path (Zernio Inbox): fetch the replies
        sitting directly under each of our comments via comment_id, so we only
        answer genuine replies to us. Falls back to OP-re-engagement on a flat
        thread read when the precise path isn't available or finds nothing."""
        uname = (username or "").lower()
        if zernio is not None and getattr(zernio, "configured", False):
            targets, seen = [], set()
            for cid in sorted(x for x in our_ids if x):
                try:
                    replies = zernio.get_post_comments(
                        post_id, account_id, subreddit=subreddit,
                        comment_id=cid, limit=25)
                except Exception:
                    replies = []
                for c in replies:
                    if (getattr(c, "author", "") or "").lower() == uname:
                        continue                      # our own comment, not a reply
                    if not getattr(c, "body", ""):
                        continue
                    if c.id and (c.id in answered or c.id in seen):
                        continue
                    c.parent_id = cid                 # it's a reply to our comment
                    seen.add(c.id)
                    targets.append(c)
            if targets:
                return targets
        # fallback: OP re-engagement from a flat thread read
        try:
            _post, comments = reddit.read(post_id)
        except Exception:
            comments = []
        return find_reply_targets(comments, our_username=username,
                                  our_comment_ids=set(our_ids), op_author=op_author,
                                  answered_ids=answered)

    def _reply_pass(self, *, acct, zernio, reddit, account_id, username, persona,
                    reply_writer, pacer, budget: int, confirm: bool,
                    res: Dict[str, Any]) -> int:
        """Follow up on replies to this account's recent comments (max 1 per
        thread per cycle). Threaded via comment_id so it pings the person. Counts
        toward the same daily cap. Returns how many we posted/queued."""
        if budget <= 0:
            return 0
        cutoff = time.time() - 3 * 86400
        acts = self.store.recent_activities(limit=300, action="sent")
        ours: Dict[str, set] = {}
        for a in acts:
            if (a.get("channel") == "comment" and a.get("account") == acct.key
                    and (a.get("ts") or 0) >= cutoff and a.get("post_id")):
                ours.setdefault(a["post_id"], set()).add(a.get("ref") or "")
        if not ours:
            return 0
        answered = {a.get("ref") for a in
                    self.store.recent_activities(limit=300, action="reply_ack")}

        posted = 0
        for post_id, our_ids in ours.items():
            if posted >= budget:
                break
            lead = self.store.get(post_id)
            title = lead.post.title if lead else ""
            sub = lead.post.subreddit if lead else ""
            op_author = lead.post.author if lead else ""
            targets = self._reply_targets_for_post(
                zernio=zernio, reddit=reddit, post_id=post_id, subreddit=sub,
                account_id=account_id, our_ids=our_ids, username=username,
                op_author=op_author, answered=answered)
            for t in targets[:1]:                     # at most one follow-up per thread
                if posted >= budget:
                    break
                pacer.read(t.body)
                pacer.think()
                draft = reply_writer.run(thread_title=title, our_comment="",
                                         reply_author=t.author, reply_body=t.body,
                                         persona=persona)
                if not (draft and draft.body):
                    continue
                if not confirm:
                    res["reply_dryrun"] += 1
                    answered.add(t.id)
                    posted += 1
                    continue
                pacer.typing(draft.body)
                try:
                    r = zernio.reply_to_post(post_id, account_id, draft.body,
                                             comment_id=t.id)
                    ref = str(r.get("commentId", "")) if isinstance(r, dict) else ""
                except Exception as exc:
                    res["notes"].append(
                        f"reply error {post_id}: {type(exc).__name__}: {exc}")
                    continue
                posted += 1
                res["reply_posted"] += 1
                answered.add(t.id)
                self.store.log_activity(
                    "sent", channel="comment", post_id=post_id, subreddit=sub,
                    author=t.author, account=acct.key, ref=ref, status="posted",
                    detail=f"reply to u/{t.author}")
                self.store.log_activity(
                    "reply_ack", post_id=post_id, account=acct.key, ref=t.id,
                    status="posted", detail="answered a reply")
                br = self.store.breaker_state(acct.key)
                if br and br.get("breaker_tripped"):
                    res["notes"].append("breaker tripped during replies, stopping")
                    return posted
                pacer.rest()
        return posted

    def warm_account(self, acct: WarmAccount, *, limit_per_query: int = 6,
                     budget: Optional[int] = None, confirm: bool = False,
                     pacer: Optional[HumanPacer] = None) -> Dict[str, Any]:
        res: Dict[str, Any] = {"label": acct.label, "subreddits": acct.subreddits,
                               "engageable": 0, "drafted": 0, "posted": 0,
                               "dryrun": 0, "blocked": 0, "cap": 0, "sent_today": 0,
                               "reply_posted": 0, "reply_dryrun": 0, "notes": []}
        if not acct.usable:
            res["notes"].append("not usable (missing key or subreddits)")
            return res

        # human personas don't post at 4am — respect the account's active window
        if confirm and not acct.awake():
            res["notes"].append(
                f"outside active hours ({acct.active_start}-{acct.active_end}, "
                f"tz{acct.tz_offset:+g}) — skipping this cycle")
            return res

        pacer = pacer or HumanPacer(enabled=confirm)
        budget = budget or acct.max_comments_per_day

        # this account's own breaker
        breaker = self.store.breaker_state(acct.key)
        if breaker and breaker.get("breaker_tripped"):
            resume = breaker.get("resume_after") or 0
            if resume and time.time() < resume:
                res["notes"].append(f"breaker OPEN until {time.strftime('%Y-%m-%d %H:%M', time.localtime(resume))}: {breaker.get('reason','')}")
                return res
            self.store.reset_breaker(acct.key)  # cooldown elapsed

        # daily cap, RAMPED by account age: start low, grow to the ceiling as the
        # account earns trust (weeks 1->2->3+). Comments + replies share this cap.
        now = time.time()
        age_days = self._account_age_days(acct)
        eff_cap = ramp_cap(acct.max_comments_per_day, age_days)
        sent_today = self.store.count_sends(since_ts=now - 86400,
                                            account=acct.key, channel="comment")
        remaining = max(0, eff_cap - sent_today)
        res["cap"] = eff_cap
        res["sent_today"] = sent_today
        if remaining <= 0:
            res["notes"].append(
                f"daily cap reached ({sent_today}/{eff_cap} at age {age_days:.0f}d)")
            return res

        zernio = ZernioClient(api_key=acct.api_key)
        reddit = RedditClient(self.settings.reddit_backend, proxy=self.settings.proxy,
                              zernio=zernio)
        self.store.record_account(acct.reddit_id, "reddit", acct.label, "")
        camp = self._scoped(acct.subreddits)
        persona = resolve_persona(acct.persona)
        discovery = DiscoveryAgent(camp, reddit, self.llm)
        engagement = EngagementAgent(camp, self.llm)
        writer = CommentWriterAgent(camp, reddit, self.llm)
        reply_writer = ReplyWriterAgent(camp, reddit, self.llm)
        monitor = HealthMonitor(camp, self.store, proxy=self.settings.proxy,
                                account_id=acct.reddit_id, username=acct.label,
                                reddit=reddit)

        # resolve this account's real Reddit username + id (skip our own comments,
        # thread replies correctly)
        acct_info = {}
        if zernio.configured:
            try:
                acct_info = zernio.find_reddit_account() or {}
            except Exception:
                acct_info = {}
        username = acct_info.get("username", "") or acct.label
        z_account_id = acct_info.get("_id", "") or acct.reddit_id

        # ── reply-back pass FIRST (continuing a convo beats a new drive-by) ──
        replied = self._reply_pass(
            acct=acct, zernio=zernio, reddit=reddit, account_id=z_account_id,
            username=username, persona=persona, reply_writer=reply_writer,
            pacer=pacer, budget=remaining, confirm=confirm, res=res)
        remaining = max(0, remaining - replied)

        subset = {s.lower() for s in acct.subreddits}

        # ── discover in this account's subs, score engagement ──
        # Only THIS cycle's fresh finds are scored (upsert returns the stored
        # lead, so we keep references to the ones actually new to the store) —
        # never the whole historical DISCOVERED backlog, which would fire dozens
        # of LLM calls and blow the cycle time.
        try:
            new_leads = discovery.run(limit_per_query=limit_per_query)
        except Exception as exc:
            res["notes"].append(f"discovery error: {type(exc).__name__}: {exc}")
            return res
        fresh = []
        for l in new_leads:
            stored = self.store.upsert(l)
            if stored is l and (l.post.subreddit or "").lower() in subset \
                    and l.stage == Stage.DISCOVERED.value:
                fresh.append(l)
        self.store.save()

        # cap engagement scoring hard (warm-up cycles must stay fast + cheap)
        max_score = max(budget * 4, 8)
        candidates = fresh
        if engagement.uses_llm and len(fresh) > max_score:
            candidates = [l for l in fresh if engagement._heuristic(l).is_asking][:max_score] \
                or fresh[:max_score]
        for l in candidates:
            try:
                engagement.run(l)
            except Exception as exc:
                l.notes.append(f"engagement error: {exc}")
        self.store.save()

        engageable = sorted(
            [l for l in candidates if l.engagement and l.engagement.verdict == "engage"],
            key=lambda l: l.engagement.score, reverse=True)
        res["engageable"] = len(engageable)

        # ── new comments with whatever cap is left after replies ──
        cap = remaining
        recent_styles: List[str] = []
        posted = 0
        for lead in engageable:
            if posted >= cap:
                break

            # act like a person: read the thread, think, then write
            pacer.read(f"{lead.post.title}\n{lead.post.selftext}")
            pacer.think()
            writer.run(lead, style_history=recent_styles, persona=persona)
            q = lead.comment_quality
            if not (lead.draft and lead.draft.body and q and q.verdict == "ready"):
                continue
            recent_styles.append(lead.draft.body)
            res["drafted"] += 1

            if not confirm:
                res["dryrun"] += 1
                posted += 1
                continue

            pacer.typing(lead.draft.body)   # time proportional to comment length

            try:
                result = zernio_comment(lead, zernio, confirm=True)
            except Exception as exc:        # never let one bad post kill the account
                res["blocked"] += 1
                res["notes"].append(f"post error {lead.post.id}: {type(exc).__name__}: {exc}")
                continue

            if result.ok:
                lead.sent_at = time.time()
                lead.sent_ref = "comment"
                lead.stage = Stage.SENT.value
                posted += 1
                res["posted"] += 1
            else:
                res["blocked"] += 1
                res["notes"].append(result.message[:120])
            self.store.save()
            self.store.log_activity(
                "sent", channel="comment", post_id=lead.post.id,
                subreddit=lead.post.subreddit, author=lead.post.author,
                account=acct.key, ref=result.ref, status=result.status,
                detail=f"warm-up: {result.message[:140]}")
            if result.ok:
                try:
                    check = monitor.verify_after_send(lead, result)
                    self.store.save()
                    res["notes"].append(f"verify {lead.post.id}: {check.note}")
                except Exception:
                    pass
            # if the account's breaker tripped mid-cycle (removal spike), stop now
            br = self.store.breaker_state(acct.key)
            if br and br.get("breaker_tripped"):
                res["notes"].append("breaker tripped mid-cycle — stopping this account")
                break
            if posted < cap:
                pacer.rest()                # step away before the next comment
        return res

    def warm_cycle(self, accounts: List[WarmAccount], *, limit_per_query: int = 6,
                   confirm: bool = False, pacer: Optional[HumanPacer] = None
                   ) -> List[Dict[str, Any]]:
        pacer = pacer or HumanPacer(enabled=confirm)
        results = []
        usable = [a for a in accounts if a.usable]
        random.shuffle(usable)  # don't always start with the same account
        for i, acct in enumerate(usable):
            try:
                results.append(self.warm_account(
                    acct, limit_per_query=limit_per_query, confirm=confirm, pacer=pacer))
            except Exception as exc:   # one account's failure never kills the cycle
                results.append({"label": acct.label, "subreddits": acct.subreddits,
                                "engageable": 0, "drafted": 0, "posted": 0,
                                "dryrun": 0, "blocked": 0,
                                "notes": [f"cycle error: {type(exc).__name__}: {exc}"]})
            if confirm and i < len(usable) - 1:
                pacer.account_gap()        # human gap before switching accounts
        # include skipped (unusable) accounts in the report
        for acct in accounts:
            if not acct.usable:
                results.append({"label": acct.label, "subreddits": acct.subreddits,
                                "engageable": 0, "drafted": 0, "posted": 0,
                                "dryrun": 0, "blocked": 0,
                                "notes": ["skipped — missing key or subreddits"]})
        return results
