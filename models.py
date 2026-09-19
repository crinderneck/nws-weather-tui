#!/usr/bin/env python3
"""
NWS Weather TUI — Data models (dataclasses).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from icons import pick_icon
from formatting import parse_iso, parse_first_number
from radar_decode import RadarCell


@dataclass
class CurrentConditions:
    station: str
    timestamp: Optional[dt.datetime]
    temperature_c: Optional[float]
    wind_mps: Optional[float]
    wind_dir_deg: Optional[float]
    gust_mps: Optional[float]
    humidity_pct: Optional[float]
    pressure_pa: Optional[float]
    visibility_m: Optional[float]
    text_description: str
    icon_key: str
    heat_index_c: Optional[float] = None
    wind_chill_c: Optional[float] = None


@dataclass
class ForecastPeriod:
    name: str
    start: Optional[dt.datetime]
    end: Optional[dt.datetime]
    is_daytime: Optional[bool]
    temperature: Optional[float]
    temperature_unit: str
    wind_speed: str
    wind_dir: str
    short_forecast: str
    detailed_forecast: str
    icon_key: str


@dataclass
class HourlyPeriod:
    start: Optional[dt.datetime]
    temperature: Optional[float]
    temperature_unit: str
    wind_speed: str
    wind_speed_num: Optional[float]
    wind_dir: str
    short_forecast: str
    icon_key: str
    pop: Optional[float]
    precip_mm: Optional[float] = None
    snow_mm: Optional[float] = None


@dataclass
class AlertItem:
    event: str
    severity: str
    urgency: str
    certainty: str
    headline: str
    sent: Optional[dt.datetime]
    effective: Optional[dt.datetime]
    expires: Optional[dt.datetime]
    description: str
    instruction: str
    geometry: Optional[Dict[str, Any]] = None


@dataclass
class AirQuality:
    timestamp: Optional[dt.datetime]
    aqi: Optional[int]
    category: str
    primary_pollutant: Optional[str]
    pm2_5: Optional[float]
    pm10: Optional[float]


@dataclass
class UVIndex:
    current: Optional[float]
    daily_max: Optional[float]


@dataclass
class RadarFrame:
    """One radar animation frame."""
    cells: List[List[RadarCell]]   # halfblock cells (empty if 256-color unavailable)
    ascii_lines: List[str]          # ASCII fallback lines
    kind_lines: List[str]           # ASCII kind classification lines
    timestamp_ms: int               # MRMS epoch ms (UTC)
    source: str = "mrms"            # "mrms" | "iem" | "wms"


def extract_current(obs_json: Dict[str, Any]) -> CurrentConditions:
    props = obs_json.get("properties", {}) or {}

    def v(path: str) -> Optional[float]:
        obj = props.get(path)
        if isinstance(obj, dict):
            val = obj.get("value")
            return val if isinstance(val, (int, float)) else None
        return None

    timestamp = (
        parse_iso(props.get("timestamp"))
        if isinstance(props.get("timestamp"), str)
        else None
    )
    desc = "Current Conditions: " + (
        props.get("textDescription") or props.get("description") or "N/A"
    )
    icon_url = props.get("icon") or ""
    is_day = None
    if isinstance(icon_url, str) and "/night/" in icon_url:
        is_day = False
    elif isinstance(icon_url, str) and "/day/" in icon_url:
        is_day = True

    station = (props.get("station") or "").split("/")[-1] or "—"
    icon_key = pick_icon(str(desc), is_day)

    return CurrentConditions(
        station=station,
        timestamp=timestamp,
        temperature_c=v("temperature"),
        wind_mps=v("windSpeed"),
        wind_dir_deg=v("windDirection"),
        gust_mps=v("windGust"),
        humidity_pct=v("relativeHumidity"),
        pressure_pa=v("barometricPressure"),
        visibility_m=v("visibility"),
        text_description=str(desc),
        icon_key=icon_key,
        heat_index_c=v("heatIndex"),
        wind_chill_c=v("windChill"),
    )


_AQI_POLLUTANT_LABELS = {
    "us_aqi_pm2_5": "PM2.5",
    "us_aqi_pm10": "PM10",
    "us_aqi_ozone": "Ozone",
    "us_aqi_no2": "NO2",
    "us_aqi_so2": "SO2",
    "us_aqi_co": "CO",
}


def aqi_category(aqi: Optional[float]) -> str:
    if aqi is None:
        return "—"
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def extract_air_quality(aq_json: Dict[str, Any]) -> Optional["AirQuality"]:
    cur = (aq_json or {}).get("current")
    if not isinstance(cur, dict):
        return None

    def num(key: str) -> Optional[float]:
        v = cur.get(key)
        return v if isinstance(v, (int, float)) else None

    aqi_val = num("us_aqi")
    if aqi_val is None:
        return None

    sub_scores = {k: num(k) for k in _AQI_POLLUTANT_LABELS}
    sub_scores = {k: v for k, v in sub_scores.items() if v is not None}
    primary = (
        _AQI_POLLUTANT_LABELS[max(sub_scores, key=sub_scores.get)]
        if sub_scores else None
    )

    ts = parse_iso(cur.get("time")) if isinstance(cur.get("time"), str) else None

    return AirQuality(
        timestamp=ts,
        aqi=int(round(aqi_val)),
        category=aqi_category(aqi_val),
        primary_pollutant=primary,
        pm2_5=num("pm2_5"),
        pm10=num("pm10"),
    )


def uv_category(uv: Optional[float]) -> str:
    if uv is None:
        return "—"
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very High"
    return "Extreme"


def extract_uv_index(uv_json: Dict[str, Any]) -> Optional["UVIndex"]:
    cur = (uv_json or {}).get("current")
    daily = (uv_json or {}).get("daily")
    cur_val = None
    if isinstance(cur, dict):
        v = cur.get("uv_index")
        cur_val = v if isinstance(v, (int, float)) else None

    max_val = None
    if isinstance(daily, dict):
        vals = daily.get("uv_index_max")
        if isinstance(vals, list) and vals and isinstance(vals[0], (int, float)):
            max_val = vals[0]

    if cur_val is None and max_val is None:
        return None
    return UVIndex(current=cur_val, daily_max=max_val)


def extract_forecast(fc_json: Dict[str, Any]) -> List[ForecastPeriod]:
    props = fc_json.get("properties", {}) or {}
    periods = props.get("periods", []) or []
    out: List[ForecastPeriod] = []
    for p in periods:
        if not isinstance(p, dict):
            continue
        start = (
            parse_iso(p.get("startTime"))
            if isinstance(p.get("startTime"), str)
            else None
        )
        end = parse_iso(p.get("endTime")) if isinstance(p.get("endTime"), str) else None
        is_day = p.get("isDaytime")
        if not isinstance(is_day, bool):
            is_day = None
        short = str(p.get("shortForecast") or "—")
        out.append(
            ForecastPeriod(
                name=str(p.get("name") or "—"),
                start=start,
                end=end,
                is_daytime=is_day,
                temperature=p.get("temperature")
                if isinstance(p.get("temperature"), (int, float))
                else None,
                temperature_unit=str(p.get("temperatureUnit") or ""),
                wind_speed=str(p.get("windSpeed") or "—"),
                wind_dir=str(p.get("windDirection") or "—"),
                short_forecast=short,
                detailed_forecast=str(p.get("detailedForecast") or "—"),
                icon_key=pick_icon(short, is_day),
            )
        )
    return out


def extract_hourly(h_json: Dict[str, Any]) -> List[HourlyPeriod]:
    props = h_json.get("properties", {}) or {}
    periods = props.get("periods", []) or []
    out: List[HourlyPeriod] = []
    for p in periods:
        if not isinstance(p, dict):
            continue
        start = (
            parse_iso(p.get("startTime"))
            if isinstance(p.get("startTime"), str)
            else None
        )
        is_day = p.get("isDaytime")
        if not isinstance(is_day, bool):
            is_day = None
        short = str(p.get("shortForecast") or "—")

        pop = None
        pop_obj = p.get("probabilityOfPrecipitation")
        if isinstance(pop_obj, dict):
            pv = pop_obj.get("value")
            pop = pv if isinstance(pv, (int, float)) else None

        out.append(
            HourlyPeriod(
                start=start,
                temperature=p.get("temperature")
                if isinstance(p.get("temperature"), (int, float))
                else None,
                temperature_unit=str(p.get("temperatureUnit") or ""),
                wind_speed=str(p.get("windSpeed") or "—"),
                wind_speed_num=parse_first_number(str(p.get("windSpeed") or "")),
                wind_dir=str(p.get("windDirection") or "—"),
                short_forecast=short,
                icon_key=pick_icon(short, is_day),
                pop=pop,
            )
        )
    return out


_DURATION_RE = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def _parse_duration(s: str) -> dt.timedelta:
    m = _DURATION_RE.match(s or "")
    if not m:
        return dt.timedelta()
    days, hours, minutes, seconds = (int(x) if x else 0 for x in m.groups())
    return dt.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def _parse_grid_values(
    values: Optional[List[Dict[str, Any]]]
) -> List[Tuple[dt.datetime, dt.datetime, float]]:
    out: List[Tuple[dt.datetime, dt.datetime, float]] = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        vt = item.get("validTime")
        val = item.get("value")
        if not isinstance(vt, str) or "/" not in vt or not isinstance(val, (int, float)):
            continue
        start_s, dur_s = vt.split("/", 1)
        start = parse_iso(start_s)
        if start is None:
            continue
        out.append((start, start + _parse_duration(dur_s), float(val)))
    return out


def extract_grid_precip(
    grid_json: Dict[str, Any]
) -> Dict[str, List[Tuple[dt.datetime, dt.datetime, float]]]:
    """Parse NWS gridpoint quantitative precipitation / snowfall time series."""
    props = (grid_json or {}).get("properties", {}) or {}
    out: Dict[str, List[Tuple[dt.datetime, dt.datetime, float]]] = {}
    for key, field in [
        ("precip_mm", "quantitativePrecipitation"),
        ("snow_mm", "snowfallAmount"),
    ]:
        obj = props.get(field)
        values = obj.get("values") if isinstance(obj, dict) else None
        out[key] = _parse_grid_values(values)
    return out


def merge_grid_precip_into_hourly(
    hourly: List["HourlyPeriod"],
    grid: Dict[str, List[Tuple[dt.datetime, dt.datetime, float]]],
) -> None:
    """Attach per-hour precip/snow accumulation (mm) from gridpoint data."""
    for key, series in grid.items():
        if not series:
            continue
        for h in hourly:
            if h.start is None:
                continue
            for start, end, val in series:
                if start <= h.start < end:
                    setattr(h, key, val)
                    break


def extract_alerts(alerts_json: Dict[str, Any]) -> List[AlertItem]:
    feats = alerts_json.get("features", []) or []
    out: List[AlertItem] = []
    for f in feats:
        props = (f or {}).get("properties", {}) or {}
        out.append(
            AlertItem(
                event=str(props.get("event") or "—"),
                severity=str(props.get("severity") or "—"),
                urgency=str(props.get("urgency") or "—"),
                certainty=str(props.get("certainty") or "—"),
                headline=str(props.get("headline") or "—"),
                sent=parse_iso(props.get("sent"))
                if isinstance(props.get("sent"), str)
                else None,
                effective=parse_iso(props.get("effective"))
                if isinstance(props.get("effective"), str)
                else None,
                expires=parse_iso(props.get("expires"))
                if isinstance(props.get("expires"), str)
                else None,
                description=str(props.get("description") or ""),
                instruction=str(props.get("instruction") or ""),
                geometry=(f or {}).get("geometry")
                if isinstance((f or {}).get("geometry"), dict) else None,
            )
        )
    sev_rank = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}
    out.sort(
        key=lambda a: (
            sev_rank.get(a.severity, 9),
            -(a.sent.timestamp() if a.sent else 0),
        )
    )
    return out
