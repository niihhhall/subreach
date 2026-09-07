# -*- coding: utf-8 -*-
"""Read-only ops dashboard for the Reddit outreach system.

A lightweight FastAPI app that renders what the pipeline has stored — the
funnel, triaged leads, the approved queue, Phase-2 engagement, account health +
reputation trend, scouted subreddits, and the activity log. It runs as its own
``web`` process alongside the ``watch`` and ``scout`` workers and reads the same
store (SQLite locally, Postgres on cloud). It never writes and never posts.

Security
--------
Auth is a single shared secret in ``DASHBOARD_TOKEN``:

* unset            → every page shows a setup notice (503), nothing leaks;
* provided wrong   → login page (401);
* provided right   → access granted via ``?token=`` (once) or the ``dash_token``
                     cookie (thereafter).

There are no write endpoints, so there is nothing to CSRF. Put it behind HTTPS
(the platform's router does this on Heroku/Render) and keep the token secret.

Run it::

    uvicorn reddit_outreach.web:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import glob
import html
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .config import Campaign, Settings
from .models import Lead, Stage
from .store import open_store
from .triage import triage_lead, post_age_days

# load .env exactly like the CLI does, so the web process sees the same config
try:
    from .cli import _load_dotenv
    _load_dotenv()
except Exception:  # pragma: no cover - dotenv is best-effort
    pass

app = FastAPI(title="Reddit Outreach — Dashboard", docs_url=None, redoc_url=None)

# Read-only JSON API for the Next.js client dashboard (token-gated, CORS-enabled).
try:
    from fastapi.middleware.cors import CORSMiddleware
    from .api import router as api_router
    _origins = os.environ.get("CORS_ORIGINS", "*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _origins.split(",")] if _origins != "*" else ["*"],
        allow_methods=["GET"], allow_headers=["*"],
    )
    app.include_router(api_router)
except Exception:  # pragma: no cover - API is optional; HTML dashboard still works
    pass

COOKIE = "dash_token"


# ──────────────────────────────────────────────────────────────────────────
# auth
# ──────────────────────────────────────────────────────────────────────────
def _token() -> str:
    return (os.environ.get("DASHBOARD_TOKEN") or "").strip()


def _provided(request: Request) -> str:
    return (request.query_params.get("token")
            or request.cookies.get(COOKIE) or "").strip()


def _guard(request: Request) -> Optional[HTMLResponse]:
    """Return a login/setup response if the caller isn't authorized, else None."""
    tok = _token()
    if not tok:
        return HTMLResponse(_shell("Setup required", _setup_body(), nav=False),
                            status_code=503)
    if _provided(request) != tok:
        return HTMLResponse(_shell("Sign in", _login_body(), nav=False),
                            status_code=401)
    return None


def _respond(request: Request, resp: HTMLResponse) -> HTMLResponse:
    """Persist a valid ``?token=`` as a cookie so later requests don't need it."""
    if request.query_params.get("token") and _provided(request) == _token():
        resp.set_cookie(COOKIE, _token(), httponly=True, samesite="lax",
                        max_age=30 * 86400)
    return resp


# ──────────────────────────────────────────────────────────────────────────
# campaign discovery + store access
# ──────────────────────────────────────────────────────────────────────────
def _campaigns() -> Dict[str, str]:
    """Map campaign display-name → file path for every campaigns/*.yaml|json."""
    out: Dict[str, str] = {}
    for pattern in ("campaigns/*.yaml", "campaigns/*.yml", "campaigns/*.json"):
        for path in sorted(glob.glob(pattern)):
            try:
                camp = Campaign.load(path)
            except Exception:
                continue
            out[camp.name] = path
    return out


def _select_campaign(request: Request) -> Tuple[Optional[Campaign], Dict[str, str]]:
    campaigns = _campaigns()
    if not campaigns:
        return None, campaigns
    wanted = request.query_params.get("campaign", "")
    if not wanted:
        # default to the deployed campaign (CAMPAIGN env) rather than the first file
        camp_path = os.environ.get("CAMPAIGN", "")
        if camp_path and os.path.exists(camp_path):
            try:
                wanted = Campaign.load(camp_path).name
            except Exception:
                wanted = ""
    path = campaigns.get(wanted) or next(iter(campaigns.values()))
    try:
        return Campaign.load(path), campaigns
    except Exception:
        return None, campaigns


def _open(campaign: Campaign):
    return open_store(Settings.from_env(), campaign.name)


def _account_key(store) -> Tuple[str, str]:
    """(key, username) for health/reputation lookups — mirrors HealthMonitor.key."""
    accts = store.accounts()
    if accts:
        a = accts[0]
        return (a.get("account_id") or a.get("username") or "default",
                a.get("username") or "")
    return "default", ""


# ──────────────────────────────────────────────────────────────────────────
# HTML shell + small render helpers
# ──────────────────────────────────────────────────────────────────────────
def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


# lucide-style inline icons (stroke currentColor) — keeps the UI crisp with no deps
_ICONS = {
    "/": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    "/leads": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "/queue": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
    "/engagement": '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.9-.9L3 21l1.9-5A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z"/>',
    "/health": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "/outreach": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    "/swarm": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "/threads": '<path d="M4 4h16v12H5.2L4 17.5z"/>',
    "/scout": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "/activity": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
}

NAV = [
    ("/", "Overview"),
    ("/leads", "Leads"),
    ("/queue", "Queue"),
    ("/engagement", "Engagement"),
    ("/outreach", "Outreach"),
    ("/threads", "Threads"),
    ("/swarm", "Swarm"),
    ("/health", "Health"),
    ("/scout", "Scout"),
    ("/activity", "Activity"),
]


def _icon(href: str) -> str:
    inner = _ICONS.get(href, "")
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'class="ic">{inner}</svg>')


def _nav(active: str, campaign: Optional[Campaign], campaigns: Dict[str, str]) -> str:
    """Render the left sidebar (brand + nav + campaign switcher)."""
    cname = campaign.name if campaign else ""
    q = f"?campaign={_esc(cname)}" if cname else ""
    links = "".join(
        f'<a class="{"on" if href == active else ""}" href="{href}{q}">'
        f'{_icon(href)}<span>{_esc(label)}</span></a>'
        for href, label in NAV
    )
    switcher = ""
    if len(campaigns) > 1:
        opts = "".join(
            f'<option value="{_esc(n)}"{" selected" if n == cname else ""}>{_esc(n)}</option>'
            for n in campaigns
        )
        switcher = (
            '<div class="camp"><label class="camp-l">Campaign</label>'
            '<form method="get">'
            f'<select name="campaign" onchange="this.form.submit()">{opts}</select>'
            "</form></div>"
        )
    return (
        '<aside class="sidebar">'
        '<div class="brand"><span class="dot"></span>reddit-outreach</div>'
        f'<nav>{links}</nav>'
        f'<div class="side-foot">{switcher}'
        '<div class="side-note">read-only · never posts</div></div>'
        "</aside>"
    )


_CSS = """
:root{
  --bg:#09090b; --surface:#0f0f12; --card:#131316; --card-2:#17171b;
  --line:#26262c; --line-2:#33333b; --fg:#fafafa; --dim:#a1a1aa; --faint:#71717a;
  --acc:#3b82f6; --acc-soft:rgba(59,130,246,.14);
  --hot:#f87171; --warm:#fbbf24; --cold:#60a5fa; --ok:#4ade80; --bad:#f87171;
  --sb:248px; --radius:12px;
}
*{box-sizing:border-box;}
html,body{margin:0;}
body{background:var(--bg); color:var(--fg);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;}
a{color:inherit; text-decoration:none;}
::selection{background:var(--acc-soft);}

/* ── app shell ── */
.app{display:flex; min-height:100vh;}
.sidebar{position:fixed; inset:0 auto 0 0; width:var(--sb); display:flex; flex-direction:column;
  gap:6px; padding:18px 14px; background:var(--surface); border-right:1px solid var(--line);
  z-index:40; overflow-y:auto; transition:transform .22s ease;}
.brand{display:flex; align-items:center; gap:9px; font-weight:650; font-size:15px;
  letter-spacing:-.01em; padding:6px 10px 14px;}
.brand .dot{width:9px; height:9px; border-radius:50%; background:var(--acc);
  box-shadow:0 0 0 4px var(--acc-soft);}
.sidebar nav{display:flex; flex-direction:column; gap:2px;}
.sidebar nav a{display:flex; align-items:center; gap:11px; padding:9px 11px; border-radius:9px;
  color:var(--dim); font-weight:500; transition:background .12s,color .12s;}
.sidebar nav a:hover{background:var(--card-2); color:var(--fg);}
.sidebar nav a.on{background:var(--acc-soft); color:#fff;}
.sidebar nav a.on .ic{color:var(--acc);}
.ic{width:17px; height:17px; flex-shrink:0;}
.side-foot{margin-top:auto; padding-top:14px;}
.camp{margin-bottom:12px;}
.camp-l{display:block; font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--faint); margin:0 2px 6px;}
.side-note{font-size:11px; color:var(--faint); padding:0 2px;}

.content{flex:1; min-width:0; margin-left:var(--sb); display:flex; flex-direction:column;}
.topbar{position:sticky; top:0; z-index:20; display:flex; align-items:center; gap:12px;
  height:56px; padding:0 22px; background:rgba(9,9,11,.82); backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);}
.crumb{font-weight:600; font-size:14px;}
.crumb-sub{color:var(--faint); font-size:13px;}
.crumb-sub::before{content:"/"; margin-right:8px; color:var(--line-2);}
.burger{display:none; width:36px; height:36px; align-items:center; justify-content:center;
  border:1px solid var(--line); border-radius:9px; cursor:pointer; color:var(--dim);}
.burger svg{width:18px; height:18px;}
.backdrop{display:none; position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:30;}
#nav-toggle:checked ~ .app .backdrop{display:block;}
main{padding:26px 22px 60px; max-width:1180px; width:100%; margin:0 auto;}

/* ── typography ── */
h1{font-size:22px; font-weight:650; letter-spacing:-.02em; margin:0 0 4px;}
h2{font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.07em;
  color:var(--faint); margin:30px 0 12px;}

/* ── cards / stats ── */
.cards{display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:14px;}
.card{background:linear-gradient(180deg,var(--card-2),var(--card)); border:1px solid var(--line);
  border-radius:var(--radius); padding:16px 18px; transition:border-color .15s;}
.card:hover{border-color:var(--line-2);}
.card .n{font-size:27px; font-weight:680; letter-spacing:-.02em; line-height:1.15;}
.card .l{color:var(--faint); font-size:11px; text-transform:uppercase; letter-spacing:.05em;
  margin-top:4px;}

/* ── panels + tables ── */
.panel{background:var(--card); border:1px solid var(--line); border-radius:var(--radius);
  margin-bottom:16px; overflow:hidden;}
.panel > table{margin:0;}
.panel:has(> table){overflow-x:auto;}
table{width:100%; border-collapse:collapse; min-width:520px;}
th,td{text-align:left; padding:11px 14px; border-bottom:1px solid var(--line); vertical-align:top;}
th{color:var(--faint); font-size:11px; font-weight:600; text-transform:uppercase;
  letter-spacing:.05em; background:var(--card-2); position:sticky; top:0;}
tbody tr{transition:background .1s;}
tbody tr:hover{background:var(--card-2);}
tr:last-child td{border-bottom:none;}

/* ── chips / semantics ── */
.tag{display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border-radius:999px;
  font-size:12px; font-weight:600; border:1px solid var(--line-2); white-space:nowrap;}
.hot{color:var(--hot); border-color:rgba(248,113,113,.4); background:rgba(248,113,113,.1);}
.warm{color:var(--warm); border-color:rgba(251,191,36,.4); background:rgba(251,191,36,.1);}
.cold{color:var(--cold); border-color:rgba(96,165,250,.4); background:rgba(96,165,250,.1);}
.skip,.muted{color:var(--faint);}
.ok{color:var(--ok);} .bad{color:var(--bad);}
.pill{display:inline-block; font-size:12px; font-weight:600; padding:2px 9px; border-radius:7px;
  background:var(--card-2); border:1px solid var(--line-2);}
.small{font-size:12px; color:var(--dim);}
a.title{font-weight:500; color:var(--fg);}
a.title:hover{color:var(--acc);}
.empty{color:var(--faint); padding:44px; text-align:center;}
code{background:var(--card-2); border:1px solid var(--line); padding:1px 6px; border-radius:5px;
  font-size:12.5px;}
.bar{height:8px; border-radius:4px; background:var(--card-2); overflow:hidden;}
.bar>span{display:block; height:100%; background:var(--acc);}

/* ── auth screens ── */
.auth-wrap{min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px;}
.login{width:100%; max-width:400px; background:var(--card); border:1px solid var(--line);
  border-radius:16px; padding:30px;}
.login h1{margin-bottom:10px;}
.login input{width:100%; padding:11px 13px; margin:14px 0 4px; border-radius:9px;
  border:1px solid var(--line-2); background:var(--bg); color:var(--fg); font-size:14px;}
.login input:focus{outline:none; border-color:var(--acc); box-shadow:0 0 0 3px var(--acc-soft);}
.login button{width:100%; margin-top:12px; padding:11px; border:none; border-radius:9px;
  background:var(--acc); color:#fff; font-weight:600; font-size:14px; cursor:pointer;}
.login button:hover{background:#2f6fe0;}

/* ── responsive ── */
@media (max-width:860px){
  .sidebar{transform:translateX(-100%); box-shadow:0 0 40px rgba(0,0,0,.5);}
  #nav-toggle:checked ~ .app .sidebar{transform:none;}
  .content{margin-left:0;}
  .burger{display:inline-flex;}
  main{padding:18px 14px 50px;}
  .cards{grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px;}
  h1{font-size:19px;}
}
"""

_BURGER = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
           'stroke-linecap="round"><path d="M3 6h18"/><path d="M3 12h18"/>'
           '<path d="M3 18h18"/></svg>')


def _shell(title: str, body: str, *, active: str = "", nav: bool = True,
           campaign: Optional[Campaign] = None,
           campaigns: Optional[Dict[str, str]] = None,
           head_extra: str = "") -> str:
    head = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_esc(title)} · reddit-outreach</title>'
            f'<style>{_CSS}</style>{head_extra}</head><body>')
    if not nav:
        return f'{head}<div class="auth-wrap">{body}</div></body></html>'

    sidebar = _nav(active, campaign, campaigns or {})
    cname = campaign.name if campaign else ""
    sub = f'<div class="crumb-sub">{_esc(cname)}</div>' if cname else ""
    return f"""{head}
<input type="checkbox" id="nav-toggle" hidden>
<div class="app">
{sidebar}
<label for="nav-toggle" class="backdrop"></label>
<div class="content">
<header class="topbar">
<label for="nav-toggle" class="burger" aria-label="Toggle menu">{_BURGER}</label>
<div class="crumb">{_esc(title)}</div>{sub}
</header>
<main>{body}</main>
</div></div></body></html>"""


def _setup_body() -> str:
    return (
        '<div class="login"><h1>Dashboard is locked</h1>'
        '<p class="small">Set a <code>DASHBOARD_TOKEN</code> environment variable '
        "to a long random secret, then restart the web process. Open the dashboard "
        "with <code>?token=YOUR_TOKEN</code> once and it will remember you.</p></div>"
    )


def _login_body() -> str:
    return (
        '<div class="login"><h1>Sign in</h1>'
        '<form method="get" action="/">'
        '<input type="password" name="token" placeholder="Dashboard token" autofocus>'
        '<button type="submit">Enter</button></form>'
        '<p class="small">Wrong or missing token.</p></div>'
    )


def _tier_class(tier: str) -> str:
    return {"hot": "hot", "warm": "warm", "cold": "cold"}.get(tier, "skip")


def _fmt_age(days: float) -> str:
    return f"{days:.0f}d" if days is not None and days >= 0 else "?"


def _fmt_ts(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        return "-"


def _no_campaign() -> HTMLResponse:
    body = ('<div class="empty">No campaigns found. Add a file under '
            '<code>campaigns/*.yaml</code> and reload.</div>')
    return HTMLResponse(_shell("No campaigns", body, nav=False), status_code=200)


# ──────────────────────────────────────────────────────────────────────────
# routes
# ──────────────────────────────────────────────────────────────────────────
@app.get("/health-check")
def health_check():
    """Unauthenticated liveness probe for the platform's load balancer."""
    return {"ok": True}


@app.get("/favicon.ico")
def favicon():
    """Silence the browser's favicon probe (no icon, no 404 noise)."""
    from fastapi import Response
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    store = _open(campaign)
    try:
        funnel = store.funnel()
        subs = store.subreddit_breakdown()
        key, username = _account_key(store)
        health = store.latest_health(key)
        breaker = store.breaker_state(key)
        rep = store.reputation_history(key, limit=1)
        recent = store.recent_activities(limit=8)
        engageable = sum(1 for l in store.all()
                         if l.engagement and l.engagement.verdict == "engage")
    finally:
        store.close()

    total = sum(funnel.values())
    order = ["discovered", "qualified", "researched", "drafted", "approved",
             "needs_revision", "sent", "disqualified", "rejected"]
    cards = "".join(
        f'<div class="card"><div class="n">{funnel.get(s, 0)}</div>'
        f'<div class="l">{_esc(s.replace("_", " "))}</div></div>'
        for s in order if funnel.get(s)
    ) or '<div class="empty">No leads yet — start the <code>watch</code> agent.</div>'

    # status strip
    hstatus = (health or {}).get("status", "unknown")
    hscore = (health or {}).get("score", "-")
    tripped = bool(breaker and breaker.get("breaker_tripped"))
    breaker_html = (f'<span class="bad">OPEN — {_esc(breaker.get("reason", ""))}</span>'
                    if tripped else '<span class="ok">closed</span>')
    karma = rep[0].get("total_karma") if rep else None

    def _avg(r):
        ap = r.get("avg_priority")
        return f"{ap:.0f}" if ap is not None else "-"

    subs_rows = "".join(
        f"<tr><td>r/{_esc(r['subreddit'])}</td><td>{r['leads']}</td>"
        f"<td>{r.get('sent') or 0}</td><td>{_avg(r)}</td></tr>"
        for r in subs[:12]
    ) or '<tr><td colspan="4" class="muted">none</td></tr>'

    act_rows = "".join(
        f'<tr><td class="small">{_fmt_ts(a["ts"])}</td>'
        f'<td>{_esc(a["action"])}</td>'
        f'<td>{("r/" + _esc(a["subreddit"])) if a.get("subreddit") else ""}</td>'
        f'<td class="small">{_esc((a.get("detail") or "")[:80])}</td></tr>'
        for a in recent
    ) or '<tr><td colspan="4" class="muted">no activity yet</td></tr>'

    body = f"""
<h1>{_esc(campaign.name)}</h1>
<p class="small">{_esc(campaign.product)}</p>
<h2>Funnel ({total} leads)</h2>
<div class="cards">{cards}</div>
<h2>Status</h2>
<div class="cards">
  <div class="card"><div class="n">{_esc(hstatus).upper()}</div>
    <div class="l">account health ({_esc(hscore)}/100)</div></div>
  <div class="card"><div class="n">{engageable}</div>
    <div class="l">threads to engage</div></div>
  <div class="card"><div class="n">{_esc(karma if karma is not None else "-")}</div>
    <div class="l">total karma</div></div>
  <div class="card"><div class="n" style="font-size:16px">{breaker_html}</div>
    <div class="l">send breaker</div></div>
</div>
<h2>Top subreddits</h2>
<div class="panel"><table>
<tr><th>subreddit</th><th>leads</th><th>sent</th><th>avg priority</th></tr>
{subs_rows}</table></div>
<h2>Recent activity</h2>
<div class="panel"><table>
<tr><th>when</th><th>action</th><th>where</th><th>detail</th></tr>
{act_rows}</table></div>
"""
    return _respond(request, HTMLResponse(
        _shell("Overview", body, active="/", campaign=campaign, campaigns=campaigns)))


@app.get("/leads", response_class=HTMLResponse)
def leads(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    tier_filter = request.query_params.get("tier", "")
    store = _open(campaign)
    try:
        active = [Stage.QUALIFIED.value, Stage.RESEARCHED.value, Stage.DRAFTED.value,
                  Stage.APPROVED.value, Stage.NEEDS_REVISION.value, Stage.SENT.value]
        leads_list = store.by_stage(*active)
    finally:
        store.close()

    triaged = [(l, triage_lead(l)) for l in leads_list]
    if tier_filter:
        triaged = [(l, t) for (l, t) in triaged if t.tier == tier_filter]
    triaged.sort(key=lambda lt: lt[1].score, reverse=True)
    triaged = triaged[:200]

    rows = ""
    for lead, t in triaged:
        q = lead.qualification
        pains = "; ".join(q.pain_points[:3]) if q and q.pain_points else ""
        pains_html = f'<div class="small muted">{_esc(pains)}</div>' if pains else ""
        sent = ' <span class="ok small">✓sent</span>' if lead.sent_at else ""
        rows += (
            "<tr>"
            f'<td><span class="tag {_tier_class(t.tier)}">{_esc(t.tier).upper()} {t.score}</span></td>'
            f'<td>{q.priority if q else 0}</td>'
            f'<td class="small">{_fmt_age(t.age_days)} · {t.num_comments}c<br>{_esc(t.saturation_tag)}</td>'
            f'<td>r/{_esc(lead.post.subreddit)}</td>'
            f'<td><a href="{_esc(lead.post.full_url)}" target="_blank" rel="noopener" '
            f'class="title">{_esc(lead.post.title[:120])}</a>'
            f'{pains_html}{sent}</td>'
            "</tr>"
        )
    if not rows:
        rows = '<tr><td colspan="5" class="muted">no leads at this filter</td></tr>'

    def tab(t, label):
        q = f"?campaign={_esc(campaign.name)}" + (f"&tier={t}" if t else "")
        on = "on" if tier_filter == t else ""
        return f'<a class="pill" style="{"background:#21262d" if on else ""}" href="/leads{q}">{label}</a>'

    filters = " ".join([tab("", "all"), tab("hot", "🔥 hot"),
                        tab("warm", "🌤 warm"), tab("cold", "❄ cold")])
    body = f"""
<h1>Leads</h1>
<p class="small">Qualified prospects, ranked by sendability (priority discounted for age + crowding). {filters}</p>
<div class="panel"><table>
<tr><th>tier</th><th>priority</th><th>age/sat</th><th>sub</th><th>post</th></tr>
{rows}</table></div>
"""
    return _respond(request, HTMLResponse(
        _shell("Leads", body, active="/leads", campaign=campaign, campaigns=campaigns)))


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    store = _open(campaign)
    try:
        leads_list = store.by_stage(Stage.APPROVED.value, Stage.NEEDS_REVISION.value)
    finally:
        store.close()
    leads_list.sort(key=lambda l: l.qualification.priority if l.qualification else 0,
                    reverse=True)

    rows = ""
    for lead in leads_list:
        pr = lead.qualification.priority if lead.qualification else 0
        verdict = lead.compliance.verdict if lead.compliance else "?"
        draft = lead.draft.body if lead.draft else ""
        rows += (
            "<tr>"
            f'<td><span class="pill">{_esc(lead.stage)}</span></td>'
            f'<td>{pr}</td>'
            f'<td>{_esc(verdict)}</td>'
            f'<td>r/{_esc(lead.post.subreddit)}<br>'
            f'<a href="{_esc(lead.post.full_url)}" target="_blank" rel="noopener" '
            f'class="title small">{_esc(lead.post.title[:90])}</a></td>'
            f'<td class="small">{_esc(draft)}</td>'
            "</tr>"
        )
    if not rows:
        rows = ('<tr><td colspan="5" class="muted">queue is empty — run the pipeline '
                'to draft outreach</td></tr>')
    body = f"""
<h1>Outreach queue</h1>
<p class="small">Approved drafts awaiting a human send. Read-only — send from the CLI
(<code>send</code>) once the shadowban lifts.</p>
<div class="panel"><table>
<tr><th>stage</th><th>priority</th><th>verdict</th><th>post</th><th>draft</th></tr>
{rows}</table></div>
"""
    return _respond(request, HTMLResponse(
        _shell("Queue", body, active="/queue", campaign=campaign, campaigns=campaigns)))


@app.get("/engagement", response_class=HTMLResponse)
def engagement(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    store = _open(campaign)
    try:
        all_leads = store.all()
    finally:
        store.close()

    engaged = [l for l in all_leads if l.engagement and l.engagement.verdict == "engage"]
    engaged.sort(key=lambda l: l.engagement.score, reverse=True)

    rows = ""
    for lead in engaged[:150]:
        e = lead.engagement
        cq = lead.comment_quality
        age = post_age_days(lead.post.created_utc)
        comment = ""
        if lead.draft and lead.draft.body:
            tag = ""
            if cq:
                cls = "ok" if cq.verdict == "ready" else "warm"
                tag = (f'<span class="tag {cls}">{_esc(cq.verdict)} · '
                       f'helpful={cq.helpful} human={cq.human}</span> ')
            comment = (f'<div class="small">{tag}</div>'
                       f'<div class="small muted">{_esc(lead.draft.body)}</div>')
        angle_html = f'<div class="small">angle: {_esc(e.angle)}</div>' if e.angle else ""
        rows += (
            "<tr>"
            f'<td><span class="pill">{e.score}</span></td>'
            f'<td class="small">va={e.value_add}<br>fit={e.sub_fit}</td>'
            f'<td class="small">{_fmt_age(age)} · {lead.post.num_comments}c</td>'
            f'<td>r/{_esc(lead.post.subreddit)}<br>'
            f'<a href="{_esc(lead.post.full_url)}" target="_blank" rel="noopener" '
            f'class="title small">{_esc(lead.post.title[:90])}</a>'
            f'{angle_html}{comment}</td>'
            "</tr>"
        )
    if not rows:
        rows = ('<tr><td colspan="4" class="muted">no engagement threads scored yet — '
                'run <code>engage</code></td></tr>')
    body = f"""
<h1>Engagement (Phase 2 / CQS)</h1>
<p class="small">Threads worth a genuine, non-promotional comment to build contributor
quality. Comments shown are dry-run drafts — nothing is posted.</p>
<div class="panel"><table>
<tr><th>score</th><th>signals</th><th>age/sat</th><th>thread + drafted comment</th></tr>
{rows}</table></div>
"""
    return _respond(request, HTMLResponse(
        _shell("Engagement", body, active="/engagement", campaign=campaign,
               campaigns=campaigns)))


@app.get("/outreach", response_class=HTMLResponse)
def outreach(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    store = _open(campaign)
    try:
        all_leads = store.all()
        sends = store.recent_activities(limit=200, action="sent")
        handoff_acts = store.recent_activities(limit=200, action="handoff")
    finally:
        store.close()

    dm_enabled = bool(getattr(campaign, "dm_enabled", False))
    handed_ids = {a.get("post_id") for a in handoff_acts if a.get("status") == "sent"}
    dm_sent_ids = {a.get("post_id") for a in sends if a.get("channel") == "dm"}

    # ── Phase 3: DM drafts ──
    dm_leads = [l for l in all_leads if l.dm_quality]
    dm_leads.sort(key=lambda l: l.qualification.priority if l.qualification else 0,
                  reverse=True)
    dm_rows = ""
    for lead in dm_leads[:150]:
        q = lead.dm_quality
        pr = lead.qualification.priority if lead.qualification else 0
        cls = "ok" if q.verdict == "ready" else "warm"
        sent = (lead.stage == Stage.DM_SENT.value) or (lead.post.id in dm_sent_ids)
        state = ('<span class="ok small">✓ sent</span>' if sent
                 else '<span class="small muted">draft</span>')
        body = _esc(lead.draft.body) if lead.draft else ""
        dm_rows += (
            "<tr>"
            f'<td>u/{_esc(lead.post.author)}<br><span class="small muted">r/{_esc(lead.post.subreddit)}</span></td>'
            f'<td>{pr}</td>'
            f'<td><span class="tag {cls}">{_esc(q.verdict)}</span>'
            f'<div class="small muted">p={q.personal} ns={q.non_spammy}</div></td>'
            f'<td class="small">{body}</td>'
            f'<td>{state}</td>'
            "</tr>"
        )
    if not dm_rows:
        dm_rows = ('<tr><td colspan="5" class="muted">no DM drafts yet — run '
                   '<code>dm &lt;campaign&gt;</code></td></tr>')

    # ── Phase 4: handoffs (sent + pending) ──
    pending = [l for l in all_leads
               if l.stage in (Stage.DM_SENT.value, Stage.APPROVED.value)
               and l.post.id not in handed_ids]
    pending.sort(key=lambda l: l.qualification.priority if l.qualification else 0,
                 reverse=True)
    ho_rows = "".join(
        f'<tr><td class="small">{_fmt_ts(a["ts"])}</td>'
        f'<td>u/{_esc(a.get("author"))}</td>'
        f'<td class="{"ok" if a.get("status") == "sent" else "bad"}">{_esc(a.get("status"))}</td>'
        f'<td class="small">{_esc((a.get("detail") or "")[:80])}</td></tr>'
        for a in handoff_acts
    ) or '<tr><td colspan="4" class="muted">no handoffs yet</td></tr>'
    pend_rows = "".join(
        f'<tr><td>u/{_esc(l.post.author)}</td>'
        f'<td>{l.qualification.priority if l.qualification else 0}</td>'
        f'<td><span class="pill">{_esc(l.stage)}</span></td>'
        f'<td><a class="title small" href="{_esc(l.post.full_url)}" target="_blank" '
        f'rel="noopener">{_esc(l.post.title[:80])}</a></td></tr>'
        for l in pending[:50]
    ) or '<tr><td colspan="4" class="muted">nothing pending</td></tr>'

    dm_banner = (
        '<div class="panel" style="padding:14px 16px"><b class="ok">DMs enabled</b> '
        f'<span class="small">· cap {getattr(campaign, "max_dms_per_day", 5)}/day · '
        'sends are still health-gated + dry-run unless --confirm</span></div>'
        if dm_enabled else
        '<div class="panel" style="padding:14px 16px"><b class="warm">DMs OFF</b> '
        '<span class="small">· cold DMs are high ban-risk; set '
        '<code>dm_enabled: true</code> in the campaign to allow sending</span></div>'
    )
    dm_sent_count = len(dm_sent_ids)
    handed_count = len(handed_ids)

    body = f"""
<h1>Outreach — DMs &amp; handoff</h1>
<p class="small">Phase 3 (cold DMs) and Phase 4 (handoff to Markeye's WhatsApp SDR).
Drafting is safe; sending is gated and off by default.</p>
<div class="cards">
  <div class="card"><div class="n">{len(dm_leads)}</div><div class="l">DM drafts</div></div>
  <div class="card"><div class="n">{dm_sent_count}</div><div class="l">DMs sent</div></div>
  <div class="card"><div class="n">{handed_count}</div><div class="l">handed off</div></div>
  <div class="card"><div class="n">{len(pending)}</div><div class="l">pending handoff</div></div>
</div>
<h2>DM drafts (Phase 3)</h2>
{dm_banner}
<div class="panel"><table>
<tr><th>recipient</th><th>priority</th><th>quality</th><th>draft</th><th>state</th></tr>
{dm_rows}</table></div>
<h2>Pending handoff</h2>
<div class="panel"><table>
<tr><th>lead</th><th>priority</th><th>stage</th><th>post</th></tr>
{pend_rows}</table></div>
<h2>Handoff log (Phase 4)</h2>
<div class="panel"><table>
<tr><th>when</th><th>lead</th><th>status</th><th>detail</th></tr>
{ho_rows}</table></div>
"""
    return _respond(request, HTMLResponse(
        _shell("Outreach", body, active="/outreach", campaign=campaign,
               campaigns=campaigns)))


@app.get("/threads", response_class=HTMLResponse)
def threads(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    store = _open(campaign)
    try:
        comments = store.recent_activities(limit=300, action="sent")
        posts_made = [a for a in comments if a.get("channel") == "post"]
        replies = [a for a in comments if a.get("channel") == "comment"
                   and str(a.get("detail") or "").startswith("reply to")]
        top_comments = [a for a in comments if a.get("channel") == "comment"
                        and not str(a.get("detail") or "").startswith("reply to")]
    finally:
        store.close()

    def _link(pid):
        return (f'<a class="title small" target="_blank" rel="noopener" '
                f'href="https://www.reddit.com/comments/{_esc(pid)}">{_esc(pid)}</a>')

    def _rows(items, kind):
        out = ""
        for a in items[:120]:
            out += (
                "<tr>"
                f'<td class="small">{_fmt_ts(a["ts"])}</td>'
                f'<td>{_esc(a.get("account") or "")}</td>'
                f'<td>r/{_esc(a.get("subreddit") or "")}</td>'
                f'<td>{("u/" + _esc(a["author"])) if a.get("author") else ""}</td>'
                f'<td>{_link(a.get("post_id"))}</td>'
                f'<td class="small">{_esc((a.get("detail") or "")[:80])}</td>'
                "</tr>"
            )
        return out or f'<tr><td colspan="6" class="muted">no {kind} yet</td></tr>'

    body = f"""
<h1>Threads &amp; posts</h1>
<p class="small">Everything each account did on Reddit: top-level comments, threaded
replies, and any submissions. All migrates to Supabase with the activity log.</p>
<div class="cards">
  <div class="card"><div class="n">{len(top_comments)}</div><div class="l">comments</div></div>
  <div class="card"><div class="n">{len(replies)}</div><div class="l">replies</div></div>
  <div class="card"><div class="n">{len(posts_made)}</div><div class="l">threads/posts</div></div>
</div>
<h2>Threads / submissions</h2>
<div class="panel"><table>
<tr><th>when</th><th>account</th><th>sub</th><th>author</th><th>post</th><th>detail</th></tr>
{_rows(posts_made, "submissions")}</table></div>
<h2>Replies (follow-ups)</h2>
<div class="panel"><table>
<tr><th>when</th><th>account</th><th>sub</th><th>replied to</th><th>post</th><th>detail</th></tr>
{_rows(replies, "replies")}</table></div>
<h2>Comments</h2>
<div class="panel"><table>
<tr><th>when</th><th>account</th><th>sub</th><th>author</th><th>post</th><th>detail</th></tr>
{_rows(top_comments, "comments")}</table></div>
"""
    return _respond(request, HTMLResponse(
        _shell("Threads", body, active="/threads", campaign=campaign, campaigns=campaigns)))


@app.get("/swarm", response_class=HTMLResponse)
def swarm(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()

    try:
        from .swarm import load_accounts
        accounts, warns = load_accounts(
            os.environ.get("SWARM_ACCOUNTS_PATH", "accounts.yaml"))
    except Exception as exc:
        accounts, warns = [], [f"could not load roster: {exc}"]

    import time as _t
    now = _t.time()
    store = _open(campaign)
    try:
        rows = ""
        for a in accounts:
            health = store.latest_health(a.key) or {}
            breaker = store.breaker_state(a.key) or {}
            rep = store.reputation_history(a.key, limit=1)
            karma = rep[0].get("total_karma") if rep else None
            today = store.count_sends(since_ts=now - 86400, account=a.key,
                                      channel="comment")
            tripped = bool(breaker.get("breaker_tripped"))
            awake = a.awake()
            status = (health.get("status") or "unknown")
            hcls = {"healthy": "ok", "banned": "bad", "at_risk": "warm",
                    "degraded": "warm"}.get(status, "muted")
            breaker_html = ('<span class="bad">OPEN</span>' if tripped
                            else '<span class="ok">closed</span>')
            awake_html = ('<span class="ok">awake</span>' if awake
                          else '<span class="muted">asleep</span>')
            keyok = "yes" if a.api_key else '<span class="bad">MISSING</span>'
            rows += (
                "<tr>"
                f'<td><b>{_esc(a.label)}</b><br><span class="small muted">{_esc(a.email)}</span></td>'
                f'<td class="small">{", ".join("r/" + _esc(s) for s in a.subreddits)}</td>'
                f'<td>{_esc(today)}/{a.max_comments_per_day}</td>'
                f'<td>{_esc(karma if karma is not None else "-")}</td>'
                f'<td><span class="tag {hcls}">{_esc(status)}</span></td>'
                f'<td>{breaker_html}</td>'
                f'<td class="small">{awake_html}<br>{a.active_start}-{a.active_end} '
                f'tz{a.tz_offset:+g}</td>'
                f'<td class="small">key={keyok}</td>'
                "</tr>"
            )
        if not rows:
            rows = ('<tr><td colspan="8" class="muted">no accounts in the roster — '
                    'create <code>accounts.yaml</code> (or set SWARM_ACCOUNTS)</td></tr>')
    finally:
        store.close()

    warn_html = ""
    if warns:
        items = "".join(f"<li>{_esc(w)}</li>" for w in warns)
        warn_html = f'<div class="panel" style="padding:14px 16px"><b class="warm">Roster notes</b><ul class="small">{items}</ul></div>'

    body = f"""
<h1>Warm-up swarm</h1>
<p class="small">Per-account warm-up health. Each persona has its own subreddits,
waking hours, karma, breaker, and daily comment budget. Comment-only, no promo,
no cross-voting — genuine reputation building.</p>
{warn_html}
<div class="panel"><table>
<tr><th>account</th><th>subreddits</th><th>today</th><th>karma</th>
<th>health</th><th>breaker</th><th>active hrs</th><th>key</th></tr>
{rows}</table></div>
<p class="small">Karma + health populate as the swarm runs and the health/reputation
probes fire. Run: <code>warm &lt;campaign&gt; --confirm --loop</code>.</p>
"""
    return _respond(request, HTMLResponse(
        _shell("Swarm", body, active="/swarm", campaign=campaign, campaigns=campaigns)))


@app.get("/health", response_class=HTMLResponse)
def health(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    store = _open(campaign)
    try:
        key, username = _account_key(store)
        latest = store.latest_health(key)
        hist = store.health_history(key, limit=20)
        breaker = store.breaker_state(key)
        rep = store.reputation_history(key, limit=30)
        verifs = store.recent_activities(limit=15, action="verify")
    finally:
        store.close()

    tripped = bool(breaker and breaker.get("breaker_tripped"))
    status = (latest or {}).get("status", "unknown")
    score = (latest or {}).get("score", "-")
    signals = (latest or {}).get("signals", {}) if latest else {}

    breaker_panel = (
        f'<div class="panel"><b class="bad">🔴 Circuit breaker OPEN</b><br>'
        f'<span class="small">{_esc(breaker.get("reason", ""))}</span><br>'
        f'<span class="small">auto-resume: {_fmt_ts(breaker.get("resume_after"))}</span></div>'
        if tripped else
        '<div class="panel"><b class="ok">🟢 Circuit breaker closed</b> '
        '<span class="small">— sends allowed</span></div>'
    )

    sig_html = ""
    if signals:
        sig_html = (
            '<div class="cards">'
            f'<div class="card"><div class="n">{_esc(signals.get("shadowbanned"))}</div>'
            '<div class="l">shadowbanned</div></div>'
            f'<div class="card"><div class="n">'
            f'{signals.get("comment_karma", 0) + signals.get("link_karma", 0)}</div>'
            '<div class="l">karma</div></div>'
            f'<div class="card"><div class="n">{signals.get("account_age_days", 0)}</div>'
            '<div class="l">account age (d)</div></div>'
            f'<div class="card"><div class="n">'
            f'{signals.get("recent_removed", 0)}/{signals.get("recent_verified", 0)}</div>'
            '<div class="l">recent removed</div></div>'
            "</div>"
        )

    # karma trend chart (chronological)
    rep_chron = list(reversed(rep))
    labels = [f'"{_fmt_ts(r["ts"])}"' for r in rep_chron]
    kdata = [str(int(r.get("total_karma") or 0)) for r in rep_chron]
    chart = ""
    if len(rep_chron) >= 2:
        chart = f"""
<h2>Karma trend</h2>
<div class="panel"><canvas id="kchart" height="90"></canvas></div>
<script>
new Chart(document.getElementById('kchart'), {{
  type:'line',
  data:{{labels:[{",".join(labels)}],
    datasets:[{{label:'total karma',data:[{",".join(kdata)}],
      borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,.14)',
      fill:true,tension:.35,pointRadius:2,pointBackgroundColor:'#3b82f6'}}]}},
  options:{{plugins:{{legend:{{labels:{{color:'#a1a1aa'}}}}}},
    scales:{{x:{{ticks:{{color:'#71717a',maxTicksLimit:8}},grid:{{color:'#26262c'}}}},
            y:{{ticks:{{color:'#71717a'}},grid:{{color:'#26262c'}}}}}}}}
}});
</script>"""

    hist_rows = "".join(
        f'<tr><td class="small">{_fmt_ts(h["ts"])}</td>'
        f'<td>{_esc(h.get("status"))}</td><td>{_esc(h.get("score"))}</td>'
        f'<td class="small">{_esc(h.get("detail") or "")}</td></tr>'
        for h in hist
    ) or '<tr><td colspan="4" class="muted">no health probes yet</td></tr>'

    verif_rows = "".join(
        f'<tr><td class="small">{_fmt_ts(v["ts"])}</td>'
        f'<td>r/{_esc(v.get("subreddit"))}</td>'
        f'<td class="{"ok" if v.get("status") == "visible" else "bad" if v.get("status") == "removed" else "muted"}">'
        f'{_esc(v.get("status"))}</td>'
        f'<td class="small">{_esc((v.get("detail") or "")[:70])}</td></tr>'
        for v in verifs
    ) or '<tr><td colspan="4" class="muted">no verified sends yet</td></tr>'

    body = f"""
<h1>Account health & reputation</h1>
<p class="small">Account: <b>u/{_esc(username) or "—"}</b> · latest status
<b>{_esc(status).upper()}</b> ({_esc(score)}/100)</p>
{breaker_panel}
{sig_html}
{chart}
<h2>Health probe history</h2>
<div class="panel"><table>
<tr><th>when</th><th>status</th><th>score</th><th>detail</th></tr>
{hist_rows}</table></div>
<h2>Comment verifications</h2>
<div class="panel"><table>
<tr><th>when</th><th>sub</th><th>outcome</th><th>detail</th></tr>
{verif_rows}</table></div>
"""
    head = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>' if chart else ""
    return _respond(request, HTMLResponse(
        _shell("Health", body, active="/health", campaign=campaign,
               campaigns=campaigns, head_extra=head)))


@app.get("/scout", response_class=HTMLResponse)
def scout(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    store = _open(campaign)
    try:
        scouted = store.scouted_subreddits()
    finally:
        store.close()

    by_vertical: Dict[str, List[Dict[str, Any]]] = {}
    for s in scouted:
        by_vertical.setdefault(s.get("vertical") or "general", []).append(s)

    in_feed = {x.lower() for x in campaign.feed_subreddits}
    active_n = sum(1 for s in scouted if s.get("active"))

    sections = ""
    for vertical in sorted(by_vertical):
        rows = ""
        for s in sorted(by_vertical[vertical], key=lambda x: (x.get("active", 0),
                                                              x.get("relevance", 0)),
                        reverse=True):
            live = ('<span class="ok">live</span>' if s.get("active")
                    else '<span class="muted">inactive</span>')
            used = ' <span class="pill">in campaign</span>' if \
                s["subreddit"].lower() in in_feed else ""
            rows += (
                f'<tr><td>r/{_esc(s["subreddit"])}{used}</td>'
                f'<td>{s.get("relevance", 0)}</td>'
                f'<td>{live}</td>'
                f'<td class="small">{s.get("sample_count", 0)}</td>'
                f'<td class="small">{_fmt_ts(s.get("last_seen"))}</td></tr>'
            )
        sections += (
            f'<h2>{_esc(vertical)} ({len(by_vertical[vertical])})</h2>'
            f'<div class="panel"><table>'
            '<tr><th>subreddit</th><th>relevance</th><th>status</th>'
            '<th>samples</th><th>last seen</th></tr>'
            f'{rows}</table></div>'
        )
    if not sections:
        sections = ('<div class="empty">No scouted subreddits yet — run the '
                    '<code>scout</code> agent.</div>')

    body = f"""
<h1>Scouted subreddits</h1>
<p class="small">{len(scouted)} discovered ({active_n} live) across
{len(by_vertical)} vertical(s). The scout writes these; the watch agent reads them.</p>
{sections}
"""
    return _respond(request, HTMLResponse(
        _shell("Scout", body, active="/scout", campaign=campaign, campaigns=campaigns)))


@app.get("/activity", response_class=HTMLResponse)
def activity(request: Request):
    guard = _guard(request)
    if guard:
        return guard
    campaign, campaigns = _select_campaign(request)
    if not campaign:
        return _no_campaign()
    action = request.query_params.get("action", "")
    store = _open(campaign)
    try:
        rows_data = store.recent_activities(limit=200, action=action)
    finally:
        store.close()

    rows = "".join(
        "<tr>"
        f'<td class="small">{_fmt_ts(a["ts"])}</td>'
        f'<td>{_esc(a.get("action"))}</td>'
        f'<td>{_esc(a.get("channel") or "")}</td>'
        f'<td>{("r/" + _esc(a["subreddit"])) if a.get("subreddit") else ""}</td>'
        f'<td>{("u/" + _esc(a["author"])) if a.get("author") else ""}</td>'
        f'<td>{_esc(a.get("status") or "")}</td>'
        f'<td class="small">{_esc((a.get("detail") or "")[:120])}</td>'
        "</tr>"
        for a in rows_data
    ) or '<tr><td colspan="7" class="muted">no activity logged yet</td></tr>'
    body = f"""
<h1>Activity log</h1>
<p class="small">Most recent {len(rows_data)} events (append-only audit trail).</p>
<div class="panel"><table>
<tr><th>when</th><th>action</th><th>channel</th><th>sub</th><th>author</th>
<th>status</th><th>detail</th></tr>
{rows}</table></div>
"""
    return _respond(request, HTMLResponse(
        _shell("Activity", body, active="/activity", campaign=campaign,
               campaigns=campaigns)))
