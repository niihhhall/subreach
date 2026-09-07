# -*- coding: utf-8 -*-
"""Phase 4 — hand a qualified lead off to Markeye (the WhatsApp AI SDR).

This module does NOT run an SDR sequence. BANT qualification, Calendly booking,
and the 5-message cadence all live inside Markeye. Our only job is a clean,
signed **webhook handoff**: when a Reddit lead is ready (they replied, opted in,
or you decided to move them to WhatsApp), we POST a structured payload to
Markeye's endpoint and Markeye takes over.

Contract
--------
POST <webhook_url>
  headers:
    Content-Type: application/json
    X-Markeye-Event: lead.handoff
    X-Markeye-Signature: sha256=<hex hmac of the raw body>   (if a secret is set)
    X-Idempotency-Key: <post_id>
  body: see ``build_payload`` — {event, source, campaign, ts, lead{...}, contact{...}}

Safety
------
* **Idempotent** — we skip a lead we've already handed off (checked via the
  activity log), so retries/loops can't double-fire into Markeye.
* **Dry-run by default** — no URL configured, or ``confirm=False``, returns a
  preview and sends nothing.
* **Signed** — HMAC-SHA256 over the exact bytes so Markeye can verify origin.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .models import Lead, Stage

HANDOFF = "handoff"          # activity action
EVENT = "lead.handoff"


@dataclass
class HandoffResult:
    ok: bool
    status: str = ""          # sent | dry-run | duplicate | disabled | error
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    ref: str = ""             # Markeye's returned id, or the http status


class HandoffClient:
    """Builds, signs, and delivers the Markeye handoff webhook."""

    def __init__(self, campaign, store, *, post_fn: Optional[Callable] = None,
                 timeout: int = 10, retries: int = 3):
        self.campaign = campaign
        self.store = store
        self.timeout = timeout
        self.retries = retries
        self._post_fn = post_fn      # injectable for tests; else lazy `requests`
        self.url = (getattr(campaign, "handoff_webhook_url", "")
                    or os.environ.get("MARKEYE_WEBHOOK_URL", "")).strip()
        self.secret = (getattr(campaign, "handoff_secret", "")
                       or os.environ.get("MARKEYE_WEBHOOK_SECRET", "")).strip()

    # ── payload + signature ─────────────────────────────────────────────
    def build_payload(self, lead: Lead, *, whatsapp: str = "",
                      reason: str = "") -> Dict[str, Any]:
        q = lead.qualification
        return {
            "event": EVENT,
            "source": "reddit-outreach",
            "campaign": self.campaign.name,
            "ts": time.time(),
            "reason": reason or "manual handoff",
            "lead": {
                "post_id": lead.post.id,
                "subreddit": lead.post.subreddit,
                "url": lead.post.full_url,
                "title": lead.post.title,
                "priority": q.priority if q else 0,
                "fit_score": q.fit_score if q else 0,
                "intent_score": q.intent_score if q else 0,
                "pain_points": (q.pain_points[:5] if q else []),
            },
            "contact": {
                "platform": "reddit",
                "username": lead.post.author,
                "whatsapp": whatsapp,          # if you collected it in the DM thread
            },
            "context": {
                "last_draft": lead.draft.body if lead.draft else "",
            },
        }

    def _sign(self, body: bytes) -> str:
        if not self.secret:
            return ""
        digest = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    @property
    def configured(self) -> bool:
        return bool(self.url)

    # ── emit ─────────────────────────────────────────────────────────────
    def emit(self, lead: Lead, *, whatsapp: str = "", reason: str = "",
             confirm: bool = False) -> HandoffResult:
        payload = self.build_payload(lead, whatsapp=whatsapp, reason=reason)

        if not getattr(self.campaign, "handoff_enabled", True):
            return HandoffResult(False, status="disabled", payload=payload,
                                 message="handoff_enabled is false for this campaign")

        # idempotency — never hand the same lead off twice
        try:
            already = self.store.activity_exists(HANDOFF, lead.post.id)
        except Exception:
            already = False
        if already:
            return HandoffResult(True, status="duplicate", payload=payload,
                                 message=f"lead {lead.post.id} was already handed off")

        if not self.configured or not confirm:
            why = ("no webhook URL configured (set handoff_webhook_url or "
                   "MARKEYE_WEBHOOK_URL)") if not self.configured else \
                  "dry-run — re-run with --confirm to POST"
            return HandoffResult(True, status="dry-run", payload=payload,
                                 message=f"would POST handoff for u/{lead.post.author}: {why}")

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Markeye-Event": EVENT,
            "X-Idempotency-Key": lead.post.id,
        }
        sig = self._sign(body)
        if sig:
            headers["X-Markeye-Signature"] = sig

        result = self._deliver(body, headers)
        # persist outcome to the activity log (audit + idempotency + dashboard)
        self.store.log_activity(
            HANDOFF, channel="webhook", post_id=lead.post.id,
            subreddit=lead.post.subreddit, author=lead.post.author,
            ref=result.ref, status=("sent" if result.ok else "error"),
            detail=(result.message[:200]))
        if result.ok:
            lead.stage = Stage.HANDED_OFF.value
            try:
                self.store.save()
            except Exception:
                pass
        result.payload = payload
        return result

    def _deliver(self, body: bytes, headers: Dict[str, str]) -> HandoffResult:
        post_fn = self._post_fn or self._requests_post
        last_err = ""
        for attempt in range(1, self.retries + 1):
            try:
                status_code, text = post_fn(self.url, body, headers, self.timeout)
            except Exception as exc:  # network error — retry
                last_err = f"{type(exc).__name__}: {exc}"
            else:
                if 200 <= status_code < 300:
                    ref = self._extract_ref(text) or str(status_code)
                    return HandoffResult(True, status="sent", ref=ref,
                                         message=f"handoff accepted ({status_code})")
                # 4xx (except 429) won't get better on retry
                if 400 <= status_code < 500 and status_code != 429:
                    return HandoffResult(False, status="error", ref=str(status_code),
                                         message=f"Markeye rejected ({status_code}): {text[:160]}")
                last_err = f"HTTP {status_code}: {text[:160]}"
            if attempt < self.retries:
                time.sleep(min(8, 2 ** attempt))
        return HandoffResult(False, status="error", message=f"delivery failed: {last_err}")

    @staticmethod
    def _requests_post(url, body, headers, timeout):
        import requests
        resp = requests.post(url, data=body, headers=headers, timeout=timeout)
        return resp.status_code, resp.text

    @staticmethod
    def _extract_ref(text: str) -> str:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return str(data.get("id") or data.get("conversation_id")
                           or data.get("ref") or "")
        except Exception:
            pass
        return ""
