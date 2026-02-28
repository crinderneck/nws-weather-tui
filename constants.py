#!/usr/bin/env python3
"""
NWS Weather TUI — Constants, config defaults, and city coordinates.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")

MAJOR_CITIES: List[Tuple[str, float, float]] = [
    ("SEA", 47.6062, -122.3321),
    ("SPK", 47.6588, -117.4260),
    ("TAC", 47.2529, -122.4443),
    ("YKM", 46.6021, -120.5059),
    ("BLI", 48.7519, -122.4787),
    ("OLY", 47.0379, -122.9007),
    ("EVT", 47.9790, -122.2021),
    ("PSC", 46.2112, -119.1372),
    ("PDX", 45.5152, -122.6784),
    ("SLM", 44.9429, -123.0351),
    ("EUG", 44.0521, -123.0868),
    ("MFR", 42.3265, -122.8756),
    ("RDM", 44.0582, -121.3153),
    ("SFO", 37.7749, -122.4194),
    ("LAX", 34.0522, -118.2437),
    ("SAN", 32.7157, -117.1611),
    ("SMF", 38.5816, -121.4944),
    ("FAT", 36.7378, -119.7871),
    ("SJC", 37.3382, -121.8863),
    ("BFL", 35.3733, -119.0187),
    ("RDD", 40.5865, -122.3917),
    ("LAS", 36.1699, -115.1398),
    ("RNO", 39.5296, -119.8138),
    ("BOI", 43.6150, -116.2023),
    ("IDA", 43.4666, -112.0340),
    ("TWF", 42.5630, -114.4609),
    ("PIH", 42.8713, -112.4455),
    ("BIL", 45.7833, -108.5007),
    ("MSO", 46.8721, -113.9940),
    ("GTF", 47.4941, -111.2833),
    ("BZN", 45.6770, -111.0429),
    ("HLN", 46.5958, -112.0270),
    ("CYS", 41.1400, -104.8197),
    ("CPR", 42.8666, -106.3131),
    ("DEN", 39.7392, -104.9903),
    ("COS", 38.8339, -104.8214),
    ("FNL", 40.5853, -105.0844),
    ("GJT", 39.0638, -108.5503),
    ("PUB", 38.2544, -104.6091),
    ("SLC", 40.7608, -111.8910),
    ("PVU", 40.2338, -111.6585),
    ("OGD", 41.2230, -111.9738),
    ("SGU", 37.0965, -113.5684),
    ("PHX", 33.4484, -112.0740),
    ("TUS", 32.2226, -110.9747),
    ("FLG", 35.1983, -111.6513),
    ("YUM", 32.6927, -114.6277),
    ("ABQ", 35.0844, -106.6504),
    ("SAF", 35.6870, -105.9378),
    ("LCR", 32.3199, -106.7637),
    ("DAL", 32.7767, -96.7970),
    ("HOU", 29.7604, -95.3698),
    ("SAT", 29.4241, -98.4936),
    ("AUS", 30.2672, -97.7431),
    ("ELP", 31.7619, -106.4850),
    ("LBB", 33.5779, -101.8552),
    ("AMA", 35.2220, -101.8313),
    ("CRP", 27.8006, -97.3964),
    ("ICT", 37.6872, -97.3301),
    ("TOP", 39.0473, -95.6752),
    ("OMA", 41.2565, -95.9345),
    ("LNK", 40.8136, -96.7026),
    ("FSD", 43.5446, -96.7311),
    ("RAP", 44.0805, -103.2310),
    ("FAR", 46.8772, -96.7898),
    ("BIS", 46.8083, -100.7837),
    ("MSP", 44.9778, -93.2650),
    ("DLH", 46.7867, -92.1005),
    ("RST", 44.0121, -92.4802),
    ("DSM", 41.5868, -93.6250),
    ("CID", 41.9779, -91.6656),
    ("STL", 38.6270, -90.1994),
    ("MCI", 39.0997, -94.5786),
    ("SGF", 37.2090, -93.2923),
    ("MKE", 43.0389, -87.9065),
    ("MSN", 43.0731, -89.4012),
    ("GRB", 44.5133, -88.0133),
    ("CHI", 41.8781, -87.6298),
    ("SPI", 39.7817, -89.6501),
    ("DTW", 42.3314, -83.0458),
    ("GRR", 42.9634, -85.6681),
    ("FNT", 43.0125, -83.6875),
    ("MQT", 46.5440, -87.3954),
    ("IND", 39.7684, -86.1581),
    ("FWA", 41.1306, -85.1289),
    ("CMH", 39.9612, -82.9988),
    ("CLE", 41.4993, -81.6944),
    ("CVG", 39.1031, -84.5120),
    ("TOL", 41.6528, -83.5379),
    ("SDF", 38.2527, -85.7585),
    ("LEX", 38.0406, -84.5037),
    ("BNA", 36.1627, -86.7816),
    ("MEM", 35.1495, -90.0490),
    ("TYS", 35.9606, -83.9207),
    ("CHA", 35.0456, -85.3097),
    ("JAN", 32.2988, -90.1848),
    ("BHM", 33.5186, -86.8104),
    ("MGM", 32.3668, -86.2999),
    ("MOB", 30.6954, -88.0399),
    ("HSV", 34.7304, -86.5861),
    ("ATL", 33.7490, -84.3880),
    ("SAV", 32.0809, -81.0912),
    ("AGS", 33.4735, -82.0105),
    ("MIA", 25.7617, -80.1918),
    ("JAX", 30.3322, -81.6557),
    ("TPA", 27.9506, -82.4572),
    ("MCO", 28.5383, -81.3792),
    ("TLH", 30.4518, -84.2807),
    ("PNS", 30.4213, -87.2169),
    ("CAE", 34.0007, -81.0348),
    ("CHS", 32.7765, -79.9311),
    ("CLT", 35.2271, -80.8431),
    ("RDU", 35.7796, -78.6382),
    ("GSO", 36.0726, -79.7920),
    ("ORF", 36.8529, -75.9780),
    ("RIC", 37.5407, -77.4360),
    ("ROA", 37.2710, -79.9414),
    ("CRW", 38.3498, -81.6326),
    ("BWI", 39.2904, -76.6122),
    ("DCA", 38.9072, -77.0369),
    ("PHL", 39.9526, -75.1652),
    ("PIT", 40.4406, -79.9959),
    ("ABE", 40.6084, -75.4902),
    ("ERI", 42.1292, -80.0851),
    ("EWR", 40.7357, -74.1724),
    ("NYC", 40.7128, -74.0060),
    ("BUF", 42.8864, -78.8784),
    ("ROC", 43.1566, -77.6088),
    ("ALB", 42.6526, -73.7562),
    ("SYR", 43.0481, -76.1474),
    ("HVN", 41.3083, -72.9279),
    ("BDL", 41.7658, -72.6851),
    ("BOS", 42.3601, -71.0589),
    ("ORH", 42.2626, -71.8023),
    ("PVD", 41.8240, -71.4128),
    ("PWM", 43.6591, -70.2568),
    ("BGR", 44.8012, -68.7778),
    ("BTV", 44.4759, -73.2121),
    ("MHT", 42.9956, -71.4548),
    ("MSY", 29.9511, -90.0715),
    ("BTR", 30.4515, -91.1871),
    ("SHV", 32.5252, -93.7502),
    ("LIT", 34.7465, -92.2896),
    ("OKC", 35.4676, -97.5164),
    ("TUL", 36.1540, -95.9928),
    ("ILG", 39.7447, -75.5484),
    ("ANC", 61.2181, -149.9003),
    ("FAI", 64.8378, -147.7164),
    ("JNU", 58.3005, -134.4197),
    ("HNL", 21.3069, -157.8583),
    ("ITO", 19.7297, -155.0900),
]

APP_NAME = "nws-weather-tui"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_PATH = os.path.join(CONFIG_DIR, "state.json")
RADAR_LAST_PNG_PATH = os.path.join(CONFIG_DIR, "radar-last.png")
DEBUG_LOG_PATH = os.path.join(CONFIG_DIR, "debug.log")

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
