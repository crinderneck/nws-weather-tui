#!/usr/bin/env python3
"""
NWS Weather TUI — Current conditions view.
"""

from __future__ import annotations

import time
from typing import List, Tuple, TYPE_CHECKING

import curses

from conversions import c_to_f, dewpoint_c, m_to_mi, mps_to_mph, pa_to_inhg
from formatting import fmt_num, fmt_time
from geo import clamp
from helpers import safe_addstr
from icons import ICON_BIG
from views_radar import draw_radar_panel
from windsock import windsock_lines

if TYPE_CHECKING:
    from app import App

_CARDINAL = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _deg_to_cardinal(deg: float) -> str:
    idx = int((deg + 11.25) / 22.5) % 16
    return _CARDINAL[idx]


def _aqi_attr(aqi: int) -> int:
    if aqi <= 50:
        return curses.color_pair(3)               # Good — green
    if aqi <= 100:
        return curses.color_pair(2)                # Moderate — yellow
    if aqi <= 150:
        return curses.color_pair(2) | curses.A_BOLD  # Unhealthy for Sensitive Groups
    if aqi <= 200:
        return curses.color_pair(4)                # Unhealthy — red
    if aqi <= 300:
        return curses.color_pair(5)                # Very Unhealthy — magenta
    return curses.color_pair(4) | curses.A_BOLD    # Hazardous


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

    # --- Build the text block first, so the icon can be vertically centered against it ---
    text_lines: List[Tuple[str, int]] = [
        (temp_str, curses.color_pair(2) | curses.A_BOLD),
        (c.text_description, curses.A_DIM),
        (f"Dew Point: {dp_str}", curses.color_pair(2)),
        (f"Wind: {wind_str}  Gust: {gust_str}  Dir: {wind_dir}", 0),
        (f"Humidity: {hum_str}   Pressure: {press_str}   Visibility: {vis_str}", 0),
    ]
    if app.air_quality and app.air_quality.aqi is not None:
        aq = app.air_quality
        pollutant = f"  ({aq.primary_pollutant})" if aq.primary_pollutant else ""
        text_lines.append(
            (f"Air Quality: {aq.aqi} \u2014 {aq.category}{pollutant}", _aqi_attr(aq.aqi))
        )
    text_lines.append((
        f"Station: {c.station}   Observed: {fmt_time(c.timestamp, app.use_24h, with_date=True)}",
        curses.A_DIM,
    ))
    if app.alerts:
        top = app.alerts[0]
        text_lines.append((
            f"Active Alerts: {len(app.alerts)}  (press 'a')",
            curses.color_pair(4) | curses.A_BOLD,
        ))
        text_lines.append((f"  {top.event} \u2014 {top.headline}", curses.color_pair(4)))
    else:
        text_lines.append(("Active Alerts: 0", curses.A_DIM))

    # --- Icon, vertically centered against the text block ---
    icon_h = min(len(icon_lines), rows)
    text_h = min(len(text_lines), rows)
    icon_y0 = max(0, (text_h - icon_h) // 2)
    for i, line in enumerate(icon_lines[: rows - icon_y0]):
        safe_addstr(win, icon_y0 + i, 0, line[:left_w], curses.color_pair(2))

    # --- Text block ---
    y = 0
    for text, attr in text_lines:
        safe_addstr(win, y, x0, text[: cols - x0 - 1], attr)
        y += 1

    # --- Windsock, top-aligned to the right of the text block ---
    text_max_w = max((len(t) for t, _ in text_lines), default=0)
    sock_x = x0 + text_max_w + 3
    sock_lines = windsock_lines(mps_to_mph(c.wind_mps), time.time())
    sock_w = max((len(l) for l in sock_lines), default=0)
    if sock_w and sock_x + sock_w < cols:
        for i, line in enumerate(sock_lines[:rows]):
            safe_addstr(win, i, sock_x, line, curses.color_pair(6))

    # --- Radar panel ---
    if app.show_radar_map and y + 4 < rows:
        draw_radar_panel(app, win, y, cols, rows, full_screen=False)

    win.noutrefresh()
