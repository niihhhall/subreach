# -*- coding: utf-8 -*-
"""Tests for human-like pacing (delays computed, never actually slept in tests)."""

from reddit_outreach.pacing import (
    HumanPacer, PacingProfile, within_active_hours, parse_active_hours,
)


class _FixedRng:
    """Deterministic RNG: uniform -> midpoint, random -> 1.0 (no long break)."""
    def uniform(self, a, b):
        return (a + b) / 2.0

    def random(self):
        return 1.0

    def shuffle(self, seq):
        pass


def _pacer():
    # enabled=False => compute delays but never sleep
    return HumanPacer(enabled=False, rng=_FixedRng())


def test_read_time_scales_with_thread_length():
    p = _pacer()
    short = p.read("tiny post")
    long = p.read("word " * 2000)
    assert long > short
    assert short >= p.p.read_min and long <= p.p.read_max


def test_typing_time_scales_with_comment_length():
    p = _pacer()
    short = p.typing("ok thanks")
    long = p.typing("x" * 2000)
    assert long > short
    assert long <= p.p.type_max


def test_disabled_pacer_never_sleeps():
    slept = []
    p = HumanPacer(enabled=False, sleep_fn=lambda s: slept.append(s), rng=_FixedRng())
    p.read("hello world")
    p.think()
    p.rest()
    assert slept == []          # nothing actually slept


def test_speed_compresses_waits():
    calls = []
    p = HumanPacer(enabled=True, speed=1000.0, sleep_fn=lambda s: calls.append(s),
                   rng=_FixedRng())
    p.think()
    assert calls and all(c < 1.0 for c in calls)   # compressed by speed factor


def test_within_active_hours_normal_and_wraparound():
    # normal window 8-17 at 12:00 UTC -> awake; at 20:00 -> asleep
    noon = 12 * 3600
    assert within_active_hours(8, 17, now=noon) is True
    assert within_active_hours(8, 17, now=20 * 3600) is False
    # wrap-around window 22-6 at 02:00 -> awake; at 12:00 -> asleep
    assert within_active_hours(22, 6, now=2 * 3600) is True
    assert within_active_hours(22, 6, now=12 * 3600) is False
    # always-on
    assert within_active_hours(None, None, now=noon) is True


def test_tz_offset_shifts_window():
    # 12:00 UTC with tz -8 => local 04:00, outside an 8-23 window
    assert within_active_hours(8, 23, now=12 * 3600, tz_offset_hours=-8) is False
    assert within_active_hours(8, 23, now=20 * 3600, tz_offset_hours=-8) is True  # local 12:00


def test_parse_active_hours():
    assert parse_active_hours("8-23") == (8, 23)
    assert parse_active_hours([9, 24]) == (9, 24)
    assert parse_active_hours(None) == (None, None)
    assert parse_active_hours("garbage") == (None, None)
