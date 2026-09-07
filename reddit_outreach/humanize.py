# -*- coding: utf-8 -*-
"""Make generated comments read like a real redditor typed them.

Two jobs:

1. **Kill AI tells (always).** The em-dash (—) is the single biggest giveaway,
   so it is removed unconditionally, along with en-dashes and the usual robotic
   connective tissue ("Moreover", "Furthermore", "It's important to note...").
   Real people use commas and periods, not em-dashes.

2. **Add human texture (optional, tunable).** Redditors write casually: lowercase
   starts, dropped trailing periods, and the occasional harmless slip (a missing
   apostrophe, a lowercase "i"). People make small mistakes, and a comment that
   is *too* clean reads like a bot. This is applied lightly and at most once per
   comment so it stays believable, never sloppy.

Pure text in, pure text out. No I/O, seedable RNG for deterministic tests.
"""

from __future__ import annotations

import random
import re
from typing import Optional

# AI-tell openers/phrases to strip (case-insensitive)
_AI_PHRASES = [
    r"\bMoreover,?\s*",
    r"\bFurthermore,?\s*",
    r"\bIn conclusion,?\s*",
    r"\bAdditionally,?\s*",
    r"\bIt'?s important to note that\s*",
    r"\bIt is important to note that\s*",
    r"\bNeedless to say,?\s*",
    r"\bRest assured,?\s*",
]
_AI_WORDS = [(r"\bdelve\b", "dig"), (r"\bleverage\b", "use"),
             (r"\butilize\b", "use"), (r"\bplethora\b", "ton")]

_CONTRACTIONS = ["don't", "doesn't", "didn't", "can't", "won't", "you're",
                 "it's", "that's", "i'm", "i've", "they're", "we're", "isn't"]


def de_ai(text: str) -> str:
    """Remove em/en dashes and robotic phrasing. Always safe to run."""
    if not text:
        return text
    t = text
    # dashes -> comma (parenthetical) or hyphen. Order matters.
    t = t.replace(" — ", ", ").replace(" – ", ", ").replace(" -- ", ", ")
    t = t.replace("—", ", ").replace("–", "-").replace("--", ", ")
    for pat in _AI_PHRASES:
        t = re.sub(pat, "", t, flags=re.IGNORECASE)
    for pat, repl in _AI_WORDS:
        t = re.sub(pat, repl, t, flags=re.IGNORECASE)
    # tidy artifacts from the replacements
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)      # no space before punctuation
    t = re.sub(r",\s*,", ",", t)                  # collapse double commas
    t = re.sub(r"[ \t]{2,}", " ", t)              # collapse runs of spaces
    t = re.sub(r"\n{3,}", "\n\n", t)              # cap blank lines
    # capitalize a sentence start left bare by a stripped opener
    t = re.sub(r"(^|[.!?]\s+)([a-z])",
               lambda m: m.group(1) + m.group(2).upper(), t)
    return t.strip()


def humanize(text: str, *, casual: bool = True, typo_rate: float = 0.2,
             rng: Optional[random.Random] = None) -> str:
    """de_ai + light human texture. ``casual`` = lowercase starts / dropped
    periods; ``typo_rate`` = chance of one harmless slip (0 disables)."""
    r = rng or random.Random()
    t = de_ai(text)
    if not t:
        return t

    if casual:
        # redditors often skip the trailing period on a short comment
        if t.endswith(".") and "\n" not in t[-2:] and r.random() < 0.45:
            t = t[:-1]
        # and sometimes start lowercase
        if t[:1].isupper() and not t[:1].isdigit() and r.random() < 0.35:
            t = t[0].lower() + t[1:]

    if typo_rate > 0 and r.random() < typo_rate:
        t = _one_slip(t, r)
    return t


def _one_slip(t: str, r: random.Random) -> str:
    """Apply at most ONE realistic, non-destructive human imperfection."""
    options = []
    contr = [m for m in re.finditer(
        r"\b(" + "|".join(re.escape(c) for c in _CONTRACTIONS) + r")\b", t, re.I)]
    if contr:
        options.append("apostrophe")
    if re.search(r"\bI\b", t):
        options.append("lower_i")
    if not options:
        return t
    choice = r.choice(options)
    if choice == "apostrophe":                      # "don't" -> "dont"
        m = r.choice(contr)
        return t[:m.start()] + m.group(0).replace("'", "") + t[m.end():]
    # lowercase one standalone "I"
    idxs = [m.start() for m in re.finditer(r"\bI\b", t)]
    pos = r.choice(idxs)
    return t[:pos] + "i" + t[pos + 1:]


def has_em_dash(text: str) -> bool:
    """Guardrail check used in tests: no em/en dash may survive."""
    return "—" in (text or "") or "–" in (text or "")
