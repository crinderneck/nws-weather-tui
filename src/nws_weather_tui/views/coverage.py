#!/usr/bin/env python3
"""
NWS Weather TUI — Outside NWS coverage: the startup notice when the IP
address is outside the US, and each panel's message when the location is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

import curses

from nws_weather_tui import __version__
from nws_weather_tui.helpers import safe_addstr, wrap_lines

if TYPE_CHECKING:
    from nws_weather_tui.app import App

TEXT_W = 64  # the notice's reading width


def draw_no_coverage(app: "App", win, what: str, x: int = 0, y: int = 0,
                     hint: bool = True) -> None:
    """A panel's whole body when the location is outside NWS coverage;
    `what` is the panel's data, e.g. "forecast". No key hint where the
    keys don't act yet (the splash: any key only skips it)."""
    rows, cols = win.getmaxyx()
    w = max(1, min(cols - 1 - x, TEXT_W + 16))
    lines: List[Tuple[str, int]] = [
        (f"✗ No {what} for {app.location_name}", curses.color_pair(4) | curses.A_BOLD),
        ("", 0),
    ]
    body = (f"{app.lat:.4f}, {app.lon:.4f} is outside National Weather Service "
            "coverage. The NWS only forecasts for the US and its territories.")
    lines += [(line, 0) for line in wrap_lines(body, w)]
    if hint:
        keys = "Press l to choose a US location"
        keys += ", or n for your next favorite." if app.favorites else "."
        lines += [("", 0), (keys, curses.A_DIM)]
    for i, (text, attr) in enumerate(lines[: max(0, rows - y)]):
        safe_addstr(win, y + i, x, text[: cols - 1 - x], attr)


def draw_ip_notice(app: "App", rows: int, cols: int) -> None:
    """In place of the startup splash: the IP address is outside the US."""
    win = app.stdscr
    loc = app.ip_location
    where = f"{loc.place} ({loc.country})" if loc and loc.place else (loc.country if loc else "?")
    w = max(1, min(cols - 4, TEXT_W))
    lines: List[Tuple[str, int]] = [
        ("✗  You appear to be outside the US", curses.color_pair(4) | curses.A_BOLD),
        ("", 0),
    ]
    for para in (
        f"Your IP address places you in {where}.",
        "This app uses the US National Weather Service, which only forecasts "
        "for the US and its territories. Weather for anywhere else won't load.",
    ):
        lines += [(line, 0) for line in wrap_lines(para, w)] + [("", 0)]
    lines += [
        (f"Location: {app.location_name}", curses.color_pair(1) | curses.A_BOLD),
        ("", 0),
        ("Enter  continue        q  quit", curses.A_BOLD),
        ("", 0),
    ]
    lines += [(line, curses.A_DIM) for line in wrap_lines(
        'Set "detect_location": false in config.json to skip this check.', w)]

    x = max(1, (cols - w) // 2)
    y0 = max(0, (rows - len(lines) - 2) // 2)
    for i, (text, attr) in enumerate(lines):
        if y0 + i >= rows - 1:
            break
        safe_addstr(win, y0 + i, x, text[: cols - x - 1], attr)
    footer = f"NWS Weather TUI v{__version__}"
    safe_addstr(win, rows - 1, max(1, (cols - len(footer)) // 2), footer[: cols - 2],
                curses.A_DIM)
