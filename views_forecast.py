#!/usr/bin/env python3
"""
NWS Weather TUI — Forecast view (horizontal day cards).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import curses

from formatting import fmt_time, parse_iso
from geo import clamp
from helpers import get_sunrise_sunset, safe_addstr, wrap_lines
from icons import ICON_BIG, ICON_TINY
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


def draw_forecast(app: "App", win) -> None:
    win.erase()
    rows, cols = win.getmaxyx()
    periods = app.forecast_periods
    if not periods:
        safe_addstr(
            win, 0, 0, "No forecast yet. Press r to refresh.", curses.A_DIM
        )
        win.noutrefresh()
        return

    cards = _build_day_cards(periods)
    if not cards:
        win.noutrefresh()
        return

    # --- Layout constants ---
    CARD_W = 24          # width of each card column
    GAP = 2              # gap between cards
    HEADER_ROWS = 2      # title + blank line

    visible_cards = max(1, (cols + GAP) // (CARD_W + GAP))
    app.fc_scroll = clamp(app.fc_scroll, 0, max(0, len(cards) - 1))

    # Center the cards if there's extra space
    total_w = min(visible_cards, len(cards)) * (CARD_W + GAP) - GAP
    x_offset = max(0, (cols - total_w) // 2)

    # Title
    safe_addstr(win, 0, 0, "Forecast"[: cols - 1], curses.A_BOLD)

    # Determine which cards to show
    start_idx = app.fc_scroll
    if start_idx + visible_cards > len(cards):
        start_idx = max(0, len(cards) - visible_cards)
    end_idx = min(start_idx + visible_cards, len(cards))

    # Precompute sunrise/sunset per date
    sun_cache: Dict[str, Tuple[Optional[dt.datetime], Optional[dt.datetime]]] = {}

    y_base = HEADER_ROWS

    for ci, card_idx in enumerate(range(start_idx, end_idx)):
        card = cards[card_idx]
        x = x_offset + ci * (CARD_W + GAP)

        if x + CARD_W > cols:
            break

        # Draw separator between cards
        if ci > 0:
            sep_x = x - GAP // 2 - 1
            if 0 <= sep_x < cols:
                for sy in range(y_base, min(rows - 1, y_base + 12)):
                    safe_addstr(win, sy, sep_x, "\u2502", curses.A_DIM)

        y = y_base

        # Day label
        attr = curses.A_BOLD
        label_str = card.label.center(CARD_W)
        safe_addstr(win, y, x, label_str[:CARD_W], attr)
        y += 1

        # Icon (big ASCII art, centered in card width)
        icon_art = ICON_BIG.get(card.icon_key, ICON_BIG.get("unknown", ""))
        icon_lines = icon_art.strip("\n").split("\n") if icon_art else []
        for il in range(len(icon_lines)):
            if y >= rows - 2:
                break
            line = icon_lines[il]
            if len(line) > CARD_W:
                line = line[:CARD_W]
            padded = line.center(CARD_W)
            safe_addstr(win, y, x, padded[:CARD_W], curses.A_DIM)
            y += 1

        # Temperature line: high° low°
        if y < rows - 2:
            unit_suffix = f"\u00b0{card.temp_unit}" if ci == 0 else "\u00b0"
            hi = f"{card.high:.0f}{unit_suffix}" if card.high is not None else "\u2014"
            lo = f"{card.low:.0f}{unit_suffix}" if card.low is not None else "\u2014"
            hi_str = hi
            lo_str = lo
            temp_x = x + (CARD_W - len(f"{hi_str} {lo_str}")) // 2
            safe_addstr(win, y, temp_x, hi_str, curses.A_BOLD)
            safe_addstr(win, y, temp_x + len(hi_str), " ")
            safe_addstr(win, y, temp_x + len(hi_str) + 1, lo_str, curses.A_DIM)
            y += 1

        # Short forecast (wrapped to card width, up to 2 lines)
        if y < rows - 2 and card.short_forecast:
            wrapped = wrap_lines(card.short_forecast, CARD_W)
            for wl in wrapped[:2]:
                if y >= rows - 2:
                    break
                centered = wl.center(CARD_W)
                safe_addstr(win, y, x, centered[:CARD_W], curses.A_DIM)
                y += 1

        # Sunrise / Sunset
        sdt = card.start_dt
        if sdt and y < rows - 1:
            date_key = sdt.date().isoformat()
            if date_key not in sun_cache:
                sun_cache[date_key] = get_sunrise_sunset(
                    app.lat, app.lon, sdt.date()
                )
            sunrise_dt, sunset_dt = sun_cache[date_key]

            use_24h = getattr(app, "use_24h", False)
            sr_str = fmt_time(sunrise_dt, use_24h) if sunrise_dt else "—"
            ss_str = fmt_time(sunset_dt, use_24h) if sunset_dt else "—"
            sun_line = f"\u2600\u2191{sr_str}  \u2600\u2193{ss_str}"
            sun_x = x + (CARD_W - len(sun_line)) // 2
            safe_addstr(win, y, sun_x, sun_line[:CARD_W], curses.A_DIM)
            y += 1

    # Footer with scroll hint
    if len(cards) > visible_cards:
        hint = f"← {app.fc_scroll + 1}/{len(cards)} → (j/k)"[: cols - 1]
        safe_addstr(win, rows - 1, 0, hint, curses.A_DIM)

    win.noutrefresh()
