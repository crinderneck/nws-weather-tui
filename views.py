#!/usr/bin/env python3
"""
NWS Weather TUI — Views/rendering code.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import curses

from constants import CONFIG_PATH, NWS_RADAR_PALETTE, STATE_PATH
from helpers import (
    c_to_f,
    clamp,
    dewpoint_c,
    fmt_num,
    fmt_time,
    get_sunrise_sunset,
    m_to_mi,
    mps_to_mph,
    pa_to_inhg,
    parse_iso,
    safe_addstr,
    wrap_lines,
)
from icons import ICON_BIG, ICON_TINY
from sparklines import bar_pct, sparkline

if TYPE_CHECKING:
    from app import App


# ---------------------------------------------------------------------------
# Shared layout helpers
# ---------------------------------------------------------------------------

def _draw_radar_panel(
    app: "App",
    win,
    y: int,
    cols: int,
    rows: int,
    full_screen: bool = False,
) -> None:
    """Draw radar map, legend, and overlays starting at row y.

    When full_screen=True the panel fills the entire win; otherwise it shares
    space with the current-conditions panel above.
    """
    radar_cfg = dict(app.cfg.get("radar", {}) or {})
    ramp = str(radar_cfg.get("ascii_ramp", " .:-=+*#%@"))
    show_state_lines = bool(radar_cfg.get("show_state_lines", True))
    show_city_labels = bool(radar_cfg.get("show_city_labels", True))

    # --- header line ---
    n_frames = len(app._radar_frames)
    frame_idx = app._radar_frame_idx + 1  # 1-based display
    anim_tag = (
        f"  ANIM {frame_idx}/{n_frames}" if app._radar_anim_playing
        else f"  frame {frame_idx}/{max(1, n_frames)}" if n_frames > 1
        else ""
    )
    ts_tag = f"  {app._radar_ts_utc}" if app._radar_ts_utc else ""
    mode_tag = " [256-color]" if app._radar_has_256color else " [ASCII]"
    state_tag = f" — {app.state_code}" if app.state_code else ""
    header = (
        f"Radar{state_tag}{ts_tag}{anim_tag}{mode_tag}"
        f"  [w] full  [A] anim  [</> step]  [o] browser"
        f"  (O=you @=city |=border  click to jump)"
    )
    safe_addstr(win, y, 0, header[: cols - 1], curses.color_pair(15) | curses.A_BOLD)
    y += 1

    # --- legend line ---
    if y < rows:
        app.draw_radar_legend(win, y, 0, cols)
        y += 1

    # --- radar map ---
    map_rows = rows - y - 1
    map_cols = max(20, cols - 1) if full_screen else max(20, min(cols - 1, int((cols - 1) * 0.96)))
    map_x = (cols - 1 - map_cols) // 2 if not full_screen else 0

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
        # --- 256-color halfblock rendering ---
        for i, row_cells in enumerate(app._radar_cells[:map_rows]):
            ry = y + i
            if ry >= rows:
                break
            app._draw_radar_halfblock_line(win, ry, row_cells, cols, x_off=map_x)
            if show_state_lines and i < len(app._radar_state_overlay):
                app._draw_state_overlay_line(
                    win, ry, app._radar_state_overlay[i], cols, x_off=map_x
                )
            if i < len(city_lines):
                app._draw_city_overlay_line(win, ry, city_lines[i], cols, x_off=map_x)

    elif app._radar_ascii:
        # --- ASCII fallback rendering ---
        for i, line in enumerate(app._radar_ascii[:map_rows]):
            ry = y + i
            if ry >= rows:
                break
            kind = app._radar_kind[i] if i < len(app._radar_kind) else ""
            app._draw_radar_ascii_line(win, ry, line, kind, cols, ramp, x_off=map_x)
            if show_state_lines and i < len(app._radar_state_overlay):
                app._draw_state_overlay_line(
                    win, ry, app._radar_state_overlay[i], cols, x_off=map_x
                )
            if i < len(city_lines):
                app._draw_city_overlay_line(win, ry, city_lines[i], cols, x_off=map_x)

    elif app._radar_err:
        safe_addstr(
            win, y, map_x,
            f"(radar unavailable: {app._radar_err})"[:map_cols],
            curses.color_pair(4),
        )
    else:
        safe_addstr(
            win, y, map_x,
            "(loading radar…)"[:map_cols],
            curses.A_DIM,
        )


# ---------------------------------------------------------------------------
# Header / Footer
# ---------------------------------------------------------------------------

def draw_header(app: "App", rows: int, cols: int) -> None:
    title = f"{app.location_name} — NWS Weather TUI"
    safe_addstr(app.stdscr, 0, 1, title, curses.color_pair(1) | curses.A_BOLD)

    view_label = {
        "current": "CURRENT",
        "forecast": "FORECAST",
        "hourly": "HOURLY",
        "alerts": "ALERTS",
        "help": "HELP",
        "radar": "RADAR",
    }.get(app.view, app.view.upper())

    fav_tag = f" Fav:{len(app.favorites)}"
    right = (
        f"[{view_label}]"
        f" Units:{app.units.upper()}"
        f" Auto:{'PAUSED' if app.paused else f'{app.auto_refresh_seconds}s'}"
        f"{fav_tag}"
    )
    safe_addstr(
        app.stdscr, 0,
        clamp(cols - len(right) - 1, 1, cols - 1),
        right, curses.color_pair(5),
    )
    safe_addstr(app.stdscr, 1, 0, "─" * (cols - 1), curses.A_DIM)

    if time.time() < app.status_until and app.status_msg:
        attr = curses.color_pair(4) if app.offline_mode else curses.color_pair(2)
        safe_addstr(app.stdscr, 2, 1, app.status_msg[: cols - 2], attr)
    else:
        lr = (
            dt.datetime.fromtimestamp(app.last_refresh).astimezone()
            if app.last_refresh else None
        )
        nxt = (
            dt.datetime.fromtimestamp(app.next_refresh).astimezone()
            if app.next_refresh else None
        )
        s = (
            f"Last: {fmt_time(lr, app.use_24h, with_date=True)}"
            f"   Next: {fmt_time(nxt, app.use_24h, with_date=True)}"
        )
        if app.offline_mode:
            s += "   OFFLINE"
        safe_addstr(
            app.stdscr, 2, 1, s[: cols - 2],
            curses.A_DIM if not app.offline_mode else curses.color_pair(4),
        )


def draw_footer(app: "App", rows: int, cols: int) -> None:
    safe_addstr(app.stdscr, rows - 2, 0, "─" * (cols - 1), curses.A_DIM)
    helptext = (
        "c Current|f Forecast|h Hourly|a Alerts|w Radar|"
        "l Locate|r Refresh|u Units|t 12/24h|p Pause|g Graph|"
        "A Anim|</> Frame|[/] Favs|? Help|q Quit"
    )
    safe_addstr(app.stdscr, rows - 1, 1, helptext[: cols - 2], curses.A_DIM)


# ---------------------------------------------------------------------------
# Current conditions view
# ---------------------------------------------------------------------------

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
    x0 = left_w

    for i, line in enumerate(icon_lines[:rows]):
        safe_addstr(win, i, 0, line[:left_w], curses.color_pair(2))

    y = 0
    if app.units == "us":
        temp_str = f"{fmt_num(c_to_f(c.temperature_c), 1)} °F"
        dp_str = f"{fmt_num(c_to_f(dewpoint_c(c.temperature_c, c.humidity_pct)), 1)} °F"
        wind_str = f"{fmt_num(mps_to_mph(c.wind_mps), 1)} mph"
        gust_str = (
            f"{fmt_num(mps_to_mph(c.gust_mps), 1)} mph"
            if c.gust_mps is not None else "—"
        )
        press_str = (
            f"{fmt_num(pa_to_inhg(c.pressure_pa), 2)} inHg"
            if c.pressure_pa is not None else "—"
        )
        vis_str = (
            f"{fmt_num(m_to_mi(c.visibility_m), 1)} mi"
            if c.visibility_m is not None else "—"
        )
    else:
        temp_str = f"{fmt_num(c.temperature_c, 1)} °C"
        dp_str = f"{fmt_num(dewpoint_c(c.temperature_c, c.humidity_pct), 1)} °C"
        wind_str = f"{fmt_num(c.wind_mps, 1)} m/s"
        gust_str = f"{fmt_num(c.gust_mps, 1)} m/s" if c.gust_mps is not None else "—"
        press_str = (
            f"{fmt_num((c.pressure_pa or 0) / 100.0, 1)} hPa"
            if c.pressure_pa is not None else "—"
        )
        vis_str = (
            f"{fmt_num((c.visibility_m or 0) / 1000.0, 1)} km"
            if c.visibility_m is not None else "—"
        )

    wind_dir = f"{fmt_num(c.wind_dir_deg, 0)}°" if c.wind_dir_deg is not None else "—"
    hum_str = f"{fmt_num(c.humidity_pct, 0)}%" if c.humidity_pct is not None else "—"

    safe_addstr(win, y, x0, c.text_description[: cols - x0 - 1], curses.A_BOLD)
    y += 1
    safe_addstr(
        win, y, x0,
        f"Temperature: {temp_str}   Dew Point: {dp_str}"[: cols - x0 - 1],
        curses.color_pair(3) | curses.A_BOLD,
    )
    y += 1
    safe_addstr(
        win, y, x0,
        f"Wind: {wind_str}  Gust: {gust_str}  Dir: {wind_dir}"[: cols - x0 - 1],
    )
    y += 1
    safe_addstr(
        win, y, x0,
        f"Humidity: {hum_str}   Pressure: {press_str}   Visibility: {vis_str}"[
            : cols - x0 - 1
        ],
    )
    y += 1
    safe_addstr(
        win, y, x0,
        f"Station: {c.station}   Observed: {fmt_time(c.timestamp, app.use_24h, with_date=True)}"[
            : cols - x0 - 1
        ],
        curses.A_DIM,
    )
    y += 1

    if app.alerts:
        safe_addstr(
            win, y, x0,
            f"Active Alerts: {len(app.alerts)}  (press 'a')"[: cols - x0 - 1],
            curses.color_pair(4) | curses.A_BOLD,
        )
        y += 1
        top = app.alerts[0]
        safe_addstr(
            win, y, x0,
            f"  {top.event} — {top.headline}"[: cols - x0 - 1],
            curses.color_pair(4),
        )
        y += 1
    else:
        safe_addstr(win, y, x0, "Active Alerts: 0"[: cols - x0 - 1], curses.color_pair(3))
        y += 1

    # --- Mini graphs ---
    if app.show_graph_panel_on_current and app.hourly_periods and y + 5 < rows:
        safe_addstr(win, y, x0, "Next 24 hours:", curses.A_BOLD)
        y += 1
        graph_w = max(10, cols - x0 - 18)
        temps = [h.temperature for h in app.hourly_periods]
        winds = [h.wind_speed_num for h in app.hourly_periods]
        pops = [h.pop for h in app.hourly_periods]

        safe_addstr(win, y, x0, "Temp  ")
        safe_addstr(win, y, x0 + 6, sparkline(temps, graph_w), curses.color_pair(7))
        y += 1
        safe_addstr(win, y, x0, "Wind  ")
        safe_addstr(win, y, x0 + 6, sparkline(winds, graph_w), curses.color_pair(6))
        y += 1

        clean_pops = [p for p in pops if isinstance(p, (int, float))]
        peak_pop = float(max(clean_pops)) if clean_pops else None
        safe_addstr(win, y, x0, "PoP   ")
        safe_addstr(win, y, x0 + 6, bar_pct(peak_pop, graph_w), curses.color_pair(5))
        safe_addstr(
            win, y, x0 + 6 + graph_w + 1,
            f"peak {fmt_num(peak_pop, 0)}%"[: cols - (x0 + 6 + graph_w + 2)],
            curses.A_DIM,
        )
        y += 2

    # --- Radar panel ---
    if app.show_radar_map and y + 4 < rows:
        _draw_radar_panel(app, win, y, cols, rows, full_screen=False)

    win.noutrefresh()


# ---------------------------------------------------------------------------
# Dedicated full-screen radar view
# ---------------------------------------------------------------------------

def draw_radar_view(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    _draw_radar_panel(app, win, 0, cols, rows, full_screen=True)
    win.noutrefresh()


# ---------------------------------------------------------------------------
# Forecast view
# ---------------------------------------------------------------------------

def draw_forecast(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    periods = app.forecast_periods
    if not periods:
        safe_addstr(
            win, 0, 0, "No forecast yet. Press r to refresh.", curses.color_pair(4)
        )
        win.noutrefresh()
        return

    safe_addstr(
        win, 0, 0, "Forecast  (NWS day/night periods):"[: cols - 1], curses.A_BOLD
    )

    start_row = 2
    app.fc_scroll = clamp(app.fc_scroll, 0, max(0, len(periods) - 1))

    y = start_row
    idx = app.fc_scroll
    sun_cache: Dict[str, Tuple[Optional[dt.datetime], Optional[dt.datetime]]] = {}
    while y < rows and idx < len(periods):
        p = periods[idx]
        icon = ICON_TINY.get(p.icon_key, "?")
        temp = (
            "—" if p.temperature is None
            else f"{p.temperature:.0f}°{p.temperature_unit}"
        )
        wind = f"{p.wind_dir} {p.wind_speed}".strip()

        start_dt = (
            parse_iso(p.start) if isinstance(p.start, str) else p.start
        )
        if start_dt:
            date_key = start_dt.date().isoformat()
            if date_key not in sun_cache:
                sr, ss = get_sunrise_sunset(app.lat, app.lon, start_dt.date())
                sun_cache[date_key] = (sr, ss)
            sunrise_dt, sunset_dt = sun_cache[date_key]
        else:
            sunrise_dt, sunset_dt = None, None

        if p.is_daytime and sunrise_dt:
            sun_str = f" ({fmt_time(sunrise_dt, False)})"
        elif not p.is_daytime and sunset_dt:
            sun_str = f" ({fmt_time(sunset_dt, False)})"
        else:
            sun_str = ""

        line1 = f"{icon} {p.name:<14}{sun_str:<8}  {temp:<7}  {wind:<16}  {p.short_forecast}"
        safe_addstr(
            win, y, 0, line1[: cols - 1],
            curses.color_pair(2) if idx == app.fc_scroll else 0,
        )
        y += 1

        for wline in wrap_lines(p.detailed_forecast, max(20, cols - 4)):
            if y >= rows:
                break
            safe_addstr(win, y, 2, wline[: cols - 3], curses.A_DIM)
            y += 1

        if y < rows:
            safe_addstr(win, y, 0, " " * (cols - 1))
            y += 1
        idx += 1

    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {app.fc_scroll + 1}/{len(periods)} (j/k ↑↓)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()


# ---------------------------------------------------------------------------
# Hourly view
# ---------------------------------------------------------------------------

def draw_hourly(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    hrs = app.hourly_periods
    if not hrs:
        safe_addstr(
            win, 0, 0,
            "No hourly forecast available. Press r to refresh.",
            curses.color_pair(4),
        )
        win.noutrefresh()
        return

    safe_addstr(
        win, 0, 0, f"Hourly forecast (next {len(hrs)}h):"[: cols - 1], curses.A_BOLD
    )

    graph_w = clamp(cols - 12, 10, cols - 10)
    temps = [h.temperature for h in hrs]
    winds = [h.wind_speed_num for h in hrs]
    pops = [h.pop for h in hrs]

    safe_addstr(win, 1, 0, "Temp:", curses.A_BOLD)
    safe_addstr(win, 1, 6, sparkline(temps, graph_w)[:graph_w], curses.color_pair(7))
    safe_addstr(win, 2, 0, "Wind:", curses.A_BOLD)
    safe_addstr(win, 2, 6, sparkline(winds, graph_w)[:graph_w], curses.color_pair(6))

    clean = [p for p in pops if isinstance(p, (int, float))]
    peak = float(max(clean)) if clean else None
    safe_addstr(win, 3, 0, "PoP :", curses.A_BOLD)
    safe_addstr(win, 3, 6, bar_pct(peak, graph_w)[:graph_w], curses.color_pair(5))
    safe_addstr(
        win, 3, 6 + graph_w + 1,
        f"peak {fmt_num(peak, 0)}%"[: cols - (6 + graph_w + 2)],
        curses.A_DIM,
    )

    header_y = 5
    safe_addstr(
        win, header_y, 0,
        "Time  Ic  Temp     Wind               PoP  Forecast"[: cols - 1],
        curses.A_DIM,
    )
    safe_addstr(win, header_y + 1, 0, "─" * (cols - 1), curses.A_DIM)

    start_row = header_y + 2
    view_rows = rows - start_row - 1
    app.hr_scroll = clamp(app.hr_scroll, 0, max(0, len(hrs) - max(1, view_rows)))

    w_time, w_ic, w_temp, w_wind, w_pop = 5, 2, 8, 18, 4
    fixed = w_time + 2 + w_ic + 2 + w_temp + 1 + w_wind + 2 + w_pop + 2
    w_fc = max(10, cols - fixed - 1)

    y = start_row
    for i in range(app.hr_scroll, min(len(hrs), app.hr_scroll + max(1, view_rows))):
        h = hrs[i]
        tstr = fmt_time(h.start, app.use_24h, with_date=False)[:w_time]
        icon = (ICON_TINY.get(h.icon_key, "?") or "?")[:w_ic]
        temp = (
            "—" if h.temperature is None
            else f"{h.temperature:.0f}°{h.temperature_unit}"
        )[:w_temp]
        wind = (f"{h.wind_dir} {h.wind_speed}".strip())[:w_wind]
        pop = ("—" if h.pop is None else f"{h.pop:.0f}%")[:w_pop]
        fc = (h.short_forecast or "—")[:w_fc]
        row = f"{tstr:>{w_time}}  {icon:^{w_ic}}  {temp:<{w_temp}} {wind:<{w_wind}}  {pop:>{w_pop}}  {fc}"
        safe_addstr(win, y, 0, row[: cols - 1])
        y += 1
        if y >= rows - 1:
            break

    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {app.hr_scroll + 1}/{max(1, len(hrs) - max(1, view_rows) + 1)} (j/k ↑↓)"[
            : cols - 1
        ],
        curses.A_DIM,
    )
    win.noutrefresh()


# ---------------------------------------------------------------------------
# Alerts view
# ---------------------------------------------------------------------------

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

        safe_addstr(win, y, 0, (a.headline or "—")[: cols - 1], curses.color_pair(2))
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
            safe_addstr(win, y, 0, "Instruction:", curses.A_BOLD)
            y += 1
            for wline in wrap_lines(instr, cols - 2):
                if y >= rows:
                    break
                safe_addstr(win, y, 1, wline[: cols - 2], curses.A_DIM)
                y += 1

        if y < rows:
            safe_addstr(win, y, 0, "─" * (cols - 1), curses.A_DIM)
            y += 1
        idx += 1

    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {app.alert_scroll + 1}/{len(app.alerts)} (j/k ↑↓)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()


# ---------------------------------------------------------------------------
# Help view
# ---------------------------------------------------------------------------

def draw_help(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()

    lines = [
        "NWS Weather TUI — Help",
        "",
        "Views:",
        "  c  Current conditions — station obs, mini-graphs, radar panel",
        "  f  Forecast (day/night NWS periods) — j/k to scroll",
        "  h  Hourly (next N hours) — sparklines + tabular view",
        "  a  Alerts — j/k to scroll",
        "  w  Full-screen radar map — press w again to return",
        "",
        "Radar keys:",
        "  A        Toggle animation (cycles through last N MRMS frames)",
        "  < / >    Step backward / forward one animation frame",
        "  o        Open weather.gov radar in browser",
        "  Mouse    Left-click a city marker/label to jump there",
        "",
        "Radar colour mode:",
        "  256-color: half-block (▀/▄) chars with NWS standard dBZ colour scale",
        "             (requires terminal supporting 256 colours + curses.can_change_color)",
        "  ASCII:     fallback ramp \" .:-=+*#%@\" with R/S/I precipitation kind colouring",
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
        "  [ / ]  Cycle saved favourites",
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
