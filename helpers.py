#!/usr/bin/env python3
"""
NWS Weather TUI — Helper functions and utilities.
"""

from __future__ import annotations

import datetime as dt
import io
import math
import re
import textwrap
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from constants import (
    DEBUG_LOG_PATH,
    MAJOR_CITIES,
    ensure_dir,
)

_FIRST_NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)")

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from astral import LocationInfo
    from astral.sun import sun
except Exception:
    LocationInfo = None
    sun = None


def get_sunrise_sunset(
    lat: float, lon: float, date: dt.date
) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    if sun is None or LocationInfo is None:
        return None, None
    try:
        loc = LocationInfo(latitude=lat, longitude=lon)
        s = sun(loc.observer, date=date, tzinfo=loc.timezone)
        return s["sunrise"], s["sunset"]
    except Exception:
        return None, None


def dbg(msg: str) -> None:
    try:
        ensure_dir(DEBUG_LOG_PATH.replace("debug.log", ""))
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass


def parse_iso(ts: Optional[str]) -> Optional[dt.datetime]:
    if not ts:
        return None
    try:
        ts = ts.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(ts)
    except Exception:
        return None


def local_tzinfo() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def to_local(t: Optional[object]) -> Optional[dt.datetime]:
    if t is None:
        return None
    if isinstance(t, str):
        t = parse_iso(t)
        if t is None:
            return None
    if not isinstance(t, dt.datetime):
        return None
    ltz = local_tzinfo()
    if t.tzinfo is None:
        t = t.replace(tzinfo=ltz)
    return t.astimezone(ltz)


def fmt_time(t: Optional[object], use_24h: bool, with_date: bool = False) -> str:
    tt = to_local(t)
    if not tt:
        return "—"
    if with_date:
        return (
            tt.strftime("%Y-%m-%d %H:%M")
            if use_24h
            else tt.strftime("%Y-%m-%d %I:%M %p").lstrip("0")
        )
    return (
        tt.strftime("%H:%M") if use_24h else tt.strftime("%I:%M%p").lstrip("0").lower()
    )


@lru_cache(maxsize=2048)
def _wrap_lines_cached(text: str, width: int) -> Tuple[str, ...]:
    return tuple(
        textwrap.wrap(
            text, width=width, replace_whitespace=False, drop_whitespace=False
        )
    )


def wrap_lines(text: str, width: int) -> Tuple[str, ...]:
    if width <= 1:
        return (text,)
    return _wrap_lines_cached(text, width)


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def safe_addstr(win, y: int, x: int, s: str, attr: int = 0) -> None:
    try:
        win.addstr(y, x, s, attr)
    except Exception:
        pass


def mps_to_mph(mps: Optional[float]) -> Optional[float]:
    return None if mps is None else mps * 2.2369362920544


def c_to_f(c: Optional[float]) -> Optional[float]:
    return None if c is None else c * 9.0 / 5.0 + 32.0


def pa_to_inhg(pa: Optional[float]) -> Optional[float]:
    return None if pa is None else pa / 3386.389


def m_to_mi(m: Optional[float]) -> Optional[float]:
    return None if m is None else m / 1609.344


def fmt_num(x: Optional[float], digits: int = 0) -> str:
    if x is None:
        return "—"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "—"
    return f"{x:.{digits}f}"


def parse_first_number(s: str) -> Optional[float]:
    if not s:
        return None
    m = _FIRST_NUMBER_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


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


def _classify_precip_kind(r: int, g: int, b: int) -> str:
    vmax = max(r, g, b)
    vmin = min(r, g, b)
    sat = vmax - vmin
    if sat < 14:
        return "?"
    if g > r and g >= b:
        return "R"
    if (b >= g and b > r) or (b > 130 and g > 90 and r < 120):
        return "S"
    if r > 120 and b > 120:
        return "I"
    return "?"


def png_to_ascii(
    png_bytes: bytes, cols: int, rows: int, ramp: str
) -> Tuple[List[str], List[str]]:
    if Image is None:
        return (["(install pillow to render radar map)"], [])
    cols = max(1, cols)
    rows = max(1, rows)
    chars = ramp or " .:-=+*#%@"
    if len(chars) < 2:
        chars = " .:-=+*#%@"

    _resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    with Image.open(io.BytesIO(png_bytes)) as im:
        rgba = im.convert("RGBA")
        small = rgba.resize((cols, rows), _resample)
        # Read all pixels at once inside the context to avoid stale access
        pixel_data = list(small.getdata())  # flat (r,g,b,a) list, row-major

    # Single pass: compute scores and store RGBA
    raw_scores: List[float] = []
    for r, g, b, a in pixel_data:
        if a < 2:
            raw_scores.append(0.0)
        else:
            vmax = max(r, g, b)
            vmin = min(r, g, b)
            sat = vmax - vmin
            lum = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
            raw_scores.append((0.72 * sat) + (0.28 * (255.0 - lum)))

    active = [v for v in raw_scores if v >= 14.0]
    if active:
        active_sorted = sorted(active)
        peak = active_sorted[
            min(len(active_sorted) - 1, int(0.95 * len(active_sorted)))
        ]
    else:
        peak = 255.0
    norm_den = max(20.0, min(255.0, peak))

    lines: List[str] = []
    kind_lines: List[str] = []
    max_idx = len(chars) - 1
    for y in range(rows):
        row_chars: List[str] = []
        row_kinds: List[str] = []
        base = y * cols
        for x in range(cols):
            r, g, b, a = pixel_data[base + x]
            score = raw_scores[base + x]
            if score < 14:
                row_chars.append(" ")
                row_kinds.append(" ")
                continue
            t = min(1.0, score / norm_den)
            idx = max(1, min(max_idx, 1 + int(t * (max_idx - 1) + 0.5)))
            row_chars.append(chars[idx])
            row_kinds.append(_classify_precip_kind(r, g, b) if a >= 2 else " ")
        lines.append("".join(row_chars))
        kind_lines.append("".join(row_kinds))

    return (lines, kind_lines)


def png_to_line_overlay(
    png_bytes: bytes,
    cols: int,
    rows: int,
    mark: str = "|",
    src_bbox: Optional[Tuple[float, float, float, float]] = None,
    dst_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[str]:
    """Convert a PNG border/line image to an ASCII overlay grid.

    If src_bbox and dst_bbox are provided and differ, the source image is
    cropped/re-projected so the overlay aligns with dst_bbox's coordinate space.
    """
    if Image is None:
        return []
    cols = max(1, cols)
    rows = max(1, rows)
    _nearest = getattr(getattr(Image, "Resampling", Image), "NEAREST")
    with Image.open(io.BytesIO(png_bytes)) as im:
        rgba = im.convert("RGBA")
        img_w, img_h = rgba.size

        # Re-project source image to dst_bbox when extents differ
        if src_bbox is not None and dst_bbox is not None and src_bbox != dst_bbox:
            sx_min, sy_min, sx_max, sy_max = src_bbox
            dx_min, dy_min, dx_max, dy_max = dst_bbox
            sx_span = max(1e-9, sx_max - sx_min)
            sy_span = max(1e-9, sy_max - sy_min)
            # Image y=0 is north (sy_max), y=img_h is south (sy_min)
            left = (dx_min - sx_min) / sx_span * img_w
            right = (dx_max - sx_min) / sx_span * img_w
            top = (sy_max - dy_max) / sy_span * img_h
            bottom = (sy_max - dy_min) / sy_span * img_h
            crop_l = max(0, int(left))
            crop_t = max(0, int(top))
            crop_r = min(img_w, int(math.ceil(right)))
            crop_b = min(img_h, int(math.ceil(bottom)))
            if crop_r > crop_l and crop_b > crop_t:
                rgba = rgba.crop((crop_l, crop_t, crop_r, crop_b))

        small = rgba.resize((cols, rows), _nearest)
        pixel_data = list(small.getdata())

    grid: List[List[bool]] = []
    for y in range(rows):
        base = y * cols
        row: List[bool] = [pixel_data[base + x][3] >= 36 for x in range(cols)]
        grid.append(row)

    stitched = [r[:] for r in grid]
    for y in range(1, rows - 1):
        for x in range(1, cols - 1):
            if grid[y][x]:
                continue
            if (
                grid[y][x - 1]
                and grid[y][x + 1]
                and not grid[y - 1][x]
                and not grid[y + 1][x]
            ):
                stitched[y][x] = True
                continue
            if (
                grid[y - 1][x]
                and grid[y + 1][x]
                and not grid[y][x - 1]
                and not grid[y][x + 1]
            ):
                stitched[y][x] = True

    lines: List[str] = []
    for y in range(rows):
        row = [mark if stitched[y][x] else " " for x in range(cols)]
        lines.append("".join(row))
    return lines


def _project_to_grid(
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


def _draw_segment(
    grid: List[List[str]], x0: int, y0: int, x1: int, y1: int, mark: str
) -> None:
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        if 0 <= y0 < len(grid) and 0 <= x0 < len(grid[0]):
            grid[y0][x0] = mark
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def vector_lines_overlay(
    features: List[Dict[str, Any]],
    bbox4326: Tuple[float, float, float, float],
    cols: int,
    rows: int,
    mark: str = "|",
) -> List[str]:
    cols = max(1, cols)
    rows = max(1, rows)
    grid: List[List[str]] = [[" "] * cols for _ in range(rows)]
    for f in features:
        g = (f or {}).get("geometry") or {}
        seqs = []
        if isinstance(g.get("rings"), list):
            seqs.extend(g.get("rings"))
        if isinstance(g.get("paths"), list):
            seqs.extend(g.get("paths"))
        for seq in seqs:
            if not isinstance(seq, list) or len(seq) < 2:
                continue
            prev: Optional[Tuple[int, int]] = None
            for pt in seq:
                if not isinstance(pt, list) or len(pt) < 2:
                    continue
                lon = pt[0]
                lat = pt[1]
                if not isinstance(lon, (int, float)) or not isinstance(
                    lat, (int, float)
                ):
                    continue
                cur = _project_to_grid(float(lon), float(lat), bbox4326, cols, rows)
                if prev is not None:
                    _draw_segment(grid, prev[0], prev[1], cur[0], cur[1], mark)
                prev = cur
    return ["".join(r).rstrip() for r in grid]


def city_overlay_and_hits_for_bbox(
    cols: int,
    rows: int,
    bbox4326: Tuple[float, float, float, float],
    max_labels: int = 20,
    here: Optional[Tuple[float, float]] = None,
) -> Tuple[List[str], Dict[Tuple[int, int], Tuple[str, float, float]]]:
    cols = max(1, cols)
    rows = max(1, rows)
    minlon, minlat, maxlon, maxlat = bbox4326
    lon_span = max(1e-9, maxlon - minlon)
    lat_span = max(1e-9, maxlat - minlat)
    grid = [[" "] * cols for _ in range(rows)]
    hit_map: Dict[Tuple[int, int], Tuple[str, float, float]] = {}

    def project(lat: float, lon: float) -> Tuple[int, int]:
        x = int(round((lon - minlon) / lon_span * (cols - 1)))
        y = int(round((maxlat - lat) / lat_span * (rows - 1)))
        return clamp(x, 0, cols - 1), clamp(y, 0, rows - 1)

    def can_place(x0: int, y0: int, text: str) -> bool:
        if y0 < 0 or y0 >= rows or x0 < 0 or x0 + len(text) > cols:
            return False
        return all(grid[y0][xx] == " " for xx in range(x0, x0 + len(text)))

    def place(x0: int, y0: int, text: str) -> None:
        for i, ch in enumerate(text):
            grid[y0][x0 + i] = ch

    if here is not None:
        hlat, hlon = here
        if minlat <= hlat <= maxlat and minlon <= hlon <= maxlon:
            hx, hy = project(hlat, hlon)
            if hy - 1 >= 0:
                grid[hy - 1][hx] = "O"
            if hy - 2 >= 0 and hx - 1 >= 0 and hx + 1 < cols:
                grid[hy - 2][hx - 1] = "/"
                grid[hy - 2][hx + 1] = "\\"
            if hy >= 0:
                grid[hy][hx] = "|"
            if hy + 1 < rows and hx - 1 >= 0 and hx + 1 < cols:
                grid[hy + 1][hx - 1] = "/"
                grid[hy + 1][hx + 1] = "\\"

    placed = 0
    for code, lat, lon in MAJOR_CITIES:
        if not (minlat <= lat <= maxlat and minlon <= lon <= maxlon):
            continue
        x, y = project(lat, lon)
        if grid[y][x] != " ":
            continue
        grid[y][x] = "@"
        hit_map[(x, y)] = (code, float(lat), float(lon))
        for lx in (x + 1, x - len(code)):
            if can_place(lx, y, code):
                place(lx, y, code)
                for xx in range(lx, lx + len(code)):
                    hit_map[(xx, y)] = (code, float(lat), float(lon))
                break
        placed += 1
        if placed >= max_labels:
            break

    return (["".join(r).rstrip() for r in grid], hit_map)
