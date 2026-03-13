#!/usr/bin/env python3
"""
NWS Weather TUI — Current conditions view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import curses

from conversions import c_to_f, dewpoint_c, m_to_mi, mps_to_mph, pa_to_inhg

_CARDINAL = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _deg_to_cardinal(deg: float) -> str:
    idx = int((deg + 11.25) / 22.5) % 16
    return _CARDINAL[idx]
from formatting import fmt_num, fmt_time
from geo import clamp
from helpers import safe_addstr
from icons import ICON_BIG
from sparklines import bar_pct, sparkline
from views_radar import draw_radar_panel

if TYPE_CHECKING:
    from app import App


def draw_current(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    win_y0, win_x0 = win.getbegyx()

    if not app.current:
        safe_addstr(
            win, 0, 0,
            "No current conditions yet. Press r to refresh.",
            curses.color_pair(4),
        )
        win.noutrefresh()
        return

    c = app.current
    icon_lines = ICON_BIG.get(c.icon_key, ICON_BIG["unknown"]).strip("\n").splitlines()
    icon_w = max((len(x) for x in icon_lines), default=0)
    left_w = clamp(icon_w + 2, 12, cols - 1)
    x0 = left_w

    for i, line in enumerate(icon_lines[:rows]):
        safe_addstr(win, i, 0, line[:left_w], curses.color_pair(2))

    y = 0
    dp_val = dewpoint_c(c.temperature_c, c.humidity_pct)
    if app.units == "us":
        temp_str = f"{fmt_num(c_to_f(c.temperature_c), 1)} \u00b0F"
        dp_str = f"{fmt_num(c_to_f(dp_val), 1)} \u00b0F" if dp_val is not None else "\u2014"
        wind_str = f"{fmt_num(mps_to_mph(c.wind_mps), 1)} mph"
        gust_str = (
            f"{fmt_num(mps_to_mph(c.gust_mps), 1)} mph"
            if c.gust_mps is not None else "\u2014"
        )
        press_str = (
            f"{fmt_num(pa_to_inhg(c.pressure_pa), 2)} inHg"
            if c.pressure_pa is not None else "\u2014"
        )
        vis_str = (
            f"{fmt_num(m_to_mi(c.visibility_m), 1)} mi"
            if c.visibility_m is not None else "\u2014"
        )
    else:
        temp_str = f"{fmt_num(c.temperature_c, 1)} \u00b0C"
        dp_str = f"{fmt_num(dp_val, 1)} \u00b0C" if dp_val is not None else "\u2014"
        wind_str = f"{fmt_num(c.wind_mps, 1)} m/s"
        gust_str = f"{fmt_num(c.gust_mps, 1)} m/s" if c.gust_mps is not None else "\u2014"
        press_str = (
            f"{fmt_num((c.pressure_pa or 0) / 100.0, 1)} hPa"
            if c.pressure_pa is not None else "\u2014"
        )
        vis_str = (
            f"{fmt_num((c.visibility_m or 0) / 1000.0, 1)} km"
            if c.visibility_m is not None else "\u2014"
        )

    wind_dir = (
        f"{_deg_to_cardinal(c.wind_dir_deg)} ({fmt_num(c.wind_dir_deg, 0)}\u00b0)"
        if c.wind_dir_deg is not None else "\u2014"
    )
    hum_str = f"{fmt_num(c.humidity_pct, 0)}%" if c.humidity_pct is not None else "\u2014"

    safe_addstr(
        win, y, x0, temp_str[: cols - x0 - 1],
        curses.color_pair(2) | curses.A_BOLD,
    )
    y += 1
    safe_addstr(win, y, x0, c.text_description[: cols - x0 - 1], curses.A_DIM)
    y += 1
    safe_addstr(
        win, y, x0,
        f"Dew Point: {dp_str}"[: cols - x0 - 1],
        curses.color_pair(2),
    )
    y += 1
    safe_addstr(
        win, y, x0,
        f"Wind: {wind_str}  Gust: {gust_str}  Dir: {wind_dir}"[: cols - x0 - 1],
    )
    y += 1
    safe_addstr(
        win, y, x0,
        f"Humidity: {hum_str}   Pressure: {press_str}   Visibility: {vis_str}"[
            : cols - x0 - 1
        ],
    )
    y += 1
    safe_addstr(
        win, y, x0,
        f"Station: {c.station}   Observed: {fmt_time(c.timestamp, app.use_24h, with_date=True)}"[
            : cols - x0 - 1
        ],
        curses.A_DIM,
    )
    y += 1

    if app.alerts:
        safe_addstr(
            win, y, x0,
            f"Active Alerts: {len(app.alerts)}  (press 'a')"[: cols - x0 - 1],
            curses.color_pair(4) | curses.A_BOLD,
        )
        y += 1
        top = app.alerts[0]
        safe_addstr(
            win, y, x0,
            f"  {top.event} \u2014 {top.headline}"[: cols - x0 - 1],
            curses.color_pair(4),
        )
        y += 1
    else:
        safe_addstr(win, y, x0, "Active Alerts: 0"[: cols - x0 - 1], curses.A_DIM)
        y += 1

    # --- Mini graphs ---
    if app.show_graph_panel_on_current and app.hourly_periods and y + 5 < rows:
        safe_addstr(win, y, x0, "Next 24 hours:", curses.A_BOLD)
        y += 1
        graph_w = max(10, cols - x0 - 18)
        temps = [h.temperature for h in app.hourly_periods]
        winds = [h.wind_speed_num for h in app.hourly_periods]
        pops = [h.pop for h in app.hourly_periods]

        clean_temps = [t for t in temps if t is not None]
        t_lo = f"{min(clean_temps):.0f}" if clean_temps else ""
        t_hi = f"{max(clean_temps):.0f}" if clean_temps else ""
        safe_addstr(win, y, x0, "Temp  ")
        safe_addstr(win, y, x0 + 6, sparkline(temps, graph_w), curses.color_pair(7))
        safe_addstr(win, y, x0 + 6 + graph_w + 1, f"{t_lo}-{t_hi}"[: cols - (x0 + 6 + graph_w + 2)], curses.A_DIM)
        y += 1
        clean_winds = [w for w in winds if w is not None]
        w_hi = f"{max(clean_winds):.0f}" if clean_winds else ""
        safe_addstr(win, y, x0, "Wind  ")
        safe_addstr(win, y, x0 + 6, sparkline(winds, graph_w), curses.color_pair(6))
        safe_addstr(win, y, x0 + 6 + graph_w + 1, f"max {w_hi}"[: cols - (x0 + 6 + graph_w + 2)], curses.A_DIM)
        y += 1

        clean_pops = [p for p in pops if isinstance(p, (int, float))]
        peak_pop = float(max(clean_pops)) if clean_pops else None
        safe_addstr(win, y, x0, "PoP   ")
        safe_addstr(win, y, x0 + 6, bar_pct(peak_pop, graph_w), curses.color_pair(5))
        safe_addstr(
            win, y, x0 + 6 + graph_w + 1,
            f"peak {fmt_num(peak_pop, 0)}%"[: cols - (x0 + 6 + graph_w + 2)],
            curses.A_DIM,
        )
        y += 2

    # --- Radar panel ---
    if app.show_radar_map and y + 4 < rows:
        draw_radar_panel(app, win, y, cols, rows, full_screen=False)

    win.noutrefresh()
