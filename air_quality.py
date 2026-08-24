#!/usr/bin/env python3
"""
NWS Weather TUI — Air quality (Open-Meteo Air Quality API, no key required).
"""

from __future__ import annotations

from typing import Any, Dict

from cache import TTLCache
from helpers import dbg

_FIELDS = (
    "us_aqi,pm2_5,pm10,"
    "us_aqi_pm2_5,us_aqi_pm10,us_aqi_ozone,us_aqi_no2,us_aqi_so2,us_aqi_co"
)


class AirQualityClient:
    def __init__(self, session, timeout: int, cache: TTLCache) -> None:
        self.s = session
        self.timeout = timeout
        self.cache = cache

    def current(self, lat: float, lon: float, ttl: int) -> Dict[str, Any]:
        url = (
            "https://air-quality-api.open-meteo.com/v1/air-quality"
            f"?latitude={lat:.4f}&longitude={lon:.4f}&current={_FIELDS}"
        )
        cached = self.cache.get(url)
        if cached is not None:
            return cached  # type: ignore[return-value]
        try:
            r = self.s.get(url, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            self.cache.set(url, data, ttl)
            return data
        except Exception as e:
            # Supplementary data source — never take the whole refresh offline.
            dbg(f"Air quality fetch failed: {e}")
            return {}
