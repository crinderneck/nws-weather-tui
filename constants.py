#!/usr/bin/env python3
"""
NWS Weather TUI — Constants, config defaults, and paths.

City data has been extracted to ``cities.py``.
Radar palette has been extracted to ``radar_palette.py``.
Re-exports are kept here for backward compatibility.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")

# --- Re-exports from extracted modules ---
from cities import MAJOR_CITIES  # noqa: F401
from radar_palette import (      # noqa: F401
    N_RADAR_COLORS,
    NWS_RADAR_PALETTE,
    radar_curses_color,
    radar_dual_pair,
    radar_single_pair,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_NAME = "nws-weather-tui"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_PATH = os.path.join(CONFIG_DIR, "state.json")
RADAR_LAST_PNG_PATH = os.path.join(CONFIG_DIR, "radar-last.png")
DEBUG_LOG_PATH = os.path.join(CONFIG_DIR, "debug.log")

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "location_name": "Spokane, WA",
    "lat": 47.6588,
    "lon": -117.4260,
    "units": "us",
    "use_24h": False,
    "auto_refresh_seconds": 300,
    "http_timeout": 10,
    "user_agent": os.getenv(
        "WEATHER_APP_UA", "NWSWeatherTUI/1.0 (contact: cjrinderneck@proton.me)"
    ),
    "show_graph_panel_on_current": True,
    "hourly_hours": 24,
    "show_radar_map": True,
    "favorites": [],
    "radar": {
        "show_state_lines": True,
        "show_city_labels": True,
        "max_city_labels": 20,
        "ascii_ramp": " .:-=+*#%@",
        "animation_frames": 4,
        "animation_interval_s": 0.5,
        "animation_step_min": 5,
    },
    "cache_ttls": {
        "points": 86400,
        "stations": 86400,
        "observation": 300,
        "forecast": 600,
        "forecast_hourly": 600,
        "alerts": 300,
        "radar": 300,
    },
}

# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def save_json(path: str, obj: Dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def deep_merge(defaults: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(defaults)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        elif isinstance(v, list) and isinstance(out.get(k), list):
            out[k] = v
        else:
            out[k] = v
    return out


def load_config() -> Dict[str, Any]:
    ensure_dir(CONFIG_DIR)
    on_disk = load_json(CONFIG_PATH)
    if on_disk is None:
        save_json(CONFIG_PATH, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    cfg = deep_merge(DEFAULT_CONFIG, on_disk)
    save_json(CONFIG_PATH, cfg)
    return cfg


BASE = "https://api.weather.gov"

MIN_COLS = 70
MIN_ROWS = 22
