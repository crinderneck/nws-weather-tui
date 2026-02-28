#!/usr/bin/env python3
"""
NWS Weather TUI — NWS API client with retries.
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
    def __init__(self, user_agent: str, timeout: int, ttls: Dict[str, int]):
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

    def _get_bytes(
        self, url: str, ttl: int, tries: int = 3, backoff: float = 0.6
    ) -> Optional[bytes]:
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        last_err: Optional[Exception] = None
        for i in range(tries):
            try:
                r = self.s.get(url, timeout=self.timeout)
                ct = (r.headers.get("Content-Type") or "").lower()

                if "vnd.ogc.se_xml" in ct or "xml" in ct and "image" not in ct:
                    dbg(f"RADAR BAD CT={ct} url={url} status={r.status_code}")
                    dbg("RADAR BODY:\n" + r.text[:2000])
                    return None
                r.raise_for_status()
                data = r.content
                self.cache.set(url, data, ttl)
                return data
            except Exception as e:
                last_err = e
                time.sleep(backoff * (2**i))
        raise last_err or RuntimeError("request failed")

    def _get_json(
        self, url: str, ttl: int, tries: int = 3, backoff: float = 0.6
    ) -> Dict[str, Any]:
        cached = self.cache.get(url)
        if cached is not None:
            return cached
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
                time.sleep(backoff * (2**i))
        raise last_err or RuntimeError("request failed")

    def points(self, lat: float, lon: float) -> Dict[str, Any]:
        url = f"{BASE}/points/{lat:.4f},{lon:.4f}"
        return self._get_json(url, ttl=self.ttls["points"])

    def stations(self, stations_url: str) -> Dict[str, Any]:
        return self._get_json(stations_url, ttl=self.ttls["stations"])

    def latest_observation(self, station_id: str) -> Dict[str, Any]:
        url = f"{BASE}/stations/{station_id}/observations/latest"
        return self._get_json(url, ttl=self.ttls["observation"])

    def forecast(self, forecast_url: str, units: str) -> Dict[str, Any]:
        url = forecast_url + ("&" if "?" in forecast_url else "?") + f"units={units}"
        return self._get_json(url, ttl=self.ttls["forecast"])

    def forecast_hourly(self, hourly_url: str, units: str) -> Dict[str, Any]:
        url = hourly_url + ("&" if "?" in hourly_url else "?") + f"units={units}"
        return self._get_json(url, ttl=self.ttls["forecast_hourly"])

    def alerts(self, lat: float, lon: float) -> Dict[str, Any]:
        url = f"{BASE}/alerts/active?point={lat:.4f},{lon:.4f}"
        return self._get_json(url, ttl=self.ttls["alerts"])

    def geocode_us(self, query: str) -> Optional[Tuple[str, float, float]]:
        from constants import ZIP_RE

        q = (query or "").strip()
        if not q:
            return None
        ck = f"geocode:{q.lower()}"
        cached = self.cache.get(ck)
        if cached is not None:
            return cached

        if ZIP_RE.fullmatch(q):
            zip5 = q[:5]
            r = self.s.get(f"https://api.zippopotam.us/us/{zip5}", timeout=self.timeout)
            if r.ok:
                data = r.json()
                places = (data or {}).get("places") or []
                if places:
                    p0 = places[0] or {}
                    lat_s = p0.get("latitude")
                    lon_s = p0.get("longitude")
                    try:
                        lat = float(lat_s)
                        lon = float(lon_s)
                        place = str(p0.get("place name") or "").strip()
                        state = str(
                            p0.get("state abbreviation") or p0.get("state") or ""
                        ).strip()
                        name = f"{zip5} {place}, {state}".strip().strip(",")
                        out = (name, lat, lon)
                        self.cache.set(ck, out, 86400)
                        return out
                    except Exception:
                        pass

        for candidate in (q, f"{q}, USA"):
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
            data = r.json()
            matches = ((data or {}).get("result") or {}).get("addressMatches") or []
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

        self.cache.set(ck, None, 600)
        return None

    def radar_wms_png(
        self,
        radar_id: str,
        bbox4326: Tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> Optional[bytes]:
        minlon, minlat, maxlon, maxlat = bbox4326

        mrms_base = "https://mapservices.weather.noaa.gov/eventdriven/rest/services/radar/radar_base_reflectivity_time/ImageServer"
        mrms_endpoints = [mrms_base + "/exportImage", mrms_base + "/export"]
        latest_ms: Optional[int] = None
        try:
            ck = mrms_base + ":latest_time"
            cached_latest = self.cache.get(ck)
            if isinstance(cached_latest, int):
                latest_ms = cached_latest
            else:
                meta = self.s.get(
                    mrms_base, params={"f": "pjson"}, timeout=self.timeout
                )
                meta.raise_for_status()
                mj = meta.json()
                te = ((mj or {}).get("timeInfo") or {}).get("timeExtent") or []
                if (
                    isinstance(te, list)
                    and len(te) >= 2
                    and isinstance(te[1], (int, float))
                ):
                    latest_ms = int(te[1])
                    self.cache.set(ck, latest_ms, 180)
        except Exception as e:
            dbg(f"RADAR MRMS latest-time lookup failed: {e}")

        mrms_params = {
            "bbox": f"{minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}",
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{width},{height}",
            "format": "png32",
            "transparent": "true",
            "adjustAspectRatio": "false",
            "f": "image",
        }
        if latest_ms is not None:
            mrms_params["time"] = str(latest_ms)
            dbg(f"RADAR MRMS using latest time={latest_ms}")
        last_mrms_err: Optional[Exception] = None
        for ep in mrms_endpoints:
            try:
                r = self.s.get(ep, params=mrms_params, timeout=self.timeout)
                r.raise_for_status()
                data = r.content
                if isinstance(data, (bytes, bytearray)) and data.startswith(
                    b"\x89PNG\r\n\x1a\n"
                ):
                    return data
                dbg(
                    f"RADAR MRMS NON-PNG endpoint={ep} ct={(r.headers.get('Content-Type') or '').lower()} bytes={len(data)}"
                )
            except Exception as e:
                last_mrms_err = e
                dbg(f"RADAR MRMS fetch failed endpoint={ep} err={e}")

        if last_mrms_err:
            dbg(f"RADAR falling back to station WMS due to MRMS error: {last_mrms_err}")

        rid = (radar_id or "").strip()
        if not rid:
            raise RuntimeError("radar station missing and MRMS source unavailable")
        rid_l = rid.lower()
        rid_u = rid.upper()
        bases = [
            f"https://opengeo.ncep.noaa.gov/geoserver/{rid_l}/ows",
            f"https://opengeo.ncep.noaa.gov/geoserver/{rid_u}/ows",
        ]

        discovered_layers: List[str] = []
        for base in bases:
            cap_url = base + "?service=WMS&version=1.1.1&request=GetCapabilities"
            try:
                r = self.s.get(cap_url, timeout=self.timeout)
                r.raise_for_status()
                names = re.findall(r"<Name>([^<]+)</Name>", r.text or "")
                if not names:
                    continue

                def rank(name: str) -> int:
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

                ranked = sorted(names, key=rank, reverse=True)
                discovered_layers.extend([n for n in ranked if rank(n) > 0])
            except Exception as e:
                dbg(f"RADAR capabilities fetch failed base={base} err={e}")

        layers_try = discovered_layers + [
            f"{rid_l}:{rid_l}_bref_raw",
            f"{rid_l}:{rid_l}_bref_qcd",
            f"{rid_l}:{rid_l}_bref",
            f"{rid_u}:{rid_u}_bref_raw",
            f"{rid_u}:{rid_u}_bref_qcd",
            f"{rid_u}:{rid_u}_bref",
            f"{rid_l}_bref_raw",
            f"{rid_l}_bref_qcd",
            f"{rid_l}_bref",
            f"{rid_u}_bref_raw",
            f"{rid_u}_bref_qcd",
            f"{rid_u}_bref",
        ]

        seen: set[str] = set()
        layers_ordered: List[str] = []
        for layer in layers_try:
            if layer and layer not in seen:
                seen.add(layer)
                layers_ordered.append(layer)

        last_err: Optional[Exception] = None
        for base in bases:
            for layer in layers_ordered:
                params = (
                    f"service=WMS&version=1.1.1&request=GetMap"
                    f"&layers={layer}"
                    f"&styles="
                    f"&format=image/png&transparent=true"
                    f"&srs=EPSG:4326"
                    f"&bbox={minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}"
                    f"&width={width}&height={height}"
                )
                url = base + "?" + params
                try:
                    data = self._get_bytes(
                        url, ttl=self.ttls.get("radar", 300), tries=2, backoff=0.8
                    )
                    if isinstance(data, (bytes, bytearray)) and data.startswith(
                        b"\x89PNG\r\n\x1a\n"
                    ):
                        return data
                    dbg(
                        f"RADAR NON-PNG payload base={base} layer={layer} bytes={len(data) if data else 0}"
                    )
                except Exception as e:
                    last_err = e
        if last_err is None:
            raise RuntimeError("radar WMS returned non-image data for all layers")
        raise last_err or RuntimeError("radar fetch failed")

    def state_lines_png(
        self, bbox4326: Tuple[float, float, float, float], width: int, height: int
    ) -> Tuple[Optional[bytes], Optional[Tuple[float, float, float, float]]]:
        minlon, minlat, maxlon, maxlat = bbox4326
        base = "https://mapservices.weather.noaa.gov/static/rest/services/nws_reference_maps/nws_reference_map/MapServer/export"
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
        try:
            meta = self.s.get(
                base, params={**params_common, "f": "pjson"}, timeout=self.timeout
            )
            meta.raise_for_status()
            mj = meta.json()
            href = mj.get("href")
            ext = mj.get("extent") or {}
            out_bbox: Optional[Tuple[float, float, float, float]] = None
            xmin = ext.get("xmin")
            ymin = ext.get("ymin")
            xmax = ext.get("xmax")
            ymax = ext.get("ymax")
            if all(isinstance(v, (int, float)) for v in [xmin, ymin, xmax, ymax]):
                out_bbox = (float(xmin), float(ymin), float(xmax), float(ymax))
            if isinstance(href, str) and href:
                r = self.s.get(href, timeout=self.timeout)
                r.raise_for_status()
                data = r.content
                if isinstance(data, (bytes, bytearray)) and data.startswith(
                    b"\x89PNG\r\n\x1a\n"
                ):
                    return data, out_bbox
        except Exception as e:
            dbg(f"state_lines pjson export path failed: {e}")

        r = self.s.get(
            base, params={**params_common, "f": "image"}, timeout=self.timeout
        )
        r.raise_for_status()
        data = r.content
        if not isinstance(data, (bytes, bytearray)) or not data.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            raise RuntimeError("state-lines export returned non-image data")
        return data, None

    def state_bbox(
        self, state_code: str
    ) -> Optional[Tuple[float, float, float, float]]:
        st = (state_code or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", st):
            return None
        ck = f"state_bbox:{st}"
        cached = self.cache.get(ck)
        if cached is not None:
            return cached

        layer_url = "https://mapservices.weather.noaa.gov/static/rest/services/nws_reference_maps/nws_reference_map/MapServer/3"
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
            f
            for f in ["STUSPS", "STATE_ABBR", "USPS", "ABBREV", "STATE"]
            if f in fields
        ] or ["STUSPS", "STATE"]
        last_err: Optional[Exception] = None
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
                qj = r.json()
                ext = qj.get("extent") or {}
                xmin = ext.get("xmin")
                ymin = ext.get("ymin")
                xmax = ext.get("xmax")
                ymax = ext.get("ymax")
                if all(isinstance(v, (int, float)) for v in [xmin, ymin, xmax, ymax]):
                    out = (float(xmin), float(ymin), float(xmax), float(ymax))
                    self.cache.set(ck, out, 86400)
                    return out
            except Exception as e:
                last_err = e
        if last_err:
            dbg(f"state_bbox lookup failed for {st}: {last_err}")
        self.cache.set(ck, None, 900)
        return None

    def state_lines_features(
        self,
        bbox4326: Tuple[float, float, float, float],
        state_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        minlon, minlat, maxlon, maxlat = bbox4326
        layer_url = "https://mapservices.weather.noaa.gov/static/rest/services/nws_reference_maps/nws_reference_map/MapServer/3"
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
                out: List[Dict[str, Any]] = []
                for f in feats:
                    a = (f or {}).get("attributes") or {}
                    vals = [str(v).upper() for v in a.values() if isinstance(v, str)]
                    if st in vals:
                        out.append(f)
                if out:
                    return out
            return feats
        except Exception as e:
            dbg(f"state_lines_features query failed: {e}")
            return []
