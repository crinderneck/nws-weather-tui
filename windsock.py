#!/usr/bin/env python3
"""
NWS Weather TUI — Animated ASCII windsock (speed-driven droop + flutter).
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

_CALM = r"""
 o
 |)
 |)
 |)
 |
"""

_LIGHT_A = r"""
 o
 |\_
 | \_
 |   `
 |
"""
_LIGHT_B = r"""
 o
 |\_
 |  \_
 |    '
 |
"""

_BREEZY_A = r"""
 o
 |=\__
 |    \__
 |       `
 |
"""
_BREEZY_B = r"""
 o
 |=\__
 |     \__
 |        '
 |
"""

_WINDY_A = r"""
 o
 |==\_______
 |          \_
 |
 |
"""
_WINDY_B = r"""
 o
 |==\________
 |           \_
 |
 |
"""

_STRONG_A = r"""
 o
 |===\_________/
 |
 |
 |
"""
_STRONG_B = r"""
 o
 |===\_________\
 |
 |
 |
"""

# (upper mph bound for this level, candidate frames, flutter interval in
# seconds — None means static/no flutter, used only for dead calm).
_LEVELS: List[Tuple[float, List[str], Optional[float]]] = [
    (3.0, [_CALM], None),
    (7.0, [_LIGHT_A, _LIGHT_B], 1.0),
    (12.0, [_BREEZY_A, _BREEZY_B], 0.7),
    (18.0, [_WINDY_A, _WINDY_B], 0.5),
    (float("inf"), [_STRONG_A, _STRONG_B], 0.35),
]

# A gust randomly dying down: every so often the sock droops through each
# level below its current one, then picks back up to the real wind speed.
_FALL_CYCLE_S = 22.0   # average spacing between candidate fall windows
_FALL_CHANCE = 0.35    # odds a given cycle actually contains a fall
_FALL_STEP_S = 0.55    # time spent resting on each descending level


def _level_index(mph: float) -> int:
    for i, (max_mph, _frames, _interval) in enumerate(_LEVELS):
        if mph <= max_mph:
            return i
    return len(_LEVELS) - 1


def _frame_for_level(level_idx: int, now: float) -> List[str]:
    frames, interval = _LEVELS[level_idx][1], _LEVELS[level_idx][2]
    if interval is None or len(frames) == 1:
        frame = frames[0]
    else:
        frame = frames[int(now / interval) % len(frames)]
    return frame.strip("\n").splitlines()


def _cycle_rand(cycle_idx: int, salt: int) -> float:
    """Deterministic pseudo-random float in [0, 1) for a given fall cycle."""
    return random.Random(cycle_idx * 1_000_003 + salt).random()


def _falling_level(level_idx: int, now: float) -> Optional[int]:
    """If a random fall is happening right now, the level it's resting on."""
    if level_idx <= 0:
        return None  # already calm — nothing below it to fall through
    cycle_idx = int(now // _FALL_CYCLE_S)
    if _cycle_rand(cycle_idx, 0) >= _FALL_CHANCE:
        return None
    fall_len = (level_idx + 1) * _FALL_STEP_S
    latest_start = max(0.0, _FALL_CYCLE_S - fall_len)
    fall_start = cycle_idx * _FALL_CYCLE_S + _cycle_rand(cycle_idx, 1) * latest_start
    t_into_fall = now - fall_start
    if not (0.0 <= t_into_fall < fall_len):
        return None
    step = int(t_into_fall // _FALL_STEP_S)
    return max(0, level_idx - step)


def windsock_lines(mph: Optional[float], now: float) -> List[str]:
    """ASCII lines for the windsock frame matching wind speed `mph` at
    animation clock `now` (seconds, e.g. time.time()).

    Droop/extension encodes wind speed; two frames per speed level (past
    dead calm) alternate on a speed-scaled interval to flutter the tail.
    Randomly, a gust dies down: the sock steps through each level below
    the current one before picking back up to the real wind speed.
    """
    level_idx = _level_index(mph if mph is not None else 0.0)
    fall_idx = _falling_level(level_idx, now)
    return _frame_for_level(fall_idx if fall_idx is not None else level_idx, now)
