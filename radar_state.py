#!/usr/bin/env python3
"""
NWS Weather TUI — Radar state management, animation, and background fetch.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import threading
import time
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from constants import RADAR_LAST_PNG_PATH, ensure_dir
from geo import bbox_around, clamp, expand_bbox_km
from helpers import dbg
from models import RadarFrame
from overlays import city_overlay_and_hits_for_bbox, png_to_line_overlay, vector_lines_overlay
from radar_decode import png_to_ascii, png_to_halfblock_radar

if TYPE_CHECKING:
    from app import App


def reset_radar_state(app: "App") -> None:
    app._radar_frames = []
    app._radar_frame_idx = 0
    app._radar_anim_playing = False
    app._radar_cells = []
    app._radar_ascii = []
    app._radar_kind = []
    app._radar_ts_ms = 0
    app._radar_ts_utc = ""
    app._radar_state_overlay = []
    app._radar_city_overlay = []
    app._radar_city_hitmap = {}
    app._radar_err = None
    app._radar_last = 0.0
    app._radar_src_cols = 0
    app._radar_src_rows = 0
    app._radar_map_x = 0
    app._radar_map_y = 0
    app._radar_map_cols = 0
    app._radar_map_rows = 0


def set_current_radar_frame(app: "App") -> None:
    """Copy data from the current animation frame index to display state."""
    if not app._radar_frames:
        return
    idx = clamp(app._radar_frame_idx, 0, len(app._radar_frames) - 1)
    f = app._radar_frames[idx]
    app._radar_cells = f.cells
    app._radar_ascii = f.ascii_lines
    app._radar_kind = f.kind_lines
    app._radar_ts_ms = f.timestamp_ms
    app._radar_ts_utc = ts_ms_to_utc_str(f.timestamp_ms)


def ts_ms_to_utc_str(ts_ms: int) -> str:
    if not ts_ms:
        return "—"
    try:
        ts_dt = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc)
        return ts_dt.strftime("%H:%Mz")
    except Exception:
        return "—"


def save_radar_png(png: bytes) -> None:
    try:
        ensure_dir(os.path.dirname(RADAR_LAST_PNG_PATH))
        tmp = RADAR_LAST_PNG_PATH + ".tmp"
        with open(tmp, "wb") as f:
            f.write(png)
        os.replace(tmp, RADAR_LAST_PNG_PATH)
    except Exception as e:
        dbg(f"RADAR save failed: {e}")


def toggle_radar_anim(app: "App") -> bool:
    if len(app._radar_frames) < 2:
        app._flash("Animation requires ≥2 frames. Try refreshing (r).", 2.5)
        return True
    app._radar_anim_playing = not app._radar_anim_playing
    if app._radar_anim_playing:
        app._radar_anim_last = time.time()
        app._flash(
            f"Animation ON  ({len(app._radar_frames)} frames)", 1.5
        )
    else:
        app._flash("Animation OFF", 1.2)
    return True


def step_radar_frame(app: "App", direction: int) -> bool:
    if not app._radar_frames:
        return True
    n = len(app._radar_frames)
    app._radar_frame_idx = (app._radar_frame_idx + direction) % n
    set_current_radar_frame(app)
    app._radar_anim_playing = False
    return True


def maybe_refresh_radar(app: "App", target_cols: int, target_rows: int) -> None:
    if not app.show_radar_map:
        return
    if app._bg_radar_running:
        return
    ttl = int(app.cfg.get("cache_ttls", {}).get("radar", 300))
    if (
        (time.time() - app._radar_last) < ttl
        and (app._radar_cells or app._radar_ascii)
        and app._radar_src_cols == target_cols
        and app._radar_src_rows == target_rows
    ):
        return

    try:
        from PIL import Image as _PIL_Image  # noqa: F401
    except ImportError:
        app._radar_ascii = ["(install pillow to render radar map)"]
        app._radar_kind = []
        app._radar_state_overlay = []
        app._radar_city_hitmap = {}
        app._radar_err = "pillow missing"
        app._radar_last = time.time()
        return

    radar_cfg = dict(app.cfg.get("radar", {}) or {})
    ramp = str(radar_cfg.get("ascii_ramp", " .:-=+*#%@"))
    show_state_lines = bool(radar_cfg.get("show_state_lines", True))
    show_city_labels = bool(radar_cfg.get("show_city_labels", True))
    max_city_labels = int(radar_cfg.get("max_city_labels", 20))
    n_frames = int(radar_cfg.get("animation_frames", 8))
    step_min = int(radar_cfg.get("animation_step_min", 5))

    bbox = app.client.state_bbox(app.state_code) if app.state_code else None
    bbox = (
        expand_bbox_km(bbox, 20.0)
        if bbox
        else bbox_around(app.lat, app.lon, 300.0)
    )

    minlon, minlat, maxlon, maxlat = bbox
    cos_lat = abs(math.cos(math.radians((minlat + maxlat) / 2)))
    geo_aspect = ((maxlon - minlon) * cos_lat) / max(1e-9, maxlat - minlat)
    req_h = max(64, target_rows * 12)
    req_w = max(64, int(req_h * geo_aspect))

    app._radar_bbox = bbox
    app._radar_src_cols = target_cols
    app._radar_src_rows = target_rows
    app._radar_last = time.time()
    app._bg_radar_running = True
    app._is_loading = True
    app.status_msg = "/ Loading radar..."
    app.status_until = time.time() + 3600

    ctx = {
        "radar_station": app.radar_station or "",
        "bbox": bbox,
        "req_w": req_w, "req_h": req_h,
        "target_cols": target_cols, "target_rows": target_rows,
        "has_256color": app._radar_has_256color,
        "ramp": ramp,
        "show_state_lines": show_state_lines,
        "show_city_labels": show_city_labels,
        "max_city_labels": max_city_labels,
        "n_frames": n_frames, "step_min": step_min,
        "lat": app.lat, "lon": app.lon,
        "state_code": app.state_code,
        "anim_playing": app._radar_anim_playing,
    }
    threading.Thread(
        target=_bg_radar_fetch, args=(app, ctx, app._bg_generation), daemon=True
    ).start()


def _bg_radar_fetch(app: "App", ctx: Dict[str, Any], gen: int) -> None:
    """Run in background thread — fetches radar frames + overlays."""
    result: Dict[str, Any] = {"ok": False}
    try:
        raw_frames = app.client.radar_frames_png(
            ctx["radar_station"], ctx["bbox"],
            ctx["req_w"], ctx["req_h"],
            n_frames=ctx["n_frames"], step_minutes=ctx["step_min"],
        )
        if not raw_frames:
            raise RuntimeError("radar returned no frames")

        new_frames: List[RadarFrame] = []
        for fi, (png, ts_ms) in enumerate(raw_frames):
            if fi == len(raw_frames) - 1:
                save_radar_png(png)
            if ctx["has_256color"]:
                cells = png_to_halfblock_radar(png, ctx["target_cols"], ctx["target_rows"])
                if not any(fg or bg for row in cells for _, fg, bg in row):
                    dbg(f"RADAR skipping blank frame ts={ts_ms}")
                    continue
                ascii_lines, kind_lines = [], []
            else:
                cells = []
                ascii_lines, kind_lines = png_to_ascii(
                    png, ctx["target_cols"], ctx["target_rows"], ctx["ramp"]
                )
                if not any(ch != " " for line in ascii_lines for ch in line):
                    dbg(f"RADAR skipping blank frame ts={ts_ms}")
                    continue
            new_frames.append(RadarFrame(
                cells=cells, ascii_lines=ascii_lines,
                kind_lines=kind_lines, timestamp_ms=ts_ms,
            ))
        if not new_frames:
            png, ts_ms = raw_frames[-1]
            if ctx["has_256color"]:
                cells = png_to_halfblock_radar(png, ctx["target_cols"], ctx["target_rows"])
                new_frames.append(RadarFrame(
                    cells=cells, ascii_lines=[], kind_lines=[], timestamp_ms=ts_ms,
                ))
            else:
                ascii_lines, kind_lines = png_to_ascii(
                    png, ctx["target_cols"], ctx["target_rows"], ctx["ramp"]
                )
                new_frames.append(RadarFrame(
                    cells=[], ascii_lines=ascii_lines,
                    kind_lines=kind_lines, timestamp_ms=ts_ms,
                ))
        result["frames"] = new_frames

        state_overlay: List[str] = []
        city_overlay: List[str] = []
        city_hitmap: Dict[Tuple[int, int], Tuple[str, float, float]] = {}

        if ctx["show_state_lines"]:
            try:
                feats = app.client.state_lines_features(ctx["bbox"], ctx["state_code"])
                state_overlay = vector_lines_overlay(
                    feats, ctx["bbox"], ctx["target_cols"], ctx["target_rows"], mark="|"
                )
                if not any(state_overlay):
                    ol, out_bbox = app.client.state_lines_png(
                        ctx["bbox"], ctx["req_w"], ctx["req_h"]
                    )
                    if ol:
                        state_overlay = png_to_line_overlay(
                            ol, ctx["target_cols"], ctx["target_rows"],
                            mark="|", src_bbox=out_bbox, dst_bbox=ctx["bbox"],
                        )
            except Exception as oe:
                dbg(f"RADAR state-lines overlay failed: {oe}")

        if ctx["show_city_labels"]:
            city_overlay, city_hitmap = city_overlay_and_hits_for_bbox(
                ctx["target_cols"], ctx["target_rows"], ctx["bbox"],
                max_labels=ctx["max_city_labels"],
                here=(ctx["lat"], ctx["lon"]),
            )

        result["state_overlay"] = state_overlay
        result["city_overlay"] = city_overlay
        result["city_hitmap"] = city_hitmap
        result["anim_playing"] = ctx["anim_playing"]
        result["ok"] = True

    except Exception as e:
        result["error"] = str(e)
        dbg(f"RADAR refresh failed: {e}")

    result["_gen"] = gen
    with app._bg_lock:
        app._bg_radar_pending = result


def apply_bg_radar(app: "App") -> None:
    """Main-thread: apply completed background radar results."""
    with app._bg_lock:
        result = app._bg_radar_pending
        app._bg_radar_pending = None
    if result is None:
        return
    if result.get("_gen") != app._bg_generation:
        app._bg_radar_running = False
        return
    app._bg_radar_running = False
    app._is_loading = app._bg_weather_running
    app._radar_last = time.time()

    if result.get("ok"):
        frames = result["frames"]
        app._radar_frames = frames
        if not result.get("anim_playing"):
            app._radar_frame_idx = len(frames) - 1
        set_current_radar_frame(app)
        app._radar_state_overlay = result.get("state_overlay", [])
        app._radar_city_overlay = result.get("city_overlay", [])
        app._radar_city_hitmap = result.get("city_hitmap", {})
        app._radar_err = None
        if not app._bg_weather_running:
            app._flash("Radar updated.", 1.1)
    else:
        app._radar_cells = []
        app._radar_ascii = []
        app._radar_kind = []
        app._radar_state_overlay = []
        app._radar_city_overlay = []
        app._radar_city_hitmap = {}
        app._radar_err = result.get("error", "unknown")
