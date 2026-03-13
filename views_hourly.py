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
            curses.A_DIM,
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
    safe_addstr(win, 3, 0, "PoP: ", curses.A_BOLD)
    safe_addstr(win, 3, 6, bar_pct(peak, graph_w)[:graph_w], curses.color_pair(5))
    safe_addstr(
        win, 3, 6 + graph_w + 1,
        f"peak {fmt_num(peak, 0)}%"[: cols - (6 + graph_w + 2)],
        curses.A_DIM,
    )

    # Column x-positions (proportional, with minimums)
    x_time = 0
    x_icon = 8
    x_temp = 12
    x_wind = 21
    x_pop = min(40, max(30, cols - 40))
    x_fc = min(46, x_pop + 6)

    header_y = 5
    safe_addstr(win, header_y, x_time, "Time", curses.A_BOLD)
    safe_addstr(win, header_y, x_icon, "Ic", curses.A_BOLD)
    safe_addstr(win, header_y, x_temp, "Temp", curses.A_BOLD)
    safe_addstr(win, header_y, x_wind, "Wind", curses.A_BOLD)
    safe_addstr(win, header_y, x_pop, "PoP", curses.A_BOLD)
    safe_addstr(win, header_y, x_fc, "Forecast", curses.A_BOLD)
    safe_addstr(win, header_y + 1, 0, "\u2500" * (cols - 1), curses.A_DIM)

    start_row = header_y + 2
    view_rows = rows - start_row - 1
    app.hr_scroll = clamp(app.hr_scroll, 0, max(0, len(hrs) - max(1, view_rows)))
    w_fc = max(10, cols - x_fc - 1)

    y = start_row
    for i in range(app.hr_scroll, min(len(hrs), app.hr_scroll + max(1, view_rows))):
        h = hrs[i]
        tstr = fmt_time(h.start, app.use_24h, with_date=False)
        icon = ICON_TINY.get(h.icon_key, "?") or "?"
        temp = (
            "\u2014" if h.temperature is None
            else f"{h.temperature:.0f}\u00b0{h.temperature_unit}"
        )
        wind = f"{h.wind_dir} {h.wind_speed}".strip()
        pop = "\u2014" if h.pop is None else f"{h.pop:.0f}%"
        fc = (h.short_forecast or "\u2014")[:w_fc]

        safe_addstr(win, y, x_time, tstr[:7].rjust(7))
        safe_addstr(win, y, x_icon, icon[:2])
        safe_addstr(win, y, x_temp, temp[:8])
        safe_addstr(win, y, x_wind, wind[:19])
        safe_addstr(win, y, x_pop, pop[:5].rjust(4))
        safe_addstr(win, y, x_fc, fc)
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
