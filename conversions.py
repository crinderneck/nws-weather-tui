#!/usr/bin/env python3
"""
NWS Weather TUI — Unit conversion functions.
"""

from __future__ import annotations

import math
from typing import Optional


def mps_to_mph(mps: Optional[float]) -> Optional[float]:
    return None if mps is None else mps * 2.2369362920544


def c_to_f(c: Optional[float]) -> Optional[float]:
    return None if c is None else c * 9.0 / 5.0 + 32.0


def pa_to_inhg(pa: Optional[float]) -> Optional[float]:
    return None if pa is None else pa / 3386.389


def m_to_mi(m: Optional[float]) -> Optional[float]:
    return None if m is None else m / 1609.344


def dewpoint_c(temp_c: Optional[float], humidity_pct: Optional[float]) -> Optional[float]:
    """Calculate dew point temperature using the Magnus formula approximation."""
    if temp_c is None or humidity_pct is None:
        return None
    if humidity_pct <= 0:
        return None
    a, b = 17.27, 237.7
    try:
        gamma = (a * temp_c) / (b + temp_c) + math.log(humidity_pct / 100.0)
        return (b * gamma) / (a - gamma)
    except (ValueError, ZeroDivisionError):
        return None
