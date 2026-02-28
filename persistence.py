#!/usr/bin/env python3
"""
NWS Weather TUI — Config and state persistence.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, Optional, TYPE_CHECKING

from constants import CONFIG_PATH, STATE_PATH, load_json, save_json
from formatting import parse_iso

if TYPE_CHECKING:
    from app import App


def save_app_config(app: "App") -> None:
    app.cfg.update({
        "location_name": app.location_name,
        "lat": app.lat,
        "lon": app.lon,
        "units": app.units,
        "use_24h": app.use_24h,
        "auto_refresh_seconds": app.auto_refresh_seconds,
        "http_timeout": app.timeout,
        "show_graph_panel_on_current": app.show_graph_panel_on_current,
        "hourly_hours": app.hourly_hours,
        "show_radar_map": app.show_radar_map,
        "favorites": app.favorites,
    })
    save_json(CONFIG_PATH, app.cfg)


def _serialize_current(app: "App") -> Optional[Dict[str, Any]]:
    if not app.current:
        return None
    d = app.current.__dict__.copy()
    if isinstance(d.get("timestamp"), dt.datetime):
        d["timestamp"] = d["timestamp"].isoformat()
    return d


def save_app_state(app: "App") -> None:
    def fix_dt(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: v.isoformat() if isinstance(v, dt.datetime) else fix_dt(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [fix_dt(i) for i in obj]
        return obj

    state = fix_dt({
        "saved_at": dt.datetime.now().astimezone().isoformat(),
        "location_name": app.location_name,
        "lat": app.lat,
        "lon": app.lon,
        "units": app.units,
        "use_24h": app.use_24h,
        "current": _serialize_current(app),
        "forecast_periods": [p.__dict__ for p in app.forecast_periods],
        "hourly_periods": [h.__dict__ for h in app.hourly_periods],
        "alerts": [a.__dict__ for a in app.alerts],
        "radar_station": app.radar_station,
        "state_code": app.state_code,
    })
    save_json(STATE_PATH, state)


def _parse_field(value: Any, field_name: str) -> Any:
    if value is None:
        return None
    if field_name in ("start", "end", "sent", "effective", "expires", "timestamp"):
        return parse_iso(value) if isinstance(value, str) else None
    if field_name in (
        "temperature", "wind_speed_num", "pop", "humidity_pct",
        "pressure_pa", "visibility_m", "wind_mps", "wind_dir_deg", "gust_mps",
    ):
        return value if isinstance(value, (int, float)) else None
    if field_name == "is_daytime":
        return value if isinstance(value, bool) else None
    return value


def load_app_state(app: "App") -> bool:
    from models import (
        AlertItem,
        CurrentConditions,
        ForecastPeriod,
        HourlyPeriod,
    )

    st = load_json(STATE_PATH)
    if not st:
        return False
    app.location_name = str(st.get("location_name") or app.location_name)
    try:
        app.lat = float(st.get("lat", app.lat))
        app.lon = float(st.get("lon", app.lon))
    except (TypeError, ValueError):
        pass
    app.units = str(st.get("units") or app.units)
    app.use_24h = bool(st.get("use_24h", app.use_24h))
    app.radar_station = st.get("radar_station", "") or None
    sc = st.get("state_code")
    if isinstance(sc, str) and re.fullmatch(r"[A-Za-z]{2}", sc.strip()):
        app.state_code = sc.strip().upper()

    c = st.get("current")
    if isinstance(c, dict):
        ts = parse_iso(c.get("timestamp")) if isinstance(c.get("timestamp"), str) else None
        try:
            app.current = CurrentConditions(
                station=str(c.get("station") or "\u2014"),
                timestamp=ts,
                temperature_c=c.get("temperature_c"),
                wind_mps=c.get("wind_mps"),
                wind_dir_deg=c.get("wind_dir_deg"),
                gust_mps=c.get("gust_mps"),
                humidity_pct=c.get("humidity_pct"),
                pressure_pa=c.get("pressure_pa"),
                visibility_m=c.get("visibility_m"),
                text_description=str(c.get("text_description") or "\u2014"),
                icon_key=str(c.get("icon_key") or "unknown"),
            )
        except Exception:
            app.current = None

    for key, cls, fields in [
        ("forecast_periods", ForecastPeriod, [
            "name", "start", "end", "is_daytime", "temperature",
            "temperature_unit", "wind_speed", "wind_dir",
            "short_forecast", "detailed_forecast", "icon_key",
        ]),
        ("hourly_periods", HourlyPeriod, [
            "start", "temperature", "temperature_unit", "wind_speed",
            "wind_speed_num", "wind_dir", "short_forecast", "icon_key", "pop",
        ]),
        ("alerts", AlertItem, [
            "event", "severity", "urgency", "certainty", "headline",
            "sent", "effective", "expires", "description", "instruction",
        ]),
    ]:
        items = st.get(key, [])
        setattr(app, key, [
            cls(**{f: _parse_field(p.get(f), f) for f in fields})
            for p in items if isinstance(p, dict)
        ])
    return True
