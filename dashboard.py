#!/usr/bin/env python3
"""
NWS Weather TUI — Multi-location favorites dashboard (background fetch).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, TYPE_CHECKING

from models import extract_current

if TYPE_CHECKING:
    from app import App

_DASH_TTL = 300  # seconds


def refresh_dashboard(app: "App", force: bool = False) -> None:
    if not app.favorites:
        return
    if not force and (time.time() - app._dash_last) < _DASH_TTL:
        return
    if app._bg_dash_running:
        return
    app._dash_last = time.time()
    app._bg_dash_running = True
    favorites = list(app.favorites)
    gen = app._bg_generation
    threading.Thread(
        target=_bg_dashboard_fetch, args=(app, favorites, gen), daemon=True
    ).start()


def _fetch_one(app: "App", fav: Dict[str, Any]) -> Dict[str, Any]:
    try:
        lat = float(fav["lat"])
        lon = float(fav["lon"])
        points_data = app.client.points(lat, lon)
        props = (points_data or {}).get("properties", {}) or {}
        stations_url = props.get("observationStations")
        if not stations_url:
            return {"error": "no station"}
        stations = app.client.stations(stations_url)
        feats = (stations or {}).get("features", []) or []
        if not feats:
            return {"error": "no station"}
        sid = ((feats[0] or {}).get("properties", {}) or {}).get("stationIdentifier")
        if not isinstance(sid, str) or not sid:
            return {"error": "no station"}
        current = extract_current(app.client.latest_observation(sid))
        return {"current": current}
    except Exception as e:
        return {"error": str(e)}


def _bg_dashboard_fetch(app: "App", favorites: list, gen: int) -> None:
    """Run in background thread — fetches current conditions for every favorite."""
    results: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(favorites)))) as pool:
        futures = {
            pool.submit(_fetch_one, app, fav): i for i, fav in enumerate(favorites)
        }
        for future in futures:
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {"error": str(e)}

    with app._bg_lock:
        app._bg_dash_pending = {"_gen": gen, "results": results}


def apply_bg_dashboard(app: "App") -> None:
    """Main-thread: apply completed background dashboard results."""
    with app._bg_lock:
        result = app._bg_dash_pending
        app._bg_dash_pending = None
    if result is None:
        return
    app._bg_dash_running = False
    if result.get("_gen") != app._bg_generation:
        return
    for idx, data in (result.get("results") or {}).items():
        data["ts"] = time.time()
        app._dash_data[idx] = data
