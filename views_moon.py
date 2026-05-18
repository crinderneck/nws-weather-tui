#!/usr/bin/env python3
"""
NWS Weather TUI — Moon phase view.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import TYPE_CHECKING

import curses

from formatting import fmt_time
from helpers import safe_addstr
from moon import (
    get_moonrise_moonset,
    lunation_number,
    moon_age,
    moon_illumination,
    moon_phase_name,
    next_moon_phases,
)

if TYPE_CHECKING:
    from app import App


# ---------------------------------------------------------------------------
# ASCII moon renderer
# ---------------------------------------------------------------------------

# 15-row sphere template: each row is (start_col, end_col) of the lit disc
# within a 30-char wide frame.  Row 0 = top.
_MOON_ROWS = 15
_MOON_COLS = 40
_ASPECT = 2.0  # terminal chars are ~2x taller than wide

def _sphere_spans() -> list[tuple[int, int]]:
    """Compute the column spans of a circle on each row."""
    r = _MOON_ROWS / 2.0
    spans = []
    for row in range(_MOON_ROWS):
        y = (row + 0.5) - r
        half_w = (r * r - y * y) ** 0.5 * _ASPECT if abs(y) < r else 0.0
        cx = _MOON_COLS / 2.0
        left = int(cx - half_w + 0.5)
        right = int(cx + half_w + 0.5)
        spans.append((left, right))
    return spans

_SPANS = _sphere_spans()


def _render_moon(age: float) -> list[str]:
    """
    Render a 15×30 ASCII art moon showing current phase.

    Uses block chars to show the illuminated vs shadow side.
    Waxing: right side lit first.  Waning: left side lit first.
    """
    # Phase angle determines terminator position
    # 0 = new, 0.5 = full
    phase_frac = age / 29.53058770576  # 0..1 through cycle
    waxing = phase_frac < 0.5

    lines = []
    for row in range(_MOON_ROWS):
        left, right = _SPANS[row]
        width = right - left
        if width <= 0:
            lines.append(" " * _MOON_COLS)
            continue

        chars = [" "] * _MOON_COLS

        # Terminator position via cosine:
        # Waxing (right side lit first):
        #   phase_frac=0 (new) → cos_term=+1 → norm>=1 → nothing lit
        #   phase_frac=0.25 (1Q) → cos_term=0 → right half lit
        #   phase_frac=0.5 (full) → cos_term=-1 → all lit
        # Waning (left side stays lit):
        #   phase_frac=0.5 (full) → cos_term=+1 → norm<=1 → all lit
        #   phase_frac=0.75 (3Q) → cos_term=0 → left half lit
        #   phase_frac=1.0 (new) → cos_term=-1 → nothing lit
        if waxing:
            cos_term = math.cos(2 * math.pi * phase_frac)
        else:
            cos_term = math.cos(2 * math.pi * (phase_frac - 0.5))

        for col in range(left, right):
            # Normalize col position within disc: -1 (left) to +1 (right)
            norm = (2.0 * (col - left) / max(width - 1, 1)) - 1.0

            if waxing:
                lit = norm >= cos_term
            else:
                lit = norm <= cos_term

            if lit:
                chars[col] = "\u2588"  # █ Full block (lit)
            else:
                chars[col] = "\u2591"  # ░ Light shade (shadow)

        lines.append("".join(chars))
    return lines


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
    lun_num = lunation_number(today)
    upcoming = next_moon_phases(today)

    y = 0

    # Title
    title = "Moon Phase"
    if y < rows:
        safe_addstr(win, y, 0, title, curses.A_BOLD)
        y += 1

    # Render the moon
    moon_lines = _render_moon(age)
    # Center the moon horizontally
    moon_x = max((cols - _MOON_COLS) // 2, 0)
    for line in moon_lines:
        if y >= rows:
            break
        safe_addstr(win, y, moon_x, line[:cols - moon_x],
                    curses.color_pair(3))  # yellow
        y += 1

    y += 1

    # Phase info
    info_lines = [
        f"{phase} \u2014 {illum:.0%} illuminated",
        f"Moon age: {age:.1f} days into lunation",
        f"Lunation #{lun_num}",
    ]

    # Moonrise / moonset
    rise, mset = get_moonrise_moonset(app.lat, app.lon, today)
    if rise or mset:
        rise_s = fmt_time(rise, app.use_24h) if rise else "N/A"
        set_s = fmt_time(mset, app.use_24h) if mset else "N/A"
        info_lines.append(f"Moonrise: {rise_s}   Moonset: {set_s}")
    else:
        info_lines.append("Moonrise/Moonset: install 'astral' for times")

    info_x = max((cols - max(len(s) for s in info_lines)) // 2, 0)
    for line in info_lines:
        if y >= rows:
            break
        safe_addstr(win, y, info_x, line[:cols - 1])
        y += 1

    y += 1

    # Upcoming phases
    if y < rows:
        safe_addstr(win, y, 0, "Upcoming phases:", curses.A_BOLD)
        y += 1
    for name, pdate in upcoming:
        if y >= rows:
            break
        days_away = (pdate - today).days
        label = f"  {name:<16} {pdate.strftime('%b %d')}  ({days_away}d)"
        safe_addstr(win, y, 0, label[:cols - 1])
        y += 1

    win.noutrefresh()
