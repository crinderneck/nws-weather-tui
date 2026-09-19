#!/usr/bin/env python3
"""
NWS Weather TUI — Sparklines and bar chart functions.
"""

from __future__ import annotations

from typing import List, Optional

from geo import clamp

_BRAILLE_BASE = 0x2800
# Unicode braille dot bit values, addressed as [col][row] (2 cols x 4 rows/cell).
_BRAILLE_BITS = [
    [0x01, 0x02, 0x04, 0x40],  # left column, top to bottom
    [0x08, 0x10, 0x20, 0x80],  # right column, top to bottom
]


def _resample(values: List[Optional[float]], n: int) -> List[Optional[float]]:
    """Resample a value series to exactly n points via linear interpolation,
    propagating None (gaps) rather than interpolating across them."""
    if n <= 0:
        return []
    if len(values) == 1:
        return [values[0]] * n
    m = len(values)
    out: List[Optional[float]] = []
    for i in range(n):
        t = i * (m - 1) / max(1, n - 1)
        lo_idx = int(t)
        hi_idx = min(lo_idx + 1, m - 1)
        frac = t - lo_idx
        v_lo, v_hi = values[lo_idx], values[hi_idx]
        if v_lo is None or v_hi is None:
            out.append(v_lo if frac < 0.5 else v_hi)
        else:
            out.append(v_lo + (v_hi - v_lo) * frac)
    return out


def braille_graph(values: List[Optional[float]], width: int, height: int) -> List[str]:
    """Render a continuous line graph using Braille dot characters.

    Packs a 2 (horizontal) x 4 (vertical) sub-pixel grid into every
    character cell, so a `height`-row graph has 4x the vertical resolution
    and 2x the horizontal resolution of a single-row block sparkline —
    enough to actually show the shape of a trend instead of a coarse
    8-level silhouette.
    """
    if width <= 0 or height <= 0:
        return [""] * max(0, height)
    if not values or all(v is None for v in values):
        return [" " * width] * height

    px_w = width * 2
    px_h = height * 4
    samples = _resample(values, px_w)

    clean = [v for v in samples if v is not None]
    lo, hi = min(clean), max(clean)
    flat = (hi - lo) < 1e-9

    def to_row(v: float) -> int:
        if flat:
            return px_h // 2
        t = (v - lo) / (hi - lo)
        return clamp(px_h - 1 - int(round(t * (px_h - 1))), 0, px_h - 1)

    grid = [[0] * width for _ in range(height)]

    def set_px(x: int, y: int) -> None:
        if 0 <= x < px_w and 0 <= y < px_h:
            cell_x, sub_x = divmod(x, 2)
            cell_y, sub_y = divmod(y, 4)
            grid[cell_y][cell_x] |= _BRAILLE_BITS[sub_x][sub_y]

    def draw_segment(x0: int, y0: int, x1: int, y1: int) -> None:
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0
        while True:
            set_px(x, y)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    prev: Optional[tuple] = None
    for x, v in enumerate(samples):
        if v is None:
            prev = None
            continue
        y = to_row(v)
        if prev is not None:
            draw_segment(prev[0], prev[1], x, y)
        else:
            set_px(x, y)
        prev = (x, y)

    return [
        "".join(chr(_BRAILLE_BASE + cell) if cell else " " for cell in row)
        for row in grid
    ]


def bar_pct(pct: Optional[float], width: int, fill: str = "█", empty: str = "░") -> str:
    if width <= 0:
        return ""
    if pct is None:
        return empty * width
    pct = clamp(int(round(pct)), 0, 100)
    filled = int(round((pct / 100.0) * width))
    return fill * filled + empty * (width - filled)
