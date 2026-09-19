#!/usr/bin/env python3
"""
NWS Weather TUI — Current conditions view.
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple, TYPE_CHECKING

import curses

from conversions import c_to_f, dewpoint_c, m_to_mi, mps_to_mph, pa_to_inhg
from curses_init import WINDSOCK_ORANGE_PAIR
from formatting import fmt_num, fmt_time
from geo import clamp
from helpers import safe_addstr
from icons import ICON_BIG
from models import uv_category
from views_radar import draw_radar_panel
from windsock import WINDSOCK_MAX_W, windsock_lines

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


def _uv_attr(uv: float) -> int:
    if uv < 3:
        return curses.color_pair(3)                # Low — green
    if uv < 6:
        return curses.color_pair(2)                # Moderate — yellow
    if uv < 8:
        return curses.color_pair(2) | curses.A_BOLD  # High
    if uv < 11:
        return curses.color_pair(4)                # Very High — red
    return curses.color_pair(4) | curses.A_BOLD    # Extreme


def _draw_windsock(win, lines: List[str], x0: int, has_256color: bool) -> None:
    """Draw windsock lines with a gray pole and orange/white sock stripes.

    Stripe color alternates every 2 glyphs along the sock body, counted in
    drawing order (so it stripes correctly whether the sock is drooping
    near-vertical or extended near-horizontal), not by screen column.
    """
    gray_attr = curses.color_pair(14) | curses.A_DIM
    white_attr = curses.color_pair(14)
    orange_attr = (
        curses.color_pair(WINDSOCK_ORANGE_PAIR) if has_256color else curses.color_pair(2)
    )
    stripe_w = 2

    counter = 0
    for row, line in enumerate(lines):
        run_start: Optional[int] = None
        run_attr = None

        def flush(end_col: int) -> None:
            nonlocal run_start, run_attr
            if run_start is not None:
                safe_addstr(win, row, x0 + run_start, line[run_start:end_col], run_attr)
                run_start = None

        for col, ch in enumerate(line):
            if ch == " ":
                flush(col)
                continue
            if col <= 1:
                attr = gray_attr
            else:
                attr = white_attr if (counter // stripe_w) % 2 == 0 else orange_attr
                counter += 1
            if attr != run_attr:
                flush(col)
                run_start = col
                run_attr = attr
        flush(len(line))


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

    dp_val = dewpoint_c(c.temperature_c, c.humidity_pct)
    feels_like_c = c.heat_index_c if c.heat_index_c is not None else c.wind_chill_c
    show_feels_like = (
        feels_like_c is not None
        and c.temperature_c is not None
        and abs(feels_like_c - c.temperature_c) >= 1.0
    )
    if app.units == "us":
        temp_str = f"{fmt_num(c_to_f(c.temperature_c), 1)} \u00b0F"
        dp_str = f"{fmt_num(c_to_f(dp_val), 1)} \u00b0F" if dp_val is not None else "\u2014"
        feels_str = f"{fmt_num(c_to_f(feels_like_c), 1)} \u00b0F"
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
        feels_str = f"{fmt_num(feels_like_c, 1)} \u00b0C"
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
    ]
    if show_feels_like:
        label = "Heat Index" if c.heat_index_c is not None else "Wind Chill"
        text_lines.append((f"{label}: {feels_str}", curses.color_pair(2) | curses.A_BOLD))
    text_lines.append((f"Dew Point: {dp_str}", curses.color_pair(2)))
    text_lines += [
        (f"Wind: {wind_str}  Gust: {gust_str}  Dir: {wind_dir}", 0),
        (f"Humidity: {hum_str}   Pressure: {press_str}   Visibility: {vis_str}", 0),
    ]
    if app.air_quality and app.air_quality.aqi is not None:
        aq = app.air_quality
        pollutant = f"  ({aq.primary_pollutant})" if aq.primary_pollutant else ""
        text_lines.append(
            (f"Air Quality: {aq.aqi} \u2014 {aq.category}{pollutant}", _aqi_attr(aq.aqi))
        )
    if app.uv_index and app.uv_index.current is not None:
        uv = app.uv_index.current
        text_lines.append(
            (f"UV Index: {fmt_num(uv, 1)} \u2014 {uv_category(uv)}", _uv_attr(uv))
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

    # --- Horizontally center the icon + text + windsock block as a whole ---
    text_max_w = max((len(t) for t, _ in text_lines), default=0)
    sock_lines = windsock_lines(mps_to_mph(c.wind_mps), time.time())
    # Lay out with the sock's fixed maximum width, not this frame's actual
    # width, so the icon/text to its left don't shift as it droops/flutters.
    sock_w = WINDSOCK_MAX_W
    gap = 3

    block_w_with_sock = left_w + text_max_w + gap + sock_w
    show_sock = sock_w > 0 and block_w_with_sock <= cols - 1
    block_w = block_w_with_sock if show_sock else (left_w + text_max_w)
    margin = max(0, (cols - block_w) // 2)

    icon_x0 = margin
    x0 = margin + left_w
    sock_x = x0 + text_max_w + gap

    # --- Icon, vertically centered against the text block ---
    icon_h = min(len(icon_lines), rows)
    text_h = min(len(text_lines), rows)
    icon_y0 = max(0, (text_h - icon_h) // 2)
    for i, line in enumerate(icon_lines[: rows - icon_y0]):
        safe_addstr(win, icon_y0 + i, icon_x0, line[:left_w], curses.color_pair(2))

    # --- Text block ---
    y = 0
    for text, attr in text_lines:
        safe_addstr(win, y, x0, text[: cols - x0 - 1], attr)
        y += 1

    # --- Windsock, top-aligned to the right of the text block ---
    if show_sock:
        _draw_windsock(win, sock_lines[:rows], sock_x, app._radar_has_256color)

    # --- Radar panel ---
    if app.show_radar_map and y + 4 < rows:
        draw_radar_panel(app, win, y, cols, rows, full_screen=False)

    win.noutrefresh()
