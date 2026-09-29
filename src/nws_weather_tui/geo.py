#!/usr/bin/env python3
"""
NWS Weather TUI — Geographic math utilities.
"""

from __future__ import annotations

import math
from typing import Tuple


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def bbox_around(
    lat: float, lon: float, radius_km: float
) -> Tuple[float, float, float, float]:
    dlat = radius_km / 111.32
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    dlon = radius_km / (111.32 * cos_lat)
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def expand_bbox_km(
    bbox4326: Tuple[float, float, float, float], pad_km: float
) -> Tuple[float, float, float, float]:
    minlon, minlat, maxlon, maxlat = bbox4326
    pad_km = max(0.0, float(pad_km))
    if pad_km <= 0:
        return bbox4326
    center_lat = (minlat + maxlat) / 2.0
    dlat = pad_km / 111.32
    cos_lat = max(0.1, abs(math.cos(math.radians(center_lat))))
    dlon = pad_km / (111.32 * cos_lat)
    return (minlon - dlon, minlat - dlat, maxlon + dlon, maxlat + dlat)


def project_to_grid(
    lon: float,
    lat: float,
    bbox4326: Tuple[float, float, float, float],
    cols: int,
    rows: int,
) -> Tuple[int, int]:
    minlon, minlat, maxlon, maxlat = bbox4326
    lon_span = max(1e-9, maxlon - minlon)
    lat_span = max(1e-9, maxlat - minlat)
    x = int(round((lon - minlon) / lon_span * (cols - 1)))
    y = int(round((maxlat - lat) / lat_span * (rows - 1)))
    return clamp(x, 0, cols - 1), clamp(y, 0, rows - 1)
