#!/usr/bin/env python3
"""
NWS Weather TUI — Main application.
"""

from __future__ import annotations

import re
import signal
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import curses

from client import NWSClient
from constants import (
    DEFAULT_CONFIG,
    MIN_COLS,
    MIN_ROWS,
    STATE_PATH,
    load_config,
    save_json,
)
from curses_init import init_curses, init_radar_colors
from geo import clamp
from helpers import safe_addstr
from input_handler import handle_key
from models import (
    AlertItem,
    CurrentConditions,
    ForecastPeriod,
    HourlyPeriod,
    RadarFrame,
)
from persistence import load_app_state, save_app_config
from radar_decode import RadarCell
from radar_state import reset_radar_state
from views import (
    draw_header,
    draw_footer,
    draw_current,
    draw_forecast,
    draw_hourly,
    draw_alerts,
    draw_help,
    draw_moon,
    draw_favorites,
)
from weather_refresh import refresh_all


class App:
    def __init__(self, stdscr, cfg: Dict[str, Any]) -> None:
        self.stdscr = stdscr
        self.cfg = cfg

        # --- Location & preferences ---
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
        self.fav_edit_idx: int = 0

        # --- API client ---
        self.client = NWSClient(
            user_agent=str(cfg.get("user_agent", DEFAULT_CONFIG["user_agent"])),
            timeout=self.timeout,
            ttls=dict(cfg.get("cache_ttls", DEFAULT_CONFIG["cache_ttls"])),
        )

        # --- UI state ---
        self.view: str = "current"
        self._prev_view: str = "current"
        self.paused: bool = False
        self.status_msg: str = ""
        self.status_until: float = 0.0
        self._spinner_idx: int = 0
        self._spinner_frames = ["|", "/", "-", "\\"]
        self._is_loading: bool = False
        self._in_refresh: bool = False
        self._bg_lock = threading.Lock()
        self._bg_generation: int = 0
        self._bg_weather_pending: Optional[Dict[str, Any]] = None
        self._bg_weather_running: bool = False
        self._bg_radar_pending: Optional[Dict[str, Any]] = None
        self._bg_radar_running: bool = False
        self._state_thread: Optional[threading.Thread] = None

        # --- NWS data ---
        self.points_data: Optional[Dict[str, Any]] = None
        self.forecast_url: Optional[str] = None
        self.hourly_url: Optional[str] = None
        self.stations_url: Optional[str] = None
        self.station_id: Optional[str] = None
        self.radar_station: Optional[str] = None
        self.state_code: Optional[str] = None

        self.current: Optional[CurrentConditions] = None
        self.forecast_periods: List[ForecastPeriod] = []
        self.hourly_periods: List[HourlyPeriod] = []
        self.alerts: List[AlertItem] = []

        self.last_refresh: float = 0.0
        self.next_refresh: float = 0.0
        self.offline_mode: bool = False
        self.offline_reason: str = ""

        # --- Scroll positions ---
        self.fc_scroll: int = 0
        self.hr_scroll: int = 0
        self.alert_scroll: int = 0
        self.alert_line_scroll: int = 0
        self.help_scroll: int = 0

        # --- Radar state ---
        self._radar_frames: List[RadarFrame] = []
        self._radar_frame_idx: int = 0
        self._radar_anim_playing: bool = False
        self._radar_anim_last: float = 0.0
        self._radar_anim_interval: float = float(
            dict(cfg.get("radar", {}) or {}).get("animation_interval_s", 0.5)
        )

        self._radar_cells: List[List[RadarCell]] = []
        self._radar_ascii: List[str] = []
        self._radar_kind: List[str] = []
        self._radar_ts_ms: int = 0
        self._radar_ts_utc: str = ""

        self._radar_state_overlay: List[str] = []
        self._radar_city_overlay: List[str] = []
        self._radar_city_hitmap: Dict[Tuple[int, int], Tuple[str, float, float]] = {}
        self._radar_last: float = 0.0
        self._radar_err: Optional[str] = None
        self._radar_bbox: Optional[Tuple[float, float, float, float]] = None
        self._radar_src_cols: int = 0
        self._radar_src_rows: int = 0
        self._radar_map_x: int = 0
        self._radar_map_y: int = 0
        self._radar_map_cols: int = 0
        self._radar_map_rows: int = 0

        # 256-color radar mode
        self._radar_has_256color: bool = False

        # --- Init curses ---
        init_curses(self.stdscr)
        self._radar_has_256color = init_radar_colors()

        try:
            self._load_points()
        except Exception:
            pass  # background refresh will retry
        refresh_all(self, force=True, allow_offline=True)

    # ------------------------------------------------------------------
    # Status / loading messages
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

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
        reset_radar_state(self)
        self._bg_generation += 1
        self._bg_weather_running = False
        self._bg_radar_running = False
        try:
            self._load_points()
        except Exception:
            pass
        refresh_all(self, force=True, allow_offline=True)
        self._save_cfg()

    # ------------------------------------------------------------------
    # Config / state persistence
    # ------------------------------------------------------------------

    def _save_cfg(self) -> None:
        save_app_config(self)

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

    def _save_state(self) -> None:
        from persistence import _build_state_dict
        snapshot = _build_state_dict(self)
        t = threading.Thread(
            target=self._write_state_bg, args=(snapshot,), daemon=False
        )
        t.start()
        self._state_thread = t

    @staticmethod
    def _write_state_bg(snapshot: dict) -> None:
        try:
            save_json(STATE_PATH, snapshot)
        except Exception:
            pass

    def _load_state(self) -> bool:
        return load_app_state(self)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.stdscr.nodelay(False)
        self.stdscr.timeout(500)
        while True:
            self._tick()
            ch = self.stdscr.getch()
            if ch != -1 and not handle_key(self, ch):
                break
        self._cleanup()

    def _cleanup(self) -> None:
        if self._state_thread is not None:
            self._state_thread.join(timeout=2.0)

    def _tick(self) -> None:
        from radar_state import apply_bg_radar, set_current_radar_frame
        from weather_refresh import apply_bg_weather

        # Apply any completed background work
        if self._bg_weather_pending is not None:
            apply_bg_weather(self)
        if self._bg_radar_pending is not None:
            apply_bg_radar(self)

        if not self.paused:
            refresh_all(self, force=False, allow_offline=True)

        # Update loading spinner
        if self._bg_weather_running or self._bg_radar_running:
            frame = self._spinner_frames[self._spinner_idx % len(self._spinner_frames)]
            self._spinner_idx += 1
            self._is_loading = True
            if self._bg_weather_running:
                self.status_msg = f"{frame} Loading weather data..."
            else:
                self.status_msg = f"{frame} Loading radar..."
            self.status_until = time.time() + 3600

        # Advance radar animation
        if self._radar_anim_playing and len(self._radar_frames) > 1:
            now = time.time()
            if now - self._radar_anim_last >= self._radar_anim_interval:
                self._radar_frame_idx = (
                    (self._radar_frame_idx + 1) % len(self._radar_frames)
                )
                set_current_radar_frame(self)
                self._radar_anim_last = now

        now = time.time()
        wait_ms = 500
        if self.next_refresh and not self.paused:
            wait_ms = min(wait_ms, max(50, int((self.next_refresh - now) * 1000)))
        if self.status_msg and now < self.status_until:
            wait_ms = min(wait_ms, max(50, int((self.status_until - now) * 1000)))
        if self._radar_anim_playing and self._radar_frames:
            wait_ms = min(wait_ms, int(self._radar_anim_interval * 1000))
        if self._bg_weather_running or self._bg_radar_running:
            wait_ms = min(wait_ms, 200)
        self.stdscr.timeout(clamp(wait_ms, 50, 1000))
        self._draw()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        self.stdscr.erase()
        rows, cols = self.stdscr.getmaxyx()
        self._radar_map_x = 0
        self._radar_map_y = 0
        self._radar_map_cols = 0
        self._radar_map_rows = 0

        if rows < MIN_ROWS or cols < MIN_COLS:
            safe_addstr(
                self.stdscr, 0, 0,
                f"Terminal too small ({cols}\u00d7{rows}). Need \u2265{MIN_COLS}\u00d7{MIN_ROWS}.",
                curses.color_pair(4) | curses.A_BOLD,
            )
            safe_addstr(self.stdscr, 2, 0, "Resize and try again.  Press q to quit.")
            self.stdscr.refresh()
            return

        draw_header(self, rows, cols)

        body_top = 3
        body_h = rows - body_top - 2
        body_w = cols - 2
        try:
            win = self.stdscr.derwin(body_h, body_w, body_top, 1)
        except curses.error:
            self.stdscr.refresh()
            return

        drawers = {
            "current": draw_current,
            "forecast": draw_forecast,
            "hourly": draw_hourly,
            "alerts": draw_alerts,
            "help": draw_help,
            "moon": draw_moon,
            "favorites": draw_favorites,
        }
        drawer = drawers.get(self.view)
        if drawer:
            drawer(self, win)

        draw_footer(self, rows, cols)

        self.stdscr.refresh()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
