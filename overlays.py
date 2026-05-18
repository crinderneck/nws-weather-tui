#!/usr/bin/env python3
"""
NWS Weather TUI — Map overlay rendering (state lines, city labels).
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Optional, Tuple

from cities import MAJOR_CITIES
from geo import clamp, project_to_grid

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]


def png_to_line_overlay(
    png_bytes: bytes,
    cols: int,
    rows: int,
    mark: str = "|",
    src_bbox: Optional[Tuple[float, float, float, float]] = None,
    dst_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[str]:
    """Convert a PNG border/line image to an ASCII overlay grid."""
    if Image is None:
        return []
    cols = max(1, cols)
    rows = max(1, rows)
    _nearest = getattr(getattr(Image, "Resampling", Image), "NEAREST")
    with Image.open(io.BytesIO(png_bytes)) as im:
        rgba = im.convert("RGBA")
        img_w, img_h = rgba.size

        if src_bbox is not None and dst_bbox is not None and src_bbox != dst_bbox:
            sx_min, sy_min, sx_max, sy_max = src_bbox
            dx_min, dy_min, dx_max, dy_max = dst_bbox
            sx_span = max(1e-9, sx_max - sx_min)
            sy_span = max(1e-9, sy_max - sy_min)
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
        grid.append([pixel_data[base + x][3] >= 36 for x in range(cols)])

    # Stitch 1-pixel gaps (both horizontal and vertical)
    stitched = [r[:] for r in grid]
    for y in range(1, rows - 1):
        for x in range(1, cols - 1):
            if grid[y][x]:
                continue
            if (
                grid[y][x - 1] and grid[y][x + 1]
                and not grid[y - 1][x] and not grid[y + 1][x]
            ):
                stitched[y][x] = True
            elif (
                grid[y - 1][x] and grid[y + 1][x]
                and not grid[y][x - 1] and not grid[y][x + 1]
            ):
                stitched[y][x] = True

    return ["".join(mark if stitched[y][x] else " " for x in range(cols)) for y in range(rows)]


def _draw_segment(
    grid: List[List[str]], x0: int, y0: int, x1: int, y1: int, mark: str
) -> None:
    """Bresenham line segment draw into a grid."""
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
    """Rasterise GeoJSON-style features (rings/paths) into an ASCII overlay."""
    cols = max(1, cols)
    rows = max(1, rows)
    grid: List[List[str]] = [[" "] * cols for _ in range(rows)]
    for f in features:
        g = (f or {}).get("geometry") or {}
        seqs: List[Any] = []
        if isinstance(g.get("rings"), list):
            seqs.extend(g["rings"])
        if isinstance(g.get("paths"), list):
            seqs.extend(g["paths"])
        for seq in seqs:
            if not isinstance(seq, list) or len(seq) < 2:
                continue
            prev: Optional[Tuple[int, int]] = None
            for pt in seq:
                if not isinstance(pt, list) or len(pt) < 2:
                    continue
                lon, lat = pt[0], pt[1]
                if not (isinstance(lon, (int, float)) and isinstance(lat, (int, float))):
                    continue
                cur = project_to_grid(float(lon), float(lat), bbox4326, cols, rows)
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
    """Place city labels on a character grid and return a click hit map.

    Optimized with set-based occupied cell tracking for O(1) lookups.
    """
    cols = max(1, cols)
    rows = max(1, rows)
    minlon, minlat, maxlon, maxlat = bbox4326
    lon_span = max(1e-9, maxlon - minlon)
    lat_span = max(1e-9, maxlat - minlat)
    grid = [[" "] * cols for _ in range(rows)]
    hit_map: Dict[Tuple[int, int], Tuple[str, float, float]] = {}

    occupied: set = set()

    def project(lat: float, lon: float) -> Tuple[int, int]:
        x = int(round((lon - minlon) / lon_span * (cols - 1)))
        y = int(round((maxlat - lat) / lat_span * (rows - 1)))
        return clamp(x, 0, cols - 1), clamp(y, 0, rows - 1)

    def mark_occupied(x0: int, y0: int, length: int) -> None:
        for xx in range(x0, x0 + length):
            occupied.add((xx, y0))

    def is_occupied(x0: int, y0: int, length: int) -> bool:
        if y0 < 0 or y0 >= rows or x0 < 0 or x0 + length > cols:
            return True
        for xx in range(x0, x0 + length):
            if (xx, y0) in occupied:
                return True
        return False

    def place(x0: int, y0: int, text: str) -> None:
        for i, ch in enumerate(text):
            grid[y0][x0 + i] = ch
        mark_occupied(x0, y0, len(text))

    if here is not None:
        hlat, hlon = here
        if minlat <= hlat <= maxlat and minlon <= hlon <= maxlon:
            hx, hy = project(hlat, hlon)
            if hy - 1 >= 0:
                grid[hy - 1][hx] = "O"
                occupied.add((hx, hy - 1))
            if hy >= 0:
                grid[hy][hx] = "|"
                occupied.add((hx, hy))
            if hy >= 0 and hx - 1 >= 0 and hx + 1 < cols:
                grid[hy][hx - 1] = "/"
                grid[hy][hx + 1] = "\\"
                occupied.add((hx - 1, hy))
                occupied.add((hx + 1, hy))
            if hy + 1 < rows and hx - 1 >= 0 and hx + 1 < cols:
                grid[hy + 1][hx - 1] = "/"
                grid[hy + 1][hx + 1] = "\\"
                occupied.add((hx - 1, hy + 1))
                occupied.add((hx + 1, hy + 1))

    placed = 0
    for code, lat, lon in MAJOR_CITIES:
        if placed >= max_labels:
            break
        if not (minlat <= lat <= maxlat and minlon <= lon <= maxlon):
            continue
        x, y = project(lat, lon)
        if (x, y) in occupied:
            continue
        grid[y][x] = "@"
        hit_map[(x, y)] = (code, float(lat), float(lon))
        occupied.add((x, y))
        text_len = len(code)
        for lx in (x + 1, x - text_len):
            if not is_occupied(lx, y, text_len):
                place(lx, y, code)
                for xx in range(lx, lx + text_len):
                    hit_map[(xx, y)] = (code, float(lat), float(lon))
                break
        placed += 1

    return (["".join(r) for r in grid], hit_map)
