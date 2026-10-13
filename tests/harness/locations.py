"""Locations, terminal sizes and views covered by the regression harness."""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(TESTS_DIR)
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures")
HTTP_FIXTURES_DIR = os.path.join(FIXTURES_DIR, "http")
REFERENCE_DIR = os.path.join(FIXTURES_DIR, "reference")
MANIFEST_PATH = os.path.join(FIXTURES_DIR, "manifest.json")
SNAPSHOT_DIR = os.path.join(TESTS_DIR, "snapshots")

# Denver: no point alerts but Colorado has some (area-alert fallback).
# Columbus: no alerts anywhere in the state (empty paths).
# Ventura: several stacked point alerts (Red Flag, Heat, Wind, Beach Hazards).
LOCATIONS: Dict[str, Dict[str, object]] = {
    "denver": {
        "name": "Denver, CO", "lat": 39.7392, "lon": -104.9903, "tz": "America/Denver",
    },
    "columbus": {
        "name": "Columbus, OH", "lat": 39.9612, "lon": -82.9988, "tz": "America/New_York",
    },
    "ventura": {
        "name": "Ventura, CA", "lat": 34.2805, "lon": -119.2945,
        "tz": "America/Los_Angeles",
    },
}

SIZES: List[Tuple[int, int]] = [(80, 24), (120, 40), (200, 60)]

# Views whose content depends on the location.
LOCATION_VIEWS: List[str] = ["current", "forecast", "hourly", "alerts", "afd", "hwo", "moon"]
# Views that look the same whichever location is active; rendered once, for Denver.
GLOBAL_VIEWS: List[str] = ["help", "favorites", "dashboard"]
GLOBAL_VIEW_LOCATION = "denver"


def views_for(location: str) -> List[str]:
    if location == GLOBAL_VIEW_LOCATION:
        return LOCATION_VIEWS + GLOBAL_VIEWS
    return list(LOCATION_VIEWS)


def favorites() -> List[Dict[str, object]]:
    return [
        {"name": str(loc["name"]), "lat": loc["lat"], "lon": loc["lon"]}
        for loc in LOCATIONS.values()
    ]


def app_config(location: str) -> Dict[str, object]:
    loc = LOCATIONS[location]
    return {
        "location_name": loc["name"],
        "lat": loc["lat"],
        "lon": loc["lon"],
        "units": "us",
        "use_24h": False,
        "alert_notify": [],  # no bells or tab retitles mid-test
        "favorites": favorites(),
    }
