#!/usr/bin/env python3
"""
NWS Weather TUI — US geocoding (ZIP via Zippopotam.us, places via Nominatim).
"""

from __future__ import annotations

from typing import Optional, Tuple

from cache import TTLCache
from constants import ZIP_RE
from helpers import dbg


class Geocoder:
    def __init__(self, session, timeout: int, cache: TTLCache) -> None:
        self.s = session
        self.timeout = timeout
        self.cache = cache

    def geocode_us(self, query: str) -> Optional[Tuple[str, float, float]]:
        q = (query or "").strip()
        if not q:
            return None
        ck = f"geocode:{q.lower()}"
        cached = self.cache.get(ck)
        if cached is not None:
            return cached  # type: ignore[return-value]

        if ZIP_RE.fullmatch(q):
            result = self._geocode_zip(q[:5])
            if result:
                self.cache.set(ck, result, 86400)
                return result

        result = self._geocode_nominatim(q)
        if result:
            self.cache.set(ck, result, 86400)
            return result

        self.cache.set(ck, None, 600)
        return None

    def _geocode_zip(self, zip5: str) -> Optional[Tuple[str, float, float]]:
        try:
            r = self.s.get(
                f"https://api.zippopotam.us/us/{zip5}", timeout=self.timeout
            )
            if r.ok:
                data = r.json()
                places = (data or {}).get("places") or []
                if places:
                    p0 = places[0] or {}
                    lat_s, lon_s = p0.get("latitude"), p0.get("longitude")
                    if lat_s is None or lon_s is None:
                        return None
                    lat_f, lon_f = float(lat_s), float(lon_s)
                    place = str(p0.get("place name") or "").strip()
                    state = str(
                        p0.get("state abbreviation") or p0.get("state") or ""
                    ).strip()
                    name = f"{zip5} {place}, {state}".strip().strip(",")
                    return (name, lat_f, lon_f)
        except Exception as e:
            dbg(f"ZIP geocode failed: {e}")
        return None

    def _geocode_nominatim(self, q: str) -> Optional[Tuple[str, float, float]]:
        try:
            r = self.s.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q,
                    "format": "jsonv2",
                    "countrycodes": "us",
                    "limit": "1",
                    "addressdetails": "1",
                },
                headers={"User-Agent": self.s.headers.get("User-Agent", "nws-weather-tui/1.0")},
                timeout=self.timeout,
            )
            r.raise_for_status()
            results = r.json()
            if not results:
                return None
            hit = results[0]
            lat = float(hit["lat"])
            lon = float(hit["lon"])
            name = _format_nominatim_name(hit)
            return (name, lat, lon)
        except Exception as e:
            dbg(f"Nominatim geocode failed for '{q}': {e}")
        return None


def _format_nominatim_name(hit: dict) -> str:
    addr = hit.get("address") or {}
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("hamlet")
        or addr.get("county")
        or ""
    )
    state = addr.get("state") or ""
    if city and state:
        return f"{city}, {state}"
    if city:
        return city
    if state:
        return state
    return hit.get("display_name") or "Unknown"
