#!/usr/bin/env python3
"""
NWS Weather TUI — Forecast view (horizontal day cards).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

import curses

from formatting import fmt_time, parse_iso
from geo import clamp
from helpers import get_sunrise_sunset, safe_addstr, wrap_lines
from icons import ICON_BIG
from models import ForecastPeriod

if TYPE_CHECKING:
    from app import App


@dataclass
class DayCard:
    """Paired day/night forecast for a single calendar day."""
    label: str              # e.g. "Fri", "Sat"
    day: Optional[ForecastPeriod]
    night: Optional[ForecastPeriod]

    @property
    def high(self) -> Optional[float]:
        return self.day.temperature if self.day else None

    @property
    def low(self) -> Optional[float]:
        return self.night.temperature if self.night else None

    @property
    def icon_key(self) -> str:
        if self.day:
            return self.day.icon_key
        if self.night:
            return self.night.icon_key
        return "unknown"

    @property
    def short_forecast(self) -> str:
        if self.day:
            return self.day.short_forecast
        if self.night:
            return self.night.short_forecast
        return ""

    @property
    def temp_unit(self) -> str:
        if self.day:
            return self.day.temperature_unit
        if self.night:
            return self.night.temperature_unit
        return "F"

    @property
    def start_dt(self) -> Optional[dt.datetime]:
        """Earliest start datetime for sunrise/sunset lookup."""
        for p in (self.day, self.night):
            if p and p.start:
                if isinstance(p.start, dt.datetime):
                    return p.start
                if isinstance(p.start, str):
                    s = parse_iso(p.start)
                    if s:
                        return s
        return None


_SHORT_DAY = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
    "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
    "Today": "Today", "This": "Today", "Tonight": "Nite",
}


def _build_day_cards(periods: List[ForecastPeriod]) -> List[DayCard]:
    """Group NWS day/night period pairs into DayCards."""
    cards: List[DayCard] = []
    i = 0
    while i < len(periods):
        p = periods[i]
        # Determine short label from period name
        base_name = p.name.split(" Night")[0].split(" ")[0]  # "Monday Night" -> "Monday"
        label = _SHORT_DAY.get(base_name, base_name[:3])

        if p.is_daytime:
            day_p = p
            night_p = None
            # Check if next period is the matching night
            if i + 1 < len(periods) and not periods[i + 1].is_daytime:
                night_p = periods[i + 1]
                i += 2
            else:
                i += 1
            cards.append(DayCard(label=label, day=day_p, night=night_p))
        else:
            # Night-only (e.g. first period is "Tonight")
            cards.append(DayCard(label=label, day=None, night=p))
            i += 1
    return cards


CARD_MIN_W = 15   # narrowest card that still fits the big icon
CARD_MAX_W = 60
GAP = 1           # separator column between cards
ICON_ROWS = 5
TEXT_PAD = 3      # blank columns between the description text and the separators


def _card_attr_temp(v: Optional[float], unit: str) -> int:
    """Colour a temperature by how warm it is (same scale as Hourly)."""
    from views_hourly import _temp_attr
    return _temp_attr(v, unit.upper() != "C")


def _card_lines(card: DayCard, w: int, app: "App") -> List[Tuple[str, int, bool]]:
    """(text, attr, centered) lines for one card, top to bottom."""
    # Fixed-height blocks so every card's rows line up across the screen.
    out: List[Tuple[str, int, bool]] = []
    icon_art = ICON_BIG.get(card.icon_key, ICON_BIG.get("unknown", ""))
    icon = [line.rstrip()[:w] for line in (icon_art.strip("\n").split("\n") if icon_art else [])]
    icon += [""] * (ICON_ROWS - len(icon))
    out += [(line, curses.color_pair(2), True) for line in icon[:ICON_ROWS]]
    short = list(wrap_lines(card.short_forecast, w))[:2]
    short += [""] * (2 - len(short))
    out += [(line, curses.A_BOLD, True) for line in short]

    pops = [p.pop for p in (card.day, card.night) if p is not None and p.pop is not None]
    pop = max(pops) if pops else None
    if pop is not None and pop >= 10:
        attr = curses.color_pair(6) | (curses.A_BOLD if pop >= 60 else 0)
        out.append((f"Precip {pop:.0f}%", attr if pop >= 30 else curses.A_DIM, True))
    else:
        out.append(("Dry", curses.A_DIM, True))
    wind_p = card.day or card.night
    wind = ""
    if wind_p and wind_p.wind_speed and wind_p.wind_speed != "—":
        wind = f"{wind_p.wind_dir} {wind_p.wind_speed}"[:w]
    out.append((wind, curses.A_DIM, True))

    sun = ""
    sdt = card.start_dt
    if sdt:
        rise, sset = get_sunrise_sunset(app.lat, app.lon, sdt.date())
        sun = f"\u2191{fmt_time(rise, app.use_24h)}  \u2193{fmt_time(sset, app.use_24h)}"
    out.append((sun if len(sun) <= w else "", curses.color_pair(2) | curses.A_DIM, True))

    # Detailed day/night narratives fill whatever height is left.
    for label, period in (("Day", card.day), ("Night", card.night)):
        if period is None or not period.detailed_forecast or period.detailed_forecast == "—":
            continue
        out.append(("", 0, False))
        out.append((label, curses.color_pair(1) | curses.A_BOLD, False))
        for wl in wrap_lines(period.detailed_forecast, max(1, w - 2 * TEXT_PAD)):
            out.append((wl, 0, False))
    return out


def _card_label(card: DayCard, w: int) -> str:
    sdt = card.start_dt
    name = "Tonight" if card.day is None and card.label in ("Nite", "Today") else card.label
    if sdt is None:
        return name
    local = sdt.astimezone()
    long = f"{name} · {local.strftime('%b')} {local.day}"
    return long if len(long) <= w else name


def draw_forecast(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    periods = app.forecast_periods
    if not periods:
        safe_addstr(win, 0, 0, "No forecast yet. Press r to refresh.", curses.A_DIM)
        win.noutrefresh()
        return

    cards = _build_day_cards(periods)
    if not cards:
        win.noutrefresh()
        return

    # As many cards as fit at the minimum width (ideally all of them), then
    # widen them to share the full terminal width.
    avail = cols - 1
    visible = clamp((avail + GAP) // (CARD_MIN_W + GAP), 1, len(cards))
    card_w = min(CARD_MAX_W, (avail - GAP * (visible - 1)) // visible)
    total_w = visible * card_w + GAP * (visible - 1)
    x0 = max(0, (avail - total_w) // 2)

    app.fc_scroll = clamp(app.fc_scroll, 0, max(0, len(cards) - visible))
    start = app.fc_scroll
    bottom = rows - 1 if len(cards) > visible else rows

    for ci, card in enumerate(cards[start:start + visible]):
        x = x0 + ci * (card_w + GAP)
        if ci:
            for sy in range(0, bottom):
                safe_addstr(win, sy, x - 1, "\u2502", curses.A_DIM)

        safe_addstr(win, 0, x, _card_label(card, card_w).center(card_w)[:card_w],
                    curses.color_pair(1) | curses.A_BOLD)
        unit = card.temp_unit or "F"
        hi = "\u2014" if card.high is None else f"{card.high:.0f}\u00b0"
        lo = "\u2014" if card.low is None else f"{card.low:.0f}\u00b0"
        tx = x + (card_w - len(f"{hi} / {lo}")) // 2
        safe_addstr(win, 1, tx, hi, _card_attr_temp(card.high, unit) | curses.A_BOLD)
        safe_addstr(win, 1, tx + len(hi), " / ", curses.A_DIM)
        safe_addstr(win, 1, tx + len(hi) + 3, lo, _card_attr_temp(card.low, unit))

        y = 3
        lines = _card_lines(card, card_w, app)
        for i, (text, attr, centered) in enumerate(lines):
            if y >= bottom:
                break
            # Description text sits TEXT_PAD columns in from both separators.
            tx, tw = (x, card_w) if centered else (x + TEXT_PAD, max(1, card_w - 2 * TEXT_PAD))
            if y == bottom - 1 and i < len(lines) - 1:
                text = (text[: tw - 1] + "\u2026") if text else "\u2026"
            safe_addstr(win, y, tx + ((tw - len(text)) // 2 if centered else 0),
                        text[:tw], attr)
            y += 1

    if len(cards) > visible:
        hint = (f"Days {start + 1}–{start + visible} of {len(cards)} · "
                "j/k \u2190\u2192 scroll · widen the terminal to see every day")
        safe_addstr(win, rows - 1, 0, hint[: cols - 1], curses.A_DIM)

    win.noutrefresh()
