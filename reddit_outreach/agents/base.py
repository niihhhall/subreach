# -*- coding: utf-8 -*-
"""Base class shared by all pipeline agents.

Every agent is given the campaign (its instructions) and an LLM handle. Agents
must implement a deterministic ``_heuristic`` fallback so the pipeline runs even
when no LLM is configured, and an LLM path used when one is available.
"""

from __future__ import annotations

from typing import Optional

from ..config import Campaign
from ..llm import LLM


class BaseAgent:
    #: human-readable name used in logs
    role: str = "agent"

    def __init__(self, campaign: Campaign, llm: Optional[LLM] = None):
        self.campaign = campaign
        self.llm = llm or LLM("mock")

    @property
    def uses_llm(self) -> bool:
        return self.llm.available

    def _campaign_brief(self) -> str:
        c = self.campaign
        return (
            f"Product: {c.product}\n"
            f"Value proposition: {c.value_proposition}\n"
            f"Ideal customer (ICP): {c.icp}\n"
            f"Tone: {c.tone}"
        )
