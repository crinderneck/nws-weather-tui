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
    safe_addstr(app.stdscr, 0, 1, title, curses.color_pair(1) | curses.A_BOLD)

    view_label = {
        "current": "CURRENT",
        "forecast": "FORECAST",
        "hourly": "HOURLY",
        "alerts": "ALERTS",
        "help": "HELP",
        "radar": "RADAR",
    }.get(app.view, app.view.upper())

    fav_tag = f" Fav:{len(app.favorites)}"
    right = (
        f"[{view_label}]"
        f" Units:{app.units.upper()}"
        f" Auto:{'PAUSED' if app.paused else f'{app.auto_refresh_seconds}s'}"
        f"{fav_tag}"
    )
    safe_addstr(
        app.stdscr, 0,
        clamp(cols - len(right) - 1, 1, cols - 1),
        right, curses.color_pair(5),
    )
    safe_addstr(app.stdscr, 1, 0, "\u2500" * (cols - 1), curses.A_DIM)

    if time.time() < app.status_until and app.status_msg:
        attr = curses.color_pair(4) if app.offline_mode else curses.color_pair(2)
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
    helptext = (
        "c Current|f Forecast|h Hourly|a Alerts|w Radar|"
        "l Locate|r Refresh|u Units|t 12/24h|p Pause|g Graph|"
        "A Anim|</> Frame|[/] Favs|? Help|q Quit"
    )
    safe_addstr(app.stdscr, rows - 1, 1, helptext[: cols - 2], curses.A_DIM)
