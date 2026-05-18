#!/usr/bin/env python3
"""
NWS Weather TUI — Header and footer chrome.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import TYPE_CHECKING

import curses

from formatting import fmt_time
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
    else:
        lr = (
            dt.datetime.fromtimestamp(app.last_refresh).astimezone()
            if app.last_refresh else None
        )
        nxt = (
            dt.datetime.fromtimestamp(app.next_refresh).astimezone()
            if app.next_refresh else None
        )
        s = (
            f"Last: {fmt_time(lr, app.use_24h, with_date=True)}"
            f"   Next: {fmt_time(nxt, app.use_24h, with_date=True)}"
        )
        if app.offline_mode:
            s += "   OFFLINE"
        safe_addstr(
            app.stdscr, 2, 1, s[: cols - 2],
            curses.A_DIM if not app.offline_mode else curses.color_pair(4),
        )


def draw_footer(app: "App", rows: int, cols: int) -> None:
    safe_addstr(app.stdscr, rows - 2, 0, "\u2500" * (cols - 1), curses.A_DIM)
    if cols >= 100:
        helptext = (
            "c Current \u00b7 f Forecast \u00b7 h Hourly \u00b7 a Alerts \u00b7 m Moon"
            "  \u2502  "
            "l Locate \u00b7 r Refresh \u00b7 u Units \u00b7 t 12/24h \u00b7 p Pause \u00b7 g Graph"
            "  \u2502  "
            "A Anim \u00b7 </> Frame \u00b7 e Favs \u00b7 n/b Cycle \u00b7 Esc Back \u00b7 ? Help \u00b7 q Quit"
        )
    else:
        helptext = (
            "c/f/h/a/w/m Views \u00b7 l Locate \u00b7 r Refresh \u00b7 u Units"
            " \u00b7 Esc Back \u00b7 ? Help \u00b7 q Quit"
        )
    footer_x = (cols - len(helptext)) // 2
    safe_addstr(app.stdscr, rows - 1, footer_x, helptext[: cols - 1], curses.A_DIM)
