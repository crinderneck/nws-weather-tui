#!/usr/bin/env python3
"""
NWS Weather TUI — Header and footer chrome.
"""

from __future__ import annotations

import time
from typing import List, Tuple, TYPE_CHECKING

import curses

from geo import clamp
from helpers import safe_addstr

if TYPE_CHECKING:
    from app import App


def draw_header(app: "App", rows: int, cols: int) -> None:
    title = f"{app.location_name} \u2014 NWS Weather TUI"

    view_label = {
        "current": "CURRENT",
        "forecast": "FORECAST",
        "hourly": "HOURLY",
        "alerts": "ALERTS",
        "help": "HELP",
        "moon": "MOON",
        "favorites": "FAVORITES",
        "afd": "DISCUSSION",
        "hwo": "OUTLOOK",
        "dashboard": "DASHBOARD",
    }.get(app.view, app.view.upper())

    fav_tag = (
        f" Fav:{app.fav_idx + 1}/{len(app.favorites)}"
        if app.favorites else " Fav:0"
    )
    offline_tag = " [OFFLINE]" if app.offline_mode else ""
    right = (
        f"[{view_label}]"
        f"{offline_tag}"
        f" Units:{app.units.upper()}"
        f" Auto:{'PAUSED' if app.paused else f'{app.auto_refresh_seconds}s'}"
        f"{fav_tag}"
    )
    right_x = clamp(cols - len(right) - 1, 1, cols - 1)
    max_title = max(1, right_x - 2)
    safe_addstr(app.stdscr, 0, 1, title[:max_title], curses.color_pair(1) | curses.A_BOLD)
    safe_addstr(
        app.stdscr, 0, right_x,
        right, curses.color_pair(5),
    )
    safe_addstr(app.stdscr, 1, 0, "\u2500" * (cols - 1), curses.A_DIM)

    if time.time() < app.status_until and app.status_msg:
        attr = curses.color_pair(4) if app.offline_mode else curses.color_pair(2)
        if app._is_loading:
            attr |= curses.A_BOLD
        safe_addstr(app.stdscr, 2, 1, app.status_msg[: cols - 2], attr)


# Footer key hints: (group, priority, key, label). Lower priority numbers
# are kept first when the terminal is too narrow for everything; the
# survivors are drawn in list order, groups separated by a rule.
FOOTER_ITEMS: List[Tuple[int, int, str, str]] = [
    (0, 2, "c", "Current"),
    (0, 2, "f", "Forecast"),
    (0, 2, "h", "Hourly"),
    (0, 3, "a", "Alerts"),
    (0, 4, "m", "Moon"),
    (0, 4, "d", "Discussion"),
    (0, 5, "H", "Outlook"),
    (1, 3, "l", "Locate"),
    (1, 3, "r", "Refresh"),
    (1, 5, "u", "Units"),
    (1, 6, "t", "12/24h"),
    (1, 6, "p", "Pause"),
    (2, 7, "A", "Anim"),
    (2, 7, "</>", "Frame"),
    (2, 5, "e", "Favs"),
    (2, 5, "D", "Dashboard"),
    (2, 6, "n/b", "Cycle"),
    (2, 4, "Esc", "Back"),
    (2, 1, "?", "Help"),
    (2, 1, "q", "Quit"),
]
_ITEM_SEP = " \u00b7 "
_GROUP_SEP = "  \u2502  "


def _footer_width(items: List[Tuple[int, int, str, str]]) -> int:
    width = sum(len(k) + 1 + len(label) for _, _, k, label in items)
    for a, b in zip(items, items[1:]):
        width += len(_GROUP_SEP) if a[0] != b[0] else len(_ITEM_SEP)
    return width


def _footer_fit(cols: int) -> List[Tuple[int, int, str, str]]:
    """The highest-priority footer items that fit in `cols`, in display order."""
    kept: List[Tuple[int, int, str, str]] = []
    for item in sorted(FOOTER_ITEMS, key=lambda it: it[1]):
        trial = [it for it in FOOTER_ITEMS if it in kept or it is item]
        if _footer_width(trial) <= cols:
            kept = trial
    return kept


def draw_footer(app: "App", rows: int, cols: int) -> None:
    safe_addstr(app.stdscr, rows - 2, 0, "\u2500" * (cols - 1), curses.A_DIM)
    items = _footer_fit(cols - 2)
    x = max(0, (cols - _footer_width(items)) // 2)
    y = rows - 1
    for i, (group, _, key, label) in enumerate(items):
        if i:
            sep = _GROUP_SEP if items[i - 1][0] != group else _ITEM_SEP
            safe_addstr(app.stdscr, y, x, sep, curses.A_DIM)
            x += len(sep)
        safe_addstr(app.stdscr, y, x, key, curses.color_pair(1) | curses.A_BOLD)
        x += len(key) + 1
        safe_addstr(app.stdscr, y, x, label, curses.A_DIM)
        x += len(label)
