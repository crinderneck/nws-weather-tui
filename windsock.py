#!/usr/bin/env python3
"""
NWS Weather TUI — Animated ASCII windsock (speed-driven droop + flutter).
"""

from __future__ import annotations

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


def windsock_lines(mph: Optional[float], now: float) -> List[str]:
    """ASCII lines for the windsock frame matching wind speed `mph` at
    animation clock `now` (seconds, e.g. time.time()).

    Droop/extension encodes wind speed; two frames per speed level (past
    dead calm) alternate on a speed-scaled interval to flutter the tail.
    """
    v = mph if mph is not None else 0.0
    frames, interval = _LEVELS[-1][1], _LEVELS[-1][2]
    for max_mph, lvl_frames, lvl_interval in _LEVELS:
        if v <= max_mph:
            frames, interval = lvl_frames, lvl_interval
            break
    if interval is None or len(frames) == 1:
        frame = frames[0]
    else:
        idx = int(now / interval) % len(frames)
        frame = frames[idx]
    return frame.strip("\n").splitlines()
