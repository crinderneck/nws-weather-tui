#!/usr/bin/env python3
"""
NWS Weather TUI — Help screen view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import curses

from constants import CONFIG_PATH, STATE_PATH
from helpers import safe_addstr, wrap_lines

if TYPE_CHECKING:
    from app import App


def draw_help(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()

    lines = [
        "NWS Weather TUI \u2014 Help",
        "",
        "Views:",
        "  c  Current conditions \u2014 station obs, mini-graphs, radar panel",
        "  f  Forecast (day/night NWS periods) \u2014 j/k to scroll",
        "  h  Hourly (next N hours) \u2014 sparklines + tabular view",
        "  a  Alerts \u2014 j/k to scroll",
        "  w  Full-screen radar map \u2014 press w again to return",
        "  m  Moon phase \u2014 current phase, illumination, upcoming dates",
        "",
        "Favourites editor (press e):",
        "  j / k    Move cursor up / down",
        "  d        Delete selected favourite",
        "  r        Rename selected favourite",
        "  a        Add new favourite (search by city/ZIP)",
        "  J / K    Reorder selected favourite up / down",
        "  Enter    Jump to selected favourite",
        "  e / Esc  Exit editor",
        "",
        "Radar keys:",
        "  A        Toggle animation (cycles through last N MRMS frames)",
        "  < / >    Step backward / forward one animation frame",
        "  o        Open weather.gov radar in browser",
        "  Mouse    Left-click a city marker/label to jump there",
        "",
        "Radar colour mode:",
        '  256-color: half-block (\u2580/\u2584) chars with NWS standard dBZ colour scale',
        "             (requires terminal supporting 256 colours + curses.can_change_color)",
        '  ASCII:     fallback ramp " .:-=+*#%@" with R/S/I precipitation kind colouring',
        "",
        "Radar sources (tried in order):",
        "  1. NOAA MRMS ImageServer  (national composite, near real-time)",
        "  2. Iowa State IEM NEXRAD WMS  (CONUS composite, NWS colour table)",
        "  3. NWS station OpenGeoServer WMS  (per-station, lower resolution)",
        "",
        "Other actions:",
        "  l  Search location (city, state or ZIP)",
        "  r  Force refresh",
        "  u  Toggle US / SI units",
        "  t  Toggle 12h/24h clock",
        "  p  Pause/resume auto-refresh",
        "  g  Toggle mini-graphs on current view",
        "  F  Toggle current location as favourite",
        "  n / b  Cycle saved favourites",
        "  e  Open favourites editor",
        "  q  Quit",
        "",
        "Config:",
        f"  {CONFIG_PATH}",
        "",
        "Offline state:",
        f"  {STATE_PATH}",
        "",
        "Requires: pip install pillow requests",
        "Optional: pip install astral  (for sunrise/sunset times)",
    ]

    y = 0
    for i, line in enumerate(lines):
        for wline in wrap_lines(line, cols - 1):
            if y >= rows:
                break
            safe_addstr(win, y, 0, wline[: cols - 1], curses.A_BOLD if i == 0 else 0)
            y += 1
        if y >= rows:
            break

    win.noutrefresh()
