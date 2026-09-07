# -*- coding: utf-8 -*-
"""Send paths for approved drafts.

Two honest modes:

* ``manual`` — copies the draft to your clipboard and opens the Reddit thread
  in your logged-in browser, so you post the *comment* yourself. This is the
  only path that works for thread-reply outreach (no API can comment for you
  without risking a ban / breaking Reddit ToS).

* ``zernio`` — publishes the draft as a Reddit *submission* to a subreddit via
  the Zernio API. Reddit has no comment API through Zernio, so this is for the
  "post valuable content to a target subreddit" motion, not thread replies.
  Defaults to creating a DRAFT in Zernio so nothing goes live by accident.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .models import Lead, Stage
from .utils import copy_to_clipboard, open_in_browser
from .zernio import ZernioClient, ZernioError


@dataclass
class SendResult:
    ok: bool
    ref: str = ""            # zernio post id or "manual"
    status: str = ""         # draft | scheduled | published | posted | error
    message: str = ""


def manual_send(lead: Lead, *, open_browser: bool = True) -> SendResult:
    """Copy the draft and open the thread for the user to post by hand."""
    if not lead.draft or not lead.draft.body.strip():
        return SendResult(False, message="lead has no draft body")
    copied = copy_to_clipboard(lead.draft.body)
    opened = open_in_browser(lead.post.full_url) if open_browser else False
    parts = []
    parts.append("draft copied to clipboard" if copied else "clipboard unavailable (copy manually)")
    if open_browser:
        parts.append("thread opened in browser" if opened else "could not open browser")
    return SendResult(True, ref="manual", status="assisted", message="; ".join(parts))


def zernio_publish(
    lead: Lead,
    zernio: ZernioClient,
    *,
    subreddit: str = "",
    title: str = "",
    account_id: str = "",
    profile_id: str = "",
    mode: str = "draft",             # draft | publish | schedule
    scheduled_for: str = "",
    timezone: str = "UTC",
) -> SendResult:
    """Publish the draft as a Reddit submission via Zernio."""
    if not zernio.configured:
        return SendResult(False, status="error", message="ZERNIO_API_KEY not set")
    if not lead.draft or not lead.draft.body.strip():
        return SendResult(False, status="error", message="lead has no draft body")

    if not account_id or not profile_id:
        acct = zernio.find_reddit_account()
        if not acct:
            return SendResult(False, status="error",
                              message="no Reddit account connected in Zernio (run zernio-setup)")
        account_id = account_id or acct.get("_id", "")
        profile_id = profile_id or acct.get("profileId", "")

    target_sub = subreddit or lead.post.subreddit
    if not target_sub:
        return SendResult(False, status="error", message="no target subreddit (pass --subreddit)")

    post_title = title or _derive_title(lead)

    try:
        post = zernio.create_reddit_post(
            account_id=account_id,
            profile_id=profile_id,
            title=post_title,
            content=lead.draft.body,
            subreddit=target_sub,
            is_draft=(mode == "draft"),
            publish_now=(mode == "publish"),
            scheduled_for=scheduled_for if mode == "schedule" else "",
            timezone=timezone,
        )
    except ZernioError as exc:
        return SendResult(False, status="error", message=str(exc))

    post_id = str(post.get("_id", ""))
    status = str(post.get("status", mode))
    lead.sent_ref = post_id
    lead.sent_at = time.time()
    lead.stage = Stage.SENT.value
    lead.notes.append(f"zernio post {post_id} ({status}) -> r/{target_sub}")
    return SendResult(True, ref=post_id, status=status,
                      message=f"created Zernio post {post_id} ({status}) to r/{target_sub}")


def zernio_comment(
    lead: Lead,
    zernio: ZernioClient,
    *,
    account_id: str = "",
    confirm: bool = False,
) -> SendResult:
    """Reply to the discovered thread with the lead's draft (Inbox add-on).

    This is the primary Reddit outreach write: a value-first comment on the
    exact thread. Dry-run unless ``confirm=True``.
    """
    if not zernio.configured:
        return SendResult(False, status="error", message="ZERNIO_API_KEY not set")
    if not lead.draft or not lead.draft.body.strip():
        return SendResult(False, status="error", message="lead has no draft body")

    if not account_id:
        acct = zernio.find_reddit_account()
        if not acct:
            return SendResult(False, status="error",
                              message="no Reddit account connected (run zernio-setup)")
        account_id = acct.get("_id", "")

    if not confirm:
        return SendResult(True, status="dry-run",
                          message=f"[dry-run] would reply on {lead.post.full_url} "
                                  f"with {len(lead.draft.body)} chars. Re-run with --confirm to post.")

    try:
        res = zernio.reply_to_post(lead.post.id, account_id, lead.draft.body)
    except ZernioError as exc:
        hint = " (Inbox add-on may be required)" if "403" in str(exc) else ""
        return SendResult(False, status="error", message=f"{exc}{hint}")

    cid = str(res.get("commentId", ""))
    lead.sent_ref = f"comment:{cid}"
    lead.sent_at = time.time()
    lead.stage = Stage.SENT.value
    lead.notes.append(f"replied on thread {lead.post.id} -> comment {cid}")
    return SendResult(True, ref=cid, status="posted",
                      message=f"posted reply (comment {cid}) on r/{lead.post.subreddit}")


def zernio_dm(
    lead: Lead,
    zernio: ZernioClient,
    *,
    message: str = "",
    account_id: str = "",
    confirm: bool = False,
) -> SendResult:
    """Cold-DM the post author (Inbox add-on). Reddit is strict about DMs —
    use sparingly and only where it genuinely helps. Dry-run unless confirm."""
    if not zernio.configured:
        return SendResult(False, status="error", message="ZERNIO_API_KEY not set")
    author = lead.post.author
    if not author:
        return SendResult(False, status="error", message="no author username on this post")
    text = message or (lead.draft.body if lead.draft else "")
    if not text.strip():
        return SendResult(False, status="error", message="no message body")

    if not account_id:
        acct = zernio.find_reddit_account()
        if not acct:
            return SendResult(False, status="error", message="no Reddit account connected")
        account_id = acct.get("_id", "")

    if not confirm:
        return SendResult(True, status="dry-run",
                          message=f"[dry-run] would DM u/{author} ({len(text)} chars). "
                                  f"Re-run with --confirm to send.")

    try:
        res = zernio.create_conversation(account_id, participant_username=author, message=text)
    except ZernioError as exc:
        hint = ""
        if "403" in str(exc):
            hint = " (Inbox add-on may be required)"
        elif "422" in str(exc) or "DM_NOT_ALLOWED" in str(exc):
            hint = " (user does not accept DMs)"
        return SendResult(False, status="error", message=f"{exc}{hint}")

    lead.sent_ref = f"dm:{author}"
    lead.sent_at = time.time()
    lead.stage = Stage.SENT.value
    lead.notes.append(f"DM sent to u/{author}")
    return SendResult(True, ref=author, status="posted", message=f"DM sent to u/{author}")


def _derive_title(lead: Lead) -> str:
    """Reddit submissions need a title; derive a reasonable one."""
    base = lead.post.title.strip().rstrip("?.!")
    title = f"Re: {base}" if base else "Sharing something that helped with this"
    return title[:290]
