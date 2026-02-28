#!/usr/bin/env python3
"""
NWS Weather TUI — Sparklines and bar chart functions.
"""

from __future__ import annotations

from typing import List, Optional

from helpers import clamp

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: List[Optional[float]], width: int) -> str:
    if width <= 0:
        return ""
    if not values:
        return " " * width
    if len(values) != width:
        out: List[Optional[float]] = []
        if len(values) == 1:
            out = [values[0]] * width
        else:
            for i in range(width):
                idx = int(i * (len(values) - 1) / max(1, width - 1))
                out.append(values[idx])
        values = out

    clean = [v for v in values if v is not None]
    if not clean:
        return " " * width
    lo, hi = min(clean), max(clean)
    if hi - lo < 1e-9:
        return SPARK_CHARS[0] * width

    chars: List[str] = []
    for v in values:
        if v is None:
            chars.append(" ")
            continue
        t = (v - lo) / (hi - lo)
        idx = int(t * (len(SPARK_CHARS) - 1))
        chars.append(SPARK_CHARS[clamp(idx, 0, len(SPARK_CHARS) - 1)])
    return "".join(chars)


def bar_pct(pct: Optional[float], width: int, fill: str = "█", empty: str = "░") -> str:
    if width <= 0:
        return ""
    if pct is None:
        return empty * width
    pct = clamp(int(round(pct)), 0, 100)
    filled = int(round((pct / 100.0) * width))
    return fill * filled + empty * (width - filled)
