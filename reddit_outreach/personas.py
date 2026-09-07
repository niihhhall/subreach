# -*- coding: utf-8 -*-
"""Per-account personas + reply-angle selection for the comment brain.

Two ideas:

* **Persona** — each warm-up account writes as a distinct person: its own voice,
  casualness, and typo rate. Three accounts that all write identically look like
  one operator running a cluster; distinct personas kill that fingerprint.

* **Angle** — a good commenter doesn't reply the same way to every thread. The
  brain reads the thread and picks one of four moves:
    - ``direct``   : share what actually worked, one concrete tactic
    - ``question`` : help in a line, then ask one genuine diagnostic question
    - ``reframe``  : gently challenge the premise before giving the tactic
    - ``short``    : one or two casual sentences, a single specific point
  The choice is driven by thread signals (is the OP asking? venting? is the
  thread already crowded?) and biased by the persona's natural tendencies.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

ANGLES = ["direct", "question", "reframe", "short"]

ANGLE_INSTRUCTIONS = {
    "direct": ("Share what actually worked for you: one concrete tactic, led by "
               "lived experience. No pitch."),
    "question": ("Be genuinely helpful in a sentence or two, then end with ONE "
                 "honest diagnostic question that helps them and reveals their "
                 "situation."),
    "reframe": ("Gently challenge the premise first, shift how they're thinking "
                "about the problem, then give the practical tactic."),
    "short": ("Keep it very short, one or two sentences, a single specific point, "
              "casual."),
}

_FRUSTRATION = re.compile(
    r"\b(burning money|wast\w+|frustrat\w+|ghost\w*|overwhelm\w*|struggl\w+|"
    r"fed up|hate|stuck|drowning|can'?t keep up|losing|no idea|help)\b", re.I)


@dataclass
class Persona:
    name: str = "default"
    voice: str = "a helpful, experienced peer who has run a business"
    style: str = "practical and warm, a couple of sentences, plain language"
    typo_rate: float = 0.18
    casual: bool = True
    angles: List[str] = field(default_factory=lambda: list(ANGLES))


# Three deliberately different writers (mapped to the three warm-up accounts).
PRESETS = {
    "operator": Persona(
        name="operator",
        voice="a practical small-business owner who has been in the trenches",
        style=("warm, been-there, concrete. medium length, a couple of sentences. "
               "talks like a founder, not a marketer"),
        typo_rate=0.15, casual=True,
        angles=["direct", "reframe", "question"]),
    "marketer": Persona(
        name="marketer",
        voice="a sharp performance marketer who thinks in funnels and numbers",
        style=("analytical and precise, references specifics, tends to ask a "
               "pointed diagnostic question. slightly cleaner writing than most"),
        typo_rate=0.08, casual=False,
        angles=["question", "direct", "reframe"]),
    "tradesman": Persona(
        name="tradesman",
        voice="a blunt home-services operator who runs a crew and hates fluff",
        style=("short, blunt, mostly lowercase, no corporate words, one specific "
               "point and done"),
        typo_rate=0.3, casual=True,
        angles=["short", "reframe", "direct"]),
    "default": Persona(),
}


def resolve_persona(name: Optional[str]) -> Persona:
    return PRESETS.get((name or "").strip().lower(), PRESETS["default"])


def choose_angle(*, is_asking: bool, num_comments: int, text: str,
                 persona: Persona, rng: Optional[random.Random] = None) -> str:
    """Pick a reply angle from thread signals, biased by the persona."""
    r = rng or random.Random()
    saturated = (num_comments or 0) > 25
    frustrated = bool(_FRUSTRATION.search(text or ""))

    candidates: List[str] = []
    if saturated:
        candidates.append("short")        # late to a crowded thread, be brief
    if frustrated:
        candidates.append("reframe")      # venting, shift the mindset
    if is_asking:
        candidates += ["question", "direct"]
    if not candidates:
        candidates = ["direct", "question"]

    prefs = persona.angles or ANGLES
    # persona-preferred angles that also fit the thread, in persona order
    pool = [a for a in prefs if a in candidates]
    if not pool:
        pool = candidates
    # favor the persona's top preference but keep some variety
    if len(pool) > 1 and r.random() < 0.7:
        return pool[0]
    return r.choice(pool)
