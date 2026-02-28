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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import curses

from client import NWSClient
from constants import (
    DEFAULT_CONFIG,
    MIN_COLS,
    MIN_ROWS,
    N_RADAR_COLORS,
    NWS_RADAR_PALETTE,
    RADAR_LAST_PNG_PATH,
    ensure_dir,
    load_config,
    radar_curses_color,
    radar_dual_pair,
    radar_single_pair,
)
from formatting import fmt_time, parse_iso
from geo import bbox_around, clamp, expand_bbox_km
from helpers import dbg, safe_addstr
from overlays import city_overlay_and_hits_for_bbox, png_to_line_overlay, vector_lines_overlay
from persistence import load_app_state, save_app_config, save_app_state
from radar_decode import RadarCell, png_to_ascii, png_to_halfblock_radar
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
    draw_radar_view,
)


@dataclass
class RadarFrame:
    """One radar animation frame."""
    cells: List[List[RadarCell]]   # halfblock cells (empty if 256-color unavailable)
    ascii_lines: List[str]          # ASCII fallback lines
    kind_lines: List[str]           # ASCII kind classification lines
    timestamp_ms: int               # MRMS epoch ms (UTC)
    source: str = "mrms"            # "mrms" | "iem" | "wms"


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

        # --- API client ---
        self.client = NWSClient(
            user_agent=str(cfg.get("user_agent", DEFAULT_CONFIG["user_agent"])),
            timeout=self.timeout,
            ttls=dict(cfg.get("cache_ttls", DEFAULT_CONFIG["cache_ttls"])),
        )

        # --- UI state ---
        self.view: str = "current"
        self.paused: bool = False
        self.status_msg: str = ""
        self.status_until: float = 0.0
        self._spinner_idx: int = 0
        self._spinner_frames = ["|", "/", "-", "\\"]
        self._is_loading: bool = False
        self._in_refresh: bool = False

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

        # --- Radar state ---
        self._radar_frames: List[RadarFrame] = []
        self._radar_frame_idx: int = 0
        self._radar_anim_playing: bool = False
        self._radar_anim_last: float = 0.0
        self._radar_anim_interval: float = float(
            dict(cfg.get("radar", {}) or {}).get("animation_interval_s", 0.5)
        )

        # Current frame display data (derived from _radar_frames[_radar_frame_idx])
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
        self._init_curses()
        self._radar_has_256color = self._init_radar_colors()

        self._load_points()
        self.refresh_all(force=True, allow_offline=True)

    # ------------------------------------------------------------------
    # Curses initialisation
    # ------------------------------------------------------------------

    def _init_curses(self) -> None:
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        # UI color pairs 1-19
        curses.init_pair(1,  curses.COLOR_CYAN,    -1)  # header, info
        curses.init_pair(2,  curses.COLOR_YELLOW,  -1)  # highlights, forecast header
        curses.init_pair(3,  curses.COLOR_GREEN,   -1)  # OK, temperature
        curses.init_pair(4,  curses.COLOR_RED,     -1)  # errors, alerts
        curses.init_pair(5,  curses.COLOR_MAGENTA, -1)  # header right, PoP bar
        curses.init_pair(6,  curses.COLOR_BLUE,    -1)  # wind sparkline
        curses.init_pair(7,  curses.COLOR_RED,     -1)  # temp sparkline
        curses.init_pair(8,  curses.COLOR_CYAN,    -1)  # radar default (ASCII)
        curses.init_pair(9,  curses.COLOR_GREEN,   -1)  # radar rain (ASCII)
        curses.init_pair(10, curses.COLOR_BLUE,    -1)  # radar snow (ASCII)
        curses.init_pair(11, curses.COLOR_MAGENTA, -1)  # radar sleet (ASCII)
        curses.init_pair(12, curses.COLOR_WHITE,   -1)  # city dot @
        curses.init_pair(13, curses.COLOR_YELLOW,  curses.COLOR_BLACK)  # radar anim indicator
        curses.init_pair(14, curses.COLOR_WHITE,   -1)  # general bold
        curses.init_pair(15, curses.COLOR_CYAN,    -1)  # radar view title
        try:
            mask = curses.ALL_MOUSE_EVENTS | getattr(curses, "REPORT_MOUSE_POSITION", 0)
            curses.mousemask(mask)
            curses.mouseinterval(0)
        except curses.error:
            pass

    def _init_radar_colors(self) -> bool:
        """Initialise NWS radar colors and all needed pairs for 256-color mode.

        Color IDs 16-29 are assigned to the 14 NWS radar palette entries.
        Pair  20-33: single-color radar cells (fg=NWS color, bg=default)
        Pair  34-229: dual-color radar halfblock cells (fg × bg, 14×14)

        Returns True if 256-color mode was successfully initialised.
        """
        try:
            if curses.COLORS < 256 or not curses.can_change_color():
                return False
            # Init custom colors
            for i, (_, _, _, r1k, g1k, b1k, *_rest) in enumerate(NWS_RADAR_PALETTE):
                curses.init_color(radar_curses_color(i + 1), r1k, g1k, b1k)
            # Single-color pairs (fg=nws, bg=transparent)
            for nws_idx in range(1, N_RADAR_COLORS + 1):
                curses.init_pair(
                    radar_single_pair(nws_idx),
                    radar_curses_color(nws_idx),
                    -1,
                )
            # Dual-color pairs (fg=nws_fg, bg=nws_bg) for ▀ halfblocks
            for fg in range(1, N_RADAR_COLORS + 1):
                for bg in range(1, N_RADAR_COLORS + 1):
                    pair_num = radar_dual_pair(fg, bg)
                    if pair_num < 256:
                        curses.init_pair(
                            pair_num,
                            radar_curses_color(fg),
                            radar_curses_color(bg),
                        )
            return True
        except curses.error as e:
            dbg(f"256-color radar init failed: {e}")
            return False

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
    # Radar PNG persistence
    # ------------------------------------------------------------------

    def _save_radar_png(self, png: bytes) -> None:
        try:
            ensure_dir(os.path.dirname(RADAR_LAST_PNG_PATH))
            tmp = RADAR_LAST_PNG_PATH + ".tmp"
            with open(tmp, "wb") as f:
                f.write(png)
            os.replace(tmp, RADAR_LAST_PNG_PATH)
        except Exception as e:
            dbg(f"RADAR save failed: {e}")

    # ------------------------------------------------------------------
    # Radar timestamp
    # ------------------------------------------------------------------

    @staticmethod
    def _ts_ms_to_utc_str(ts_ms: int) -> str:
        if not ts_ms:
            return "—"
        try:
            ts_dt = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc)
            return ts_dt.strftime("%H:%Mz")
        except Exception:
            return "—"

    # ------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------

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
        if self.view not in ("current", "radar") or not self.show_radar_map:
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

    # ------------------------------------------------------------------
    # Input prompt
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Location actions
    # ------------------------------------------------------------------

    def _search_location(self) -> bool:
        q = self._prompt_line("Location (city/state or ZIP): ")
        if q is None or not q.strip():
            self._flash("Location search canceled.", 1.4)
            return True
        try:
            self._show_loading("Searching location...")
            g = self.client.geocode_us(q.strip())
            if not g:
                self._flash(f"No match found for '{q}'.", 2.5)
                return True
            name, lat, lon = g
            self._apply_location(name, lat, lon)
            self._flash(f"Location set: {name}", 1.8)
        except Exception as e:
            self._flash(f"Location search failed: {e}", 3.5)
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
        self._reset_radar_state()
        self._in_refresh = True
        self._show_loading(f"Switching location to {name}...")
        self._load_points()
        self.refresh_all(force=True, allow_offline=True)
        self._save_cfg()

    def _reset_radar_state(self) -> None:
        self._radar_frames = []
        self._radar_frame_idx = 0
        self._radar_anim_playing = False
        self._radar_cells = []
        self._radar_ascii = []
        self._radar_kind = []
        self._radar_ts_ms = 0
        self._radar_ts_utc = ""
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

    # ------------------------------------------------------------------
    # Config / state persistence (delegated to persistence module)
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

    def _pick_station(self) -> None:
        if not self.stations_url:
            return
        stations = self.client.stations(self.stations_url)
        feats = stations.get("features", []) or []
        if feats:
            sid = ((feats[0] or {}).get("properties", {}) or {}).get("stationIdentifier")
            if isinstance(sid, str) and sid:
                self.station_id = sid

    def _save_state(self) -> None:
        save_app_state(self)

    def _load_state(self) -> bool:
        return load_app_state(self)

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    def _toggle_favorite(self) -> bool:
        eps = 1e-4
        idx = next(
            (
                i for i, f in enumerate(self.favorites)
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
        except (KeyError, TypeError, ValueError):
            self._flash("Favorite is invalid (missing lat/lon).", 2.0)
        return True

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

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
            self._show_loading("Saving snapshot...")
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

    # ------------------------------------------------------------------
    # Radar refresh
    # ------------------------------------------------------------------

    def _maybe_refresh_radar(self, target_cols: int, target_rows: int) -> None:
        if not self.show_radar_map:
            return
        ttl = int(self.cfg.get("cache_ttls", {}).get("radar", 300))
        if (
            (time.time() - self._radar_last) < ttl
            and (self._radar_cells or self._radar_ascii)
            and self._radar_src_cols == target_cols
            and self._radar_src_rows == target_rows
        ):
            return

        try:
            from PIL import Image as _PIL_Image  # noqa: F401
        except ImportError:
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
        n_frames = int(radar_cfg.get("animation_frames", 4))
        step_min = int(radar_cfg.get("animation_step_min", 5))

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
            # Fetch animation frames
            raw_frames = self.client.radar_frames_png(
                self.radar_station or "",
                bbox,
                req_w,
                req_h,
                n_frames=n_frames,
                step_minutes=step_min,
            )
            if not raw_frames:
                raise RuntimeError("radar returned no frames")

            # Convert each raw PNG to a RadarFrame
            new_frames: List[RadarFrame] = []
            for png, ts_ms in raw_frames:
                self._save_radar_png(png)
                if self._radar_has_256color:
                    cells = png_to_halfblock_radar(png, target_cols, target_rows)
                    ascii_lines, kind_lines = [], []
                else:
                    cells = []
                    ascii_lines, kind_lines = png_to_ascii(
                        png, target_cols, target_rows, ramp
                    )
                new_frames.append(RadarFrame(
                    cells=cells,
                    ascii_lines=ascii_lines,
                    kind_lines=kind_lines,
                    timestamp_ms=ts_ms,
                ))
            self._radar_frames = new_frames
            # If animation is off, show the latest frame
            if not self._radar_anim_playing:
                self._radar_frame_idx = len(new_frames) - 1
            self._set_current_radar_frame()

            # Overlays (shared across all frames since same bbox)
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
                                ol, target_cols, target_rows,
                                mark="|", src_bbox=out_bbox, dst_bbox=bbox,
                            )
                except Exception as oe:
                    dbg(f"RADAR state-lines overlay failed: {oe}")

            if show_city_labels:
                self._radar_city_overlay, self._radar_city_hitmap = (
                    city_overlay_and_hits_for_bbox(
                        target_cols, target_rows, bbox,
                        max_labels=max_city_labels,
                        here=(self.lat, self.lon),
                    )
                )
            self._radar_err = None

        except Exception as e:
            self._radar_cells = []
            self._radar_ascii = []
            self._radar_kind = []
            self._radar_state_overlay = []
            self._radar_city_overlay = []
            self._radar_city_hitmap = {}
            self._radar_err = str(e)
            dbg(f"RADAR refresh failed: {e}")

        self._radar_last = time.time()

    def _set_current_radar_frame(self) -> None:
        """Copy data from the current animation frame index to display state."""
        if not self._radar_frames:
            return
        idx = clamp(self._radar_frame_idx, 0, len(self._radar_frames) - 1)
        f = self._radar_frames[idx]
        self._radar_cells = f.cells
        self._radar_ascii = f.ascii_lines
        self._radar_kind = f.kind_lines
        self._radar_ts_ms = f.timestamp_ms
        self._radar_ts_utc = self._ts_ms_to_utc_str(f.timestamp_ms)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

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

        # Advance radar animation
        if self._radar_anim_playing and len(self._radar_frames) > 1:
            now = time.time()
            if now - self._radar_anim_last >= self._radar_anim_interval:
                self._radar_frame_idx = (
                    (self._radar_frame_idx + 1) % len(self._radar_frames)
                )
                self._set_current_radar_frame()
                self._radar_anim_last = now

        now = time.time()
        wait_ms = 500
        if self.next_refresh and not self.paused:
            wait_ms = min(wait_ms, max(50, int((self.next_refresh - now) * 1000)))
        if self.status_msg and now < self.status_until:
            wait_ms = min(wait_ms, max(50, int((self.status_until - now) * 1000)))
        if self._radar_anim_playing and self._radar_frames:
            wait_ms = min(wait_ms, int(self._radar_anim_interval * 1000))
        self.stdscr.timeout(clamp(wait_ms, 50, 1000))
        self._draw()

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

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
            ord("w"): lambda: self._toggle_radar_view(),
            ord("l"): self._search_location,
            ord("r"): self._do_refresh,
            ord("u"): self._toggle_units,
            ord("t"): self._toggle_time_format,
            ord("p"): self._toggle_pause,
            ord("g"): self._toggle_graphs,
            ord("A"): self._toggle_radar_anim,
            ord("o"): self._open_radar_browser,
            ord("["): lambda: self._cycle_favorite(-1),
            ord("]"): lambda: self._cycle_favorite(1),
            ord("n"): lambda: self._cycle_favorite(1),
            ord("b"): lambda: self._cycle_favorite(-1),
            ord("F"): self._toggle_favorite,
        }
        handler = key_handlers.get(ch)
        if handler:
            return handler()  # type: ignore[return-value]
        if ch in (curses.KEY_DOWN, ord("j")):
            self._scroll(1)
        elif ch in (curses.KEY_UP, ord("k")):
            self._scroll(-1)
        elif ch in (curses.KEY_LEFT, ord("<")):
            self._step_radar_frame(-1)
        elif ch in (curses.KEY_RIGHT, ord(">")):
            self._step_radar_frame(1)
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

    def _do_refresh(self) -> bool:
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

    def _toggle_radar_view(self) -> bool:
        """Toggle between the radar view and the current conditions view."""
        if self.view == "radar":
            self.view = "current"
        else:
            self.view = "radar"
            # Ensure radar is enabled
            self.show_radar_map = True
            self._save_cfg()
        return True

    def _toggle_radar_anim(self) -> bool:
        if len(self._radar_frames) < 2:
            self._flash("Animation requires ≥2 frames. Try refreshing (r).", 2.5)
            return True
        self._radar_anim_playing = not self._radar_anim_playing
        if self._radar_anim_playing:
            self._radar_anim_last = time.time()
            self._flash(
                f"Animation ON  ({len(self._radar_frames)} frames)", 1.5
            )
        else:
            self._flash("Animation OFF", 1.2)
        return True

    def _step_radar_frame(self, direction: int) -> bool:
        if not self._radar_frames:
            return True
        n = len(self._radar_frames)
        self._radar_frame_idx = (self._radar_frame_idx + direction) % n
        self._set_current_radar_frame()
        self._radar_anim_playing = False
        return True

    def _open_radar_browser(self) -> bool:
        url = "https://radar.weather.gov/"
        try:
            subprocess.Popen(
                ["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
        self._flash(f"Opened {url}", 3.0)
        return True

    def _scroll(self, direction: int) -> None:
        if self.view == "forecast":
            self.fc_scroll += direction
        elif self.view == "alerts":
            self.alert_scroll += direction
        elif self.view == "hourly":
            self.hr_scroll += direction

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
                f"Terminal too small ({cols}×{rows}). Need ≥{MIN_COLS}×{MIN_ROWS}.",
                curses.color_pair(4) | curses.A_BOLD,
            )
            safe_addstr(self.stdscr, 2, 0, "Resize and try again.  Press q to quit.")
            self.stdscr.refresh()
            return

        draw_header(self, rows, cols)

        body_top = 3
        body_h = rows - body_top - 2
        body_w = cols - 2
        win = self.stdscr.derwin(body_h, body_w, body_top, 1)

        drawers = {
            "current": draw_current,
            "forecast": draw_forecast,
            "hourly": draw_hourly,
            "alerts": draw_alerts,
            "help": draw_help,
            "radar": draw_radar_view,
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
