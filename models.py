#!/usr/bin/env python3
"""
NWS Weather TUI — Data models (dataclasses).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from icons import pick_icon
from helpers import parse_iso, parse_first_number


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
    )


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
