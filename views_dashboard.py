#!/usr/bin/env python3
"""
NWS Weather TUI — Multi-location favorites dashboard view.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import curses

from conversions import c_to_f, mps_to_mph
from formatting import fmt_num
from geo import clamp
from helpers import safe_addstr
from icons import ICON_TINY

if TYPE_CHECKING:
    from app import App


def draw_dashboard(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()

    from dashboard import refresh_dashboard
    refresh_dashboard(app)

    safe_addstr(win, 0, 0, "Favorites Dashboard", curses.color_pair(1) | curses.A_BOLD)
    safe_addstr(win, 1, 0, "─" * min(cols - 1, 40), curses.A_DIM)

    if not app.favorites:
        safe_addstr(win, 3, 0, "No favorites yet.", curses.A_DIM)
        safe_addstr(win, 4, 0, "Press 'F' from any view to save the current location.", curses.A_DIM)
        win.noutrefresh()
        return

    header = f"{'':<2} {'Name':<24} {'Temp':>7}  {'Ic':<2}  {'Condition':<20} {'Wind':<12} {'Updated'}"
    safe_addstr(win, 3, 0, header[: cols - 1], curses.A_DIM)

    app.dash_idx = clamp(app.dash_idx, 0, len(app.favorites) - 1)
    max_visible = rows - 6
    for i, fav in enumerate(app.favorites):
        y = 4 + i
        if i >= max_visible or y >= rows - 2:
            break
        name = str(fav.get("name", "—"))[:24]
        is_here = (
            abs(float(fav.get("lat", 0)) - app.lat) < 1e-4
            and abs(float(fav.get("lon", 0)) - app.lon) < 1e-4
        )
        marker = "▸" if i == app.dash_idx else " "
        here_tag = "*" if is_here else " "

        data = app._dash_data.get(i)
        if data is None:
            line = f"{marker}{here_tag} {name:<24} {'loading…':>7}"
        elif data.get("error"):
            line = f"{marker}{here_tag} {name:<24} {'—':>7}  {'?':<2}  (unavailable)"
        else:
            c = data.get("current")
            temp_str = (
                f"{fmt_num(c_to_f(c.temperature_c), 0)}°F"
                if app.units == "us"
                else f"{fmt_num(c.temperature_c, 0)}°C"
            )
            wind_str = (
                f"{fmt_num(mps_to_mph(c.wind_mps), 0)} mph"
                if app.units == "us"
                else f"{fmt_num(c.wind_mps, 0)} m/s"
            )
            icon = ICON_TINY.get(c.icon_key, "?") or "?"
            cond = (c.text_description or "—").replace("Current Conditions: ", "")[:20]
            age_s = time.time() - data.get("ts", time.time())
            updated = f"{int(age_s // 60)}m ago" if age_s >= 60 else "just now"
            line = (
                f"{marker}{here_tag} {name:<24} {temp_str:>7}  {icon:<2}  "
                f"{cond:<20} {wind_str:<12} {updated}"
            )

        attr = curses.color_pair(2) | curses.A_BOLD if i == app.dash_idx else 0
        safe_addstr(win, y, 0, line[: cols - 1], attr)

    hint_y = rows - 2
    hints = "j/k Move | Enter Jump | r Refresh | D/Esc Back    * = current location"
    safe_addstr(win, hint_y, 0, hints[: cols - 1], curses.A_DIM)

    win.noutrefresh()
