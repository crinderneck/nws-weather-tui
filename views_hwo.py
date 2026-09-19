#!/usr/bin/env python3
"""
NWS Weather TUI — Hazardous Weather Outlook (HWO) view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import curses

from formatting import fmt_time, parse_iso
from geo import clamp
from helpers import safe_addstr
from text_product import render_text_product

if TYPE_CHECKING:
    from app import App


def draw_hwo(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()

    hwo = app.hwo
    if not hwo or not hwo.get("text"):
        safe_addstr(
            win, 0, 0,
            "No hazardous weather outlook available yet.",
            curses.color_pair(3) | curses.A_BOLD,
        )
        win.noutrefresh()
        return

    office = hwo.get("office") or "—"
    issued_dt = parse_iso(hwo.get("issuance_time"))
    issued_s = fmt_time(issued_dt, app.use_24h, True) if issued_dt else "—"
    header = f"Hazardous Weather Outlook — {office}   Issued: {issued_s}"
    safe_addstr(win, 0, 0, header[: cols - 1], curses.color_pair(15) | curses.A_BOLD)

    lines = render_text_product(hwo["text"], max(1, cols - 1))
    total = len(lines)
    view_rows = rows - 3

    app.hwo_scroll = clamp(app.hwo_scroll, 0, max(0, total - max(1, view_rows)))

    y = 2
    for line, is_title in lines[app.hwo_scroll:]:
        if y >= rows - 1:
            break
        attr = curses.color_pair(2) | curses.A_BOLD if is_title else 0
        safe_addstr(win, y, 0, line[: cols - 1], attr)
        y += 1

    scroll_pos = app.hwo_scroll + 1
    scroll_max = max(1, total - max(1, view_rows) + 1)
    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {scroll_pos}/{scroll_max} (j/k ↑↓)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()
