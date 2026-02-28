#!/usr/bin/env python3
"""
NWS Weather TUI — Main application.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

import curses

from client import NWSClient
from constants import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    MIN_COLS,
    MIN_ROWS,
    RADAR_LAST_PNG_PATH,
    STATE_PATH,
    ensure_dir,
    load_config,
    load_json,
    save_json,
)
from helpers import (
    bbox_around,
    clamp,
    city_overlay_and_hits_for_bbox,
    dbg,
    expand_bbox_km,
    fmt_time,
    parse_iso,
    png_to_ascii,
    png_to_line_overlay,
    safe_addstr,
    vector_lines_overlay,
    parse_first_number,
)
from models import (
    AlertItem,
    CurrentConditions,
    ForecastPeriod,
    HourlyPeriod,
    extract_alerts,
    extract_current,
    extract_forecast,
    extract_hourly,
)
from views import (
    draw_header,
    draw_footer,
    draw_current,
    draw_forecast,
    draw_hourly,
    draw_alerts,
    draw_help,
)


class App:
    def __init__(self, stdscr, cfg: Dict[str, Any]):
        self.stdscr = stdscr
        self.cfg = cfg

        self.location_name: str = str(cfg.get("location_name", "—"))
        self.lat: float = float(cfg.get("lat", 0.0))
        self.lon: float = float(cfg.get("lon", 0.0))
        self.units: str = str(cfg.get("units", "us"))
        self.use_24h: bool = bool(cfg.get("use_24h", False))
        self.auto_refresh_seconds: int = int(cfg.get("auto_refresh_seconds", 300))
        self.timeout: int = int(cfg.get("http_timeout", 10))
        self.show_graph_panel_on_current: bool = bool(
            cfg.get("show_graph_panel_on_current", True)
        )
        self.hourly_hours: int = int(cfg.get("hourly_hours", 24))
        self.show_radar_map: bool = bool(cfg.get("show_radar_map", True))

        self.favorites: List[Dict[str, Any]] = list(cfg.get("favorites", []) or [])
        self.fav_idx: int = 0

        self.client = NWSClient(
            user_agent=str(cfg.get("user_agent", DEFAULT_CONFIG["user_agent"])),
            timeout=self.timeout,
            ttls=dict(cfg.get("cache_ttls", DEFAULT_CONFIG["cache_ttls"])),
        )

        self.view = "current"
        self.paused = False
        self.status_msg = ""
        self.status_until = 0.0
        self._spinner_idx = 0
        self._spinner_frames = ["|", "/", "-", "\\"]
        self._is_loading = False
        self._in_refresh = False

        self.points_data: Optional[Dict[str, Any]] = None
        self.forecast_url: Optional[str] = None
        self.hourly_url: Optional[str] = None
        self.stations_url: Optional[str] = None
        self.station_id: Optional[str] = None
        self.radar_station: Optional[str] = None
        self.state_code: Optional[str] = None
        self.sunrise: Optional[str] = None
        self.sunset: Optional[str] = None

        self.current: Optional[CurrentConditions] = None
        self.forecast_periods: List[ForecastPeriod] = []
        self.hourly_periods: List[HourlyPeriod] = []
        self.alerts: List[AlertItem] = []

        self.last_refresh = 0.0
        self.next_refresh = 0.0
        self.offline_mode = False
        self.offline_reason = ""

        self.fc_scroll = 0
        self.hr_scroll = 0
        self.alert_scroll = 0

        self._radar_ascii: List[str] = []
        self._radar_kind: List[str] = []
        self._radar_state_overlay: List[str] = []
        self._radar_city_overlay: List[str] = []
        self._radar_last = 0.0
        self._radar_err: Optional[str] = None
        self._radar_bbox: Optional[Tuple[float, float, float, float]] = None
        self._radar_src_cols = 0
        self._radar_src_rows = 0
        self._radar_city_hitmap: Dict[Tuple[int, int], Tuple[str, float, float]] = {}
        self._radar_map_x = 0
        self._radar_map_y = 0
        self._radar_map_cols = 0
        self._radar_map_rows = 0

        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)
        curses.init_pair(6, curses.COLOR_BLUE, -1)
        curses.init_pair(7, curses.COLOR_RED, -1)
        try:
            for i, color in enumerate(
                [
                    curses.COLOR_CYAN,
                    curses.COLOR_GREEN,
                    curses.COLOR_YELLOW,
                    curses.COLOR_RED,
                    curses.COLOR_MAGENTA,
                ],
                8,
            ):
                curses.init_pair(i, color, -1)
        except curses.error:
            pass
        try:
            mask = curses.ALL_MOUSE_EVENTS | getattr(curses, "REPORT_MOUSE_POSITION", 0)
            curses.mousemask(mask)
            curses.mouseinterval(0)
        except curses.error:
            pass

        self._load_points()
        self.refresh_all(force=True, allow_offline=True)

    def _flash(self, msg: str, seconds: float = 2.0) -> None:
        self._is_loading = False
        self.status_msg = msg
        self.status_until = time.time() + seconds

    def _show_loading(self, msg: str) -> None:
        frame = self._spinner_frames[self._spinner_idx % len(self._spinner_frames)]
        self._spinner_idx += 1
        self._is_loading = True
        self.status_msg = f"{frame} {msg}"
        self.status_until = time.time() + 3600
        self._draw()

    def _save_radar_png(self, png: bytes) -> None:
        try:
            ensure_dir(os.path.dirname(RADAR_LAST_PNG_PATH))
            tmp = RADAR_LAST_PNG_PATH + ".tmp"
            with open(tmp, "wb") as f:
                f.write(png)
            os.replace(tmp, RADAR_LAST_PNG_PATH)
        except Exception as e:
            dbg(f"RADAR save failed: {e}")

    def _radar_char_attr(self, ch: str, ramp: str, kind: str = " ") -> int:
        if not ch or ch == " ":
            return curses.A_DIM
        levels = ramp or " .:-=+*#%@"
        idx = levels.find(ch)
        if idx < 0:
            idx = 1
        t = idx / max(1, len(levels) - 1)
        base = {  # kind -> color pair
            "R": 9,  # rain - green
            "S": 6,  # snow - blue
            "I": 5,  # sleet - magenta
        }.get(kind, 8)  # default - cyan
        base = curses.color_pair(base)
        if t < 0.25:
            return base | curses.A_DIM
        if t < 0.8:
            return base
        return base | curses.A_BOLD

    def _draw_radar_line(
        self,
        win,
        y: int,
        line: str,
        kind_line: str,
        cols: int,
        ramp: str,
        x_off: int = 0,
    ) -> None:
        max_w = max(0, cols - 1 - x_off)
        line = (line or "")[:max_w]
        kind_line = (kind_line or "")[:max_w]
        if len(kind_line) < len(line):
            kind_line += " " * (len(line) - len(kind_line))
        if not line:
            return
        x = max(0, x_off)
        run_attr = self._radar_char_attr(
            line[0], ramp, kind_line[0] if kind_line else " "
        )
        run = [line[0]]
        for i, ch in enumerate(line[1:], start=1):
            a = self._radar_char_attr(
                ch, ramp, kind_line[i] if i < len(kind_line) else " "
            )
            if a == run_attr:
                run.append(ch)
                continue
            safe_addstr(win, y, x, "".join(run), run_attr)
            x += len(run)
            run = [ch]
            run_attr = a
        safe_addstr(win, y, x, "".join(run), run_attr)

    def _draw_state_overlay_line(
        self, win, y: int, line: str, cols: int, x_off: int = 0
    ) -> None:
        line = (line or "")[: max(0, cols - 1 - x_off)]
        if not line:
            return
        for x, ch in enumerate(line):
            if ch != " ":
                safe_addstr(
                    win, y, x + max(0, x_off), ch, curses.color_pair(2) | curses.A_DIM
                )

    def _draw_city_overlay_line(
        self, win, y: int, line: str, cols: int, x_off: int = 0
    ) -> None:
        line = (line or "")[: max(0, cols - 1 - x_off)]
        if not line:
            return
        for x, ch in enumerate(line):
            if ch != " ":
                attr = {
                    "O": curses.color_pair(1) | curses.A_BOLD,  # you are here
                    "@": curses.color_pair(12) | curses.A_BOLD,  # city dot
                }.get(ch, curses.color_pair(3) | curses.A_BOLD)  # city label
                safe_addstr(win, y, x + max(0, x_off), ch, attr)

    def _handle_mouse(self, mx: int, my: int, bstate: int) -> None:
        click_mask = (
            getattr(curses, "BUTTON1_CLICKED", 0)
            | getattr(curses, "BUTTON1_PRESSED", 0)
            | getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0)
            | getattr(curses, "BUTTON1_TRIPLE_CLICKED", 0)
            | getattr(curses, "BUTTON1_RELEASED", 0)
        )
        if click_mask and not (bstate & click_mask):
            return
        if self.view != "current" or not self.show_radar_map:
            return
        if self._radar_map_cols <= 0 or self._radar_map_rows <= 0:
            return

        rx = int(mx) - self._radar_map_x
        ry = int(my) - self._radar_map_y
        if rx < 0 or ry < 0 or rx >= self._radar_map_cols or ry >= self._radar_map_rows:
            return

        hit = self._radar_city_hitmap.get((rx, ry))
        if not hit:
            return

        code, lat, lon = hit
        if abs(self.lat - lat) < 1e-4 and abs(self.lon - lon) < 1e-4:
            self._flash(f"Already at {code}.", 1.2)
            return

        self._apply_location(code, lat, lon)
        self._flash(f"Location set: {code}", 1.8)

    def _prompt_line(self, prompt: str, max_len: int = 96) -> Optional[str]:
        rows, cols = self.stdscr.getmaxyx()
        max_input = clamp(min(max_len, cols - len(prompt) - 4), 1, max_len)
        old_paused = self.paused
        self.paused = True
        curses.echo()
        curses.curs_set(1)
        self.stdscr.timeout(-1)
        self.stdscr.nodelay(False)
        try:
            safe_addstr(self.stdscr, rows - 1, 0, " " * max(1, cols - 1))
            safe_addstr(self.stdscr, rows - 1, 1, prompt[: cols - 2], curses.A_BOLD)
            self.stdscr.refresh()
            x = clamp(len(prompt) + 1, 1, max(1, cols - 2))
            self.stdscr.move(rows - 1, x)
            raw = self.stdscr.getstr(rows - 1, x, max_input)
            return raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            return None
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.paused = old_paused
            self.stdscr.timeout(500)
            self.stdscr.nodelay(False)

    def _search_location(self) -> bool:
        q = self._prompt_line("Location (city/state or ZIP): ")
        if q is None:
            self._flash("Location search canceled.", 1.4)
            return True
        q = q.strip()
        if not q:
            self._flash("No location entered.", 1.4)
            return True
        try:
            self._show_loading("Searching location...")
            g = self.client.geocode_us(q)
            if not g:
                self._flash(f"No match found for '{q}'.", 2.5)
                return True
            name, lat, lon = g
            self._apply_location(name, lat, lon)
            self._flash(f"Location set: {name}", 1.8)
        except Exception as e:
            self._flash(f"Location search failed: {e}", 3.5)
        return True

    def _save_cfg(self) -> None:
        self.cfg.update(
            {
                "location_name": self.location_name,
                "lat": self.lat,
                "lon": self.lon,
                "units": self.units,
                "use_24h": self.use_24h,
                "auto_refresh_seconds": self.auto_refresh_seconds,
                "http_timeout": self.timeout,
                "show_graph_panel_on_current": self.show_graph_panel_on_current,
                "hourly_hours": self.hourly_hours,
                "show_radar_map": self.show_radar_map,
                "favorites": self.favorites,
            }
        )
        save_json(CONFIG_PATH, self.cfg)

    def _load_points(self) -> None:
        self.points_data = self.client.points(self.lat, self.lon)
        props = self.points_data.get("properties", {}) or {}
        self.forecast_url = props.get("forecast")
        self.hourly_url = props.get("forecastHourly")
        self.stations_url = props.get("observationStations")
        rs = props.get("radarStation")
        self.radar_station = rs.strip() if isinstance(rs, str) and rs else None
        rel = (props.get("relativeLocation") or {}).get("properties", {})
        st = rel.get("state") if isinstance(rel, dict) else None
        self.state_code = (
            st.strip().upper()
            if isinstance(st, str) and re.fullmatch(r"[A-Za-z]{2}", st.strip())
            else None
        )
        if not self.state_code:
            m = re.search(r",\s*([A-Za-z]{2})(?:\b|$)", self.location_name or "")
            self.state_code = m.group(1).upper() if m else None
        self.sunrise = props.get("astronomicalData", {}).get("sunrise")
        self.sunset = props.get("astronomicalData", {}).get("sunset")

    def _pick_station(self) -> None:
        if not self.stations_url:
            return
        stations = self.client.stations(self.stations_url)
        feats = stations.get("features", []) or []
        if feats:
            station_id = ((feats[0] or {}).get("properties", {}) or {}).get(
                "stationIdentifier"
            )
            if isinstance(station_id, str) and station_id:
                self.station_id = station_id

    def _save_state(self) -> None:
        state = {
            "saved_at": dt.datetime.now().astimezone().isoformat(),
            "location_name": self.location_name,
            "lat": self.lat,
            "lon": self.lon,
            "units": self.units,
            "use_24h": self.use_24h,
            "current": self._serialize_current(),
            "forecast_periods": [p.__dict__ for p in self.forecast_periods],
            "hourly_periods": [h.__dict__ for h in self.hourly_periods],
            "alerts": [a.__dict__ for a in self.alerts],
            "radar_station": self.radar_station,
            "state_code": self.state_code,
        }

        def fix_dt(obj):
            if isinstance(obj, dict):
                for k, v in list(obj.items()):
                    if isinstance(v, dt.datetime):
                        obj[k] = v.isoformat()
                    elif isinstance(v, dict):
                        fix_dt(v)
                    elif isinstance(v, list):
                        for it in v:
                            fix_dt(it) if isinstance(it, dict) else None
            return obj

        save_json(STATE_PATH, fix_dt(state))

    def _serialize_current(self) -> Optional[Dict[str, Any]]:
        if not self.current:
            return None
        d = self.current.__dict__.copy()
        if isinstance(d.get("timestamp"), dt.datetime):
            d["timestamp"] = d["timestamp"].isoformat()
        return d

    def _load_state(self) -> bool:
        st = load_json(STATE_PATH)
        if not st:
            return False

        self.location_name = str(st.get("location_name") or self.location_name)
        try:
            self.lat = float(st.get("lat", self.lat))
            self.lon = float(st.get("lon", self.lon))
        except Exception:
            pass
        self.units = str(st.get("units") or self.units)
        self.use_24h = bool(st.get("use_24h", self.use_24h))
        self.radar_station = st.get("radar_station", "").strip() or None
        sc = st.get("state_code")
        if isinstance(sc, str) and re.fullmatch(r"[A-Za-z]{2}", sc.strip()):
            self.state_code = sc.strip().upper()

        c = st.get("current")
        if isinstance(c, dict):
            ts = (
                parse_iso(c.get("timestamp"))
                if isinstance(c.get("timestamp"), str)
                else None
            )
            try:
                self.current = CurrentConditions(
                    station=str(c.get("station") or "—"),
                    timestamp=ts,
                    temperature_c=c.get("temperature_c"),
                    wind_mps=c.get("wind_mps"),
                    wind_dir_deg=c.get("wind_dir_deg"),
                    gust_mps=c.get("gust_mps"),
                    humidity_pct=c.get("humidity_pct"),
                    pressure_pa=c.get("pressure_pa"),
                    visibility_m=c.get("visibility_m"),
                    text_description=str(c.get("text_description") or "—"),
                    icon_key=str(c.get("icon_key") or "unknown"),
                )
            except Exception:
                self.current = None

        for key, cls, fields in [
            (
                "forecast_periods",
                ForecastPeriod,
                [
                    "name",
                    "start",
                    "end",
                    "is_daytime",
                    "temperature",
                    "temperature_unit",
                    "wind_speed",
                    "wind_dir",
                    "short_forecast",
                    "detailed_forecast",
                    "icon_key",
                ],
            ),
            (
                "hourly_periods",
                HourlyPeriod,
                [
                    "start",
                    "temperature",
                    "temperature_unit",
                    "wind_speed",
                    "wind_speed_num",
                    "wind_dir",
                    "short_forecast",
                    "icon_key",
                    "pop",
                ],
            ),
            (
                "alerts",
                AlertItem,
                [
                    "event",
                    "severity",
                    "urgency",
                    "certainty",
                    "headline",
                    "sent",
                    "effective",
                    "expires",
                    "description",
                    "instruction",
                ],
            ),
        ]:
            items = st.get(key, [])
            setattr(
                self,
                key,
                [
                    cls(**{f: _parse_field(p.get(f), f) for f in fields})
                    for p in items
                    if isinstance(p, dict)
                ],
            )

        return True

    def _apply_location(self, name: str, lat: float, lon: float) -> None:
        self.location_name = name
        self.lat = float(lat)
        self.lon = float(lon)
        self.points_data = None
        self.forecast_url = None
        self.hourly_url = None
        self.stations_url = None
        self.station_id = None
        self.radar_station = None
        self.state_code = None
        self.client.cache.clear()
        self._radar_ascii = []
        self._radar_kind = []
        self._radar_state_overlay = []
        self._radar_city_overlay = []
        self._radar_city_hitmap = {}
        self._radar_err = None
        self._radar_last = 0.0
        self._radar_src_cols = 0
        self._radar_src_rows = 0
        self._radar_map_x = 0
        self._radar_map_y = 0
        self._radar_map_cols = 0
        self._radar_map_rows = 0
        self._show_loading(f"Switching location to {name}...")
        self._load_points()
        self.refresh_all(force=True, allow_offline=True)
        self._save_cfg()

    def _toggle_favorite(self) -> bool:
        eps = 1e-4
        idx = next(
            (
                i
                for i, f in enumerate(self.favorites)
                if abs(float(f.get("lat", 0)) - self.lat) < eps
                and abs(float(f.get("lon", 0)) - self.lon) < eps
            ),
            None,
        )
        if idx is not None:
            self.favorites.pop(idx)
            self._flash("Removed from favorites.", 1.2)
        else:
            self.favorites.append(
                {"name": self.location_name, "lat": self.lat, "lon": self.lon}
            )
            self._flash("Added to favorites.", 1.2)
        self.fav_idx = clamp(self.fav_idx, 0, max(0, len(self.favorites) - 1))
        self._save_cfg()
        return True

    def _cycle_favorite(self, direction: int) -> bool:
        if not self.favorites:
            self._flash("No favorites yet. Press F to add this location.", 2.0)
            return True
        self.fav_idx = (self.fav_idx + direction) % len(self.favorites)
        f = self.favorites[self.fav_idx]
        try:
            self._apply_location(
                str(f.get("name") or "Favorite"), float(f["lat"]), float(f["lon"])
            )
        except Exception:
            self._flash("Favorite is invalid (missing lat/lon).", 2.0)
        return True

    def refresh_all(self, force: bool = False, allow_offline: bool = False) -> None:
        now = time.time()
        if not force and now < self.next_refresh:
            return

        self._in_refresh = True
        try:
            self.offline_mode = False
            self.offline_reason = ""
            self._show_loading("Checking forecast endpoints...")

            if not self.points_data:
                self._show_loading("Locating nearest NWS gridpoint...")
                self._load_points()
            if not self.station_id:
                self._show_loading("Finding observation station...")
                self._pick_station()

            if self.station_id:
                self._show_loading("Fetching current conditions...")
                self.current = extract_current(
                    self.client.latest_observation(self.station_id)
                )

            if self.forecast_url:
                self._show_loading("Fetching forecast periods...")
                self.forecast_periods = extract_forecast(
                    self.client.forecast(self.forecast_url, self.units)
                )

            if self.hourly_url:
                self._show_loading("Fetching hourly forecast...")
                hf = extract_hourly(
                    self.client.forecast_hourly(self.hourly_url, self.units)
                )
                self.hourly_periods = (
                    hf[: self.hourly_hours] if self.hourly_hours > 0 else hf
                )

            self._show_loading("Fetching active alerts...")
            self.alerts = extract_alerts(self.client.alerts(self.lat, self.lon))

            self.last_refresh = now
            self.next_refresh = now + self.auto_refresh_seconds
            self._show_loading("Saving latest snapshot...")
            self._save_state()
            self._flash("Updated.", 1.1)

        except Exception as e:
            self.offline_mode = True
            self.offline_reason = str(e)
            self.next_refresh = now + 60
            if allow_offline and self._load_state():
                self._flash(f"Offline: showing last saved data ({e})", 4.0)
            else:
                self._flash(f"Refresh failed: {e}", 6.0)
        finally:
            self._in_refresh = False

    def _maybe_refresh_radar(self, target_cols: int, target_rows: int) -> None:
        if not self.show_radar_map:
            return
        ttl = int(self.cfg.get("cache_ttls", {}).get("radar", 300))
        if (
            (time.time() - self._radar_last) < ttl
            and self._radar_ascii
            and self._radar_src_cols == target_cols
            and self._radar_src_rows == target_rows
        ):
            return

        if not self.radar_station:
            self._radar_ascii = ["(no radarStation from NWS points)"]
            self._radar_kind = []
            self._radar_state_overlay = []
            self._radar_city_hitmap = {}
            self._radar_err = "no radarStation"
            self._radar_last = time.time()
            return

        try:
            from PIL import Image
        except Exception:
            self._radar_ascii = ["(install pillow to render radar map)"]
            self._radar_kind = []
            self._radar_state_overlay = []
            self._radar_city_hitmap = {}
            self._radar_err = "pillow missing"
            self._radar_last = time.time()
            return

        radar_cfg = dict(self.cfg.get("radar", {}) or {})
        ramp = str(radar_cfg.get("ascii_ramp", " .:-=+*#%@"))
        show_state_lines = bool(radar_cfg.get("show_state_lines", True))
        show_city_labels = bool(radar_cfg.get("show_city_labels", True))
        max_city_labels = int(radar_cfg.get("max_city_labels", 20))

        bbox = self.client.state_bbox(self.state_code) if self.state_code else None
        bbox = (
            expand_bbox_km(bbox, 20.0)
            if bbox
            else bbox_around(self.lat, self.lon, 300.0)
        )

        minlon, minlat, maxlon, maxlat = bbox
        geo_aspect = (maxlon - minlon) / max(1e-9, maxlat - minlat)
        req_h = max(64, target_rows * 12)
        req_w = max(64, int(req_h * geo_aspect))

        self._radar_bbox = bbox
        self._radar_src_cols = target_cols
        self._radar_src_rows = target_rows
        try:
            png = self.client.radar_wms_png(self.radar_station, bbox, req_w, req_h)
            if png is None:
                raise RuntimeError("radar returned no data")
            self._save_radar_png(png)
            self._radar_ascii, self._radar_kind = png_to_ascii(
                png, target_cols, target_rows, ramp
            )
            self._radar_state_overlay = []
            self._radar_city_overlay = []
            self._radar_city_hitmap = {}
            if show_state_lines:
                try:
                    feats = self.client.state_lines_features(bbox, self.state_code)
                    self._radar_state_overlay = vector_lines_overlay(
                        feats, bbox, target_cols, target_rows, mark="|"
                    )
                    if not any(self._radar_state_overlay):
                        ol, out_bbox = self.client.state_lines_png(bbox, req_w, req_h)
                        if ol:
                            self._radar_state_overlay = png_to_line_overlay(
                                ol,
                                target_cols,
                                target_rows,
                                mark="|",
                                src_bbox=out_bbox,
                                dst_bbox=bbox,
                            )
                except Exception as oe:
                    dbg(f"RADAR state-lines overlay failed: {oe}")
            if show_city_labels:
                self._radar_city_overlay, self._radar_city_hitmap = (
                    city_overlay_and_hits_for_bbox(
                        target_cols,
                        target_rows,
                        bbox,
                        max_labels=max_city_labels,
                        here=(self.lat, self.lon),
                    )
                )
            self._radar_err = None
        except Exception as e:
            self._radar_ascii = []
            self._radar_kind = []
            self._radar_state_overlay = []
            self._radar_city_overlay = []
            self._radar_city_hitmap = {}
            self._radar_err = str(e)
        self._radar_last = time.time()

    def run(self) -> None:
        self.stdscr.nodelay(False)
        self.stdscr.timeout(500)
        while True:
            self._tick()
            ch = self.stdscr.getch()
            if ch != -1 and not self._handle_key(ch):
                break

    def _tick(self) -> None:
        if not self.paused:
            self.refresh_all(force=False, allow_offline=True)
        now = time.time()
        wait_ms = 500
        if self.next_refresh and not self.paused:
            wait_ms = min(wait_ms, max(50, int((self.next_refresh - now) * 1000)))
        if self.status_msg and now < self.status_until:
            wait_ms = min(wait_ms, max(50, int((self.status_until - now) * 1000)))
        self.stdscr.timeout(clamp(wait_ms, 50, 1000))
        self._draw()

    def _handle_key(self, ch: int) -> bool:
        key_handlers = {
            ord("q"): lambda: False,
            ord("Q"): lambda: False,
            ord("?"): lambda: self._set_view("help"),
            curses.KEY_MOUSE: self._handle_mouse_event,
            ord("c"): lambda: self._set_view("current"),
            ord("f"): lambda: self._set_view("forecast"),
            ord("h"): lambda: self._set_view("hourly"),
            ord("a"): lambda: self._set_view("alerts"),
            ord("l"): lambda: self._search_location(),
            ord("r"): lambda: self._refresh(),
            ord("u"): lambda: self._toggle_units(),
            ord("t"): lambda: self._toggle_time_format(),
            ord("p"): lambda: self._toggle_pause(),
            ord("g"): lambda: self._toggle_graphs(),
            ord("w"): lambda: self._toggle_radar(),
            ord("o"): lambda: self._open_radar(),
            ord("["): lambda: self._cycle_favorite(-1),
            ord("]"): lambda: self._cycle_favorite(1),
            ord("n"): lambda: self._cycle_favorite(1),
            ord("b"): lambda: self._cycle_favorite(-1),
            ord("F"): lambda: self._toggle_favorite(),
        }

        handler = key_handlers.get(ch)
        if handler:
            return handler()

        if ch in (curses.KEY_DOWN, ord("j")):
            self._scroll(1)
        elif ch in (curses.KEY_UP, ord("k")):
            self._scroll(-1)
        return True

    def _set_view(self, view: str) -> bool:
        self.view = view
        return True

    def _handle_mouse_event(self) -> bool:
        try:
            _id, mx, my, _z, bstate = curses.getmouse()
            self._handle_mouse(mx, my, bstate)
        except Exception:
            pass
        return True

    def _refresh(self) -> bool:
        self._show_loading("Refreshing now...")
        self.refresh_all(force=True, allow_offline=True)
        self._radar_last = 0.0
        return True

    def _toggle_units(self) -> bool:
        self.units = "si" if self.units == "us" else "us"
        self.client.cache.clear()
        self._flash(f"Units: {self.units.upper()}", 1.2)
        self._show_loading(f"Switching units to {self.units.upper()}...")
        self.refresh_all(force=True, allow_offline=True)
        self._save_cfg()
        return True

    def _toggle_time_format(self) -> bool:
        self.use_24h = not self.use_24h
        self._flash("Toggled time format.", 1.2)
        self._save_cfg()
        return True

    def _toggle_pause(self) -> bool:
        self.paused = not self.paused
        self._flash("Paused." if self.paused else "Resumed.", 1.2)
        return True

    def _toggle_graphs(self) -> bool:
        self.show_graph_panel_on_current = not self.show_graph_panel_on_current
        self._flash(
            "Graph panel ON" if self.show_graph_panel_on_current else "Graph panel OFF",
            1.2,
        )
        self._save_cfg()
        return True

    def _toggle_radar(self) -> bool:
        self.show_radar_map = not self.show_radar_map
        if self.show_radar_map:
            self._radar_last = 0.0
        self._flash("Radar map ON" if self.show_radar_map else "Radar map OFF", 1.2)
        self._save_cfg()
        return True

    def _open_radar(self) -> bool:
        url = "https://mrms.nssl.noaa.gov/qvs/product_viewer/"
        subprocess.Popen(
            ["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._flash(f"Opened {url}", 5.0)
        return True

    def _scroll(self, direction: int) -> bool:
        scroll_handlers = {
            "forecast": lambda: setattr(self, "fc_scroll", self.fc_scroll + direction),
            "alerts": lambda: setattr(
                self, "alert_scroll", self.alert_scroll + direction
            ),
            "hourly": lambda: setattr(self, "hr_scroll", self.hr_scroll + direction),
        }
        handler = scroll_handlers.get(self.view)
        if handler:
            handler()
        return True

    def _draw(self) -> None:
        self.stdscr.erase()
        rows, cols = self.stdscr.getmaxyx()
        self._radar_map_x = 0
        self._radar_map_y = 0
        self._radar_map_cols = 0
        self._radar_map_rows = 0

        if rows < MIN_ROWS or cols < MIN_COLS:
            safe_addstr(
                self.stdscr,
                0,
                0,
                f"Terminal too small ({cols}x{rows}). Need at least {MIN_COLS}x{MIN_ROWS}.",
                curses.color_pair(4) | curses.A_BOLD,
            )
            safe_addstr(self.stdscr, 2, 0, "Resize and try again. Press q to quit.")
            self.stdscr.refresh()
            return

        draw_header(self, rows, cols)

        body_top = 3
        body_h = rows - body_top - 2
        body_w = cols - 2
        win = self.stdscr.derwin(body_h, body_w, body_top, 1)

        view_drawers = {
            "current": draw_current,
            "forecast": draw_forecast,
            "hourly": draw_hourly,
            "alerts": draw_alerts,
            "help": draw_help,
        }
        drawer = view_drawers.get(self.view)
        if drawer:
            drawer(self, win)

        draw_footer(self, rows, cols)
        self.stdscr.refresh()


def _parse_field(value, field_name: str):
    """Parse field based on field name for state loading."""
    if value is None:
        return None
    if field_name in ("start", "end", "sent", "effective", "expires", "timestamp"):
        return parse_iso(value) if isinstance(value, str) else None
    if field_name in (
        "temperature",
        "wind_speed_num",
        "pop",
        "humidity_pct",
        "pressure_pa",
        "visibility_m",
        "wind_mps",
        "wind_dir_deg",
        "gust_mps",
    ):
        return value if isinstance(value, (int, float)) else None
    if field_name == "is_daytime":
        return value if isinstance(value, bool) else None
    return value


def main(stdscr) -> None:
    cfg = load_config()
    signal.signal(signal.SIGINT, lambda *_: None)
    app = App(stdscr, cfg)
    app.run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
