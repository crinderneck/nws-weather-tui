#!/usr/bin/env python3
"""
NWS Weather TUI — Hourly forecast view.

Rather than charting temperature (which just traces the day/night cycle),
the top of the page calls out what is actually *notable* in the coming
hours: when precipitation starts and stops, thunder risk, gusts, feels-like
divergence, swings that run against the diurnal cycle (fronts), humidity
and cloud transitions. Below that a condition ribbon shows at a glance
when the sky is clear, cloudy or wet, and the table breaks the hours up by
day with sunrise/sunset markers and colour-coded values.
"""

from __future__ import annotations

import curses
import datetime as dt
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from conversions import c_to_f, mm_to_in
from formatting import fmt_num, fmt_time
from geo import clamp
from helpers import get_sunrise_sunset, safe_addstr
from icons import ICON_TINY
from models import HourlyPeriod

if TYPE_CHECKING:
    from app import App

KMH_PER_MPH = 1.609344

# Colour pairs (see curses_init.py).
C_CYAN = 1
C_YELLOW = 2
C_GREEN = 3
C_RED = 4
C_MAGENTA = 5
C_BLUE = 6

# A row in the scrollable table: ("day", date) | ("sun", (label, when)) |
# ("hour", index into the hourly list).
TableRow = Tuple[str, Any]
# One "at a glance" line: (tag, tag colour attr, text).
Insight = Tuple[str, int, str]


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def _is_f(hrs: List[HourlyPeriod]) -> bool:
    unit = next((h.temperature_unit for h in hrs if h.temperature_unit), "F")
    return unit.upper() == "F"


def _deg(c: Optional[float], is_f: bool) -> Optional[float]:
    """Convert an API degC value to the display unit."""
    return c_to_f(c) if is_f else c


def _delta(f_delta: float, is_f: bool) -> float:
    """Scale a threshold expressed in °F to the display unit."""
    return f_delta if is_f else f_delta * 5.0 / 9.0


def _speed(kmh: Optional[float], is_f: bool) -> Optional[float]:
    if kmh is None:
        return None
    return kmh / KMH_PER_MPH if is_f else kmh


def _local(t: Optional[dt.datetime]) -> Optional[dt.datetime]:
    return t.astimezone() if t is not None else None


def _hr(h: HourlyPeriod, app: "App") -> str:
    """Compact hour label: '4pm' / '16:00'."""
    t = _local(h.start)
    if t is None:
        return "?"
    if app.use_24h:
        return t.strftime("%H:%M")
    return t.strftime("%I%p").lstrip("0").lower()


def _span(hrs: List[HourlyPeriod], i: int, j: int, app: "App") -> str:
    """Describe hours i..j inclusive as a time range."""
    if i == 0 and j == len(hrs) - 1:
        return "all period"
    if i == 0:
        return f"now–{_hr(hrs[j], app)}"
    if j == len(hrs) - 1:
        return f"from {_hr(hrs[i], app)}"
    if i == j:
        return f"around {_hr(hrs[i], app)}"
    return f"{_hr(hrs[i], app)}–{_hr(hrs[j], app)}"


def _runs(flags: List[bool]) -> List[Tuple[int, int]]:
    """Contiguous True runs as (start, end) inclusive index pairs."""
    out: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def _argmax(
    hrs: List[HourlyPeriod], key: Callable[[HourlyPeriod], Optional[float]],
    lo: int = 0, hi: Optional[int] = None,
) -> Optional[int]:
    hi = len(hrs) - 1 if hi is None else hi
    best: Optional[int] = None
    for i in range(lo, hi + 1):
        v = key(hrs[i])
        if v is not None and (best is None or v > (key(hrs[best]) or 0)):
            best = i
    return best


# ---------------------------------------------------------------------------
# "At a glance" insights
# ---------------------------------------------------------------------------

def _precip_kind(text: str) -> str:
    t = text.lower()
    if "thunder" in t or "storm" in t:
        return "Storms"
    if "freezing" in t or "sleet" in t or "wintry" in t or "ice" in t:
        return "Wintry mix"
    if "snow" in t or "flurr" in t:
        return "Snow"
    if "drizzle" in t:
        return "Drizzle"
    if "rain" in t or "shower" in t:
        return "Rain"
    return "Precip"


def _precip_insight(hrs: List[HourlyPeriod], app: "App") -> Insight:
    pops = [h.pop or 0.0 for h in hrs]
    runs = _runs([p >= 30 for p in pops])
    peak = max(pops) if pops else 0.0

    total_mm = sum(h.precip_mm for h in hrs if h.precip_mm is not None)
    snow_mm = sum(h.snow_mm for h in hrs if h.snow_mm is not None)
    amount = ""
    if total_mm >= 0.25:
        if app.units == "us":
            amount = f" · {fmt_num(mm_to_in(total_mm), 2)} in"
            if snow_mm >= 2.5:
                amount += f" ({fmt_num(mm_to_in(snow_mm), 1)} in snow)"
        else:
            amount = f" · {fmt_num(total_mm, 1)} mm"
            if snow_mm >= 2.5:
                amount += f" ({fmt_num(snow_mm / 10.0, 1)} cm snow)"

    if not runs:
        if peak >= 15:
            return ("Precip", curses.color_pair(C_CYAN),
                    f"Mostly dry — only a slight chance (max {peak:.0f}%)")
        return ("Precip", curses.color_pair(C_GREEN),
                f"Dry for the next {len(hrs)}h")

    i, j = runs[0]
    pk = _argmax(hrs, lambda h: h.pop, i, j) or i
    kind = _precip_kind(hrs[pk].short_forecast)
    p = pops[pk]
    odds = "likely" if p >= 60 else "possible"
    if i == 0 and j < len(hrs) - 1:
        text = f"{kind} {odds} now, easing after {_hr(hrs[j], app)}"
    else:
        text = f"{kind} {odds} {_span(hrs, i, j, app)}"
    text += f" · peak {p:.0f}% at {_hr(hrs[pk], app)}{amount}"
    if len(runs) > 1:
        text += f" · again {_span(hrs, *runs[1], app)}"
    attr = curses.color_pair(C_BLUE) | (curses.A_BOLD if p >= 60 else 0)
    return ("Precip", attr, text)


def _thunder_insight(hrs: List[HourlyPeriod], app: "App") -> Optional[Insight]:
    runs = _runs([(h.thunder_pct or 0) >= 15 for h in hrs])
    if not runs:
        return None
    i, j = runs[0]
    pk = _argmax(hrs, lambda h: h.thunder_pct, i, j) or i
    p = hrs[pk].thunder_pct or 0
    return ("Thunder", curses.color_pair(C_MAGENTA) | curses.A_BOLD,
            f"Lightning risk {_span(hrs, i, j, app)} · peak {p:.0f}%")


def _wind_insight(hrs: List[HourlyPeriod], app: "App", is_f: bool) -> Optional[Insight]:
    unit = "mph" if is_f else "km/h"
    pk = _argmax(hrs, lambda h: h.gust_kmh)
    if pk is not None:
        gust = _speed(hrs[pk].gust_kmh, is_f) or 0.0
        gusty = _speed(40.0, is_f) or 0.0  # ~25 mph
        if gust >= gusty:
            windy = [(_speed(h.gust_kmh, is_f) or 0) >= gusty for h in hrs]
            i, j = next(r for r in _runs(windy) if r[0] <= pk <= r[1])
            strong = gust >= (_speed(64.0, is_f) or 0)  # ~40 mph
            attr = curses.color_pair(C_RED if strong else C_YELLOW) | curses.A_BOLD
            return ("Wind", attr,
                    (f"Gusty {_span(hrs, i, j, app)} · up to {gust:.0f} {unit}"
                     f" at {_hr(hrs[pk], app)}"))
        return ("Wind", curses.color_pair(C_GREEN),
                f"Light — gusts stay under {max(gust, 1):.0f} {unit}")
    spk = _argmax(hrs, lambda h: h.wind_speed_num)
    if spk is None:
        return None
    return ("Wind", curses.A_DIM,
            f"Strongest {hrs[spk].wind_speed} at {_hr(hrs[spk], app)}")


def _feels_insight(hrs: List[HourlyPeriod], app: "App", is_f: bool) -> Optional[Insight]:
    best: Optional[int] = None
    best_gap = 0.0
    for i, h in enumerate(hrs):
        feels = _deg(h.apparent_c, is_f)
        if feels is None or h.temperature is None:
            continue
        gap = feels - h.temperature
        if abs(gap) > abs(best_gap):
            best, best_gap = i, gap
    if best is None or abs(best_gap) < _delta(5, is_f):
        return None
    side = [
        h.apparent_c is not None and h.temperature is not None
        and ((_deg(h.apparent_c, is_f) or 0) - h.temperature) * best_gap > 0
        and abs((_deg(h.apparent_c, is_f) or 0) - h.temperature) >= _delta(3, is_f)
        for h in hrs
    ]
    i, j = next(r for r in _runs(side) if r[0] <= best <= r[1])
    colder = best_gap < 0
    why = "wind chill" if colder else "heat index"
    attr = curses.color_pair(C_CYAN if colder else C_RED)
    return ("Feels", attr,
            (f"Up to {abs(best_gap):.0f}° {'colder' if colder else 'warmer'} "
             f"than the air {_span(hrs, i, j, app)} ({why})"))


def _swing_insight(hrs: List[HourlyPeriod], app: "App", is_f: bool) -> Optional[Insight]:
    """Temperature moves that run against the day/night cycle — the only
    temperature changes worth calling out (fronts, outflow, clearing)."""
    window = 3
    thresh = _delta(7, is_f)
    best: Optional[Tuple[float, int, int]] = None
    for i in range(len(hrs) - window):
        a, b = hrs[i], hrs[i + window]
        t0 = _local(a.start)
        if a.temperature is None or b.temperature is None or t0 is None:
            continue
        change = b.temperature - a.temperature
        daytime = 8 <= t0.hour < 14
        overnight = t0.hour >= 20 or t0.hour < 5
        unusual = (change < 0 and daytime) or (change > 0 and overnight)
        if unusual and abs(change) >= thresh and (best is None or abs(change) > abs(best[0])):
            best = (change, i, i + window)
    if best is None:
        return None
    change, i, j = best
    a, b = hrs[i].temperature, hrs[j].temperature
    if change < 0:
        return ("Front", curses.color_pair(C_CYAN) | curses.A_BOLD,
                (f"Temp falls {a:.0f}°→{b:.0f}° {_span(hrs, i, j, app)}"
                 " — midday drop, likely a front or storms"))
    return ("Front", curses.color_pair(C_YELLOW) | curses.A_BOLD,
            (f"Temp rises {a:.0f}°→{b:.0f}° {_span(hrs, i, j, app)}"
             " — overnight warm-up"))


def _air_insight(hrs: List[HourlyPeriod], app: "App", is_f: bool) -> Optional[Insight]:
    dews = [_deg(h.dewpoint_c, is_f) for h in hrs]
    if all(d is None for d in dews):
        return None
    pk = max((i for i, d in enumerate(dews) if d is not None), key=lambda i: dews[i] or 0)
    top = dews[pk] or 0.0
    u = "°"
    for word, thresh_f, color in (("Oppressive", 70, C_RED), ("Muggy", 65, C_YELLOW)):
        thresh = thresh_f if is_f else (thresh_f - 32) * 5 / 9
        if top >= thresh:
            i, j = next(r for r in _runs([(d or -99) >= thresh for d in dews])
                        if r[0] <= pk <= r[1])
            return ("Air", curses.color_pair(color),
                    f"{word} {_span(hrs, i, j, app)} · dew point up to {top:.0f}{u}")
    rhs = [h.humidity_pct for h in hrs if h.humidity_pct is not None]
    lo = min(rhs) if rhs else None
    if lo is not None and lo <= 20:
        return ("Air", curses.color_pair(C_YELLOW),
                (f"Very dry — humidity down to {lo:.0f}% "
                 f"(dew point {min(d for d in dews if d is not None):.0f}{u})"))
    comfy_hi = 60 if is_f else 15.5
    if top < comfy_hi:
        return ("Air", curses.color_pair(C_GREEN),
                f"Comfortable — dew point {top:.0f}{u} or lower")
    return ("Air", curses.A_DIM, f"Slightly humid — dew point up to {top:.0f}{u}")


def _sky_insight(hrs: List[HourlyPeriod], app: "App") -> Optional[Insight]:
    sky = [h.sky_pct for h in hrs]
    if all(s is None for s in sky):
        return None

    def state(s: Optional[float]) -> Optional[str]:
        if s is None:
            return None
        return "clear" if s < 35 else ("cloudy" if s > 70 else None)

    cur = next((state(s) for s in sky[:3] if state(s)), None)
    for i, s in enumerate(sky):
        st = state(s)
        if st and cur and st != cur:
            verb = "Clearing" if st == "clear" else "Clouding over"
            return ("Sky", curses.color_pair(C_CYAN),
                    f"{verb} around {_hr(hrs[i], app)} ({s:.0f}% cover)")
        cur = cur or st
    avg = sum(s for s in sky if s is not None) / max(1, sum(s is not None for s in sky))
    desc = (
        "Mostly clear" if avg < 30 else "Mostly cloudy" if avg > 70
        else "Mixed sun and cloud"
    )
    return ("Sky", curses.A_DIM, f"{desc} throughout (avg {avg:.0f}% cover)")


def _insights(hrs: List[HourlyPeriod], app: "App") -> List[Insight]:
    is_f = _is_f(hrs)
    out: List[Optional[Insight]] = [
        _precip_insight(hrs, app),
        _thunder_insight(hrs, app),
        _swing_insight(hrs, app, is_f),
        _wind_insight(hrs, app, is_f),
        _feels_insight(hrs, app, is_f),
        _air_insight(hrs, app, is_f),
        _sky_insight(hrs, app),
    ]
    return [i for i in out if i is not None]


# ---------------------------------------------------------------------------
# Condition ribbon
# ---------------------------------------------------------------------------

def _ribbon_cell(h: HourlyPeriod) -> Tuple[str, int]:
    pop = h.pop or 0
    text = h.short_forecast.lower()
    if pop >= 30 or (h.precip_mm or 0) >= 0.25:
        if (h.thunder_pct or 0) >= 15 or "thunder" in text:
            color = C_MAGENTA
        elif "snow" in text or "flurr" in text:
            color = 14
        else:
            color = C_BLUE
        ch = "█" if pop >= 60 else "▓"
        return ch, curses.color_pair(color) | curses.A_BOLD
    if pop >= 15:
        return "▒", curses.color_pair(C_BLUE)
    sky = h.sky_pct
    if sky is None:
        sky = 80.0 if "cloud" in text and "partly" not in text else 40.0
        if "sunny" in text or "clear" in text:
            sky = 10.0 if "mostly" not in text else 25.0
    night = h.is_daytime is False
    if sky < 35:
        return ("·", curses.A_DIM) if night else ("▀", curses.color_pair(C_YELLOW))
    if sky <= 70:
        return "░", curses.A_DIM if night else curses.A_NORMAL
    return "▒", curses.A_DIM


def _draw_ribbon(win, y: int, cols: int, hrs: List[HourlyPeriod], app: "App") -> int:
    """Draw the hour ticks + condition ribbon + legend. Returns rows used."""
    avail = cols - 2
    cell = clamp(avail // max(1, len(hrs)), 1, 3)
    n = min(len(hrs), avail // cell)
    if n < 6:
        return 0
    x0 = max(0, (cols - n * cell) // 2)

    # Tick labels, only where they don't collide with the previous one.
    next_free = 0
    for i in range(n):
        t = _local(hrs[i].start)
        if t is None:
            continue
        if i == 0 or t.hour % 3 == 0:
            label = "now" if i == 0 else _hr(hrs[i], app)
            x = x0 + i * cell
            if x >= next_free and x + len(label) <= cols - 1:
                attr = curses.A_BOLD if i == 0 or t.hour == 0 else curses.A_DIM
                safe_addstr(win, y, x, label, attr)
                next_free = x + len(label) + 1

    for i in range(n):
        ch, attr = _ribbon_cell(hrs[i])
        safe_addstr(win, y + 1, x0 + i * cell, ch * cell, attr)

    legend: List[Tuple[str, int]] = [
        ("▀ sun  ", curses.color_pair(C_YELLOW)),
        ("░ partly  ", curses.A_NORMAL),
        ("▒ cloudy  ", curses.A_DIM),
        ("· clear night  ", curses.A_DIM),
        ("▓█ precip  ", curses.color_pair(C_BLUE) | curses.A_BOLD),
        ("█ storms", curses.color_pair(C_MAGENTA) | curses.A_BOLD),
    ]
    width = sum(len(s) for s, _ in legend)
    if width <= cols - 1:
        x = max(0, (cols - width) // 2)
        for s, a in legend:
            safe_addstr(win, y + 2, x, s, a)
            x += len(s)
        return 3
    return 2


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

def _temp_attr(v: Optional[float], is_f: bool) -> int:
    if v is None:
        return curses.A_DIM
    f = v if is_f else (c_to_f(v) or 0)
    if f < 32:
        return curses.color_pair(C_MAGENTA)
    if f < 50:
        return curses.color_pair(C_CYAN)
    if f < 70:
        return curses.color_pair(C_GREEN)
    if f < 85:
        return curses.color_pair(C_YELLOW)
    return curses.color_pair(C_RED) | curses.A_BOLD


def _dew_attr(v: Optional[float], is_f: bool) -> int:
    if v is None:
        return curses.A_DIM
    f = v if is_f else (c_to_f(v) or 0)
    if f >= 70:
        return curses.color_pair(C_RED)
    if f >= 65:
        return curses.color_pair(C_YELLOW)
    if f >= 55:
        return curses.A_NORMAL
    return curses.A_DIM


def _pop_attr(p: Optional[float]) -> int:
    if not p:
        return curses.A_DIM
    if p >= 60:
        return curses.color_pair(C_BLUE) | curses.A_BOLD
    if p >= 30:
        return curses.color_pair(C_BLUE)
    return curses.A_DIM


def _pop_bar(p: Optional[float]) -> str:
    if not p:
        return " "
    return " ▁▂▃▄▅▆▇█"[clamp(round(p / 12.5), 1, 8)]


def _build_rows(hrs: List[HourlyPeriod], app: "App") -> List[TableRow]:
    """Interleave day headers and sunrise/sunset markers with the hours."""
    events: List[Tuple[dt.datetime, str]] = []
    first = _local(hrs[0].start)
    last = _local(hrs[-1].start)
    if first is not None and last is not None:
        day = first.date() - dt.timedelta(days=1)
        while day <= last.date() + dt.timedelta(days=1):
            rise, sset = get_sunrise_sunset(app.lat, app.lon, day)
            for when, label in ((rise, "sunrise"), (sset, "sunset")):
                in_range = when is not None and first < when <= last + dt.timedelta(hours=1)
                # Adjacent days' lookups can yield the same event; keep one.
                if in_range and all(abs((when - e).total_seconds()) > 3600 for e, _ in events):
                    events.append((when, label))
            day += dt.timedelta(days=1)
    events.sort()

    rows: List[TableRow] = []
    prev_date: Optional[dt.date] = None
    for idx, h in enumerate(hrs):
        t = _local(h.start)
        if t is not None and t.date() != prev_date:
            rows.append(("day", t.date()))
            prev_date = t.date()
        rows.append(("hour", idx))
        end = t + dt.timedelta(hours=1) if t is not None else None
        while events and end is not None and events[0][0] < end:
            when, label = events.pop(0)
            rows.append(("sun", (label, when)))
    return rows


def _day_label(d: dt.date) -> str:
    today = dt.date.today()
    if d == today:
        name = "Today"
    elif d == today + dt.timedelta(days=1):
        name = "Tomorrow"
    else:
        name = d.strftime("%A")
    return f"{name} · {d.strftime('%b')} {d.day}"


def draw_hourly(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    hrs = app.hourly_periods
    if not hrs:
        safe_addstr(
            win, 0, 0,
            "No hourly forecast available. Press r to refresh.",
            curses.A_DIM,
        )
        win.noutrefresh()
        return

    is_f = _is_f(hrs)
    first, last = _local(hrs[0].start), _local(hrs[-1].start)
    span = ""
    if first is not None and last is not None:
        span = f"  {first.strftime('%a')} {_hr(hrs[0], app)} → " \
               f"{last.strftime('%a')} {_hr(hrs[-1], app)}"
    safe_addstr(win, 0, 0, f"Hourly · next {len(hrs)}h"[: cols - 1], curses.A_BOLD)
    safe_addstr(win, 0, len(f"Hourly · next {len(hrs)}h"), span[: max(0, cols - 30)],
                curses.A_DIM)

    # ---- At a glance ------------------------------------------------------
    y = 2
    insights = _insights(hrs, app)
    # Keep enough room for a useful table on short terminals.
    max_insights = clamp(rows - 14, 2, len(insights)) if insights else 0
    tag_w = max((len(t) for t, _, _ in insights), default=0) + 2
    for tag, attr, text in insights[:max_insights]:
        safe_addstr(win, y, 1, tag.rjust(tag_w - 2), attr)
        safe_addstr(win, y, tag_w + 1, text[: max(0, cols - tag_w - 2)])
        y += 1
    y += 1

    if rows - y >= 12:
        used = _draw_ribbon(win, y, cols, hrs, app)
        y += used + (1 if used else 0)

    # ---- Table -----------------------------------------------------------
    # (key, header, width, min terminal cols to show it)
    columns = [
        ("time", "Time", 7, 0),
        ("icon", "", 3, 0),
        ("temp", "Temp", 6, 0),
        ("feels", "Feels", 6, 70),
        ("dew", "Dew", 5, 95),
        ("sky", "Sky", 5, 105),
        ("wind", "Wind", 13, 0),
        ("gust", "Gust", 5, 80),
        ("pop", "Precip", 7, 0),
    ]
    columns = [c for c in columns if cols >= c[3]]
    x = 1
    xs: Dict[str, int] = {}
    for key, _, w, _ in columns:
        xs[key] = x
        x += w + 1
    x_fc = x
    w_fc = max(0, cols - x_fc - 1)

    for key, head, w, _ in columns:
        safe_addstr(win, y, xs[key], head.rjust(w) if key in ("temp", "feels", "dew", "sky",
                                                            "gust", "pop") else head,
                    curses.A_BOLD)
    if w_fc >= 8:
        safe_addstr(win, y, x_fc, "Forecast", curses.A_BOLD)
    y += 1

    table = _build_rows(hrs, app)
    view_rows = max(1, rows - y - 1)
    app.hr_scroll = clamp(app.hr_scroll, 0, max(0, len(table) - view_rows))
    for kind, val in table[app.hr_scroll: app.hr_scroll + view_rows]:
        if y >= rows - 1:
            break
        if kind == "day":
            label = f" {_day_label(val)} "
            safe_addstr(win, y, 0, "──" + label + "─" * max(0, cols - 4 - len(label)),
                        curses.color_pair(C_CYAN) | curses.A_BOLD)
        elif kind == "sun":
            label, when = val
            glyph = "↑" if label == "sunrise" else "↓"
            text = f"☀{glyph} {label} {fmt_time(when, app.use_24h)}"
            safe_addstr(win, y, xs["time"], "┄" * 7, curses.A_DIM)
            safe_addstr(win, y, xs["time"] + 9, text[: max(0, cols - 11)],
                        curses.color_pair(C_YELLOW))
        else:
            _draw_hour_row(win, y, val, hrs, app, xs, x_fc, w_fc, is_f)
        y += 1

    shown_to = min(len(table), app.hr_scroll + view_rows)
    hint = "j/k ↑↓ scroll"
    if len(table) > view_rows:
        hint = f"rows {app.hr_scroll + 1}–{shown_to} of {len(table)} · " + hint
    safe_addstr(win, rows - 1, 0, hint[: cols - 1], curses.A_DIM)
    win.noutrefresh()


def _draw_hour_row(
    win, y: int, idx: int, hrs: List[HourlyPeriod], app: "App",
    xs: Dict[str, int], x_fc: int, w_fc: int, is_f: bool,
) -> None:
    h = hrs[idx]
    now = idx == 0
    tstr = "now" if now else fmt_time(h.start, app.use_24h)
    safe_addstr(win, y, xs["time"], tstr[:7].rjust(7), curses.A_BOLD if now else curses.A_NORMAL)

    icon = ICON_TINY.get(h.icon_key, "?") or "?"
    safe_addstr(win, y, xs["icon"] + 1, icon[:2])

    temp = "—" if h.temperature is None else f"{h.temperature:.0f}°"
    safe_addstr(win, y, xs["temp"], temp.rjust(6), _temp_attr(h.temperature, is_f))

    if "feels" in xs:
        feels = _deg(h.apparent_c, is_f)
        if feels is None:
            safe_addstr(win, y, xs["feels"], "—".rjust(6), curses.A_DIM)
        elif h.temperature is not None and abs(feels - h.temperature) < _delta(3, is_f):
            safe_addstr(win, y, xs["feels"], "same".rjust(6), curses.A_DIM)
        else:
            safe_addstr(win, y, xs["feels"], f"{feels:.0f}°".rjust(6),
                        _temp_attr(feels, is_f))

    if "dew" in xs:
        dew = _deg(h.dewpoint_c, is_f)
        dstr = "—" if dew is None else f"{dew:.0f}°"
        safe_addstr(win, y, xs["dew"], dstr.rjust(5), _dew_attr(dew, is_f))

    if "sky" in xs:
        sstr = "—" if h.sky_pct is None else f"{h.sky_pct:.0f}%"
        safe_addstr(win, y, xs["sky"], sstr.rjust(5), curses.A_DIM)

    wind = f"{h.wind_dir} {h.wind_speed}".strip()
    safe_addstr(win, y, xs["wind"], wind[:13])

    if "gust" in xs:
        gust = _speed(h.gust_kmh, is_f)
        if gust is None:
            safe_addstr(win, y, xs["gust"], "—".rjust(5), curses.A_DIM)
        else:
            gusty = gust >= (_speed(40.0, is_f) or 0)
            attr = (curses.color_pair(C_YELLOW) | curses.A_BOLD) if gusty else curses.A_DIM
            safe_addstr(win, y, xs["gust"], f"{gust:.0f}".rjust(5), attr)

    pop_attr = _pop_attr(h.pop)
    pstr = "—" if h.pop is None else f"{h.pop:.0f}%"
    safe_addstr(win, y, xs["pop"], pstr.rjust(5), pop_attr)
    safe_addstr(win, y, xs["pop"] + 6, _pop_bar(h.pop), pop_attr)

    if w_fc >= 8:
        fc = h.short_forecast or "—"
        if (h.thunder_pct or 0) >= 15 and "thunder" not in fc.lower():
            fc += f" (thunder {h.thunder_pct:.0f}%)"
        safe_addstr(win, y, x_fc, fc[:w_fc])
