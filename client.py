#!/usr/bin/env python3
"""
NWS Weather TUI — NWS API client (weather endpoints + delegation to sub-clients).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from air_quality import AirQualityClient
from cache import TTLCache
from constants import BASE
from geocode import Geocoder
from geo_boundaries import BoundaryClient
from radar_client import RadarFetcher
from uv_index import UVIndexClient


class _ThreadLocalSession:
    """Gives each thread its own requests.Session so concurrent background
    fetches (weather refresh, radar frames) can run in parallel instead of
    serializing on a shared, lock-guarded session."""

    def __init__(self, headers: Dict[str, str]) -> None:
        self._headers = headers
        self._local = threading.local()

    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update(self._headers)
            self._local.session = s
        return s

    def get(self, *args, **kwargs):
        return self._session().get(*args, **kwargs)

    @property
    def headers(self):
        return self._headers


class NWSClient:
    def __init__(self, user_agent: str, timeout: int, ttls: Dict[str, int]) -> None:
        self.s = _ThreadLocalSession(
            {
                "User-Agent": user_agent,
                "Accept": "application/geo+json, application/json",
            }
        )
        self.timeout = timeout
        self.ttls = ttls
        self.cache = TTLCache()

        # Sub-clients
        self._radar = RadarFetcher(self.s, timeout, self.cache, ttls)
        self._geocoder = Geocoder(self.s, timeout, self.cache)
        self._boundaries = BoundaryClient(self.s, timeout, self.cache)
        self._air_quality = AirQualityClient(self.s, timeout, self.cache)
        self._uv_index = UVIndexClient(self.s, timeout, self.cache)

    # ------------------------------------------------------------------
    # Core HTTP helpers
    # ------------------------------------------------------------------

    def _get_json(
        self, url: str, ttl: int, tries: int = 3, backoff: float = 0.6
    ) -> Dict[str, Any]:
        cached = self.cache.get(url)
        if cached is not None:
            return cached  # type: ignore[return-value]
        last_err: Optional[Exception] = None
        for i in range(tries):
            try:
                r = self.s.get(url, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                self.cache.set(url, data, ttl)
                return data
            except Exception as e:
                last_err = e
                time.sleep(backoff * (2 ** i))
        if last_err:
            raise last_err
        return {}

    # ------------------------------------------------------------------
    # NWS API
    # ------------------------------------------------------------------

    def points(self, lat: float, lon: float) -> Dict[str, Any]:
        url = f"{BASE}/points/{lat:.4f},{lon:.4f}"
        return self._get_json(url, ttl=self.ttls["points"])

    def stations(self, stations_url: str) -> Dict[str, Any]:
        return self._get_json(stations_url, ttl=self.ttls["stations"])

    def latest_observation(self, station_id: str) -> Dict[str, Any]:
        url = f"{BASE}/stations/{station_id}/observations/latest"
        return self._get_json(url, ttl=self.ttls["observation"])

    def forecast(self, forecast_url: str, units: str) -> Dict[str, Any]:
        sep = "&" if "?" in forecast_url else "?"
        url = forecast_url + sep + f"units={units}"
        return self._get_json(url, ttl=self.ttls["forecast"])

    def forecast_hourly(self, hourly_url: str, units: str) -> Dict[str, Any]:
        sep = "&" if "?" in hourly_url else "?"
        url = hourly_url + sep + f"units={units}"
        return self._get_json(url, ttl=self.ttls["forecast_hourly"])

    def alerts(self, lat: float, lon: float) -> Dict[str, Any]:
        url = f"{BASE}/alerts/active?point={lat:.4f},{lon:.4f}"
        return self._get_json(url, ttl=self.ttls["alerts"])

    def forecast_discussion(self, office_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest Area Forecast Discussion (AFD) text product
        issued by a WFO (e.g. "OTX")."""
        return self._latest_text_product(office_id, "AFD", ttl_key="afd")

    def hazardous_weather_outlook(self, office_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest Hazardous Weather Outlook (HWO) text product
        issued by a WFO (e.g. "OTX") — a rolling 7-day heads-up on
        potential severe/hazardous weather."""
        return self._latest_text_product(office_id, "HWO", ttl_key="hwo")

    def _latest_text_product(
        self, office_id: str, product_type: str, ttl_key: str
    ) -> Optional[Dict[str, Any]]:
        office = (office_id or "").strip().upper()
        if not office:
            return None
        try:
            listing = self._get_json(
                f"{BASE}/products/types/{product_type}/locations/{office}",
                ttl=self.ttls.get(ttl_key, 3600),
            )
            graph = (listing or {}).get("@graph") or []
            if not graph:
                return None
            prod_id = (graph[0] or {}).get("id")
            if not isinstance(prod_id, str) or not prod_id:
                return None
            prod = self._get_json(
                f"{BASE}/products/{prod_id}", ttl=self.ttls.get(ttl_key, 3600)
            )
            text = str((prod or {}).get("productText") or "").strip()
            if not text:
                return None
            return {
                "text": text,
                "issuance_time": prod.get("issuanceTime"),
                "office": office,
            }
        except Exception:
            return None

    def forecast_grid_data(self, grid_data_url: str) -> Dict[str, Any]:
        """Fetch raw NWS gridpoint data (quantitative precip, snowfall, etc.)."""
        return self._get_json(grid_data_url, ttl=self.ttls.get("gridpoints", 600))

    # ------------------------------------------------------------------
    # Delegated: air quality
    # ------------------------------------------------------------------

    def air_quality(self, lat: float, lon: float) -> Dict[str, Any]:
        return self._air_quality.current(lat, lon, ttl=self.ttls["air_quality"])

    # ------------------------------------------------------------------
    # Delegated: UV index
    # ------------------------------------------------------------------

    def uv_index(self, lat: float, lon: float) -> Dict[str, Any]:
        return self._uv_index.current(lat, lon, ttl=self.ttls.get("uv_index", 900))

    # ------------------------------------------------------------------
    # Delegated: geocoding
    # ------------------------------------------------------------------

    def geocode_us(self, query: str) -> Optional[Tuple[str, float, float]]:
        return self._geocoder.geocode_us(query)

    # ------------------------------------------------------------------
    # Delegated: radar
    # ------------------------------------------------------------------

    def radar_wms_png(
        self,
        radar_id: str,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> Optional[bytes]:
        return self._radar.radar_wms_png(radar_id, bbox4326, width, height)

    def radar_frames_png(
        self,
        radar_id: str,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
        n_frames: int = 4,
        step_minutes: int = 5,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> List[Tuple[bytes, int]]:
        return self._radar.radar_frames_png(
            radar_id, bbox4326, width, height, n_frames, step_minutes, progress_cb
        )

    # ------------------------------------------------------------------
    # Delegated: boundaries
    # ------------------------------------------------------------------

    def state_lines_png(
        self, bbox4326: Tuple[float, float, float, float], width: int, height: int
    ) -> Tuple[Optional[bytes], Optional[Tuple[float, float, float, float]]]:
        return self._boundaries.state_lines_png(bbox4326, width, height)

    def state_bbox(
        self, state_code: str
    ) -> Optional[Tuple[float, float, float, float]]:
        return self._boundaries.state_bbox(state_code)

    def state_lines_features(
        self,
        bbox4326: Tuple[float, float, float, float],
        state_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self._boundaries.state_lines_features(bbox4326, state_code)
