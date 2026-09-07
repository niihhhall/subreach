# -*- coding: utf-8 -*-
"""Orchestrator — runs the multi-agent Reddit outreach pipeline.

    discovery -> qualification -> research -> personalization -> compliance

Each stage is resumable: leads are persisted after every stage so a crash or
rate-limit doesn't lose work. Disqualified/rejected leads short-circuit and are
not carried forward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .agents import (
    ComplianceAgent,
    DiscoveryAgent,
    PersonalizationAgent,
    QualificationAgent,
    ResearchAgent,
    SubredditScoutAgent,
    EngagementAgent,
    CommentWriterAgent,
    DMOutreachAgent,
)
from .config import Campaign, Settings
from .llm import LLM
from .models import Lead, Stage
from .reddit_client import RedditClient
from .store import open_store
from .zernio import ZernioClient


@dataclass
class RunReport:
    discovered: int = 0
    qualified: int = 0
    disqualified: int = 0
    researched: int = 0
    drafted: int = 0
    approved: int = 0
    needs_revision: int = 0
    rejected: int = 0
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"discovered={self.discovered} qualified={self.qualified} "
            f"disqualified={self.disqualified} researched={self.researched} "
            f"drafted={self.drafted} approved={self.approved} "
            f"needs_revision={self.needs_revision} rejected={self.rejected}"
        )


class Orchestrator:
    def __init__(self, campaign: Campaign, settings: Settings):
        self.campaign = campaign
        self.settings = settings
        self.llm = LLM(settings.llm_provider, settings.llm_model)
        self.zernio = ZernioClient()
        self.reddit = RedditClient(
            settings.reddit_backend, proxy=settings.proxy, zernio=self.zernio,
        )
        self.store = open_store(settings, campaign.name)

        # base feed list from the campaign; the Scout's DB finds are unioned in
        # on every cycle so the two agents coordinate purely through the store.
        self._base_feed_subreddits = list(campaign.feed_subreddits)

        self.discovery = DiscoveryAgent(campaign, self.reddit, self.llm)
        self.qualification = QualificationAgent(campaign, self.llm)
        self.research = ResearchAgent(campaign, self.reddit, self.llm)
        self.personalization = PersonalizationAgent(campaign, self.llm)
        self.compliance = ComplianceAgent(campaign, self.llm)
        self.scout = SubredditScoutAgent(campaign, self.reddit, self.llm)
        self.engagement = EngagementAgent(campaign, self.llm)
        self.comment_writer = CommentWriterAgent(campaign, self.reddit, self.llm)
        self.dm_writer = DMOutreachAgent(campaign, self.llm)

        # Record which Reddit account we outreach as (for analytics/audit).
        if self.zernio.configured:
            try:
                acct = self.zernio.find_reddit_account()
                if acct:
                    self.store.record_account(
                        acct.get("_id", ""), "reddit",
                        acct.get("username", ""), acct.get("profileId", ""),
                    )
            except Exception:
                pass

    def close(self) -> None:
        self.store.close()

    def environment(self) -> str:
        note = ""
        if self.reddit.backend == "mock":
            note = " (mock — no live data)"
        elif self.reddit.backend == "zernio":
            note = " (live via Zernio; research runs without comments)"
        return (
            f"Reddit backend: {self.reddit.backend}{note}\n"
            f"LLM: {self.llm.provider}"
            f"{'' if self.llm.available else ' (heuristic fallback — no API key)'}"
            f"{f' / {self.llm.model}' if self.llm.available else ''}"
        )

    def _refresh_feeds(self) -> None:
        """Union the campaign's base feeds with active subreddits the Scout has
        written to the DB — so a running watch picks up new subs with no restart.
        """
        if not getattr(self.campaign, "use_scouted_subreddits", True):
            return
        try:
            scouted = [r["subreddit"] for r in self.store.scouted_subreddits(active_only=True)]
        except Exception:
            scouted = []
        seen, merged = set(), []
        for s in [*self._base_feed_subreddits, *scouted]:
            if s.lower() not in seen:
                seen.add(s.lower())
                merged.append(s)
        self.campaign.feed_subreddits = merged

    def find(self, limit_per_query: int = 10) -> List[Lead]:
        """Phase-1 'finding' pass: discovery + qualification ONLY.

        Skips research / drafting / compliance, so it's fast and cheap — the
        loop you use to tune ICP + keywords until the system reliably surfaces
        the exact pain (ads running, leads lost after hours, no qualification).
        Returns qualified leads sorted by priority (highest first).
        """
        self._refresh_feeds()
        new_leads = self.discovery.run(limit_per_query=limit_per_query)
        for lead in new_leads:
            self.store.upsert(lead)
        self.store.save()

        # Qualification is the bottleneck (~10-20s/LLM call). Two-stage funnel:
        # the instant heuristic pre-filters obvious non-prospects / zero-signal
        # posts, so only promising leads hit the LLM. Then qualify those
        # concurrently. Sequential over 100+ posts = timeout; this = a couple min.
        pending = self.store.by_stage(Stage.DISCOVERED.value)
        to_llm = pending
        if self.qualification.uses_llm and len(pending) > 12:
            to_llm = self._prefilter(pending)
        self._qualify_concurrent(to_llm)
        self.store.save()

        qualified = [
            l for l in self.store.all()
            if l.qualification and not l.qualification.disqualified
        ]
        qualified.sort(
            key=lambda l: l.qualification.priority if l.qualification else 0,
            reverse=True,
        )
        self.store.log_activity(
            "find", detail=f"discovered={len(new_leads)} qualified={len(qualified)}")
        return qualified

    def _prefilter(self, leads: List[Lead], max_llm: int = 40) -> List[Lead]:
        """Stage 1 of the funnel: cheap heuristic triage before the expensive LLM.

        Scores every lead with the instant heuristic, drops obvious non-prospects
        / zero-signal posts, and keeps only the top ``max_llm`` by heuristic score.
        This BOUNDS the number of LLM calls (and thus runtime) no matter how many
        subreddits/posts discovery pulled in. Persists decisions immediately so a
        later timeout never loses the prefilter work.
        """
        scored = []
        for lead in leads:
            h = self.qualification._heuristic(lead)
            has_signal = h.is_prospect and (
                h.intent_score >= 20 or h.fit_score >= 40 or bool(h.pain_points)
            )
            score = (h.fit_score + h.intent_score) if has_signal else -1
            scored.append((lead, h, score))

        candidates = sorted((x for x in scored if x[2] >= 0),
                            key=lambda x: x[2], reverse=True)
        survivors = [lead for lead, _, _ in candidates[:max_llm]]
        keep_ids = {id(l) for l in survivors}

        for lead, h, _ in scored:
            if id(lead) not in keep_ids:
                h.disqualified = True
                h.disqualify_reason = "pre-filter: low signal or below LLM budget (heuristic)"
                lead.qualification = h
                lead.stage = Stage.DISQUALIFIED.value

        self.store.save()  # persist prefilter drops now, before the slow LLM stage
        self.store.log_activity(
            "prefilter",
            detail=f"kept={len(survivors)} dropped={len(leads) - len(survivors)} "
                   f"of {len(leads)} (LLM budget={max_llm})")
        return survivors

    def _qualify_concurrent(self, leads: List[Lead], max_workers: int = 8,
                            save_every: int = 12) -> None:
        """Qualify many leads in parallel (safe: each call mutates only its own
        lead, no shared store/Reddit access). Errors on one lead don't sink the
        batch. Persists incrementally so a timeout keeps completed work."""
        if not leads:
            return
        if len(leads) == 1:
            self.qualification.run(leads[0])
            self.store.save()
            return
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _safe(lead: Lead) -> None:
            try:
                self.qualification.run(lead)
            except Exception as exc:  # keep the batch alive
                lead.notes.append(f"qualification error: {exc}")

        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_safe, lead) for lead in leads]
            for _ in as_completed(futures):
                done += 1
                if done % save_every == 0:
                    self.store.save()
        self.store.save()

    def engage(self, limit_per_query: int = 10, max_llm: int = 40) -> List[Lead]:
        """Phase-2 engagement pass: find threads worth a genuine reputation-
        building comment. Discovery → cheap is-asking prefilter → engagement-score
        the promising ones → return 'engage'-verdict leads by score. No sending
        (dry-run); commenting is a separate, health-gated step."""
        self._refresh_feeds()
        new_leads = self.discovery.run(limit_per_query=limit_per_query)
        for lead in new_leads:
            self.store.upsert(lead)
        self.store.save()

        pending = self.store.by_stage(Stage.DISCOVERED.value)
        # cheap prefilter: only score threads that look like questions/discussions
        candidates = pending
        if self.engagement.uses_llm and len(pending) > max_llm:
            candidates = [
                l for l in pending
                if self.engagement._heuristic(l).is_asking
            ][:max_llm] or pending[:max_llm]

        self._score_engagement_concurrent(candidates)
        self.store.save()

        engageable = [
            l for l in self.store.all()
            if l.engagement and l.engagement.verdict == "engage"
        ]
        engageable.sort(key=lambda l: l.engagement.score if l.engagement else 0, reverse=True)
        self.store.log_activity(
            "engage", detail=f"scored={len(candidates)} engageable={len(engageable)}")
        return engageable

    def write_comments(self, leads: List[Lead], budget: int = 5) -> None:
        """Draft engagement comments for the top engageable leads (dry-run).
        Reads each thread's comments (avoid redundancy) + self-critiques."""
        recent_styles: List[str] = []
        for lead in leads[:budget]:
            self.comment_writer.run(lead, style_history=recent_styles)
            if lead.draft and lead.draft.body:
                recent_styles.append(lead.draft.body)  # vary the next one
            self.store.save()

    def post_engagement_comments(self, leads: List[Lead], budget: int = 3,
                                 confirm: bool = False):
        """Post 'ready' engagement comments through the health gate (comment-only).

        Every send passes the breaker + rate/pacing/warm-up gate first; each post
        is verified for visibility. Only posts with confirm=True. Returns a list
        of (lead, status, note)."""
        import time as _t
        from .health import HealthMonitor

        info = None
        if hasattr(self.reddit, "account_info"):
            try:
                info = self.reddit.account_info()
            except Exception:
                info = None
        username = (info or {}).get("username", "")
        monitor = HealthMonitor(self.campaign, self.store, proxy=self.settings.proxy,
                                username=username, reddit=self.reddit)

        ready = [l for l in leads
                 if l.draft and l.draft.body
                 and l.comment_quality and l.comment_quality.verdict == "ready"]
        results = []
        posted = 0
        for lead in ready:
            if posted >= budget:
                break
            if not confirm:
                results.append((lead, "dry-run", "ready — add --confirm to post"))
                posted += 1
                continue

            gate = monitor.guard_send(subreddit=lead.post.subreddit)
            if not gate.allowed:
                results.append((lead, "blocked", gate.reason))
                if gate.wait_seconds <= 0:
                    break  # a hard block (breaker/cap) stops the whole batch
                continue

            try:
                self.reddit.comment(lead.post.id, lead.draft.body)  # rdt only
            except Exception as exc:
                results.append((lead, "error", str(exc)))
                continue

            lead.sent_at = _t.time()
            lead.sent_ref = "comment"
            lead.stage = Stage.SENT.value
            self.store.save()
            self.store.log_activity(
                "sent", channel="comment", post_id=lead.post.id,
                subreddit=lead.post.subreddit, author=lead.post.author,
                account=username, ref="", status="posted", detail="engagement comment")

            # verify it's actually visible (catches silent removal / shadow)
            check = monitor.verify_after_send(
                lead, type("R", (), {"ref": "", "message": ""})())
            results.append((lead, "posted", check.note))
            posted += 1
        return results

    def _score_engagement_concurrent(self, leads: List[Lead], max_workers: int = 8) -> None:
        if not leads:
            return
        if len(leads) == 1:
            self.engagement.run(leads[0])
            self.store.save()
            return
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _safe(lead: Lead) -> None:
            try:
                self.engagement.run(lead)
            except Exception as exc:
                lead.notes.append(f"engagement error: {exc}")

        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for _ in as_completed([ex.submit(_safe, l) for l in leads]):
                done += 1
                if done % 12 == 0:
                    self.store.save()
        self.store.save()

    # ── Phase 3: DM outreach ─────────────────────────────────────────────
    def dm_targets(self, budget: int = 10, min_priority: int = 0) -> List[Lead]:
        """Pick the best DM candidates: qualified, in-market prospects with an
        author, ranked by priority, that we haven't already DM'd or handed off."""
        cands = [
            l for l in self.store.all()
            if l.qualification and not l.qualification.disqualified
            and l.qualification.is_prospect and l.post.author
            and l.qualification.priority >= min_priority
            and l.stage not in (Stage.DM_SENT.value, Stage.HANDED_OFF.value)
            and not l.sent_at
        ]
        cands.sort(key=lambda l: l.qualification.priority if l.qualification else 0,
                   reverse=True)
        return cands[:budget]

    def write_dms(self, leads: List[Lead], budget: int = 5) -> None:
        """Draft personal cold DMs (dry-run). Each is self-critiqued for
        personal / non-spammy / opt-out and revised once if weak."""
        for lead in leads[:budget]:
            self.dm_writer.run(lead)
            self.store.save()

    def send_dms(self, leads: List[Lead], budget: int = 3, confirm: bool = False):
        """Send 'ready' DMs — health-gated, DM-capped, and OFF unless the campaign
        sets dm_enabled and you pass confirm. Returns [(lead, status, note)]."""
        import time as _t
        from .health import HealthMonitor
        from .sender import zernio_dm

        results = []
        if not getattr(self.campaign, "dm_enabled", False):
            for lead in leads[:budget]:
                results.append((lead, "blocked",
                                "DMs disabled — set dm_enabled: true in the campaign"))
            return results

        acct = None
        if self.zernio.configured:
            try:
                acct = self.zernio.find_reddit_account()
            except Exception:
                acct = None
        username = (acct or {}).get("username", "")
        account_id = (acct or {}).get("_id", "")
        monitor = HealthMonitor(self.campaign, self.store, proxy=self.settings.proxy,
                                account_id=account_id, username=username, reddit=self.reddit)

        now = _t.time()
        cap = int(getattr(self.campaign, "max_dms_per_day", 5) or 5)
        sent_today = self.store.count_sends(since_ts=now - 86400, channel="dm")
        remaining = max(0, cap - sent_today)

        ready = [l for l in leads
                 if l.draft and l.draft.body
                 and l.dm_quality and l.dm_quality.verdict == "ready"]
        posted = 0
        for lead in ready:
            if posted >= budget:
                break
            if not confirm:
                results.append((lead, "dry-run", "ready — add --confirm to send"))
                posted += 1
                continue
            if remaining <= 0:
                results.append((lead, "blocked",
                                f"daily DM cap reached ({cap}/day)"))
                break
            gate = monitor.guard_send(subreddit="")
            if not gate.allowed:
                results.append((lead, "blocked", gate.reason))
                if gate.wait_seconds <= 0:
                    break
                continue

            res = zernio_dm(lead, self.zernio, confirm=True)
            if res.ok:
                lead.stage = Stage.DM_SENT.value
                remaining -= 1
                posted += 1
            self.store.save()
            self.store.log_activity(
                "sent", channel="dm", post_id=lead.post.id,
                subreddit=lead.post.subreddit, author=lead.post.author,
                account=username, ref=res.ref, status=res.status,
                detail=res.message[:200])
            results.append((lead, res.status, res.message))
            _t.sleep(5)  # be gentle
        return results

    # ── Phase 4: handoff to Markeye ──────────────────────────────────────
    def handoff(self, lead: Lead, *, whatsapp: str = "", reason: str = "",
                confirm: bool = False):
        """Emit a signed webhook handoff to Markeye for one lead (idempotent,
        dry-run unless confirm). Markeye owns the WhatsApp SDR sequence."""
        from .handoff import HandoffClient
        client = HandoffClient(self.campaign, self.store)
        return client.emit(lead, whatsapp=whatsapp, reason=reason, confirm=confirm)

    def run(self, limit_per_query: int = 10, draft_budget: int = 10) -> RunReport:
        """Bounded full pipeline — safe for 24/7 watch cycles.

        discovery → (funnel) qualify → draft ONLY the top ``draft_budget``
        sendable leads → compliance. Qualification is prefiltered + concurrent,
        and expensive drafting is capped so a cycle stays bounded no matter how
        many subreddits/posts came in. Leftover qualified leads stay in the
        backlog and get their shot in later cycles (ranked by sendability).
        """
        from .triage import triage_lead

        report = RunReport()

        # ── Stage 1: discovery (base feeds ∪ Scout's DB finds) ──
        self._refresh_feeds()
        new_leads = self.discovery.run(limit_per_query=limit_per_query)
        for lead in new_leads:
            self.store.upsert(lead)
        self.store.save()
        report.discovered = len(new_leads)

        # ── Stage 2: qualification (two-stage funnel, bounded + concurrent) ──
        pending = self.store.by_stage(Stage.DISCOVERED.value)
        to_llm = pending
        if self.qualification.uses_llm and len(pending) > 12:
            to_llm = self._prefilter(pending)
        self._qualify_concurrent(to_llm)
        self.store.save()
        report.qualified = sum(
            1 for l in pending if l.qualification and not l.qualification.disqualified)
        report.disqualified = sum(
            1 for l in pending if l.qualification and l.qualification.disqualified)

        # ── Stages 3-5: draft only the top sendable leads (bounded) ──
        # Pull the whole not-yet-drafted qualified backlog and rank by sendability
        # so fresh/uncrowded prospects get drafted before stale ones.
        backlog = self.store.by_stage(Stage.QUALIFIED.value)
        backlog.sort(key=lambda l: triage_lead(l).score, reverse=True)
        for lead in backlog[:draft_budget]:
            self.research.run(lead)
            report.researched += 1
            self.personalization.run(lead)
            report.drafted += 1
            self.compliance.run(lead)
            if lead.stage == Stage.APPROVED.value:
                report.approved += 1
                self.store.log_activity(
                    "approved", post_id=lead.post.id, subreddit=lead.post.subreddit,
                    author=lead.post.author,
                    detail=f"priority={lead.qualification.priority if lead.qualification else 0}",
                )
            elif lead.stage == Stage.NEEDS_REVISION.value:
                report.needs_revision += 1
            elif lead.stage == Stage.REJECTED.value:
                report.rejected += 1
            self.store.save()

        self.store.log_activity("run", detail=report.summary())
        return report
