#!/usr/bin/env python3
"""
NWS Weather TUI — Radar PNG decoding to terminal cell grids.
"""

from __future__ import annotations

import io
from typing import List, Optional, Tuple

from radar_palette import NWS_RADAR_PALETTE

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

# NWS radar pixel-matching threshold: max squared RGB distance to accept a match.
_NWS_RADAR_MATCH_THRESHOLD = 8000

# Pre-build the RGB lookup table for fast pixel matching.
_NWS_RADAR_RGB: Tuple[Tuple[int, int, int], ...] = tuple(
    (r, g, b) for r, g, b, *_ in NWS_RADAR_PALETTE
)

# Each cell: (character, fg_nws_idx, bg_nws_idx)
RadarCell = Tuple[str, int, int]


def _pixel_to_nws_idx(r: int, g: int, b: int, a: int) -> int:
    """Map a radar PNG pixel to NWS palette index.

    Returns 0 for transparent/no-data, or 1..N for the closest NWS color.
    The returned index is 1-based into NWS_RADAR_PALETTE.
    """
    if a < 10:
        return 0
    vmax = max(r, g, b)
    vmin = min(r, g, b)
    if vmax - vmin < 15 and vmax < 60:
        return 0
    best_dist = _NWS_RADAR_MATCH_THRESHOLD
    best_idx = 0
    for i, (cr, cg, cb) in enumerate(_NWS_RADAR_RGB):
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_dist:
            best_dist = d
            best_idx = i + 1
    return best_idx


def png_to_halfblock_radar(
    png_bytes: bytes, cols: int, rows: int
) -> List[List[RadarCell]]:
    """Convert a radar PNG to a halfblock cell grid for 256-color rendering.

    The image is scaled to cols x (rows*2) so each terminal row represents
    two image rows rendered as upper/lower half-block characters.
    """
    if Image is None:
        return []
    cols = max(1, cols)
    rows = max(1, rows)
    img_h = rows * 2

    _resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    with Image.open(io.BytesIO(png_bytes)) as im:
        rgba = im.convert("RGBA")
        small = rgba.resize((cols, img_h), _resample)
        pixels = list(small.getdata())

    result: List[List[RadarCell]] = []
    for ty in range(rows):
        row: List[RadarCell] = []
        base_top = (ty * 2) * cols
        base_bot = (ty * 2 + 1) * cols
        for x in range(cols):
            r0, g0, b0, a0 = pixels[base_top + x]
            r1, g1, b1, a1 = pixels[base_bot + x]
            top = _pixel_to_nws_idx(r0, g0, b0, a0)
            bot = _pixel_to_nws_idx(r1, g1, b1, a1)
            if top == 0 and bot == 0:
                row.append((" ", 0, 0))
            elif top != 0 and bot == 0:
                row.append(("\u2580", top, 0))
            elif top == 0 and bot != 0:
                row.append(("\u2584", bot, 0))
            else:
                row.append(("\u2580", top, bot))
        result.append(row)
    return result


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
    """Convert radar PNG to ASCII art with precipitation kind classification.

    Returns (ascii_lines, kind_lines) where kind chars are R/S/I/space.
    """
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
        pixel_data = list(small.getdata())

    raw_scores: List[float] = []
    for r, g, b, a in pixel_data:
        if a < 2:
            raw_scores.append(0.0)
        else:
            vmax = max(r, g, b)
            vmin = min(r, g, b)
            sat = vmax - vmin
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            raw_scores.append(0.72 * sat + 0.28 * (255.0 - lum))

    active = [v for v in raw_scores if v >= 14.0]
    if active:
        active_sorted = sorted(active)
        peak = active_sorted[min(len(active_sorted) - 1, int(0.95 * len(active_sorted)))]
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
