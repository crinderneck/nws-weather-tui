#!/usr/bin/env python3
"""
NWS Weather TUI — NWS standard base reflectivity radar color palette.
"""

from __future__ import annotations

from typing import List, Tuple

# ---------------------------------------------------------------------------
# NWS Standard Base Reflectivity Color Palette
# 14 levels: 5 dBZ through 70+ dBZ.
# Each entry: (r255, g255, b255, r1000, g1000, b1000, dbz_level, label)
#   - r/g/b 255: used for pixel-to-color matching from radar PNG
#   - r/g/b 1000: used for curses.init_color (0-1000 scale)
#   - dbz_level: approximate dBZ threshold
#   - label: display label for legend
# Curses color IDs 16-29 are reserved for these entries (index 0 -> ID 16).
# ---------------------------------------------------------------------------
NWS_RADAR_PALETTE: List[Tuple[int, int, int, int, int, int, int, str]] = [
    (  0, 236, 236,    0,  925,  925,  5, " 5"),
    (  1, 159, 244,    4,  624,  957, 10, "10"),
    (  3,   0, 244,   12,    0,  957, 15, "15"),
    (  2, 255,   0,    8, 1000,    0, 20, "20"),
    (  1, 197,   1,    4,  773,    4, 25, "25"),
    (  0, 142,   0,    0,  557,    0, 30, "30"),
    (253, 248,   2,  992,  973,    8, 35, "35"),
    (229, 188,   0,  898,  737,    0, 40, "40"),
    (253, 149,   0,  992,  584,    0, 45, "45"),
    (253,   0,   0,  992,    0,    0, 50, "50"),
    (212,   0,   0,  831,    0,    0, 55, "55"),
    (188,   0,   0,  737,    0,    0, 60, "60"),
    (248,   0, 253,  973,    0,  992, 65, "65"),
    (152,  84, 198,  596,  329,  776, 70, "70+"),
]

# Number of NWS radar colors (excluding transparent=0)
N_RADAR_COLORS = len(NWS_RADAR_PALETTE)  # 14


def radar_curses_color(nws_idx: int) -> int:
    """Return curses color index for nws_idx 1..N_RADAR_COLORS."""
    return 15 + nws_idx  # maps 1->16, 2->17, ..., 14->29


def radar_single_pair(nws_idx: int) -> int:
    """Return curses pair number for a single-color radar cell (nws_idx 1..14)."""
    return 19 + nws_idx  # maps 1->20, ..., 14->33


def radar_dual_pair(fg_idx: int, bg_idx: int) -> int:
    """Return curses pair number for dual-color halfblock cell (both 1..14)."""
    return 34 + (fg_idx - 1) * N_RADAR_COLORS + (bg_idx - 1)  # 34..229
