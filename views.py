#!/usr/bin/env python3
"""
NWS Weather TUI — Views/rendering code.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import curses

from constants import CONFIG_PATH, STATE_PATH
from helpers import (
    c_to_f,
    clamp,
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


def draw_header(app: "App", rows: int, cols: int) -> None:
    title = f"{app.location_name} — NWS Weather TUI"
    safe_addstr(app.stdscr, 0, 1, title, curses.color_pair(1) | curses.A_BOLD)

    view_label = {
        "current": "CURRENT",
        "forecast": "FORECAST",
        "hourly": "HOURLY",
        "alerts": "ALERTS",
        "help": "HELP",
    }[app.view]

    fav_tag = f" Fav:{len(app.favorites)}" if app.favorites else " Fav:0"
    right = f"[{view_label}] Units:{app.units.upper()} Auto:{'PAUSED' if app.paused else f'{app.auto_refresh_seconds}s'}{fav_tag}"
    safe_addstr(
        app.stdscr,
        0,
        clamp(cols - len(right) - 1, 1, cols - 1),
        right,
        curses.color_pair(5),
    )

    safe_addstr(app.stdscr, 1, 0, "─" * (cols - 1), curses.A_DIM)

    if time.time() < app.status_until and app.status_msg:
        msg = app.status_msg
        attr = curses.color_pair(4) if app.offline_mode else curses.color_pair(2)
        safe_addstr(app.stdscr, 2, 1, msg[: cols - 2], attr)
    else:
        lr = (
            dt.datetime.fromtimestamp(app.last_refresh).astimezone()
            if app.last_refresh
            else None
        )
        nxt = (
            dt.datetime.fromtimestamp(app.next_refresh).astimezone()
            if app.next_refresh
            else None
        )
        s = f"Last: {fmt_time(lr, app.use_24h, with_date=True)}   Next: {fmt_time(nxt, app.use_24h, with_date=True)}"
        if app.offline_mode:
            s += "   OFFLINE"
        safe_addstr(
            app.stdscr,
            2,
            1,
            s[: cols - 2],
            curses.A_DIM if not app.offline_mode else curses.color_pair(4),
        )


def draw_footer(app: "App", rows: int, cols: int) -> None:
    safe_addstr(app.stdscr, rows - 2, 0, "─" * (cols - 1), curses.A_DIM)
    helptext = "c Current|f Forecast|h Hourly|a Alerts|l Locate|w Radar|r Refresh|u Units|t 12/24h|p Pause|g Graph|[/] Favorites|? Help|q Quit"
    safe_addstr(app.stdscr, rows - 1, 1, helptext[: cols - 2], curses.A_DIM)


def draw_current(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    win_y0, win_x0 = win.getbegyx()

    if not app.current:
        safe_addstr(
            win,
            0,
            0,
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
    temp = (
        f"{fmt_num(c_to_f(c.temperature_c), 1)} °F"
        if app.units == "us"
        else f"{fmt_num(c.temperature_c, 1)} °C"
    )

    safe_addstr(win, y, x0, c.text_description[: cols - x0 - 1], curses.A_BOLD)
    y += 1
    safe_addstr(
        win,
        y,
        x0,
        f"Temperature: {temp}"[: cols - x0 - 1],
        curses.color_pair(3) | curses.A_BOLD,
    )
    y += 1

    if app.units == "us":
        wind = f"{fmt_num(mps_to_mph(c.wind_mps), 1)} mph"
        gust = (
            f"{fmt_num(mps_to_mph(c.gust_mps), 1)} mph"
            if c.gust_mps is not None
            else "—"
        )
    else:
        wind = f"{fmt_num(c.wind_mps, 1)} m/s"
        gust = f"{fmt_num(c.gust_mps, 1)} m/s" if c.gust_mps is not None else "—"
    wind_dir = f"{fmt_num(c.wind_dir_deg, 0)}°" if c.wind_dir_deg is not None else "—"
    safe_addstr(
        win, y, x0, f"Wind: {wind}  Gust: {gust}  Dir: {wind_dir}"[: cols - x0 - 1]
    )
    y += 1

    hum = f"{fmt_num(c.humidity_pct, 0)}%" if c.humidity_pct is not None else "—"
    if app.units == "us":
        press = (
            f"{fmt_num(pa_to_inhg(c.pressure_pa), 2)} inHg"
            if c.pressure_pa is not None
            else "—"
        )
        vis = (
            f"{fmt_num(m_to_mi(c.visibility_m), 1)} mi"
            if c.visibility_m is not None
            else "—"
        )
    else:
        press = (
            f"{fmt_num((c.pressure_pa or 0) / 100.0, 1)} hPa"
            if c.pressure_pa is not None
            else "—"
        )
        vis = (
            f"{fmt_num((c.visibility_m or 0) / 1000.0, 1)} km"
            if c.visibility_m is not None
            else "—"
        )
    safe_addstr(
        win,
        y,
        x0,
        f"Humidity: {hum}   Pressure: {press}   Visibility: {vis}"[: cols - x0 - 1],
    )
    y += 1

    safe_addstr(
        win,
        y,
        x0,
        f"Station: {c.station}   Observed: {fmt_time(c.timestamp, app.use_24h, with_date=True)}"[
            : cols - x0 - 1
        ],
        curses.A_DIM,
    )
    y += 1

    if app.alerts:
        safe_addstr(
            win,
            y,
            x0,
            f"Active Alerts: {len(app.alerts)}  (press 'a')"[: cols - x0 - 1],
            curses.color_pair(4) | curses.A_BOLD,
        )
        y += 1
        top = app.alerts[0]
        safe_addstr(
            win,
            y,
            x0,
            f"Top: {top.event} — {top.headline}"[: cols - x0 - 1],
            curses.color_pair(4),
        )
        y += 1
    else:
        safe_addstr(
            win, y, x0, "Active Alerts: 0"[: cols - x0 - 1], curses.color_pair(3)
        )
        y += 1

    if app.show_graph_panel_on_current and app.hourly_periods and y + 6 < rows:
        safe_addstr(win, y, x0, "Next 24 hours (hourly):", curses.A_BOLD)
        y += 1

        graph_w = max(10, cols - x0 - 18)
        temps = [h.temperature for h in app.hourly_periods]
        winds = [h.wind_speed_num for h in app.hourly_periods]
        pops = [h.pop for h in app.hourly_periods]

        sp_t = sparkline(temps, graph_w)
        safe_addstr(win, y, x0, "Temp  ")
        safe_addstr(win, y, x0 + 6, sp_t, curses.color_pair(7))
        y += 1

        sp_w = sparkline(winds, graph_w)
        safe_addstr(win, y, x0, "Wind  ")
        safe_addstr(win, y, x0 + 6, sp_w, curses.color_pair(6))
        y += 1

        peak = None
        clean = [p for p in pops if isinstance(p, (int, float))]
        if clean:
            peak = float(max(clean))
        bar = bar_pct(peak, graph_w)
        safe_addstr(win, y, x0, "PoP   ")
        safe_addstr(win, y, x0 + 6, bar, curses.color_pair(5))
        safe_addstr(
            win,
            y,
            x0 + 6 + graph_w + 1,
            f"peak {fmt_num(peak, 0)}%"[: cols - (x0 + 6 + graph_w + 2)],
            curses.A_DIM,
        )
        y += 2

    if app.show_radar_map and y + 4 < rows:
        radar_cfg = dict(app.cfg.get("radar", {}) or {})
        ramp = str(radar_cfg.get("ascii_ramp", " .:-=+*#%@"))
        show_state_lines = bool(radar_cfg.get("show_state_lines", True))
        show_city_labels = bool(radar_cfg.get("show_city_labels", True))
        state_name = app.state_code or "state"
        safe_addstr(
            win,
            y,
            0,
            f"Radar — {state_name}  [w toggle]  (O you  @ city  | borders  rain=grn snow=blu  click city to jump)"[
                : cols - 1
            ],
            curses.A_BOLD,
        )
        y += 1
        map_rows = rows - y - 1
        map_cols = max(20, min(cols - 1, int((cols - 1) * 0.82)))
        map_x = (cols - 1 - map_cols) // 2
        if map_rows >= 3:
            app._radar_map_x = win_x0 + map_x
            app._radar_map_y = win_y0 + y
            app._radar_map_cols = map_cols
            app._radar_map_rows = map_rows
            if not app._in_refresh:
                app._maybe_refresh_radar(map_cols, map_rows)
            if app._radar_ascii:
                city_lines = app._radar_city_overlay if show_city_labels else []
                for i, line in enumerate(app._radar_ascii[:map_rows]):
                    kind = app._radar_kind[i] if i < len(app._radar_kind) else ""
                    app._draw_radar_line(
                        win, y + i, line, kind, cols, ramp, x_off=map_x
                    )
                    if show_state_lines and i < len(app._radar_state_overlay):
                        app._draw_state_overlay_line(
                            win, y + i, app._radar_state_overlay[i], cols, x_off=map_x
                        )
                    if i < len(city_lines):
                        app._draw_city_overlay_line(
                            win, y + i, city_lines[i], cols, x_off=map_x
                        )
            elif app._radar_err:
                safe_addstr(
                    win,
                    y,
                    map_x,
                    f"(radar unavailable: {app._radar_err})"[:map_cols],
                    curses.color_pair(4),
                )

    win.noutrefresh()


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
        win, 0, 0, "Forecast periods (as provided by NWS):"[: cols - 1], curses.A_BOLD
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
            "—"
            if p.temperature is None
            else f"{p.temperature:.0f}°{p.temperature_unit}"
        )
        wind = f"{p.wind_dir} {p.wind_speed}".strip()

        if p.start:
            start_dt = parse_iso(p.start) if isinstance(p.start, str) else p.start
            if start_dt:
                date_key = start_dt.date().isoformat()
                if date_key not in sun_cache:
                    sr, ss = get_sunrise_sunset(app.lat, app.lon, start_dt.date())
                    sun_cache[date_key] = (sr, ss)
                sunrise_dt, sunset_dt = sun_cache[date_key]
            else:
                sunrise_dt, sunset_dt = None, None
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
            win,
            y,
            0,
            line1[: cols - 1],
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
        win,
        rows - 1,
        0,
        f"Scroll: {app.fc_scroll + 1}/{len(periods)} (j/k or ↑/↓)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()


def draw_hourly(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    hrs = app.hourly_periods
    if not hrs:
        safe_addstr(
            win,
            0,
            0,
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

    peak = None
    clean = [p for p in pops if isinstance(p, (int, float))]
    if clean:
        peak = float(max(clean))
    safe_addstr(win, 3, 0, "PoP :", curses.A_BOLD)
    safe_addstr(win, 3, 6, bar_pct(peak, graph_w)[:graph_w], curses.color_pair(5))
    safe_addstr(
        win,
        3,
        6 + graph_w + 1,
        f"peak {fmt_num(peak, 0)}%"[: cols - (6 + graph_w + 2)],
        curses.A_DIM,
    )

    header_y = 5
    safe_addstr(
        win,
        header_y,
        0,
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
            "—"
            if h.temperature is None
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
        win,
        rows - 1,
        0,
        f"Scroll: {app.hr_scroll + 1}/{max(1, len(hrs) - max(1, view_rows) + 1)} (j/k or ↑/↓)"[
            : cols - 1
        ],
        curses.A_DIM,
    )
    win.noutrefresh()


def draw_alerts(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    if not app.alerts:
        safe_addstr(
            win,
            0,
            0,
            "No active alerts for this point.",
            curses.color_pair(3) | curses.A_BOLD,
        )
        win.noutrefresh()
        return

    safe_addstr(
        win,
        0,
        0,
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

        meta = f"Sent: {fmt_time(a.sent, app.use_24h, True)}   Effective: {fmt_time(a.effective, app.use_24h, True)}   Expires: {fmt_time(a.expires, app.use_24h, True)}"
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
        win,
        rows - 1,
        0,
        f"Scroll: {app.alert_scroll + 1}/{len(app.alerts)} (j/k or ↑/↓)"[: cols - 1],
        curses.A_DIM,
    )
    win.noutrefresh()


def draw_help(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()

    lines = [
        "NWS Weather TUI Help",
        "",
        "Views:",
        "  c  Current conditions (station observation) + optional mini-graphs + radar map",
        "  f  Forecast periods (day/night) — scroll with j/k or arrow keys",
        "  h  Hourly (next N hours) — temp+wind sparklines + PoP bar + fixed columns",
        "  a  Alerts (active) — scroll with j/k or arrow keys",
        "",
        "Actions:",
        "  l  Search location (city/state or ZIP)",
        "  r  Refresh now",
        "  u  Toggle units (US / SI)",
        "  t  Toggle 12h/24h clock",
        "  p  Pause/resume auto-refresh",
        "  g  Toggle mini graphs on Current view",
        "  w  Toggle radar map panel",
        "  Mouse left-click radar city marker/label to jump there",
        "  o  Open radar in browser (mrms.nssl.noaa.gov)",
        "  F  Toggle current location favorite",
        "  [ / ]  Cycle favorites",
        "  q  Quit",
        "",
        "Config:",
        f"  Edit: {CONFIG_PATH}",
        "",
        "Offline mode:",
        f"  Last-known data saved to: {STATE_PATH}",
        "",
        "Radar map:",
        "  Uses NOAA/NCEP OpenGeoServer WMS base reflectivity for your NWS 'radarStation' (if available).",
        "  If it says install pillow: `pip install pillow`.",
    ]

    y = 0
    for line in lines:
        for wline in wrap_lines(line, cols - 1):
            if y >= rows:
                break
            safe_addstr(win, y, 0, wline[: cols - 1], curses.A_BOLD if y == 0 else 0)
            y += 1
        if y >= rows:
            break

    win.noutrefresh()
