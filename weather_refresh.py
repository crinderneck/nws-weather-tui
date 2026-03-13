#!/usr/bin/env python3
"""
NWS Weather TUI — Weather data fetching (background thread pipeline).
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, TYPE_CHECKING

from models import extract_alerts, extract_current, extract_forecast, extract_hourly

if TYPE_CHECKING:
    from app import App


def refresh_all(app: "App", force: bool = False, allow_offline: bool = False) -> None:
    now = time.time()
    if not force and now < app.next_refresh:
        return
    if app._bg_weather_running:
        return
    app.next_refresh = now + app.auto_refresh_seconds
    app._bg_weather_running = True
    app._is_loading = True
    app.status_msg = "/ Loading weather data..."
    app.status_until = time.time() + 3600
    ctx = {
        "lat": app.lat, "lon": app.lon, "units": app.units,
        "points_data": app.points_data, "forecast_url": app.forecast_url,
        "hourly_url": app.hourly_url, "stations_url": app.stations_url,
        "station_id": app.station_id, "hourly_hours": app.hourly_hours,
        "allow_offline": allow_offline,
    }
    gen = app._bg_generation
    threading.Thread(
        target=_bg_weather_fetch, args=(app, ctx, gen), daemon=True
    ).start()


def _bg_weather_fetch(app: "App", ctx: Dict[str, Any], gen: int) -> None:
    """Run in background thread — fetches all weather data."""
    result: Dict[str, Any] = {"ok": False}
    try:
        points_data = ctx["points_data"]
        station_id = ctx["station_id"]
        forecast_url = ctx["forecast_url"]
        hourly_url = ctx["hourly_url"]
        stations_url = ctx["stations_url"]

        if not points_data:
            points_data = app.client.points(ctx["lat"], ctx["lon"])
            props = (points_data or {}).get("properties", {}) or {}
            forecast_url = props.get("forecast")
            hourly_url = props.get("forecastHourly")
            stations_url = props.get("observationStations")
            rs = props.get("radarStation")
            result["radar_station"] = rs.strip() if isinstance(rs, str) and rs else None
            rel = (props.get("relativeLocation") or {}).get("properties", {})
            st = rel.get("state") if isinstance(rel, dict) else None
            result["state_code"] = (
                st.strip().upper()
                if isinstance(st, str) and re.fullmatch(r"[A-Za-z]{2}", st.strip())
                else None
            )
            result["points_data"] = points_data
            result["forecast_url"] = forecast_url
            result["hourly_url"] = hourly_url
            result["stations_url"] = stations_url

        if not station_id and stations_url:
            stations = app.client.stations(stations_url)
            feats = (stations or {}).get("features", []) or []
            if feats:
                sid = ((feats[0] or {}).get("properties", {}) or {}).get("stationIdentifier")
                if isinstance(sid, str) and sid:
                    station_id = sid
                    result["station_id"] = sid

        if station_id:
            result["current"] = extract_current(
                app.client.latest_observation(station_id)
            )
        if forecast_url:
            result["forecast_periods"] = extract_forecast(
                app.client.forecast(forecast_url, ctx["units"])
            )
        if hourly_url:
            hf = extract_hourly(
                app.client.forecast_hourly(hourly_url, ctx["units"])
            )
            h = ctx["hourly_hours"]
            result["hourly_periods"] = hf[:h] if h > 0 else hf

        result["alerts"] = extract_alerts(
            app.client.alerts(ctx["lat"], ctx["lon"])
        )
        result["ok"] = True

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["allow_offline"] = ctx["allow_offline"]

    result["_gen"] = gen
    with app._bg_lock:
        app._bg_weather_pending = result


def apply_bg_weather(app: "App") -> None:
    """Main-thread: apply completed background weather results."""
    with app._bg_lock:
        result = app._bg_weather_pending
        app._bg_weather_pending = None
    if result is None:
        return
    if result.get("_gen") != app._bg_generation:
        app._bg_weather_running = False
        return
    app._bg_weather_running = False
    app._is_loading = app._bg_radar_running

    if result.get("ok"):
        if "points_data" in result:
            app.points_data = result["points_data"]
        if "forecast_url" in result:
            app.forecast_url = result["forecast_url"]
        if "hourly_url" in result:
            app.hourly_url = result["hourly_url"]
        if "stations_url" in result:
            app.stations_url = result["stations_url"]
        if "station_id" in result:
            app.station_id = result["station_id"]
        if "radar_station" in result:
            app.radar_station = result["radar_station"]
        if "state_code" in result:
            app.state_code = result["state_code"]
            if not app.state_code:
                m = re.search(r",\s*([A-Za-z]{2})(?:\b|$)", app.location_name or "")
                app.state_code = m.group(1).upper() if m else None

        if "current" in result:
            app.current = result["current"]
        if "forecast_periods" in result:
            app.forecast_periods = result["forecast_periods"]
        if "hourly_periods" in result:
            app.hourly_periods = result["hourly_periods"]
        if "alerts" in result:
            app.alerts = result["alerts"]

        app.offline_mode = False
        app.offline_reason = ""
        app.last_refresh = time.time()
        app.next_refresh = time.time() + app.auto_refresh_seconds
        app._save_state()
        app._flash("Updated.", 1.1)
    else:
        app.offline_mode = True
        app.offline_reason = result.get("error", "unknown")
        app.next_refresh = time.time() + 60
        if result.get("allow_offline") and app._load_state():
            app._flash(f"Offline: showing last saved data ({app.offline_reason})", 4.0)
        else:
            app._flash(f"Refresh failed: {app.offline_reason}", 6.0)
