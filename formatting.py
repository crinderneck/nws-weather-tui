#!/usr/bin/env python3
"""
NWS Weather TUI — Time parsing, formatting, and number utilities.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Optional

_FIRST_NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def parse_iso(ts: Optional[str]) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _local_tzinfo() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def _to_local(t: Optional[object]) -> Optional[dt.datetime]:
    if t is None:
        return None
    if isinstance(t, str):
        t = parse_iso(t)
        if t is None:
            return None
    if not isinstance(t, dt.datetime):
        return None
    ltz = _local_tzinfo()
    if t.tzinfo is None:
        t = t.replace(tzinfo=ltz)
    return t.astimezone(ltz)


def fmt_time(t: Optional[object], use_24h: bool, with_date: bool = False) -> str:
    tt = _to_local(t)
    if not tt:
        return "\u2014"
    if with_date:
        return (
            tt.strftime("%Y-%m-%d %H:%M")
            if use_24h
            else tt.strftime("%Y-%m-%d %I:%M %p").lstrip("0")
        )
    return (
        tt.strftime("%H:%M") if use_24h else tt.strftime("%I:%M%p").lstrip("0").lower()
    )


def fmt_num(x: Optional[float], digits: int = 0) -> str:
    if x is None:
        return "\u2014"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "\u2014"
    return f"{x:.{digits}f}"


def parse_first_number(s: str) -> Optional[float]:
    if not s:
        return None
    m = _FIRST_NUMBER_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None
