# -*- coding: utf-8 -*-
"""Seed the local store with a realistic Markeye dataset for the dashboard demo.

Offline, no network. Populates leads across every pipeline stage, plus drafts,
activities (sends/handoffs/verifies), scouted subreddits, account health and a
karma trend — so the dashboard renders a full, coherent picture.

Run:  python scripts/seed_demo.py    (uses CAMPAIGN name markeye-reddit)
Idempotent: re-running is a no-op unless SEED_FORCE=1.
"""
from __future__ import annotations

import os
import random
import sys
import time

# Allow running as `python scripts/seed_demo.py` from the repo root: put the
# repo root (this file's parent's parent) on sys.path so reddit_outreach imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reddit_outreach.config import Settings
from reddit_outreach.models import (
    Compliance, Draft, Engagement, CommentQuality, Lead, Qualification,
    RedditPost, Research, Stage,
)
from reddit_outreach.store import open_store

CAMPAIGN_NAME = "markeye-reddit"
ACCOUNT_KEY = "markeye_reddit"
ACCOUNT_USER = "markeye_ai"
NOW = time.time()
HOUR = 3600.0
DAY = 86400.0

random.seed(7)

# (subreddit, author, title, selftext, pains, fit, intent, num_comments, age_hours, stage)
ROWS = [
    ("smallbusiness", "ppc_paula", "Spending $8k/mo on Google Ads but leads go cold before I can call",
     "Solo owner here. Leads come in at 9pm and by the time I reply next morning they've booked a competitor. How are you all handling after-hours lead response?",
     ["slow speed-to-lead", "after-hours leads go cold", "no coverage"], 92, 88, 41, 3, Stage.APPROVED.value),
    ("realestate", "closer_kate", "Missing weekend buyer inquiries — losing deals",
     "I run Meta ads for listings. Weekend inquiries pile up and I lose the fast ones. Anyone automate first response + qualification?",
     ["weekend leads missed", "no qualification system"], 90, 84, 28, 6, Stage.APPROVED.value),
    ("PPC", "roas_ryan", "Great CTR, terrible close rate — is it a follow-up problem?",
     "Campaigns look healthy but sales won't follow up fast enough. Speed to lead is killing ROAS.",
     ["speed to lead", "follow-up gap"], 86, 80, 55, 10, Stage.NEEDS_REVISION.value),
    ("HVAC", "coolair_mike", "After-hours calls going to voicemail = lost jobs",
     "We pay for ads but nights/weekends go to voicemail. Half never call back. Need something to answer + book.",
     ["after-hours voicemail", "lost jobs"], 88, 86, 19, 2, Stage.APPROVED.value),
    ("Entrepreneur", "growth_gabe", "How do you qualify inbound leads without hiring an SDR?",
     "Too many low-intent leads. Want to auto-qualify before my time gets wasted.",
     ["lead qualification", "no SDR"], 78, 74, 63, 14, Stage.DRAFTED.value),
    ("leadgeneration", "funnel_fiona", "Best way to instantly respond to FB lead form leads?",
     "FB lead forms convert but only if you reply in minutes. Manual is impossible at night.",
     ["instant response", "FB lead forms"], 84, 82, 37, 5, Stage.APPROVED.value),
    ("medspa", "glow_gina", "Booking requests at midnight, staff replies next day, they ghost",
     "Aesthetic clinic. Ad leads message late; by morning they're gone. Need 24/7 qualify + book.",
     ["midnight inquiries", "ghosting"], 91, 89, 22, 1, Stage.APPROVED.value),
    ("agency", "agency_alex", "Clients mad about slow lead response — what do you use?",
     "We run ads for home service clients. They complain leads aren't called fast. Looking for a white-label responder.",
     ["client churn", "slow response"], 82, 79, 44, 8, Stage.DRAFTED.value),
    ("Roofing", "roof_rob", "Storm season = flood of leads, can't answer them all",
     "After a storm we get 100+ form fills in a day. Impossible to call all fast. Losing the good ones.",
     ["lead volume spikes", "triage"], 87, 83, 31, 4, Stage.SENT.value),
    ("Mortgages", "rate_rachel", "Speed to lead in mortgage — automated first touch?",
     "Rate shoppers go with whoever calls first. Need instant, compliant first response overnight.",
     ["speed to lead", "compliance"], 85, 81, 26, 12, Stage.QUALIFIED.value),
    ("smallbusiness", "biz_ben", "Paying for leads that never get a callback",
     "Honestly embarrassing how many paid leads we drop. No system, just me and my phone.",
     ["dropped leads", "no system"], 80, 88, 18, 7, Stage.RESEARCHED.value),
    ("FacebookAds", "meta_mel", "Lead ads working but nurture is nonexistent",
     "Cost per lead is fine, but nobody follows up consistently. Leads rot.",
     ["no nurture", "inconsistent follow-up"], 79, 77, 33, 20, Stage.QUALIFIED.value),
    ("realtors", "listing_liz", "Overnight Zillow leads — anyone auto-qualifying?",
     "Zillow/portal leads at 2am. Want to qualify budget + timeline before I spend time.",
     ["overnight portal leads", "qualify budget"], 89, 85, 29, 2, Stage.APPROVED.value),
    ("Contractor", "build_bill", "Losing bids because I answer too late",
     "Homeowners want a quick reply. I'm on a jobsite all day. Missing the fast movers.",
     ["late replies", "on jobsite"], 83, 80, 24, 9, Stage.DRAFTED.value),
    ("DigitalMarketing", "seo_sara", "Is speed-to-lead really worth automating?",
     "Debating whether to automate first response. Curious what actually moved the needle for people.",
     ["evaluating automation"], 62, 55, 71, 30, Stage.QUALIFIED.value),
    ("loanoriginators", "loan_lena", "After-hours pre-qual — worth it?",
     "Most of my leads come in after 6pm. Thinking about an AI that pre-quals on WhatsApp.",
     ["after-hours pre-qual"], 84, 82, 21, 3, Stage.APPROVED.value),
    ("Esthetics", "skin_sam", "Front desk can't keep up with DM inquiries",
     "Instagram + ad DMs flood in. Front desk misses half. Want auto-reply + booking.",
     ["DM overload", "missed bookings"], 86, 84, 17, 5, Stage.SENT.value),
    ("marketing", "brand_bea", "What's your stack for instant lead follow-up?",
     "Building a follow-up stack for a client. What tools give sub-5-min response + qualification?",
     ["tool stack", "instant follow-up"], 70, 68, 48, 16, Stage.DRAFTED.value),
]

# Threads worth a pure-value engagement comment (Phase 2 / CQS).
ENGAGE_ROWS = [
    ("Entrepreneur", "curious_cara", "How fast is 'fast enough' for lead response?",
     "Trying to set an SLA for my team. What response time actually correlates with booking?",
     72, 80, 74),
    ("smallbusiness", "owner_omar", "Voicemail vs text-back for missed calls?",
     "Which recovers more leads — a voicemail drop or an instant text-back?",
     68, 75, 66),
]


def build_lead(sub, author, title, body, pains, fit, intent, ncomments, age_h, stage):
    pid = f"seed_{abs(hash((sub, title))) % 10_000_000}"
    post = RedditPost(
        id=pid, title=title, selftext=body, subreddit=sub, author=author,
        permalink=f"/r/{sub}/comments/{pid}/{author}/",
        score=random.randint(5, 220), num_comments=ncomments,
        created_utc=NOW - age_h * HOUR,
    )
    q = Qualification(
        fit_score=fit, intent_score=intent,
        reasons=[f"Strong ICP fit ({fit}) — runs paid ads, no after-hours coverage"],
        pain_points=pains, is_prospect=True, poster_role="asker",
    )
    lead = Lead(post=post, source_query="after hours leads", stage=stage,
                discovered_at=NOW - age_h * HOUR, qualification=q)

    reached = [Stage.RESEARCHED.value, Stage.DRAFTED.value, Stage.APPROVED.value,
               Stage.NEEDS_REVISION.value, Stage.SENT.value]
    if stage in reached:
        lead.research = Research(
            summary=f"Author on r/{sub} is losing paid leads after hours; wants faster qualify+book.",
            angle="Lead with a concrete way to cut speed-to-lead, then a soft, disclosed mention.",
        )
    drafted = [Stage.DRAFTED.value, Stage.APPROVED.value, Stage.NEEDS_REVISION.value,
               Stage.SENT.value]
    if stage in drafted:
        lead.draft = Draft(
            kind="comment",
            body=(f"Totally feel this — the after-hours gap is where most paid leads leak. "
                  f"One thing that helped folks I know: an instant first response that also "
                  f"asks 2-3 qualifying questions, so mornings start with warm, sorted leads "
                  f"instead of a cold pile. Curious how you handle the ones that come in "
                  f"overnight right now? (disclosure: I build Markeye, a WhatsApp AI SDR — "
                  f"happy to help either way.)"),
            opener="Totally feel this — the after-hours gap is where paid leads leak.",
            value="instant first response + 2-3 qualifying questions",
            soft_cta="how do you handle overnight leads now?",
        )
        verdict = "approved" if stage in (Stage.APPROVED.value, Stage.SENT.value) else (
            "revise" if stage == Stage.NEEDS_REVISION.value else "pending")
        lead.compliance = Compliance(verdict=verdict, self_promo_ratio_ok=True)
    if stage == Stage.SENT.value:
        lead.sent_at = NOW - random.uniform(1, 20) * HOUR
        lead.sent_ref = "comment"
    return lead


def build_engagement(sub, author, title, body, score, va, subfit):
    pid = f"eng_{abs(hash((sub, title))) % 10_000_000}"
    post = RedditPost(id=pid, title=title, selftext=body, subreddit=sub, author=author,
                      permalink=f"/r/{sub}/comments/{pid}/", score=random.randint(10, 90),
                      num_comments=random.randint(8, 40), created_utc=NOW - random.uniform(2, 24) * HOUR)
    lead = Lead(post=post, stage=Stage.QUALIFIED.value, discovered_at=NOW - 6 * HOUR)
    lead.engagement = Engagement(score=score, value_add=va, is_asking=True, sub_fit=subfit,
                                 safe=True, verdict="engage",
                                 angle="Share the SLA data + a practical text-back tip, no pitch.")
    lead.draft = Draft(kind="comment", body=(
        "In our data, replies under ~5 minutes roughly 3-4x the odds of booking vs an hour. "
        "A simple instant text-back (even 'got your message, quick q…') beats voicemail almost "
        "every time because it opens a thread they can answer on their own time."))
    lead.comment_quality = CommentQuality(helpful=88, human=84, non_redundant=True,
                                          mod_safe=True, verdict="ready")
    return lead


def main():
    settings = Settings.from_env()
    store = open_store(settings, CAMPAIGN_NAME)
    try:
        # Idempotent: skip if we've already seeded (unless SEED_FORCE=1), so the
        # docker-compose `seed` service is safe to run on every `up`.
        force = os.environ.get("SEED_FORCE", "") in ("1", "true", "yes")
        already = any(str(l.post.id).startswith("seed_") for l in store.all())
        if already and not force:
            print(f"Already seeded ({CAMPAIGN_NAME}) — skipping. Set SEED_FORCE=1 to reseed.")
            return

        store.record_account(ACCOUNT_KEY, "reddit", ACCOUNT_USER, "")

        leads = [build_lead(*r) for r in ROWS] + [build_engagement(*r) for r in ENGAGE_ROWS]
        for lead in leads:
            store.upsert(lead)
        store.save()

        # Activities: sends, a couple handoffs, and post-send verifications.
        sent_leads = [l for l in leads if l.stage == Stage.SENT.value]
        for i, l in enumerate(sent_leads):
            store.log_activity("sent", channel="comment", post_id=l.post.id,
                               subreddit=l.post.subreddit, author=l.post.author,
                               account=ACCOUNT_KEY, ref="comment", status="posted",
                               detail=f"value-first reply to u/{l.post.author}")
            store.log_activity("verify", channel="comment", post_id=l.post.id,
                               subreddit=l.post.subreddit, account=ACCOUNT_KEY,
                               status="visible", detail="comment visible logged-out")
        # A DM + a post, for the Threads/Outreach pages.
        approved = [l for l in leads if l.stage == Stage.APPROVED.value]
        if approved:
            store.log_activity("sent", channel="dm", post_id=approved[0].post.id,
                               subreddit=approved[0].post.subreddit, author=approved[0].post.author,
                               account=ACCOUNT_KEY, ref="dm1", status="posted",
                               detail="disclosed value-first DM")
            store.log_activity("sent", channel="post", subreddit="leadgeneration",
                               account=ACCOUNT_KEY, ref="post1", status="posted",
                               detail="helpful post: speed-to-lead SLA benchmarks")
        # Handoffs to Markeye (Phase 4).
        for l in sent_leads[:2]:
            store.log_activity("handoff", channel="webhook", post_id=l.post.id,
                               subreddit=l.post.subreddit, author=l.post.author,
                               account=ACCOUNT_KEY, ref="mk_" + l.post.id[-4:],
                               status="sent", detail="routed to Markeye WhatsApp SDR")

        # Scouted subreddits across verticals.
        scout = {
            "real estate": [("realtors", 92, 12), ("RealEstateMarketing", 84, 7), ("Mortgages", 80, 9)],
            "home services": [("HVAC", 90, 11), ("Roofing", 86, 8), ("Plumbing", 78, 5), ("Contractor", 82, 6)],
            "med spa / aesthetics": [("medspa", 91, 10), ("Esthetics", 85, 6), ("PlasticSurgery", 74, 4)],
            "agencies": [("agency", 88, 9), ("PPC", 83, 13), ("FacebookAds", 81, 10)],
            "general": [("smallbusiness", 79, 20), ("Entrepreneur", 76, 22), ("leadgeneration", 87, 14)],
        }
        for vertical, subs in scout.items():
            for name, rel, samples in subs:
                store.record_scouted_subreddit(subreddit=name, vertical=vertical,
                                               relevance=rel, active=(rel >= 78),
                                               sample_count=samples)

        # Account health snapshot + karma trend.
        store.record_health_snapshot(account=ACCOUNT_KEY, username=ACCOUNT_USER,
                                     score=82, status="healthy", shadowbanned=0,
                                     signals={"rate_limited": False, "removals_14d": 1,
                                              "sends_today": len(sent_leads)},
                                     detail="nominal")
        base = 1200
        for d in range(14, -1, -1):
            base += random.randint(3, 22)
            # backdate karma snapshots by writing then relying on ts=now is fine for a trend shape
            store.record_reputation(account=ACCOUNT_KEY, comment_karma=base,
                                     link_karma=180 + (14 - d) * 4,
                                     detail=f"day-{14 - d}")

        funnel = store.funnel()
        print("Seeded campaign:", CAMPAIGN_NAME)
        print("Funnel:", funnel)
        print("Scouted:", len(store.scouted_subreddits()), "subs")
        print("Activities (recent):", len(store.recent_activities(limit=100)))
    finally:
        store.close()


if __name__ == "__main__":
    main()
