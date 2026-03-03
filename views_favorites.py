#!/usr/bin/env python3
"""
NWS Weather TUI — Favorites editor view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import curses

from helpers import safe_addstr

if TYPE_CHECKING:
    from app import App


def draw_favorites(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()

    safe_addstr(win, 0, 0, "Favorites Editor", curses.color_pair(1) | curses.A_BOLD)
    safe_addstr(win, 1, 0, "\u2500" * min(cols - 1, 40), curses.A_DIM)

    if not app.favorites:
        safe_addstr(win, 3, 0, "No favorites yet.", curses.A_DIM)
        safe_addstr(win, 4, 0, "Press 'a' to add one, or 'F' from any view.", curses.A_DIM)
    else:
        header = f" {'#':>3}  {'Name':<30} {'Lat':>9}  {'Lon':>10}"
        safe_addstr(win, 3, 0, header[:cols - 1], curses.A_DIM)

        max_visible = rows - 7  # room for header, footer hints
        for i, fav in enumerate(app.favorites):
            y = 4 + i
            if i >= max_visible or y >= rows - 2:
                break
            name = str(fav.get("name", "—"))[:30]
            lat = fav.get("lat", 0.0)
            lon = fav.get("lon", 0.0)
            line = f" {i + 1:>3}  {name:<30} {lat:>9.4f}  {lon:>10.4f}"

            if i == app.fav_edit_idx:
                safe_addstr(win, y, 0, line[:cols - 1], curses.color_pair(2) | curses.A_BOLD)
            else:
                safe_addstr(win, y, 0, line[:cols - 1])

    hint_y = rows - 2
    hints = "j/k Move | d Delete | r Rename | a Add | J/K Reorder | Enter Jump | e/Esc Exit"
    safe_addstr(win, hint_y, 0, hints[:cols - 1], curses.A_DIM)

    win.noutrefresh()
