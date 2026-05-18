#!/usr/bin/env python3
"""
NWS Weather TUI — Key dispatch, mouse handling, input prompts.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional, TYPE_CHECKING

import curses

from favorites import cycle_favorite, handle_favorites_key, toggle_favorite
from geo import clamp
from helpers import safe_addstr

if TYPE_CHECKING:
    from app import App


def handle_key(app: "App", ch: int) -> bool:
    if app.view == "favorites":
        return handle_favorites_key(app, ch)
    if ch == curses.KEY_RESIZE:
        rows, cols = app.stdscr.getmaxyx()
        app._flash(f"Resized to {cols}\u00d7{rows}", 1.5)
        return True

    key_handlers = {
        ord("q"): lambda: False,
        ord("Q"): lambda: False,
        ord("?"): lambda: _set_view(app, "help"),
        curses.KEY_MOUSE: lambda: _handle_mouse_event(app),
        ord("c"): lambda: _set_view(app, "current"),
        ord("f"): lambda: _set_view(app, "forecast"),
        ord("h"): lambda: _set_view(app, "hourly"),
        ord("a"): lambda: _set_view(app, "alerts"),
        ord("m"): lambda: _set_view(app, "moon"),
        ord("l"): lambda: search_location(app),
        ord("r"): lambda: _do_refresh(app),
        ord("u"): lambda: _toggle_units(app),
        ord("t"): lambda: _toggle_time_format(app),
        ord("p"): lambda: _toggle_pause(app),
        ord("g"): lambda: _toggle_graphs(app),
        ord("A"): lambda: _toggle_radar_anim(app),
        ord("o"): lambda: _open_radar_browser(app),
        ord("e"): lambda: _set_view(app, "favorites"),
        ord("n"): lambda: cycle_favorite(app, 1),
        ord("b"): lambda: cycle_favorite(app, -1),
        ord("F"): lambda: toggle_favorite(app),
    }
    handler = key_handlers.get(ch)
    if handler:
        return handler()  # type: ignore[return-value]
    if ch in (curses.KEY_DOWN, ord("j")):
        scroll(app, 1)
    elif ch in (curses.KEY_UP, ord("k")):
        scroll(app, -1)
    elif ch in (curses.KEY_LEFT, ord("<")):
        if app.view == "current":
            from radar_state import step_radar_frame
            step_radar_frame(app, -1)
    elif ch in (curses.KEY_RIGHT, ord(">")):
        if app.view == "current":
            from radar_state import step_radar_frame
            step_radar_frame(app, 1)
    elif ch == 27:  # Escape
        app.view = "current"
    elif ch == ord("G"):
        _jump_scroll(app, "bottom")
    elif ch == curses.KEY_NPAGE:
        scroll(app, 10)
    elif ch == curses.KEY_PPAGE:
        scroll(app, -10)
    return True


def handle_mouse(app: "App", mx: int, my: int, bstate: int) -> None:
    click_mask = (
        getattr(curses, "BUTTON1_CLICKED", 0)
        | getattr(curses, "BUTTON1_PRESSED", 0)
        | getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0)
        | getattr(curses, "BUTTON1_TRIPLE_CLICKED", 0)
        | getattr(curses, "BUTTON1_RELEASED", 0)
    )
    if click_mask and not (bstate & click_mask):
        return
    if app.view != "current" or not app.show_radar_map:
        return
    if app._radar_map_cols <= 0 or app._radar_map_rows <= 0:
        return
    rx = int(mx) - app._radar_map_x
    ry = int(my) - app._radar_map_y
    if rx < 0 or ry < 0 or rx >= app._radar_map_cols or ry >= app._radar_map_rows:
        return
    hit = app._radar_city_hitmap.get((rx, ry))
    if not hit:
        return
    code, lat, lon = hit
    if abs(app.lat - lat) < 1e-4 and abs(app.lon - lon) < 1e-4:
        app._flash(f"Already at {code}.", 1.2)
        return
    app._apply_location(code, lat, lon)
    app._flash(f"Location set: {code}", 1.8)


def prompt_line(app: "App", prompt: str, max_len: int = 96) -> Optional[str]:
    rows, cols = app.stdscr.getmaxyx()
    max_input = clamp(min(max_len, cols - len(prompt) - 4), 1, max_len)
    old_paused = app.paused
    app.paused = True
    curses.echo()
    curses.curs_set(1)
    app.stdscr.timeout(-1)
    app.stdscr.nodelay(False)
    try:
        safe_addstr(app.stdscr, rows - 1, 0, " " * max(1, cols - 1))
        safe_addstr(app.stdscr, rows - 1, 1, prompt[: cols - 2], curses.A_BOLD)
        app.stdscr.refresh()
        x = clamp(len(prompt) + 1, 1, max(1, cols - 2))
        app.stdscr.move(rows - 1, x)
        raw = app.stdscr.getstr(rows - 1, x, max_input)
        return raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    finally:
        curses.noecho()
        curses.curs_set(0)
        app.paused = old_paused
        app.stdscr.timeout(500)
        app.stdscr.nodelay(False)


def _parse_lat_lon(text: str) -> Optional[tuple[float, float]]:
    """Try to parse 'lat,lon' or 'lat lon' from text. Returns (lat, lon) or None."""
    import re
    m = re.match(r"^\s*([+-]?\d+\.?\d*)\s*[,\s]\s*([+-]?\d+\.?\d*)\s*$", text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return (lat, lon)
    return None


def search_location(app: "App") -> bool:
    q = prompt_line(app, "Location (city/state, ZIP, or lat,lon): ")
    if q is None or not q.strip():
        app._flash("Location search canceled.", 1.4)
        return True
    try:
        coords = _parse_lat_lon(q.strip())
        if coords:
            lat, lon = coords
            name = f"{lat:.4f}, {lon:.4f}"
            confirm = prompt_line(app, f"Apply '{name}'? (y/n): ", max_len=3)
            if confirm and confirm.lower().startswith("y"):
                app._apply_location(name, lat, lon)
                app._flash(f"Location set: {name}", 1.8)
            else:
                app._flash("Location search canceled.", 1.4)
            return True
        app._show_loading("Searching location...")
        g = app.client.geocode_us(q.strip())
        if not g:
            app._flash(f"No match found for '{q}'.", 2.5)
            return True
        name, lat, lon = g
        confirm = prompt_line(app, f"Apply '{name}'? (y/n): ", max_len=3)
        if confirm and confirm.lower().startswith("y"):
            app._apply_location(name, lat, lon)
            app._flash(f"Location set: {name}", 1.8)
        else:
            app._flash("Location search canceled.", 1.4)
    except Exception as e:
        app._flash(f"Location search failed: {e}", 3.5)
    return True


def _set_view(app: "App", view: str) -> bool:
    app.view = view
    return True


def _handle_mouse_event(app: "App") -> bool:
    try:
        _id, mx, my, _z, bstate = curses.getmouse()
        handle_mouse(app, mx, my, bstate)
    except Exception:
        pass
    return True


def _do_refresh(app: "App") -> bool:
    app._radar_last = 0.0
    from weather_refresh import refresh_all
    refresh_all(app, force=True, allow_offline=True)
    return True


def _toggle_units(app: "App") -> bool:
    app.units = "si" if app.units == "us" else "us"
    app.client.cache.clear()
    from weather_refresh import refresh_all
    refresh_all(app, force=True, allow_offline=True)
    app._save_cfg()
    return True


def _toggle_time_format(app: "App") -> bool:
    app.use_24h = not app.use_24h
    app._flash("Toggled time format.", 1.2)
    app._save_cfg()
    return True


def _toggle_pause(app: "App") -> bool:
    app.paused = not app.paused
    app._flash("Paused." if app.paused else "Resumed.", 1.2)
    return True


def _toggle_graphs(app: "App") -> bool:
    app.show_graph_panel_on_current = not app.show_graph_panel_on_current
    app._flash(
        "Graph panel ON" if app.show_graph_panel_on_current else "Graph panel OFF",
        1.2,
    )
    app._save_cfg()
    return True


def _toggle_radar_anim(app: "App") -> bool:
    from radar_state import toggle_radar_anim
    return toggle_radar_anim(app)


def _open_radar_browser(app: "App") -> bool:
    url = "https://radar.weather.gov/"
    try:
        if sys.platform == "darwin":
            cmd = ["open", url]
        elif sys.platform == "win32":
            cmd = ["start", url]
        else:
            cmd = ["xdg-open", url]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    app._flash(f"Opened {url}", 3.0)
    return True


def _jump_scroll(app: "App", position: str) -> None:
    if position == "top":
        if app.view == "forecast":
            app.fc_scroll = 0
        elif app.view == "alerts":
            app.alert_line_scroll = 0
        elif app.view == "hourly":
            app.hr_scroll = 0
        elif app.view == "help":
            app.help_scroll = 0
    elif position == "bottom":
        if app.view == "forecast":
            app.fc_scroll = max(0, len(app.forecast_periods) - 1)
        elif app.view == "alerts":
            app.alert_line_scroll = 9999
        elif app.view == "hourly":
            app.hr_scroll = max(0, len(app.hourly_periods) - 1)
        elif app.view == "help":
            app.help_scroll = 9999


def scroll(app: "App", direction: int) -> None:
    if app.view == "forecast":
        app.fc_scroll += direction
    elif app.view == "alerts":
        app.alert_line_scroll = max(0, app.alert_line_scroll + direction)
    elif app.view == "hourly":
        app.hr_scroll += direction
    elif app.view == "help":
        app.help_scroll = max(0, app.help_scroll + direction)
