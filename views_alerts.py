#!/usr/bin/env python3
"""
NWS Weather TUI — Alerts view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import curses

from formatting import fmt_time
from geo import clamp
from helpers import safe_addstr, wrap_lines

if TYPE_CHECKING:
    from app import App


def _build_alert_lines(app: "App", cols: int) -> List[tuple]:
    """Pre-render all alert text into (text, attr) tuples for line-based scrolling."""
    out: List[tuple] = []
    for idx, a in enumerate(app.alerts):
        title = f"{a.event}  [{a.severity}/{a.urgency}/{a.certainty}]"
        out.append((title[: cols - 1], curses.color_pair(4) | curses.A_BOLD))

        meta = (
            f"Sent: {fmt_time(a.sent, app.use_24h, True)}"
            f"   Effective: {fmt_time(a.effective, app.use_24h, True)}"
            f"   Expires: {fmt_time(a.expires, app.use_24h, True)}"
        )
        out.append((meta[: cols - 1], curses.A_DIM))

        for wline in wrap_lines(a.headline or "\u2014", cols - 1):
            out.append((wline[: cols - 1], curses.color_pair(2)))

        desc = (a.description or "").strip()
        if desc:
            for wline in wrap_lines(desc, cols - 2):
                out.append((" " + wline[: cols - 2], 0))

        instr = (a.instruction or "").strip()
        if instr:
            out.append(("", 0))
            out.append(("Instruction:", curses.A_BOLD))
            for wline in wrap_lines(instr, cols - 2):
                out.append((" " + wline[: cols - 2], curses.A_DIM))

        out.append(("\u2500" * (cols - 1), curses.A_DIM))

    return out


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

    all_lines = _build_alert_lines(app, cols)
    total = len(all_lines)
    view_rows = rows - 3  # header + footer

    app.alert_line_scroll = clamp(
        app.alert_line_scroll, 0, max(0, total - max(1, view_rows))
    )
    # Keep alert_scroll in sync for backwards compat
    app.alert_scroll = app.alert_line_scroll

    y = 2
    for text, attr in all_lines[app.alert_line_scroll:]:
        if y >= rows - 1:
            break
        safe_addstr(win, y, 0, text, attr)
        y += 1

    scroll_pos = app.alert_line_scroll + 1
    scroll_max = max(1, total - max(1, view_rows) + 1)
    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {scroll_pos}/{scroll_max} (j/k \u2191\u2193)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()
