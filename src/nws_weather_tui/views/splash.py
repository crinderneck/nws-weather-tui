#!/usr/bin/env python3
"""
NWS Weather TUI — Startup splash: the sky overhead right now, and the first
refresh ticking off underneath it.

The sky needs no network, so it's up at once: the sun and moon where they
really are (east on the left, west on the right, the horizon at the bottom),
stars once it's dark. Each request fills in its row as it lands; the splash
gives way to the normal views shortly after the refresh finishes, or on any
key.
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

import curses

from nws_weather_tui import __version__
from nws_weather_tui.conversions import c_to_f, mps_to_mph
from nws_weather_tui.formatting import fmt_num, fmt_time
from nws_weather_tui.geo import clamp
from nws_weather_tui.helpers import fit_width, get_sunrise_sunset, safe_addstr, text_width
from nws_weather_tui.moon import moon_age, moon_illumination_at, moon_phase_name
from nws_weather_tui.views.current import _deg_to_cardinal
from nws_weather_tui.views.moon import _draw_moon, _moon_pixels, moon_width
from nws_weather_tui.views.style import C_CYAN, C_GREEN, C_RED, C_YELLOW, temp_attr

try:
    from astral import LocationInfo
    from astral import moon as astral_moon
    from astral import sun as astral_sun
except ImportError:
    LocationInfo = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from nws_weather_tui.app import App

# Azimuths shown edge to edge: NE on the left through S to NW on the right,
# so rising and setting bodies stay on screen most of the year.
AZ_LEFT, AZ_RIGHT = 45.0, 315.0
# Lines below the sky: horizon, info line, gap, checklist, gap, footer.
STEPS: List[Tuple[str, str]] = [
    ("location", "location"),
    ("current", "conditions"),
    ("forecast_periods", "forecast"),
    ("hourly_periods", "hourly"),
    ("alerts", "alerts"),
    ("discussion", "discussion"),
    ("air", "air quality"),
]
BELOW_SKY = 1 + 1 + 1 + len(STEPS) + 1 + 1
LABEL_W = 12
VALUE_W = 40


def _position(body: Any, lat: float, lon: float, now: dt.datetime) -> Optional[Tuple[float, float]]:
    """(azimuth, elevation) in degrees, or None without astral."""
    if LocationInfo is None:
        return None
    try:
        obs = LocationInfo(latitude=lat, longitude=lon).observer
        # astral's moon ignores the zone of a local time; give it UTC.
        utc = dt.datetime.fromtimestamp(now.timestamp(), dt.timezone.utc)
        return float(body.azimuth(obs, utc)), float(body.elevation(obs, utc))
    except Exception:
        return None


def _sky_xy(az: float, el: float, sky_h: int, cols: int) -> Tuple[int, int]:
    x = round((az - AZ_LEFT) / (AZ_RIGHT - AZ_LEFT) * (cols - 1))
    y = round((sky_h - 1) * (1 - min(el, 90.0) / 90.0))
    return clamp(x, 0, cols - 1), clamp(y, 0, sky_h - 1)


def _draw_stars(win, sky_h: int, cols: int, seed: str, count: int) -> None:
    # Seeded by place and night, so the stars hold still between frames.
    rng = random.Random(seed)
    for _ in range(count):
        y, x = rng.randrange(sky_h), rng.randrange(cols - 1)
        ch = rng.choice("··········∙∙∙*+")
        bright = ch in "*+"
        safe_addstr(win, y, x, ch, curses.A_BOLD if bright else curses.A_DIM)


def _draw_sun(win, cy: int, cx: int, cell_rows: int, sky_h: int) -> None:
    w = moon_width(cell_rows)
    grid = _moon_pixels(15.0, cell_rows * 2, w)  # a full disc
    y0 = clamp(cy - cell_rows // 2, 0, max(0, sky_h - cell_rows))
    x0 = cx - w // 2
    attr = curses.color_pair(C_YELLOW) | curses.A_BOLD
    for row in range(cell_rows):
        for col in range(w):
            t, b = grid[2 * row][col], grid[2 * row + 1][col]
            if t or b:
                ch = "█" if t and b else ("▀" if t else "▄")
                safe_addstr(win, y0 + row, x0 + col, ch, attr)


def _sky(app: "App", win, sky_h: int, cols: int, now: dt.datetime) -> None:
    sun_pos = _position(astral_sun, app.lat, app.lon, now) if LocationInfo else None
    moon_pos = _position(astral_moon, app.lat, app.lon, now) if LocationInfo else None
    sun_el = sun_pos[1] if sun_pos else (0.0 if 7 <= now.hour < 19 else -30.0)
    if sun_el < -6:  # past civil twilight
        density = 18 if sun_el < -12 else 45
        seed = f"{now.date()}{app.lat:.2f}{app.lon:.2f}"
        _draw_stars(win, sky_h, cols, seed, sky_h * cols // density)
    body_rows = 4 if sky_h >= 10 else 3
    if moon_pos and moon_pos[1] > 0:
        mx, my = _sky_xy(moon_pos[0], moon_pos[1], sky_h, cols)
        w = moon_width(body_rows)
        _draw_moon(
            win, clamp(my - body_rows // 2, 0, max(0, sky_h - body_rows)),
            clamp(mx - w // 2, 0, max(0, cols - w - 1)), moon_age(now), body_rows,
        )
    if sun_pos and sun_pos[1] > -1:
        sx, sy = _sky_xy(sun_pos[0], max(sun_pos[1], 0.0), sky_h, cols)
        w = moon_width(body_rows - 1)
        _draw_sun(win, sy, clamp(sx, w // 2, cols - w), body_rows - 1, sky_h)


def _next_sun_event(app: "App", now: dt.datetime) -> str:
    rise, set_ = get_sunrise_sunset(app.lat, app.lon, now.date())
    if rise and now < rise:
        return f"sunrise {fmt_time(rise, app.use_24h)}"
    if set_ and now < set_:
        return f"sunset {fmt_time(set_, app.use_24h)}"
    rise, _ = get_sunrise_sunset(app.lat, app.lon, now.date() + dt.timedelta(days=1))
    return f"sunrise {fmt_time(rise, app.use_24h)}" if rise else ""


def _summary(app: "App", key: str, value: Any) -> Tuple[str, int]:
    """What a finished step found, and how to colour it."""
    us = app.units == "us"
    if key == "location":
        office, station = value
        return " · ".join(s for s in (office and f"{office} office", station) if s), 0
    if key == "current" and value is not None:
        t = c_to_f(value.temperature_c) if us else value.temperature_c
        desc = value.text_description.replace("Current Conditions: ", "").strip()
        parts = [f"{fmt_num(t, 0)}°{'F' if us else 'C'}" if t is not None else "",
                 "" if desc in ("", "N/A") else desc]
        if value.wind_mps is not None:
            if value.wind_mps < 0.5:
                parts.append("calm")
            else:
                speed = (f"{fmt_num(mps_to_mph(value.wind_mps), 0)} mph" if us
                         else f"{fmt_num(value.wind_mps, 0)} m/s")
                card = (_deg_to_cardinal(value.wind_dir_deg)
                        if value.wind_dir_deg is not None else "")
                parts.append(f"wind {card} {speed}".replace("  ", " "))
        return ", ".join(p for p in parts if p), temp_attr(t, us)
    if key == "forecast_periods" and value:
        return f"{value[0].name}: {value[0].short_forecast}", 0
    if key == "hourly_periods":
        return f"{len(value)} hours", 0
    if key == "alerts":
        alerts = value[0]
        if not alerts:
            return "none here", curses.color_pair(C_GREEN)
        more = f" +{len(alerts) - 1}" if len(alerts) > 1 else ""
        return f"{alerts[0].event}{more}", curses.color_pair(C_RED) | curses.A_BOLD
    if key == "discussion":
        return "discussion + outlook", 0
    if key == "air":
        aq, uv = value
        parts = []
        if aq is not None and aq.aqi is not None:
            parts.append(f"AQI {aq.aqi} {aq.category}".strip())
        if uv is not None and uv.daily_max is not None:
            parts.append(f"UV max {fmt_num(uv.daily_max, 0)}")
        return " · ".join(parts) or "not reported", 0
    return "", 0


def _checklist(app: "App", win, y: int, cols: int) -> None:
    progress = app.load_progress
    frame = app._spinner_frames[app._spinner_idx % len(app._spinner_frames)]
    x = max(1, (cols - (4 + LABEL_W + VALUE_W)) // 2)
    for i, (key, label) in enumerate(STEPS):
        state, value = progress.get(key, (None, None))
        if state == "ok":
            mark, mark_attr = "✓", curses.color_pair(C_GREEN) | curses.A_BOLD
            text, attr = _summary(app, key, value)
        elif state == "fail":
            mark, mark_attr = "✗", curses.color_pair(C_RED) | curses.A_BOLD
            text, attr = "unavailable", curses.A_DIM
        elif app._bg_weather_running:
            mark, mark_attr, text, attr = frame, curses.color_pair(C_YELLOW), "", 0
        else:
            mark, mark_attr, text, attr = "–", curses.A_DIM, "", 0
        safe_addstr(win, y + i, x, mark, mark_attr)
        safe_addstr(win, y + i, x + 2, fit_width(label, LABEL_W), curses.A_DIM)
        width = max(1, min(VALUE_W, cols - (x + 2 + LABEL_W) - 1))
        safe_addstr(win, y + i, x + 2 + LABEL_W, fit_width(text, width).rstrip(), attr)


def draw_splash(app: "App", rows: int, cols: int) -> None:
    win = app.stdscr
    now = dt.datetime.now().astimezone()
    sky_h = clamp(rows - BELOW_SKY, 4, 16)
    top = max(0, (rows - sky_h - BELOW_SKY) // 2)
    try:
        sky = win.derwin(sky_h, cols, top, 0)
    except curses.error:
        sky = None
    if sky is not None:
        _sky(app, sky, sky_h, cols, now)

    y = top + sky_h
    safe_addstr(win, y, 0, "─" * (cols - 1), curses.color_pair(C_GREEN) | curses.A_DIM)

    age = moon_age(now)
    moon = f"{moon_phase_name(age).lower()} {round(moon_illumination_at(now) * 100)}%"
    info = " · ".join(s for s in (
        app.location_name, fmt_time(now, app.use_24h), _next_sun_event(app, now), moon,
    ) if s)
    info = fit_width(info, cols - 2).rstrip()
    safe_addstr(win, y + 1, max(1, (cols - text_width(info)) // 2), info,
                curses.color_pair(C_CYAN) | curses.A_BOLD)

    _checklist(app, win, y + 3, cols)

    footer = f"NWS Weather TUI v{__version__} · any key to skip"
    safe_addstr(win, y + 4 + len(STEPS), max(1, (cols - len(footer)) // 2),
                footer[: cols - 2], curses.A_DIM)
