#!/usr/bin/env python3
"""
NWS Weather TUI — NWS API client with retries and radar support.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from cache import TTLCache
from constants import BASE
from helpers import dbg


class NWSClient:
    def __init__(self, user_agent: str, timeout: int, ttls: Dict[str, int]) -> None:
        self.s = requests.Session()
        self.s.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/geo+json, application/json",
            }
        )
        self.timeout = timeout
        self.ttls = ttls
        self.cache = TTLCache()

    # ------------------------------------------------------------------
    # Core HTTP helpers
    # ------------------------------------------------------------------

    def _get_bytes(
        self, url: str, ttl: int, tries: int = 3, backoff: float = 0.6
    ) -> Optional[bytes]:
        cached = self.cache.get(url)
        if cached is not None:
            return cached  # type: ignore[return-value]
        last_err: Optional[Exception] = None
        for i in range(tries):
            try:
                r = self.s.get(url, timeout=self.timeout)
                ct = (r.headers.get("Content-Type") or "").lower()
                if "vnd.ogc.se_xml" in ct or ("xml" in ct and "image" not in ct):
                    dbg(f"RADAR BAD CT={ct} url={url} status={r.status_code}")
                    return None
                r.raise_for_status()
                data = r.content
                self.cache.set(url, data, ttl)
                return data
            except Exception as e:
                last_err = e
                time.sleep(backoff * (2 ** i))
        raise last_err or RuntimeError("request failed")

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
        raise last_err or RuntimeError("request failed")

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

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------

    def geocode_us(self, query: str) -> Optional[Tuple[str, float, float]]:
        from constants import ZIP_RE

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

    # ------------------------------------------------------------------
    # Radar: MRMS single frame (primary source)
    # ------------------------------------------------------------------

    def _mrms_latest_time(self) -> Optional[int]:
        """Fetch the latest available timestamp (ms) from MRMS ImageServer."""
        mrms_base = (
            "https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
            "radar/radar_base_reflectivity_time/ImageServer"
        )
        ck = mrms_base + ":latest_time"
        cached = self.cache.get(ck)
        if isinstance(cached, int):
            return cached
        try:
            meta = self.s.get(mrms_base, params={"f": "pjson"}, timeout=self.timeout)
            meta.raise_for_status()
            mj = meta.json()
            te = ((mj or {}).get("timeInfo") or {}).get("timeExtent") or []
            if isinstance(te, list) and len(te) >= 2 and isinstance(te[1], (int, float)):
                ts = int(te[1])
                self.cache.set(ck, ts, 180)
                return ts
        except Exception as e:
            dbg(f"RADAR MRMS latest-time lookup failed: {e}")
        return None

    def _mrms_time_extent(self) -> Tuple[Optional[int], Optional[int]]:
        """Return (start_ms, end_ms) of available MRMS time series."""
        mrms_base = (
            "https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
            "radar/radar_base_reflectivity_time/ImageServer"
        )
        ck = mrms_base + ":time_extent"
        cached = self.cache.get(ck)
        if isinstance(cached, tuple):
            return cached  # type: ignore[return-value]
        try:
            meta = self.s.get(mrms_base, params={"f": "pjson"}, timeout=self.timeout)
            meta.raise_for_status()
            mj = meta.json()
            te = ((mj or {}).get("timeInfo") or {}).get("timeExtent") or []
            if isinstance(te, list) and len(te) >= 2:
                t0, t1 = int(te[0]), int(te[1])
                out = (t0, t1)
                self.cache.set(ck, out, 180)
                return out
        except Exception as e:
            dbg(f"RADAR MRMS time-extent lookup failed: {e}")
        return None, None

    def _fetch_mrms_png(
        self,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
        timestamp_ms: Optional[int] = None,
    ) -> Optional[bytes]:
        """Fetch one MRMS base-reflectivity PNG for the given bbox/time."""
        minlon, minlat, maxlon, maxlat = bbox4326
        mrms_base = (
            "https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
            "radar/radar_base_reflectivity_time/ImageServer"
        )
        params: Dict[str, str] = {
            "bbox": f"{minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}",
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{width},{height}",
            "format": "png32",
            "transparent": "true",
            "adjustAspectRatio": "false",
            "f": "image",
        }
        if timestamp_ms is not None:
            params["time"] = str(timestamp_ms)

        for ep in (mrms_base + "/exportImage", mrms_base + "/export"):
            try:
                r = self.s.get(ep, params=params, timeout=self.timeout * 2)
                r.raise_for_status()
                if isinstance(r.content, (bytes, bytearray)) and r.content.startswith(
                    b"\x89PNG\r\n\x1a\n"
                ):
                    return bytes(r.content)
                dbg(
                    f"RADAR MRMS non-PNG ep={ep} "
                    f"ct={(r.headers.get('Content-Type') or '').lower()} "
                    f"bytes={len(r.content)}"
                )
            except Exception as e:
                dbg(f"RADAR MRMS fetch failed ep={ep} err={e}")
        return None

    # ------------------------------------------------------------------
    # Radar: IEM NEXRAD composite (secondary source)
    # ------------------------------------------------------------------

    def _fetch_iem_png(
        self,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> Optional[bytes]:
        """Fetch NEXRAD composite reflectivity from Iowa State IEM WMS.

        IEM uses the standard NWS reflectivity color table, making it
        compatible with our NWS palette pixel-matching.
        """
        minlon, minlat, maxlon, maxlat = bbox4326
        try:
            r = self.s.get(
                "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0r.cgi",
                params={
                    "service": "WMS",
                    "version": "1.1.1",
                    "request": "GetMap",
                    "layers": "nexrad-n0r",
                    "styles": "",
                    "srs": "EPSG:4326",
                    "bbox": f"{minlon},{minlat},{maxlon},{maxlat}",
                    "width": str(width),
                    "height": str(height),
                    "format": "image/png",
                    "transparent": "true",
                },
                timeout=self.timeout * 2,
            )
            r.raise_for_status()
            if r.content.startswith(b"\x89PNG\r\n\x1a\n"):
                return bytes(r.content)
        except Exception as e:
            dbg(f"RADAR IEM fetch failed: {e}")
        return None

    # ------------------------------------------------------------------
    # Radar: Station WMS fallback (tertiary source)
    # ------------------------------------------------------------------

    def _fetch_station_wms_png(
        self,
        radar_id: str,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> Optional[bytes]:
        """Fetch base reflectivity from NWS station OpenGeoServer WMS."""
        minlon, minlat, maxlon, maxlat = bbox4326
        rid = (radar_id or "").strip()
        if not rid:
            return None
        rid_l = rid.lower()
        rid_u = rid.upper()
        bases = [
            f"https://opengeo.ncep.noaa.gov/geoserver/{rid_l}/ows",
            f"https://opengeo.ncep.noaa.gov/geoserver/{rid_u}/ows",
        ]

        # Discover layers via GetCapabilities
        discovered_layers: List[str] = []
        for base in bases:
            cap_url = base + "?service=WMS&version=1.1.1&request=GetCapabilities"
            try:
                r = self.s.get(cap_url, timeout=self.timeout)
                r.raise_for_status()
                names = re.findall(r"<Name>([^<]+)</Name>", r.text or "")
                if not names:
                    continue

                def _rank(name: str) -> int:
                    n = name.lower()
                    score = 0
                    if "bref" in n:
                        score += 40
                    if "reflect" in n or "_ref" in n:
                        score += 25
                    if "n0q" in n:
                        score += 20
                    if rid_l in n:
                        score += 12
                    if "qcd" in n:
                        score += 5
                    if "raw" in n:
                        score += 3
                    return score

                ranked = sorted(names, key=_rank, reverse=True)
                discovered_layers.extend(n for n in ranked if _rank(n) > 0)
            except Exception as e:
                dbg(f"RADAR capabilities failed base={base}: {e}")

        layers_try = discovered_layers + [
            f"{rid_l}:{rid_l}_bref_raw",
            f"{rid_l}:{rid_l}_bref_qcd",
            f"{rid_l}:{rid_l}_bref",
            f"{rid_u}:{rid_u}_bref_raw",
            f"{rid_u}:{rid_u}_bref_qcd",
            f"{rid_u}:{rid_u}_bref",
        ]
        seen: set = set()
        unique_layers = [l for l in layers_try if l and not (seen.add(l) or l in seen)]

        for base in bases:
            for layer in unique_layers:
                params = (
                    f"service=WMS&version=1.1.1&request=GetMap"
                    f"&layers={layer}&styles=&format=image/png&transparent=true"
                    f"&srs=EPSG:4326"
                    f"&bbox={minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}"
                    f"&width={width}&height={height}"
                )
                url = base + "?" + params
                try:
                    data = self._get_bytes(url, ttl=self.ttls.get("radar", 300), tries=2)
                    if isinstance(data, (bytes, bytearray)) and data.startswith(
                        b"\x89PNG\r\n\x1a\n"
                    ):
                        return bytes(data)
                except Exception as e:
                    dbg(f"RADAR station WMS failed base={base} layer={layer}: {e}")
        return None

    # ------------------------------------------------------------------
    # Radar: public single-frame method
    # ------------------------------------------------------------------

    def radar_wms_png(
        self,
        radar_id: str,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> Optional[bytes]:
        """Fetch the latest radar PNG.

        Priority order: MRMS → IEM composite → station WMS.
        Returns raw PNG bytes or raises RuntimeError.
        """
        # 1) MRMS (best quality, near real-time national coverage)
        latest_ms = self._mrms_latest_time()
        png = self._fetch_mrms_png(bbox4326, width, height, latest_ms)
        if png:
            return png
        dbg("RADAR MRMS failed, trying IEM")

        # 2) Iowa State IEM NEXRAD composite
        png = self._fetch_iem_png(bbox4326, width, height)
        if png:
            return png
        dbg("RADAR IEM failed, trying station WMS")

        # 3) Station-specific WMS
        png = self._fetch_station_wms_png(radar_id, bbox4326, width, height)
        if png:
            return png

        raise RuntimeError("all radar sources failed (MRMS, IEM, station WMS)")

    # ------------------------------------------------------------------
    # Radar: animation frames
    # ------------------------------------------------------------------

    def radar_frames_png(
        self,
        radar_id: str,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
        n_frames: int = 4,
        step_minutes: int = 5,
    ) -> List[Tuple[bytes, int]]:
        """Fetch multiple MRMS radar frames for animation.

        Returns a list of (png_bytes, timestamp_ms) sorted oldest→newest.
        Falls back to a single IEM/station frame if MRMS time series is
        unavailable.
        """
        t_start, t_end = self._mrms_time_extent()

        if t_end is None:
            t_end = int(time.time() * 1000)
        if t_start is None:
            t_start = t_end - n_frames * step_minutes * 60 * 1000

        step_ms = step_minutes * 60 * 1000
        # Generate timestamps spaced step_ms apart ending at t_end
        timestamps = [t_end - (n_frames - 1 - i) * step_ms for i in range(n_frames)]
        # Clamp to available range
        timestamps = [max(t_start, min(t_end, t)) for t in timestamps]
        timestamps = sorted(set(timestamps))

        frames: List[Tuple[bytes, int]] = []
        for ts_ms in timestamps:
            # Use a longer timeout for animation frames (parallel-ish load)
            png = self._fetch_mrms_png(bbox4326, width, height, ts_ms)
            if png:
                frames.append((png, ts_ms))
            else:
                dbg(f"RADAR animation frame missing ts={ts_ms}")

        if not frames:
            # Fallback: single latest frame from any source
            try:
                png = self.radar_wms_png(radar_id, bbox4326, width, height)
                if png:
                    frames.append((png, t_end))
            except Exception as e:
                dbg(f"RADAR fallback single frame failed: {e}")

        return frames

    # ------------------------------------------------------------------
    # State/county boundaries
    # ------------------------------------------------------------------

    def state_lines_png(
        self, bbox4326: Tuple[float, float, float, float], width: int, height: int
    ) -> Tuple[Optional[bytes], Optional[Tuple[float, float, float, float]]]:
        minlon, minlat, maxlon, maxlat = bbox4326
        base = (
            "https://mapservices.weather.noaa.gov/static/rest/services/"
            "nws_reference_maps/nws_reference_map/MapServer/export"
        )
        params_common = {
            "bbox": f"{minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}",
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{width},{height}",
            "format": "png32",
            "transparent": "true",
            "adjustAspectRatio": "false",
            "layers": "show:3",
        }
        # Try JSON metadata path first (gives us the actual output bbox)
        try:
            meta = self.s.get(
                base, params={**params_common, "f": "pjson"}, timeout=self.timeout
            )
            meta.raise_for_status()
            mj = meta.json()
            href = mj.get("href")
            ext = mj.get("extent") or {}
            out_bbox: Optional[Tuple[float, float, float, float]] = None
            xmin, ymin, xmax, ymax = (
                ext.get("xmin"), ext.get("ymin"), ext.get("xmax"), ext.get("ymax")
            )
            if all(isinstance(v, (int, float)) for v in [xmin, ymin, xmax, ymax]):
                out_bbox = (float(xmin), float(ymin), float(xmax), float(ymax))
            if isinstance(href, str) and href:
                r = self.s.get(href, timeout=self.timeout)
                r.raise_for_status()
                if r.content.startswith(b"\x89PNG\r\n\x1a\n"):
                    return bytes(r.content), out_bbox
        except Exception as e:
            dbg(f"state_lines pjson path failed: {e}")

        # Direct image fallback
        try:
            r = self.s.get(
                base, params={**params_common, "f": "image"}, timeout=self.timeout
            )
            r.raise_for_status()
            if r.content.startswith(b"\x89PNG\r\n\x1a\n"):
                return bytes(r.content), None
        except Exception as e:
            dbg(f"state_lines image path failed: {e}")
        return None, None

    def state_bbox(
        self, state_code: str
    ) -> Optional[Tuple[float, float, float, float]]:
        st = (state_code or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", st):
            return None
        ck = f"state_bbox:{st}"
        cached = self.cache.get(ck)
        if cached is not None:
            return cached  # type: ignore[return-value]

        layer_url = (
            "https://mapservices.weather.noaa.gov/static/rest/services/"
            "nws_reference_maps/nws_reference_map/MapServer/3"
        )
        try:
            meta = self.s.get(layer_url, params={"f": "pjson"}, timeout=self.timeout)
            meta.raise_for_status()
            mj = meta.json()
            fields = [
                str((f or {}).get("name") or "").upper()
                for f in ((mj or {}).get("fields") or [])
            ]
        except Exception:
            fields = []

        candidates = [
            f for f in ["STUSPS", "STATE_ABBR", "USPS", "ABBREV", "STATE"]
            if f in fields
        ] or ["STUSPS", "STATE"]

        for fn in candidates:
            try:
                r = self.s.get(
                    layer_url + "/query",
                    params={
                        "where": f"{fn}='{st}'",
                        "returnExtentOnly": "true",
                        "outSR": "4326",
                        "f": "pjson",
                    },
                    timeout=self.timeout,
                )
                r.raise_for_status()
                ext = r.json().get("extent") or {}
                xmin, ymin, xmax, ymax = (
                    ext.get("xmin"), ext.get("ymin"),
                    ext.get("xmax"), ext.get("ymax"),
                )
                if all(isinstance(v, (int, float)) for v in [xmin, ymin, xmax, ymax]):
                    out = (float(xmin), float(ymin), float(xmax), float(ymax))
                    self.cache.set(ck, out, 86400)
                    return out
            except Exception as e:
                dbg(f"state_bbox query failed field={fn} st={st}: {e}")

        self.cache.set(ck, None, 900)
        return None

    def state_lines_features(
        self,
        bbox4326: Tuple[float, float, float, float],
        state_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        minlon, minlat, maxlon, maxlat = bbox4326
        layer_url = (
            "https://mapservices.weather.noaa.gov/static/rest/services/"
            "nws_reference_maps/nws_reference_map/MapServer/3"
        )
        params = {
            "where": "1=1",
            "geometry": f"{minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "true",
            "outSR": "4326",
            "outFields": "*",
            "f": "pjson",
        }
        try:
            r = self.s.get(layer_url + "/query", params=params, timeout=self.timeout)
            r.raise_for_status()
            feats = (r.json() or {}).get("features") or []
            if not isinstance(feats, list):
                return []
            if state_code and re.fullmatch(r"[A-Za-z]{2}", state_code):
                st = state_code.upper()
                filtered = [
                    f for f in feats
                    if st in [
                        str(v).upper()
                        for v in ((f or {}).get("attributes") or {}).values()
                        if isinstance(v, str)
                    ]
                ]
                if filtered:
                    return filtered
            return feats
        except Exception as e:
            dbg(f"state_lines_features failed: {e}")
            return []
