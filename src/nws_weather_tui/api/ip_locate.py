#!/usr/bin/env python3
"""
NWS Weather TUI — Roughly where the user is, from their IP address (ipinfo.io).

Only used at startup to warn someone outside the US that the NWS won't have
anything for them; it never changes the location.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from nws_weather_tui.constants import NWS_COUNTRIES
from nws_weather_tui.helpers import dbg

IPINFO_URL = "https://ipinfo.io/json"


@dataclass
class IPLocation:
    country: str  # ISO 3166-1 alpha-2, e.g. "US", "GB"
    place: str  # "London, England", or "" when ipinfo only knows the country

    @property
    def in_nws_area(self) -> bool:
        return self.country in NWS_COUNTRIES


def locate_ip(session: Any, timeout: float) -> Optional[IPLocation]:
    """Where the IP address is, or None if that can't be told (offline,
    rate-limited, replaying fixtures without a recording)."""
    try:
        r = session.get(IPINFO_URL, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        dbg(f"IP location lookup failed: {e}")
        return None
    country = str((data or {}).get("country") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        return None
    place = ", ".join(
        s.strip() for s in (data.get("city"), data.get("region"))
        if isinstance(s, str) and s.strip()
    )
    return IPLocation(country, place)
