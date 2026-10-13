#!/usr/bin/env python3
"""
NWS Weather TUI — Moon phase computation (pure Python, no external deps).

Phase instants use Meeus, *Astronomical Algorithms* ch. 49 (true phases,
accurate to about a minute); illumination uses the low-accuracy method of
ch. 48. A mean synodic month alone can put a phase on the wrong day: the
moon's elliptical orbit moves the true instant up to ~14 hours either way.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import List, Optional, Tuple, Union

# Mean synodic month in days
SYNODIC_MONTH = 29.53058770576

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

PHASE_NAMES = ("New Moon", "First Quarter", "Full Moon", "Last Quarter")
# Brown Lunation Number of the lunation that began with Meeus's k = 0 new moon
# (2000-01-06).
_BLN_AT_K0 = 953
_JD_UNIX_EPOCH = 2440587.5
_DELTA_T_DAYS = 69.0 / 86400  # TT - UT, ~69 s in the 2020s

try:
    from astral import LocationInfo
    from astral.moon import moonrise, moonset
    HAVE_ASTRAL = True
except ImportError:
    HAVE_ASTRAL = False

When = Union[dt.date, dt.datetime]


def _as_utc(when: When) -> dt.datetime:
    """Aware UTC datetime; a plain date means local noon of that day."""
    if not isinstance(when, dt.datetime):
        when = dt.datetime(when.year, when.month, when.day, 12).astimezone()
    elif when.tzinfo is None:
        when = when.astimezone()
    return when.astimezone(dt.timezone.utc)


def _to_jd(t: dt.datetime) -> float:
    return t.timestamp() / 86400.0 + _JD_UNIX_EPOCH


def _from_jde(jde: float) -> dt.datetime:
    seconds = (jde - _DELTA_T_DAYS - _JD_UNIX_EPOCH) * 86400.0
    return dt.datetime.fromtimestamp(round(seconds), tz=dt.timezone.utc)


def _true_phase_jde(k: float) -> float:
    """JDE of the phase with lunation index k (Meeus 49): integer k is a New
    Moon, +0.25 First Quarter, +0.5 Full Moon, +0.75 Last Quarter."""
    t = k / 1236.85
    jde = (2451550.09766 + 29.530588861 * k + 0.00015437 * t ** 2
           - 0.000000150 * t ** 3 + 0.00000000073 * t ** 4)
    e = 1 - 0.002516 * t - 0.0000074 * t ** 2
    rad = math.radians
    m = rad(2.5534 + 29.10535670 * k - 0.0000014 * t ** 2 - 0.00000011 * t ** 3)
    mp = rad(201.5643 + 385.81693528 * k + 0.0107582 * t ** 2
             + 0.00001238 * t ** 3 - 0.000000058 * t ** 4)
    f = rad(160.7108 + 390.67050284 * k - 0.0016118 * t ** 2
            - 0.00000227 * t ** 3 + 0.000000011 * t ** 4)
    om = rad(124.7746 - 1.56375588 * k + 0.0020672 * t ** 2 + 0.00000215 * t ** 3)
    sin = math.sin
    frac = round((k % 1) * 4) % 4
    if frac in (0, 2):
        new = frac == 0
        c = [
            (-0.40720 if new else -0.40614, mp),
            ((0.17241 if new else 0.17302) * e, m),
            (0.01608 if new else 0.01614, 2 * mp),
            (0.01039 if new else 0.01043, 2 * f),
            ((0.00739 if new else 0.00734) * e, mp - m),
            ((-0.00514 if new else -0.00515) * e, mp + m),
            ((0.00208 if new else 0.00209) * e * e, 2 * m),
            (-0.00111, mp - 2 * f), (-0.00057, mp + 2 * f),
            (0.00056 * e, 2 * mp + m), (-0.00042, 3 * mp),
            (0.00042 * e, m + 2 * f), (0.00038 * e, m - 2 * f),
            (-0.00024 * e, 2 * mp - m), (-0.00017, om), (-0.00007, mp + 2 * m),
            (0.00004, 2 * mp - 2 * f), (0.00004, 3 * m), (0.00003, mp + m - 2 * f),
            (0.00003, 2 * mp + 2 * f), (-0.00003, mp + m + 2 * f),
            (0.00003, mp - m + 2 * f), (-0.00002, mp - m - 2 * f),
            (-0.00002, 3 * mp + m), (0.00002, 4 * mp),
        ]
        jde += sum(coef * sin(arg) for coef, arg in c)
    else:
        c = [
            (-0.62801, mp), (0.17172 * e, m), (-0.01183 * e, mp + m),
            (0.00862, 2 * mp), (0.00804, 2 * f), (0.00454 * e, mp - m),
            (0.00204 * e * e, 2 * m), (-0.00180, mp - 2 * f), (-0.00070, mp + 2 * f),
            (-0.00040, 3 * mp), (-0.00034 * e, 2 * mp - m), (0.00032 * e, m + 2 * f),
            (0.00032 * e, m - 2 * f), (-0.00028 * e * e, mp + 2 * m),
            (0.00027 * e, 2 * mp + m), (-0.00017, om), (-0.00005, mp - m - 2 * f),
            (0.00004, 2 * mp + 2 * f), (-0.00004, mp + m + 2 * f),
            (0.00004, mp - 2 * m), (0.00003, mp + m - 2 * f), (0.00003, 3 * m),
            (0.00002, 2 * mp - 2 * f), (0.00002, mp - m + 2 * f), (-0.00002, 3 * mp + m),
        ]
        w = (0.00306 - 0.00038 * e * math.cos(m) + 0.00026 * math.cos(mp)
             - 0.00002 * math.cos(mp - m) + 0.00002 * math.cos(mp + m)
             + 0.00002 * math.cos(2 * f))
        jde += sum(coef * sin(arg) for coef, arg in c) + (w if frac == 1 else -w)
    # The planetary arguments (A1–A14) add under a minute; left out.
    return jde


def _k_near(t: dt.datetime) -> float:
    """Approximate lunation index of the new moon at or before `t`."""
    return math.floor((_to_jd(t) - 2451550.09766) / 29.530588861)


def phase_time(k: float) -> dt.datetime:
    """UTC instant of the phase with lunation index `k` (see _true_phase_jde)."""
    return _from_jde(_true_phase_jde(k))


def previous_new_moon(when: When) -> Tuple[int, dt.datetime]:
    """(k, instant) of the last new moon at or before `when`."""
    t = _as_utc(when)
    k = _k_near(t) + 1
    while phase_time(k) > t:
        k -= 1
    return k, phase_time(k)


def moon_age(when: When) -> float:
    """Days since the last true New Moon (0 = New, ~14.8 = Full)."""
    t = _as_utc(when)
    return (t - previous_new_moon(t)[1]).total_seconds() / 86400.0


def moon_phase_name(age: float) -> str:
    """Human-readable phase name from moon age in days."""
    for lo, hi, name in _PHASE_BOUNDARIES:
        if lo <= age < hi:
            return name
    return "Waning Crescent"


def moon_illumination(age: float) -> float:
    """Approximate illumination fraction 0.0–1.0 from age alone."""
    return (1.0 - math.cos(2.0 * math.pi * age / SYNODIC_MONTH)) / 2.0


def moon_illumination_at(when: When) -> float:
    """Illuminated fraction 0.0–1.0 (Meeus 48, low-accuracy method: ~1%)."""
    t = (_to_jd(_as_utc(when)) + _DELTA_T_DAYS - 2451545.0) / 36525.0
    rad = math.radians
    d = rad(297.8501921 + 445267.1114034 * t - 0.0018819 * t ** 2)
    m = rad(357.5291092 + 35999.0502909 * t - 0.0001536 * t ** 2)
    mp = rad(134.9633964 + 477198.8675055 * t + 0.0087414 * t ** 2)
    i = (180 - math.degrees(d) - 6.289 * math.sin(mp) + 2.100 * math.sin(m)
         - 1.274 * math.sin(2 * d - mp) - 0.658 * math.sin(2 * d)
         - 0.214 * math.sin(2 * mp) - 0.110 * math.sin(d))
    return (1 + math.cos(rad(i))) / 2.0


def lunation_number(when: When) -> int:
    """Brown Lunation Number of the lunation in progress (#1 began 1923-01-17)."""
    return previous_new_moon(when)[0] + _BLN_AT_K0


def next_moon_phases(date: dt.date) -> List[Tuple[str, dt.datetime]]:
    """The next four major phases from the start of local day `date`, as
    (name, local datetime), soonest first."""
    start = dt.datetime(date.year, date.month, date.day).astimezone()
    k, _ = previous_new_moon(start)
    out: List[Tuple[str, dt.datetime]] = []
    q = 0
    while len(out) < 4:
        when = phase_time(k + q / 4).astimezone()
        if when >= start:
            out.append((PHASE_NAMES[q % 4], when))
        q += 1
    return out


def get_moonrise_moonset(
    lat: float, lon: float, date: dt.date
) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    """Moonrise and moonset on local day `date`; either may be None (some
    days have no rise or no set, and without astral there are neither)."""
    if not HAVE_ASTRAL:
        return None, None
    observer = LocationInfo(latitude=lat, longitude=lon).observer

    def find(event) -> Optional[dt.datetime]:
        # astral searches one UTC day, which straddles two local days in the
        # US: an evening moonset can fall on the next UTC date, where astral
        # alone reports "never sets". Search the neighbours and keep the hit
        # on our local date.
        for offset in (-1, 0, 1):
            try:
                t = event(observer, date + dt.timedelta(days=offset),
                          tzinfo=dt.timezone.utc).astimezone()
            except (ValueError, ArithmeticError):
                continue  # no such event on that UTC day
            if t.date() == date:
                return t
        return None

    return find(moonrise), find(moonset)
