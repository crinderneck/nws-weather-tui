#!/usr/bin/env python3
"""
NWS Weather TUI — Moon phase computation (pure Python, no external deps).

Uses a simplified astronomical algorithm based on known New Moon reference
and the synodic month length (29.53058770576 days).
"""

from __future__ import annotations

import datetime as dt
import math
from typing import List, Optional, Tuple

# Synodic month in days
SYNODIC_MONTH = 29.53058770576

# Known New Moon reference: 2000-01-06 18:14 UTC
_REF_NEW_MOON = dt.datetime(2000, 1, 6, 18, 14, 0, tzinfo=dt.timezone.utc)

# Phase names and their boundaries (in days of age)
_PHASE_BOUNDARIES = [
    (0.0,    1.845,  "New Moon"),
    (1.845,  7.383,  "Waxing Crescent"),
    (7.383,  9.228,  "First Quarter"),
    (9.228,  14.765, "Waxing Gibbous"),
    (14.765, 16.610, "Full Moon"),
    (16.610, 22.148, "Waning Gibbous"),
    (22.148, 23.993, "Last Quarter"),
    (23.993, 29.531, "Waning Crescent"),
]


def moon_age(date: dt.date) -> float:
    """Days into the current lunation (0 = New Moon, ~14.76 = Full)."""
    now = dt.datetime(date.year, date.month, date.day, 12, 0, 0,
                      tzinfo=dt.timezone.utc)
    diff = (now - _REF_NEW_MOON).total_seconds() / 86400.0
    return diff % SYNODIC_MONTH


def moon_phase_name(age: float) -> str:
    """Human-readable phase name from moon age in days."""
    for lo, hi, name in _PHASE_BOUNDARIES:
        if lo <= age < hi:
            return name
    return "Waning Crescent"


def moon_illumination(age: float) -> float:
    """Approximate illumination fraction 0.0–1.0."""
    return (1.0 - math.cos(2.0 * math.pi * age / SYNODIC_MONTH)) / 2.0


def lunation_number(date: dt.date) -> int:
    """Brown Lunation Number (BLN). Lunation 1 started 1923-01-17."""
    ref = dt.datetime(1923, 1, 17, 0, 0, 0, tzinfo=dt.timezone.utc)
    now = dt.datetime(date.year, date.month, date.day, 12, 0, 0,
                      tzinfo=dt.timezone.utc)
    diff = (now - ref).total_seconds() / 86400.0
    return int(diff / SYNODIC_MONTH) + 1


def next_moon_phases(date: dt.date) -> List[Tuple[str, dt.date]]:
    """Return the next 4 major phase dates (New, First Qtr, Full, Last Qtr)."""
    age = moon_age(date)
    base = dt.datetime(date.year, date.month, date.day, 12, 0, 0,
                       tzinfo=dt.timezone.utc)

    # Target ages for major phases
    targets = [
        (0.0, "New Moon"),
        (SYNODIC_MONTH / 4, "First Quarter"),
        (SYNODIC_MONTH / 2, "Full Moon"),
        (3 * SYNODIC_MONTH / 4, "Last Quarter"),
    ]

    results: List[Tuple[str, dt.date]] = []
    for target_age, name in targets:
        days_until = (target_age - age) % SYNODIC_MONTH
        if days_until < 0.5:
            days_until += SYNODIC_MONTH
        phase_dt = base + dt.timedelta(days=days_until)
        results.append((name, phase_dt.date()))

    results.sort(key=lambda x: x[1])
    return results


def get_moonrise_moonset(
    lat: float, lon: float, date: dt.date
) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    """Moonrise/moonset using astral if available, else (None, None)."""
    try:
        from astral import LocationInfo
        from astral.moon import moonrise, moonset
        loc = LocationInfo(latitude=lat, longitude=lon)
        rise = moonrise(loc.observer, date)
        mset = moonset(loc.observer, date)
        return rise, mset
    except Exception:
        return None, None
