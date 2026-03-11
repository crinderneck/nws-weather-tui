#!/usr/bin/env python3
"""
NWS Weather TUI — Alerts view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import curses

from formatting import fmt_time
from geo import clamp
from helpers import safe_addstr, wrap_lines

if TYPE_CHECKING:
    from app import App


def draw_alerts(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    if not app.alerts:
        safe_addstr(
            win, 0, 0,
            "No active alerts for this point.",
            curses.color_pair(3) | curses.A_BOLD,
        )
        win.noutrefresh()
        return

    safe_addstr(
        win, 0, 0,
        f"Active Alerts: {len(app.alerts)}  (most severe/newest first)"[: cols - 1],
        curses.color_pair(4) | curses.A_BOLD,
    )

    start_row = 2
    app.alert_scroll = clamp(app.alert_scroll, 0, max(0, len(app.alerts) - 1))

    y = start_row
    idx = app.alert_scroll
    while y < rows and idx < len(app.alerts):
        a = app.alerts[idx]
        title = f"{a.event}  [{a.severity}/{a.urgency}/{a.certainty}]"
        safe_addstr(win, y, 0, title[: cols - 1], curses.color_pair(4) | curses.A_BOLD)
        y += 1

        meta = (
            f"Sent: {fmt_time(a.sent, app.use_24h, True)}"
            f"   Effective: {fmt_time(a.effective, app.use_24h, True)}"
            f"   Expires: {fmt_time(a.expires, app.use_24h, True)}"
        )
        safe_addstr(win, y, 0, meta[: cols - 1], curses.A_DIM)
        y += 1

        for wline in wrap_lines(a.headline or "\u2014", cols - 1):
            if y >= rows:
                break
            safe_addstr(win, y, 0, wline[: cols - 1], curses.color_pair(2))
            y += 1

        desc = (a.description or "").strip()
        if desc:
            for wline in wrap_lines(desc, cols - 2):
                if y >= rows:
                    break
                safe_addstr(win, y, 1, wline[: cols - 2])
                y += 1

        instr = (a.instruction or "").strip()
        if instr and y < rows:
            y += 1  # single blank line before instruction
            safe_addstr(win, y, 0, "Instruction:", curses.A_BOLD)
            y += 1
            for wline in wrap_lines(instr, cols - 2):
                if y >= rows:
                    break
                safe_addstr(win, y, 1, wline[: cols - 2], curses.A_DIM)
                y += 1

        if y < rows:
            safe_addstr(win, y, 0, "\u2500" * (cols - 1), curses.A_DIM)
            y += 1
        idx += 1

    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {app.alert_scroll + 1}/{len(app.alerts)} (j/k \u2191\u2193)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()
