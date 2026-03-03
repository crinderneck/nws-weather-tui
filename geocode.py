#!/usr/bin/env python3
"""
NWS Weather TUI — US geocoding (ZIP via Zippopotam.us, address via Census Bureau).
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
            zip5 = q[:5]
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
                        lat_f, lon_f = float(lat_s), float(lon_s)
                        place = str(p0.get("place name") or "").strip()
                        state = str(
                            p0.get("state abbreviation") or p0.get("state") or ""
                        ).strip()
                        name = f"{zip5} {place}, {state}".strip().strip(",")
                        out: Tuple[str, float, float] = (name, lat_f, lon_f)
                        self.cache.set(ck, out, 86400)
                        return out
            except Exception as e:
                dbg(f"ZIP geocode failed: {e}")

        for candidate in (q, f"{q}, USA"):
            try:
                r = self.s.get(
                    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
                    params={
                        "address": candidate,
                        "benchmark": "Public_AR_Current",
                        "format": "json",
                    },
                    timeout=self.timeout,
                )
                r.raise_for_status()
                matches = (
                    ((r.json() or {}).get("result") or {}).get("addressMatches") or []
                )
                if not matches:
                    continue
                m = matches[0] or {}
                coords = m.get("coordinates") or {}
                lon = coords.get("x")
                lat = coords.get("y")
                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    continue
                name = str(m.get("matchedAddress") or candidate)
                out = (name, float(lat), float(lon))
                self.cache.set(ck, out, 86400)
                return out
            except Exception as e:
                dbg(f"Census geocode failed for '{candidate}': {e}")

        self.cache.set(ck, None, 600)
        return None
