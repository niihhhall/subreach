# -*- coding: utf-8 -*-
"""Human-like pacing for the warm-up swarm.

Bots get caught because they act instantly and rhythmically: comment 0.5s after
a thread appears, every N seconds, around the clock. A real person *reads* the
thread (time proportional to its length), *thinks* for a beat, *types* the reply
(time proportional to its length), then *steps away* for a while — and does none
of this at 4am, and occasionally takes a long break.

``HumanPacer`` models exactly that. Every delay is randomized within human
ranges and, crucially, **proportional to the work** (reading a long thread and
typing a long comment take longer). Delays are injectable (``sleep_fn``) and the
RNG is seedable, so tests run instantly and deterministically.

Nothing here talks to the network — it only decides *how long to wait*.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class PacingProfile:
    """Tunable human-behavior ranges (seconds unless noted)."""
    read_wpm: float = 220.0          # reading speed (words/min)
    type_cpm: float = 950.0          # typing speed (chars/min ≈ 190 wpm)
    read_min: float = 6.0
    read_max: float = 130.0
    think_min: float = 3.0
    think_max: float = 22.0
    type_min: float = 5.0
    type_max: float = 190.0
    rest_min: float = 90.0           # gap between two comments (normal)
    rest_max: float = 360.0
    long_break_prob: float = 0.15    # sometimes a real person disappears for a bit
    long_break_min: float = 600.0
    long_break_max: float = 1500.0
    account_gap_min: float = 120.0   # gap when the swarm switches accounts
    account_gap_max: float = 600.0


class HumanPacer:
    def __init__(self, profile: Optional[PacingProfile] = None, *, enabled: bool = True,
                 speed: float = 1.0, sleep_fn: Optional[Callable[[float], None]] = None,
                 rng: Optional[random.Random] = None):
        self.p = profile or PacingProfile()
        self.enabled = enabled          # False => compute delays but don't sleep (dry-run/tests)
        self.speed = max(0.001, speed)  # >1 = faster (compress waits); for testing
        self._sleep = sleep_fn or time.sleep
        self._r = rng or random.Random()

    def _wait(self, seconds: float) -> float:
        seconds = max(0.0, seconds / self.speed)
        if self.enabled and seconds > 0:
            self._sleep(seconds)
        return seconds

    def read(self, text: str) -> float:
        """Time to read a thread — proportional to its length."""
        words = max(20.0, len(text or "") / 5.0)
        secs = (words / self.p.read_wpm) * 60.0 * self._r.uniform(0.7, 1.4)
        return self._wait(_clamp(secs, self.p.read_min, self.p.read_max))

    def think(self) -> float:
        """A beat to decide whether/how to respond."""
        return self._wait(self._r.uniform(self.p.think_min, self.p.think_max))

    def typing(self, text: str) -> float:
        """Time to type a comment — proportional to its length, plus edit pauses."""
        chars = len(text or "")
        secs = (chars / self.p.type_cpm) * 60.0 * self._r.uniform(0.8, 1.5)
        secs += self._r.uniform(2.0, 8.0)      # re-reading / small edits
        return self._wait(_clamp(secs, self.p.type_min, self.p.type_max))

    def rest(self) -> float:
        """Step away before the next comment; occasionally a longer break."""
        if self._r.random() < self.p.long_break_prob:
            return self._wait(self._r.uniform(self.p.long_break_min, self.p.long_break_max))
        return self._wait(self._r.uniform(self.p.rest_min, self.p.rest_max))

    def account_gap(self) -> float:
        """Gap when moving from one account to the next in a cycle."""
        return self._wait(self._r.uniform(self.p.account_gap_min, self.p.account_gap_max))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def within_active_hours(start: Optional[int], end: Optional[int], *,
                        now: Optional[float] = None, tz_offset_hours: float = 0.0) -> bool:
    """Is the current (tz-shifted) hour inside an account's active window?

    ``start``/``end`` are 24h integers in the account's local time. ``None`` or
    equal values mean always-on. Windows may wrap midnight (e.g. 22→6).
    """
    if start is None or end is None or start == end:
        return True
    t = (now if now is not None else time.time()) + tz_offset_hours * 3600.0
    hour = time.gmtime(t).tm_hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end       # wraps past midnight


def parse_active_hours(spec) -> tuple:
    """Parse '8-23' / [8,23] / {start,end} into (start, end) ints, or (None, None)."""
    if not spec:
        return (None, None)
    try:
        if isinstance(spec, str) and "-" in spec:
            a, b = spec.split("-", 1)
            return (int(a), int(b))
        if isinstance(spec, (list, tuple)) and len(spec) == 2:
            return (int(spec[0]), int(spec[1]))
        if isinstance(spec, dict):
            return (int(spec.get("start")), int(spec.get("end")))
    except (ValueError, TypeError):
        pass
    return (None, None)
