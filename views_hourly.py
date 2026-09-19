#!/usr/bin/env python3
"""
NWS Weather TUI — Hourly forecast view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import curses

from conversions import mm_to_in
from formatting import fmt_num, fmt_time
from geo import clamp
from helpers import safe_addstr
from icons import ICON_TINY
from sparklines import bar_pct, braille_graph

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

    temps = [h.temperature for h in hrs]
    pops = [h.pop for h in hrs]

    y = 1
    clean_temps = [t for t in temps if isinstance(t, (int, float))]
    if clean_temps:
        unit = next((h.temperature_unit for h in hrs if h.temperature_unit), "")
        lo_t, hi_t = min(clean_temps), max(clean_temps)
        label = (
            f"Temperature (°{unit})   {fmt_num(lo_t, 0)}° – {fmt_num(hi_t, 0)}°"
        )
    else:
        label = "Temperature"
    safe_addstr(win, y, 0, label[: cols - 1], curses.A_BOLD)
    y += 1

    # Prioritize height over width: a tall, narrower chart reads as an
    # actual trend line, where a single-row-tall full-width one just looks
    # like a flat squiggle. Reserve room for the fixed rows around it (title,
    # label, PoP, QPF, spacer, table header/divider, footer) plus a minimum
    # of table rows so the graph can't crowd the hourly table off-screen.
    fixed_overhead = 8
    min_table_rows = 5
    graph_h = clamp(rows - fixed_overhead - min_table_rows, 4, 10)
    graph_w = clamp(cols - 30, 30, 60)
    graph_x = max(0, (cols - graph_w) // 2)
    for i, line in enumerate(braille_graph(temps, graph_w, graph_h)):
        safe_addstr(win, y + i, graph_x, line[:graph_w], curses.color_pair(7))
    y += graph_h

    clean = [p for p in pops if isinstance(p, (int, float))]
    peak = float(max(clean)) if clean else None
    pop_bar_w = clamp(cols - 6 - 11, 10, cols - 7)
    safe_addstr(win, y, 0, "PoP: ", curses.A_BOLD)
    safe_addstr(win, y, 6, bar_pct(peak, pop_bar_w)[:pop_bar_w], curses.color_pair(5))
    safe_addstr(
        win, y, 6 + pop_bar_w + 1,
        f"peak {fmt_num(peak, 0)}%"[: cols - (6 + pop_bar_w + 2)],
        curses.A_DIM,
    )
    y += 1

    precip_mm = [h.precip_mm for h in hrs]
    snow_mm = [h.snow_mm for h in hrs]
    clean_precip = [p for p in precip_mm if isinstance(p, (int, float))]
    clean_snow = [s for s in snow_mm if isinstance(s, (int, float))]
    if clean_precip:
        total_precip_mm = sum(clean_precip)
        total_snow_mm = sum(clean_snow) if clean_snow else 0.0
        if app.units == "us":
            precip_str = f"QPF: total {fmt_num(mm_to_in(total_precip_mm), 2)} in expected"
            snow_str = (
                f"  ({fmt_num(mm_to_in(total_snow_mm), 1)} in snow)"
                if total_snow_mm > 0 else ""
            )
        else:
            precip_str = f"QPF: total {fmt_num(total_precip_mm, 1)} mm expected"
            snow_str = (
                f"  ({fmt_num(total_snow_mm, 1)} mm snow)"
                if total_snow_mm > 0 else ""
            )
        safe_addstr(win, y, 0, f"{precip_str}{snow_str}"[: cols - 1], curses.A_DIM)
        y += 1

    y += 1  # spacer before the table

    # Column x-positions (proportional, with minimums)
    x_time = 0
    x_icon = 8
    x_temp = 12
    x_wind = 21
    x_pop = min(40, max(30, cols - 40))
    x_fc = min(46, x_pop + 6)

    header_y = y
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
