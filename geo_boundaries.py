#!/usr/bin/env python3
"""
NWS Weather TUI — State boundary data fetching from NWS MapServer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from cache import TTLCache
from helpers import dbg

NWS_REF_MAP_BASE = (
    "https://mapservices.weather.noaa.gov/static/rest/services/"
    "nws_reference_maps/nws_reference_map/MapServer"
)


class BoundaryClient:
    def __init__(self, session, timeout: int, cache: TTLCache) -> None:
        self.s = session
        self.timeout = timeout
        self.cache = cache

    def state_lines_png(
        self, bbox4326: Tuple[float, float, float, float], width: int, height: int
    ) -> Tuple[Optional[bytes], Optional[Tuple[float, float, float, float]]]:
        minlon, minlat, maxlon, maxlat = bbox4326
        base = NWS_REF_MAP_BASE + "/export"
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

        layer_url = NWS_REF_MAP_BASE + "/3"
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
        layer_url = NWS_REF_MAP_BASE + "/3"
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
