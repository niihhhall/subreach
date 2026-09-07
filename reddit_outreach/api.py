# -*- coding: utf-8 -*-
"""Read-only JSON API for the client-facing Next.js dashboard.

Same live data the HTML dashboard shows, served as JSON so a separate frontend
(Vercel) can render it. Read-only — there are NO write endpoints, so a client
can never change anything. Token-gated (a CLIENT_TOKEN separate from the admin
DASHBOARD_TOKEN, so client access can be rotated independently) and CORS-enabled
for the frontend origin.

Single source of truth stays Neon; this just exposes it.
"""

from __future__ import annotations

import glob
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from .config import Campaign, Settings
from .models import Stage
from .store import open_store
from .triage import post_age_days, triage_lead

router = APIRouter(prefix="/api")


# ── auth ────────────────────────────────────────────────────────────────
def _client_token() -> str:
    return (os.environ.get("CLIENT_TOKEN")
            or os.environ.get("DASHBOARD_TOKEN") or "").strip()


def _auth(token: str = Query(default=""),
          x_client_token: str = Header(default=""),
          authorization: str = Header(default="")) -> None:
    expected = _client_token()
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    provided = (token or x_client_token or bearer or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="CLIENT_TOKEN not configured")
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid token")


# ── campaign + store helpers ──────────────────────────────────────────────
def _campaigns() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for pattern in ("campaigns/*.yaml", "campaigns/*.yml", "campaigns/*.json"):
        for path in sorted(glob.glob(pattern)):
            try:
                out[Campaign.load(path).name] = path
            except Exception:
                continue
    return out


def _default_campaign_name(campaigns: Dict[str, str]) -> str:
    camp_path = os.environ.get("CAMPAIGN", "")
    if camp_path and os.path.exists(camp_path):
        try:
            return Campaign.load(camp_path).name
        except Exception:
            pass
    return next(iter(campaigns), "")


def _resolve(campaign: str):
    campaigns = _campaigns()
    if not campaigns:
        raise HTTPException(status_code=404, detail="no campaigns configured")
    name = campaign or _default_campaign_name(campaigns)
    path = campaigns.get(name) or next(iter(campaigns.values()))
    return Campaign.load(path), campaigns


def _open(camp: Campaign):
    return open_store(Settings.from_env(), camp.name)


def _account_key(store):
    accts = store.accounts()
    if accts:
        a = accts[0]
        return (a.get("account_id") or a.get("username") or "default",
                a.get("username") or "")
    return "default", ""


# ── endpoints ─────────────────────────────────────────────────────────────
@router.get("/campaigns")
def campaigns(token: str = Query(default=""), x_client_token: str = Header(default=""),
              authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    c = _campaigns()
    return {"campaigns": list(c.keys()), "default": _default_campaign_name(c)}


@router.get("/overview")
def overview(campaign: str = "", token: str = Query(default=""),
             x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        funnel = store.funnel()
        subs = store.subreddit_breakdown()
        key, username = _account_key(store)
        health = store.latest_health(key) or {}
        breaker = store.breaker_state(key) or {}
        rep = store.reputation_history(key, limit=1)
        recent = store.recent_activities(limit=10)
        all_leads = store.all()
    finally:
        store.close()
    engageable = sum(1 for l in all_leads
                     if l.engagement and l.engagement.verdict == "engage")
    active_stages = {Stage.QUALIFIED.value, Stage.RESEARCHED.value, Stage.DRAFTED.value,
                     Stage.APPROVED.value, Stage.NEEDS_REVISION.value, Stage.SENT.value}
    tiers = {"hot": 0, "warm": 0, "cold": 0}
    for l in all_leads:
        if l.stage in active_stages:
            t = triage_lead(l).tier
            if t in tiers:
                tiers[t] += 1
    return {
        "campaign": camp.name, "product": camp.product,
        "funnel": funnel, "total": sum(funnel.values()),
        "engageable": engageable, "tiers": tiers,
        "health": {"status": health.get("status", "unknown"),
                   "score": health.get("score")},
        "breaker_open": bool(breaker.get("breaker_tripped")),
        "karma": (rep[0].get("total_karma") if rep else None),
        "subreddits": [{"subreddit": r["subreddit"], "leads": r["leads"],
                        "sent": r.get("sent") or 0,
                        "avg_priority": (round(r["avg_priority"]) if r.get("avg_priority")
                                         is not None else None)} for r in subs[:15]],
        "recent": [_activity(a) for a in recent],
    }


@router.get("/timeseries")
def timeseries(campaign: str = "", days: int = 14, token: str = Query(default=""),
               x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        leads = store.all()
        acts = store.recent_activities(limit=2000, action="sent")
    finally:
        store.close()
    day = 86400.0
    now = time.time()
    days = max(3, min(60, days))
    order = []           # list of (label, day_index) oldest -> newest
    index = {}
    for i in range(days - 1, -1, -1):
        ts = now - i * day
        di = int(ts // day)
        index[di] = len(order)
        order.append({"date": time.strftime("%b %d", time.gmtime(ts)),
                      "leads": 0, "comments": 0})
    for l in leads:
        di = int((l.discovered_at or 0) // day)
        if di in index:
            order[index[di]]["leads"] += 1
    for a in acts:
        if a.get("channel") == "comment":
            di = int((a.get("ts") or 0) // day)
            if di in index:
                order[index[di]]["comments"] += 1
    return {"series": order}


@router.get("/leads")
def leads(campaign: str = "", tier: str = "", token: str = Query(default=""),
          x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        active = [Stage.QUALIFIED.value, Stage.RESEARCHED.value, Stage.DRAFTED.value,
                  Stage.APPROVED.value, Stage.NEEDS_REVISION.value, Stage.SENT.value]
        rows = store.by_stage(*active)
    finally:
        store.close()
    triaged = [(l, triage_lead(l)) for l in rows]
    if tier:
        triaged = [(l, t) for (l, t) in triaged if t.tier == tier]
    triaged.sort(key=lambda lt: lt[1].score, reverse=True)
    return {"leads": [{
        "id": l.post.id, "tier": t.tier, "score": t.score,
        "priority": (l.qualification.priority if l.qualification else 0),
        "age_days": round(t.age_days, 1) if t.age_days >= 0 else None,
        "num_comments": t.num_comments, "saturation": t.saturation_tag,
        "subreddit": l.post.subreddit, "title": l.post.title, "url": l.post.full_url,
        "pains": (l.qualification.pain_points[:3] if l.qualification else []),
        "sent": bool(l.sent_at),
    } for l, t in triaged[:300]]}


@router.get("/queue")
def queue(campaign: str = "", token: str = Query(default=""),
          x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        rows = store.by_stage(Stage.APPROVED.value, Stage.NEEDS_REVISION.value)
    finally:
        store.close()
    rows.sort(key=lambda l: l.qualification.priority if l.qualification else 0, reverse=True)
    return {"items": [{
        "id": l.post.id, "stage": l.stage,
        "priority": (l.qualification.priority if l.qualification else 0),
        "verdict": (l.compliance.verdict if l.compliance else "?"),
        "subreddit": l.post.subreddit, "title": l.post.title, "url": l.post.full_url,
        "draft": (l.draft.body if l.draft else ""),
    } for l in rows]}


@router.get("/engagement")
def engagement(campaign: str = "", token: str = Query(default=""),
               x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        alll = store.all()
    finally:
        store.close()
    eng = [l for l in alll if l.engagement and l.engagement.verdict == "engage"]
    eng.sort(key=lambda l: l.engagement.score, reverse=True)
    return {"items": [{
        "id": l.post.id, "score": l.engagement.score,
        "value_add": l.engagement.value_add, "sub_fit": l.engagement.sub_fit,
        "age_days": (round(post_age_days(l.post.created_utc), 1)
                     if l.post.created_utc else None),
        "num_comments": l.post.num_comments, "subreddit": l.post.subreddit,
        "title": l.post.title, "url": l.post.full_url, "angle": l.engagement.angle,
        "draft": (l.draft.body if l.draft else ""),
        "quality": ({"verdict": l.comment_quality.verdict,
                     "helpful": l.comment_quality.helpful,
                     "human": l.comment_quality.human} if l.comment_quality else None),
    } for l in eng[:200]]}


@router.get("/outreach")
def outreach(campaign: str = "", token: str = Query(default=""),
             x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        alll = store.all()
        sends = store.recent_activities(limit=200, action="sent")
        handoff_acts = store.recent_activities(limit=200, action="handoff")
    finally:
        store.close()
    handed = {a.get("post_id") for a in handoff_acts if a.get("status") == "sent"}
    dm_sent = {a.get("post_id") for a in sends if a.get("channel") == "dm"}
    dm_leads = [l for l in alll if l.dm_quality]
    dm_leads.sort(key=lambda l: l.qualification.priority if l.qualification else 0, reverse=True)
    pending = [l for l in alll if l.stage in (Stage.DM_SENT.value, Stage.APPROVED.value)
               and l.post.id not in handed]
    return {
        "dm_enabled": bool(getattr(camp, "dm_enabled", False)),
        "counts": {"dm_drafts": len(dm_leads), "dm_sent": len(dm_sent),
                   "handed_off": len(handed), "pending": len(pending)},
        "dm_drafts": [{
            "id": l.post.id, "author": l.post.author, "subreddit": l.post.subreddit,
            "priority": (l.qualification.priority if l.qualification else 0),
            "verdict": (l.dm_quality.verdict if l.dm_quality else ""),
            "personal": (l.dm_quality.personal if l.dm_quality else 0),
            "non_spammy": (l.dm_quality.non_spammy if l.dm_quality else 0),
            "draft": (l.draft.body if l.draft else ""),
            "sent": (l.stage == Stage.DM_SENT.value or l.post.id in dm_sent),
        } for l in dm_leads[:150]],
        "handoffs": [_activity(a) for a in handoff_acts],
        "pending": [{"id": l.post.id, "author": l.post.author, "stage": l.stage,
                     "priority": (l.qualification.priority if l.qualification else 0),
                     "title": l.post.title, "url": l.post.full_url}
                    for l in pending[:50]],
    }


@router.get("/threads")
def threads(campaign: str = "", token: str = Query(default=""),
            x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        acts = store.recent_activities(limit=300, action="sent")
    finally:
        store.close()
    posts = [a for a in acts if a.get("channel") == "post"]
    replies = [a for a in acts if a.get("channel") == "comment"
               and str(a.get("detail") or "").startswith("reply to")]
    comments = [a for a in acts if a.get("channel") == "comment"
                and not str(a.get("detail") or "").startswith("reply to")]
    return {"counts": {"comments": len(comments), "replies": len(replies),
                       "posts": len(posts)},
            "comments": [_activity(a) for a in comments[:120]],
            "replies": [_activity(a) for a in replies[:120]],
            "posts": [_activity(a) for a in posts[:120]]}


@router.get("/swarm")
def swarm(campaign: str = "", token: str = Query(default=""),
          x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    try:
        from .swarm import load_accounts
        accounts, warns = load_accounts(os.environ.get("SWARM_ACCOUNTS_PATH", "accounts.yaml"))
    except Exception as exc:
        accounts, warns = [], [str(exc)]
    now = time.time()
    store = _open(camp)
    out = []
    try:
        for a in accounts:
            health = store.latest_health(a.key) or {}
            breaker = store.breaker_state(a.key) or {}
            rep = store.reputation_history(a.key, limit=1)
            out.append({
                "label": a.label, "subreddits": a.subreddits, "persona": a.persona,
                "today": store.count_sends(since_ts=now - 86400, account=a.key,
                                           channel="comment"),
                "cap": a.max_comments_per_day,
                "karma": (rep[0].get("total_karma") if rep else None),
                "status": health.get("status", "unknown"),
                "breaker_open": bool(breaker.get("breaker_tripped")),
                "awake": a.awake(),
                "active_hours": f"{a.active_start}-{a.active_end}",
                "tz_offset": a.tz_offset, "has_key": bool(a.api_key),
            })
    finally:
        store.close()
    return {"accounts": out, "warnings": warns}


@router.get("/health")
def health(campaign: str = "", token: str = Query(default=""),
           x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        key, username = _account_key(store)
        latest = store.latest_health(key) or {}
        hist = store.health_history(key, limit=20)
        breaker = store.breaker_state(key) or {}
        rep = store.reputation_history(key, limit=30)
        verifs = store.recent_activities(limit=15, action="verify")
    finally:
        store.close()
    return {
        "account": username, "status": latest.get("status", "unknown"),
        "score": latest.get("score"), "signals": latest.get("signals", {}),
        "breaker_open": bool(breaker.get("breaker_tripped")),
        "breaker_reason": breaker.get("reason", ""),
        "karma_trend": [{"ts": r["ts"], "total_karma": r.get("total_karma") or 0}
                        for r in reversed(rep)],
        "history": [{"ts": h["ts"], "status": h.get("status"), "score": h.get("score"),
                     "detail": h.get("detail", "")} for h in hist],
        "verifications": [_activity(v) for v in verifs],
    }


@router.get("/scout")
def scout(campaign: str = "", token: str = Query(default=""),
          x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        scouted = store.scouted_subreddits()
    finally:
        store.close()
    by: Dict[str, List[Dict[str, Any]]] = {}
    for s in scouted:
        by.setdefault(s.get("vertical") or "general", []).append({
            "subreddit": s["subreddit"], "relevance": s.get("relevance", 0),
            "active": bool(s.get("active")), "sample_count": s.get("sample_count", 0),
            "last_seen": s.get("last_seen")})
    return {"verticals": by, "total": len(scouted),
            "active": sum(1 for s in scouted if s.get("active"))}


@router.get("/activity")
def activity(campaign: str = "", action: str = "", token: str = Query(default=""),
             x_client_token: str = Header(default=""), authorization: str = Header(default="")):
    _auth(token, x_client_token, authorization)
    camp, _ = _resolve(campaign)
    store = _open(camp)
    try:
        rows = store.recent_activities(limit=200, action=action)
    finally:
        store.close()
    return {"items": [_activity(a) for a in rows]}


def _activity(a: Dict[str, Any]) -> Dict[str, Any]:
    return {"ts": a.get("ts"), "action": a.get("action"), "channel": a.get("channel"),
            "subreddit": a.get("subreddit"), "author": a.get("author"),
            "account": a.get("account"), "status": a.get("status"),
            "post_id": a.get("post_id"), "detail": (a.get("detail") or "")[:200]}
