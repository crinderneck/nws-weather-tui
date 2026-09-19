#!/usr/bin/env python3
"""
NWS Weather TUI — UV Index (Open-Meteo Forecast API, no key required).
"""

from __future__ import annotations

from typing import Any, Dict

from cache import TTLCache
from helpers import dbg


class UVIndexClient:
    def __init__(self, session, timeout: int, cache: TTLCache) -> None:
        self.s = session
        self.timeout = timeout
        self.cache = cache

    def current(self, lat: float, lon: float, ttl: int) -> Dict[str, Any]:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat:.4f}&longitude={lon:.4f}"
            "&current=uv_index&daily=uv_index_max&timezone=auto"
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
            dbg(f"UV index fetch failed: {e}")
            return {}
