#!/usr/bin/env python3
"""
NWS Weather TUI — Helper functions and utilities.

Most functions have been extracted to dedicated modules.  This file
keeps the residual helpers and re-exports everything that other modules
still import via ``from helpers import …``.
"""

from __future__ import annotations

import datetime as dt
import textwrap
from functools import lru_cache
from typing import Optional, Tuple

from constants import DEBUG_LOG_PATH, ensure_dir

# --- Re-exports from extracted modules (backward compat) ---
from conversions import c_to_f, dewpoint_c, m_to_mi, mps_to_mph, pa_to_inhg  # noqa: F401
from formatting import fmt_num, fmt_time, parse_first_number, parse_iso      # noqa: F401
from geo import bbox_around, clamp, expand_bbox_km                           # noqa: F401
from overlays import (                                                        # noqa: F401
    city_overlay_and_hits_for_bbox,
    png_to_line_overlay,
    vector_lines_overlay,
)
from radar_decode import RadarCell, png_to_ascii, png_to_halfblock_radar      # noqa: F401

try:
    from astral import LocationInfo
    from astral.sun import sun
except ImportError:
    LocationInfo = None  # type: ignore[assignment]
    sun = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Astronomy
# ---------------------------------------------------------------------------

def get_sunrise_sunset(
    lat: float, lon: float, date: dt.date
) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    if sun is None or LocationInfo is None:
        return None, None
    try:
        loc = LocationInfo(latitude=lat, longitude=lon)
        s = sun(loc.observer, date=date, tzinfo=loc.timezone)
        return s["sunrise"], s["sunset"]
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------

def dbg(msg: str) -> None:
    try:
        ensure_dir(DEBUG_LOG_PATH.replace("debug.log", ""))
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Curses / text utilities
# ---------------------------------------------------------------------------

def safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        win.addstr(y, x, s, attr)
    except Exception:
        pass


@lru_cache(maxsize=2048)
def _wrap_lines_cached(text: str, width: int) -> Tuple[str, ...]:
    return tuple(
        textwrap.wrap(
            text, width=width, replace_whitespace=False, drop_whitespace=False
        )
    )


def wrap_lines(text: str, width: int) -> Tuple[str, ...]:
    if width <= 1:
        return (text,)
    return _wrap_lines_cached(text, width)
