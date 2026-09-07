# -*- coding: utf-8 -*-
"""LLM abstraction with graceful degradation.

Supports OpenAI, Groq (OpenAI-compatible), and Anthropic. When no API key is
configured, ``available`` is False and agents fall back to deterministic
heuristics — so the whole pipeline still runs end-to-end offline.

Provider is auto-detected from environment variables:
    OPENAI_API_KEY     -> openai    (default model gpt-4o-mini)
    GROQ_API_KEY       -> groq      (default model llama-3.3-70b-versatile)
    ANTHROPIC_API_KEY  -> anthropic (default model claude-3-5-haiku-latest)
    FIREWORKS_API_KEY  -> fireworks (OpenAI-compatible; set OUTREACH_LLM_MODEL)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional


_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-3-5-haiku-latest",
    "fireworks": "accounts/fireworks/models/glm-5p2",
}


class LLM:
    """Thin, provider-agnostic chat wrapper.

    Only depends on the ``requests`` library (widely available). Never raises
    on a missing key — callers check :attr:`available` and provide a fallback.
    """

    def __init__(self, provider: str = "auto", model: str = ""):
        self.provider, self.api_key = self._resolve_provider(provider)
        self.model = model or _DEFAULT_MODELS.get(self.provider, "")

    @staticmethod
    def _resolve_provider(provider: str):
        env = {
            "openai": os.environ.get("OPENAI_API_KEY", ""),
            "groq": os.environ.get("GROQ_API_KEY", ""),
            "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
            "fireworks": os.environ.get("FIREWORKS_API_KEY", ""),
        }
        if provider != "auto":
            return provider, env.get(provider, "")
        for name in ("openai", "anthropic", "groq", "fireworks"):
            if env[name]:
                return name, env[name]
        return "mock", ""

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self.provider in _DEFAULT_MODELS

    # ── public API ────────────────────────────────────────────────────
    def complete(self, system: str, user: str, temperature: float = 0.4) -> str:
        """Return the raw text completion. Empty string if unavailable/errored."""
        if not self.available:
            return ""
        try:
            if self.provider == "anthropic":
                return self._anthropic(system, user, temperature)
            return self._openai_compatible(system, user, temperature)
        except Exception:
            return ""

    def json_complete(self, system: str, user: str) -> Optional[Dict[str, Any]]:
        """Ask for JSON and parse it. Returns None on any failure."""
        text = self.complete(
            system + "\n\nRespond with a single valid JSON object and nothing else.",
            user,
            temperature=0.2,
        )
        if not text:
            return None
        return _extract_json(text)

    # ── providers ─────────────────────────────────────────────────────
    def _openai_compatible(self, system: str, user: str, temperature: float) -> str:
        import requests

        base = {
            "openai": "https://api.openai.com/v1",
            "groq": "https://api.groq.com/openai/v1",
            "fireworks": "https://api.fireworks.ai/inference/v1",
        }.get(self.provider, "https://api.openai.com/v1")
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _anthropic(self, system: str, user: str, temperature: float) -> str:
        import requests

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1024,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction from an LLM response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
