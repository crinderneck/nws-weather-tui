#!/usr/bin/env python3
"""
NWS Weather TUI — Forecast view.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import curses

from formatting import fmt_time, parse_iso
from geo import clamp
from helpers import get_sunrise_sunset, safe_addstr, wrap_lines
from icons import ICON_TINY

if TYPE_CHECKING:
    from app import App


def draw_forecast(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    periods = app.forecast_periods
    if not periods:
        safe_addstr(
            win, 0, 0, "No forecast yet. Press r to refresh.", curses.color_pair(4)
        )
        win.noutrefresh()
        return

    safe_addstr(
        win, 0, 0, "Forecast  (NWS day/night periods):"[: cols - 1], curses.A_BOLD
    )

    start_row = 2
    app.fc_scroll = clamp(app.fc_scroll, 0, max(0, len(periods) - 1))

    y = start_row
    idx = app.fc_scroll
    sun_cache: Dict[str, Tuple[Optional[dt.datetime], Optional[dt.datetime]]] = {}
    while y < rows and idx < len(periods):
        p = periods[idx]
        icon = ICON_TINY.get(p.icon_key, "?")
        temp = (
            "\u2014" if p.temperature is None
            else f"{p.temperature:.0f}\u00b0{p.temperature_unit}"
        )
        wind = f"{p.wind_dir} {p.wind_speed}".strip()

        start_dt = (
            parse_iso(p.start) if isinstance(p.start, str) else p.start
        )
        if start_dt:
            date_key = start_dt.date().isoformat()
            if date_key not in sun_cache:
                sr, ss = get_sunrise_sunset(app.lat, app.lon, start_dt.date())
                sun_cache[date_key] = (sr, ss)
            sunrise_dt, sunset_dt = sun_cache[date_key]
        else:
            sunrise_dt, sunset_dt = None, None

        if p.is_daytime and sunrise_dt:
            sun_str = f" ({fmt_time(sunrise_dt, False)})"
        elif not p.is_daytime and sunset_dt:
            sun_str = f" ({fmt_time(sunset_dt, False)})"
        else:
            sun_str = ""

        line1 = f"{icon} {p.name:<14}{sun_str:<8}  {temp:<7}  {wind:<16}  {p.short_forecast}"
        safe_addstr(
            win, y, 0, line1[: cols - 1],
            curses.color_pair(2) if idx == app.fc_scroll else 0,
        )
        y += 1

        for wline in wrap_lines(p.detailed_forecast, max(20, cols - 4)):
            if y >= rows:
                break
            safe_addstr(win, y, 2, wline[: cols - 3], curses.A_DIM)
            y += 1

        if y < rows:
            safe_addstr(win, y, 0, " " * (cols - 1))
            y += 1
        idx += 1

    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {app.fc_scroll + 1}/{len(periods)} (j/k \u2191\u2193)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()
