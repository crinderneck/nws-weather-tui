#!/usr/bin/env python3
"""
NWS Weather TUI — Moon phase view.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import List, Optional, Tuple, TYPE_CHECKING

import curses

from nws_weather_tui.formatting import fmt_time
from nws_weather_tui.geo import clamp
from nws_weather_tui.helpers import safe_addstr
from nws_weather_tui.moon import (
    get_moonrise_moonset,
    lunation_number,
    moon_age,
    moon_illumination,
    moon_phase_name,
    next_moon_phases,
)

if TYPE_CHECKING:
    from nws_weather_tui.app import App


# ---------------------------------------------------------------------------
# ASCII moon renderer
# ---------------------------------------------------------------------------

SYNODIC = 29.53058770576
# A half-block pixel's height / width. Terminal cells are ~2.1:1, so half
# a cell is slightly taller than wide.
PX_ASPECT = 1.05
# Free pairs: radar uses 20..229 and the windsock 16, and pair numbers
# above 255 wrap on common curses builds.
_PAIR_LIT, _PAIR_DARK, _PAIR_LIT_ON_DARK = 240, 241, 242
_pairs_ready: Optional[bool] = None


def _init_pairs() -> bool:
    """Pale lit side, grey shadow, and the mixed half-block pair. False when
    the terminal can't do it — the caller then draws full blocks only."""
    global _pairs_ready
    if _pairs_ready is None:
        try:
            if curses.COLOR_PAIRS <= _PAIR_LIT_ON_DARK:
                raise curses.error("not enough colour pairs")
            lit, dark = (253, 239) if curses.COLORS >= 256 else (
                curses.COLOR_WHITE, curses.COLOR_BLACK)
            curses.init_pair(_PAIR_LIT, lit, -1)
            curses.init_pair(_PAIR_DARK, dark, -1)
            curses.init_pair(_PAIR_LIT_ON_DARK, lit, dark)
            _pairs_ready = True
        except curses.error:
            _pairs_ready = False
    return _pairs_ready


def moon_width(cell_rows: int) -> int:
    """Cells wide a moon `cell_rows` tall needs to come out round."""
    return round(cell_rows * 2 * PX_ASPECT)


def _moon_pixels(age: float, px_h: int, px_w: int) -> List[List[int]]:
    """px_h × px_w grid: 0 outside the disc, 1 shadow, 2 lit. Half-block
    pixels are roughly square, so the disc is a true circle."""
    phase = (age % SYNODIC) / SYNODIC   # 0 new … 0.5 full … 1 new
    waxing = phase < 0.5
    cos_term = math.cos(2 * math.pi * (phase if waxing else phase - 0.5))
    r = px_h * PX_ASPECT / 2.0  # radius in pixel-widths
    cx, cy = px_w / 2.0, px_h / 2.0
    grid = [[0] * px_w for _ in range(px_h)]
    for py in range(px_h):
        dy = (py + 0.5 - cy) * PX_ASPECT / r
        if abs(dy) >= 1:
            continue
        half = math.sqrt(1 - dy * dy)
        for px in range(px_w):
            dx = (px + 0.5 - cx) / r
            if abs(dx) >= half:
                continue
            norm = dx / half  # -1 left limb … +1 right limb
            lit = norm >= cos_term if waxing else norm <= cos_term
            grid[py][px] = 2 if lit else 1
    return grid


def _draw_moon(win, y0: int, x0: int, age: float, cell_rows: int) -> int:
    """Draw the moon with half blocks; returns its width in cells."""
    px_h = cell_rows * 2
    px_w = moon_width(cell_rows)
    grid = _moon_pixels(age, px_h, px_w)
    fancy = _init_pairs()
    lit_attr = curses.color_pair(_PAIR_LIT) if fancy else curses.color_pair(14) | curses.A_BOLD
    dark_attr = curses.color_pair(_PAIR_DARK) if fancy else curses.A_DIM
    for row in range(cell_rows):
        top, bot = grid[2 * row], grid[2 * row + 1]
        for col in range(px_w):
            t, b = top[col], bot[col]
            if not t and not b:
                continue
            if t == b:
                ch, attr = "█", lit_attr if t == 2 else dark_attr
            elif not t or not b:
                ch = "▄" if not t else "▀"
                attr = lit_attr if (t or b) == 2 else dark_attr
            elif fancy:
                ch = "▀" if t == 2 else "▄"
                attr = curses.color_pair(_PAIR_LIT_ON_DARK)
            else:
                ch, attr = "▀", lit_attr if t == 2 else dark_attr
            safe_addstr(win, y0 + row, x0 + col, ch, attr)
    return px_w


# ---------------------------------------------------------------------------
# Main draw function
# ---------------------------------------------------------------------------

def draw_moon(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()

    today = dt.date.today()
    age = moon_age(today)
    phase = moon_phase_name(age)
    illum = moon_illumination(age)
    upcoming = next_moon_phases(today)

    info: List[Tuple[str, int]] = [
        (phase, curses.color_pair(14) | curses.A_BOLD),
        (f"{illum:.0%} illuminated", 0),
        (f"{age:.1f} days into lunation #{lunation_number(today)}", curses.A_DIM),
        ("", 0),
    ]
    rise, mset = get_moonrise_moonset(app.lat, app.lon, today)
    if rise or mset:
        info.append((f"Moonrise  {fmt_time(rise, app.use_24h) if rise else '—'}", 0))
        info.append((f"Moonset   {fmt_time(mset, app.use_24h) if mset else '—'}", 0))
    else:
        info.append(("Moonrise/set: install 'astral' for times", curses.A_DIM))
    info += [("", 0), ("Upcoming", curses.color_pair(1) | curses.A_BOLD)]
    for name, pdate in upcoming:
        days = (pdate - today).days
        when = f"{pdate.strftime('%a %b')} {pdate.day}"
        info.append((f"{name:<14} {when:<11} in {days}d", 0))
    info_w = max(len(t) for t, _ in info)

    # Side by side when there's room for a moon as tall as the screen plus
    # the details; otherwise the moon on top, details underneath.
    side_rows = max(5, rows - 1)
    if cols >= moon_width(side_rows) + 6 + info_w:
        moon_rows = side_rows
        block_w = moon_width(moon_rows) + 6 + info_w
        x0 = max(0, (cols - block_w) // 2)
        _draw_moon(win, 0, x0, age, moon_rows)
        iy = max(0, (moon_rows - len(info)) // 2)
        ix = x0 + moon_width(moon_rows) + 6
    else:
        moon_rows = clamp(rows - len(info) - 2, 5, int((cols - 1) / (2 * PX_ASPECT)))
        _draw_moon(win, 0, max(0, (cols - moon_width(moon_rows)) // 2), age, moon_rows)
        iy = moon_rows + 1
        ix = max(0, (cols - info_w) // 2)
    for i, (text, attr) in enumerate(info):
        if iy + i >= rows:
            break
        safe_addstr(win, iy + i, ix, text[: cols - ix - 1], attr)

    win.noutrefresh()
