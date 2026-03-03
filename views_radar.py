#!/usr/bin/env python3
"""
NWS Weather TUI — Radar panel and full-screen radar view.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, List

import curses

from helpers import safe_addstr
from radar_renderer import (
    draw_city_overlay_line,
    draw_radar_ascii_line,
    draw_radar_halfblock_line,
    draw_radar_legend,
    draw_state_overlay_line,
)

if TYPE_CHECKING:
    from app import App


def draw_radar_panel(
    app: "App",
    win,
    y: int,
    cols: int,
    rows: int,
    full_screen: bool = False,
) -> None:
    """Draw radar map, legend, and overlays starting at row y."""
    radar_cfg = dict(app.cfg.get("radar", {}) or {})
    ramp = str(radar_cfg.get("ascii_ramp", " .:-=+*#%@"))
    show_state_lines = bool(radar_cfg.get("show_state_lines", True))
    show_city_labels = bool(radar_cfg.get("show_city_labels", True))

    # --- header line ---
    n_frames = len(app._radar_frames)
    frame_idx = app._radar_frame_idx + 1
    anim_tag = (
        f"  ANIM {frame_idx}/{n_frames}" if app._radar_anim_playing
        else f"  frame {frame_idx}/{max(1, n_frames)}" if n_frames > 1
        else ""
    )
    ts_tag = f"  {app._radar_ts_utc}" if app._radar_ts_utc else ""
    mode_tag = " [256-color]" if app._radar_has_256color else " [ASCII]"
    state_tag = f" \u2014 {app.state_code}" if app.state_code else ""
    header = (
        f"Radar{state_tag}{ts_tag}{anim_tag}{mode_tag}"
        f"  [w] full  [A] anim  [</> step]  [o] browser"
        f"  (O=you @=city |=border  click to jump)"
    )
    safe_addstr(win, y, 0, header[: cols - 1], curses.color_pair(15) | curses.A_BOLD)
    y += 1

    # --- legend line ---
    if y < rows:
        draw_radar_legend(win, y, 0, cols, app._radar_has_256color)
        y += 1

    # --- radar map ---
    map_rows = rows - y - 1
    max_cols = max(20, cols - 1) if full_screen else max(20, min(cols - 1, int((cols - 1) * 0.96)))

    # Constrain width to geographic aspect ratio so tall states aren't stretched
    map_cols = max_cols
    if app._radar_bbox:
        minlon, minlat, maxlon, maxlat = app._radar_bbox
        lat_span = maxlat - minlat
        lon_span = maxlon - minlon
        if lat_span > 1e-6 and lon_span > 1e-6:
            cos_lat = abs(math.cos(math.radians((minlat + maxlat) / 2)))
            geo_aspect = (lon_span * cos_lat) / lat_span
            # Terminal chars are ~2x tall as wide; half-block = 2 vpx per row
            ideal_cols = int(geo_aspect * map_rows * 2)
            map_cols = max(20, min(max_cols, ideal_cols))

    map_x = (cols - 1 - map_cols) // 2

    win_y0, win_x0 = win.getbegyx()
    app._radar_map_x = win_x0 + map_x
    app._radar_map_y = win_y0 + y
    app._radar_map_cols = map_cols
    app._radar_map_rows = max(0, map_rows)

    if map_rows < 3:
        return

    if not app._in_refresh:
        app._maybe_refresh_radar(map_cols, map_rows)

    city_lines: List[str] = app._radar_city_overlay if show_city_labels else []

    if app._radar_has_256color and app._radar_cells:
        for i, row_cells in enumerate(app._radar_cells[:map_rows]):
            ry = y + i
            if ry >= rows:
                break
            draw_radar_halfblock_line(win, ry, row_cells, cols, x_off=map_x)
            if show_state_lines and i < len(app._radar_state_overlay):
                draw_state_overlay_line(
                    win, ry, app._radar_state_overlay[i], cols, x_off=map_x
                )
            if i < len(city_lines):
                draw_city_overlay_line(win, ry, city_lines[i], cols, x_off=map_x)

    elif app._radar_ascii:
        for i, line in enumerate(app._radar_ascii[:map_rows]):
            ry = y + i
            if ry >= rows:
                break
            kind = app._radar_kind[i] if i < len(app._radar_kind) else ""
            draw_radar_ascii_line(win, ry, line, kind, cols, ramp, x_off=map_x)
            if show_state_lines and i < len(app._radar_state_overlay):
                draw_state_overlay_line(
                    win, ry, app._radar_state_overlay[i], cols, x_off=map_x
                )
            if i < len(city_lines):
                draw_city_overlay_line(win, ry, city_lines[i], cols, x_off=map_x)

    elif app._radar_err:
        safe_addstr(
            win, y, map_x,
            f"(radar unavailable: {app._radar_err})"[:map_cols],
            curses.color_pair(4),
        )
    else:
        safe_addstr(
            win, y, map_x,
            "(loading radar\u2026)"[:map_cols],
            curses.A_DIM,
        )


def draw_radar_view(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    draw_radar_panel(app, win, 0, cols, rows, full_screen=True)
    win.noutrefresh()
