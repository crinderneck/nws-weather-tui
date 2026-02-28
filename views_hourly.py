#!/usr/bin/env python3
"""
NWS Weather TUI — Hourly forecast view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import curses

from formatting import fmt_num, fmt_time
from geo import clamp
from helpers import safe_addstr
from icons import ICON_TINY
from sparklines import bar_pct, sparkline

if TYPE_CHECKING:
    from app import App


def draw_hourly(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    hrs = app.hourly_periods
    if not hrs:
        safe_addstr(
            win, 0, 0,
            "No hourly forecast available. Press r to refresh.",
            curses.color_pair(4),
        )
        win.noutrefresh()
        return

    safe_addstr(
        win, 0, 0, f"Hourly forecast (next {len(hrs)}h):"[: cols - 1], curses.A_BOLD
    )

    graph_w = clamp(cols - 12, 10, cols - 10)
    temps = [h.temperature for h in hrs]
    winds = [h.wind_speed_num for h in hrs]
    pops = [h.pop for h in hrs]

    safe_addstr(win, 1, 0, "Temp:", curses.A_BOLD)
    safe_addstr(win, 1, 6, sparkline(temps, graph_w)[:graph_w], curses.color_pair(7))
    safe_addstr(win, 2, 0, "Wind:", curses.A_BOLD)
    safe_addstr(win, 2, 6, sparkline(winds, graph_w)[:graph_w], curses.color_pair(6))

    clean = [p for p in pops if isinstance(p, (int, float))]
    peak = float(max(clean)) if clean else None
    safe_addstr(win, 3, 0, "PoP :", curses.A_BOLD)
    safe_addstr(win, 3, 6, bar_pct(peak, graph_w)[:graph_w], curses.color_pair(5))
    safe_addstr(
        win, 3, 6 + graph_w + 1,
        f"peak {fmt_num(peak, 0)}%"[: cols - (6 + graph_w + 2)],
        curses.A_DIM,
    )

    header_y = 5
    safe_addstr(
        win, header_y, 0,
        "Time  Ic  Temp     Wind               PoP  Forecast"[: cols - 1],
        curses.A_DIM,
    )
    safe_addstr(win, header_y + 1, 0, "\u2500" * (cols - 1), curses.A_DIM)

    start_row = header_y + 2
    view_rows = rows - start_row - 1
    app.hr_scroll = clamp(app.hr_scroll, 0, max(0, len(hrs) - max(1, view_rows)))

    w_time, w_ic, w_temp, w_wind, w_pop = 5, 2, 8, 18, 4
    fixed = w_time + 2 + w_ic + 2 + w_temp + 1 + w_wind + 2 + w_pop + 2
    w_fc = max(10, cols - fixed - 1)

    y = start_row
    for i in range(app.hr_scroll, min(len(hrs), app.hr_scroll + max(1, view_rows))):
        h = hrs[i]
        tstr = fmt_time(h.start, app.use_24h, with_date=False)[:w_time]
        icon = (ICON_TINY.get(h.icon_key, "?") or "?")[:w_ic]
        temp = (
            "\u2014" if h.temperature is None
            else f"{h.temperature:.0f}\u00b0{h.temperature_unit}"
        )[:w_temp]
        wind = (f"{h.wind_dir} {h.wind_speed}".strip())[:w_wind]
        pop = ("\u2014" if h.pop is None else f"{h.pop:.0f}%")[:w_pop]
        fc = (h.short_forecast or "\u2014")[:w_fc]
        row = f"{tstr:>{w_time}}  {icon:^{w_ic}}  {temp:<{w_temp}} {wind:<{w_wind}}  {pop:>{w_pop}}  {fc}"
        safe_addstr(win, y, 0, row[: cols - 1])
        y += 1
        if y >= rows - 1:
            break

    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {app.hr_scroll + 1}/{max(1, len(hrs) - max(1, view_rows) + 1)} (j/k \u2191\u2193)"[
            : cols - 1
        ],
        curses.A_DIM,
    )
    win.noutrefresh()
