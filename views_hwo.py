#!/usr/bin/env python3
"""
NWS Weather TUI — Hazardous Weather Outlook (HWO) view.

Same newspaper layout as the forecast discussion. Many offices only issue
an outlook when there's something hazardous to flag, so the empty state
says so rather than implying the data is still loading.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import curses

from formatting import fmt_time
from helpers import safe_addstr, wrap_lines
from views_afd import draw_text_product

if TYPE_CHECKING:
    from app import App


def draw_hwo(app: "App", win) -> None:
    def empty(win, rows: int, cols: int) -> None:
        office = app.office_id or "this office"
        safe_addstr(win, 0, 0, f"No Hazardous Weather Outlook from {office} right now"[: cols - 1],
                    curses.color_pair(3) | curses.A_BOLD)
        checked = fmt_time(dt.datetime.fromtimestamp(app.last_refresh), app.use_24h) \
            if app.last_refresh else "—"
        safe_addstr(win, 1, 0, f"Checked {checked}"[: cols - 1], curses.A_DIM)
        note = ("Offices issue an outlook when there's hazardous weather to flag in the "
                "coming week, so none usually means nothing notable is expected. "
                "Press d for the forecaster's current discussion, or a for alerts.")
        for i, line in enumerate(wrap_lines(note, min(cols - 1, 90))):
            if 3 + i >= rows:
                break
            safe_addstr(win, 3 + i, 0, line)

    draw_text_product(app, win, app.hwo, "Hazardous Weather Outlook", "hwo_scroll", empty=empty)
