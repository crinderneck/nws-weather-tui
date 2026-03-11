#!/usr/bin/env python3
"""
NWS Weather TUI — Favorites management and editor.
"""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING

from geo import clamp

if TYPE_CHECKING:
    from app import App


def toggle_favorite(app: "App") -> bool:
    eps = 1e-4
    idx = next(
        (
            i for i, f in enumerate(app.favorites)
            if abs(float(f.get("lat", 0)) - app.lat) < eps
            and abs(float(f.get("lon", 0)) - app.lon) < eps
        ),
        None,
    )
    if idx is not None:
        app.favorites.pop(idx)
        app._flash("Removed from favorites.", 1.2)
    else:
        app.favorites.append(
            {"name": app.location_name, "lat": app.lat, "lon": app.lon}
        )
        app._flash("Added to favorites.", 1.2)
    app.fav_idx = clamp(app.fav_idx, 0, max(0, len(app.favorites) - 1))
    app._save_cfg()
    return True


def cycle_favorite(app: "App", direction: int) -> bool:
    if not app.favorites:
        app._flash("No favorites yet. Press F to add this location.", 2.0)
        return True
    app.fav_idx = (app.fav_idx + direction) % len(app.favorites)
    f = app.favorites[app.fav_idx]
    try:
        app._apply_location(
            str(f.get("name") or "Favorite"), float(f["lat"]), float(f["lon"])
        )
    except (KeyError, TypeError, ValueError):
        app._flash("Favorite is invalid (missing lat/lon).", 2.0)
    return True


def handle_favorites_key(app: "App", ch: int) -> bool:
    if ch in (ord("e"), 27):  # e or Escape -> exit editor
        app.view = "current"
        return True
    if ch in (ord("q"), ord("Q")):
        return False
    if ch in (curses.KEY_DOWN, ord("j")):
        _fav_edit_move_cursor(app, 1)
    elif ch in (curses.KEY_UP, ord("k")):
        _fav_edit_move_cursor(app, -1)
    elif ch == ord("d"):
        _fav_edit_delete(app)
    elif ch == ord("r"):
        _fav_edit_rename(app)
    elif ch == ord("a"):
        _fav_edit_add(app)
    elif ch == ord("J"):
        _fav_edit_reorder(app, 1)
    elif ch == ord("K"):
        _fav_edit_reorder(app, -1)
    elif ch in (curses.KEY_ENTER, 10, 13):
        _fav_edit_select(app)
    return True


def _fav_edit_move_cursor(app: "App", direction: int) -> None:
    if not app.favorites:
        return
    app.fav_edit_idx = clamp(
        app.fav_edit_idx + direction, 0, len(app.favorites) - 1
    )


def _fav_edit_delete(app: "App") -> None:
    if not app.favorites:
        return
    removed = app.favorites.pop(app.fav_edit_idx)
    app._flash(f"Deleted: {removed.get('name', '—')}", 1.5)
    app.fav_edit_idx = clamp(app.fav_edit_idx, 0, max(0, len(app.favorites) - 1))
    app._save_cfg()


def _fav_edit_rename(app: "App") -> None:
    if not app.favorites:
        return
    old = str(app.favorites[app.fav_edit_idx].get("name", ""))
    from input_handler import prompt_line
    new_name = prompt_line(app, f"Rename '{old}' to: ")
    if new_name:
        app.favorites[app.fav_edit_idx]["name"] = new_name
        app._flash(f"Renamed to: {new_name}", 1.5)
        app._save_cfg()
    else:
        app._flash("Rename canceled.", 1.2)


def _fav_edit_add(app: "App") -> None:
    from input_handler import prompt_line
    q = prompt_line(app, "Add favorite (city/state or ZIP): ")
    if q is None or not q.strip():
        app._flash("Add canceled.", 1.2)
        return
    try:
        app._show_loading("Searching location...")
        g = app.client.geocode_us(q.strip())
        if not g:
            app._flash(f"No match found for '{q}'.", 2.5)
            return
        name, lat, lon = g
        app.favorites.append({"name": name, "lat": lat, "lon": lon})
        app.fav_edit_idx = len(app.favorites) - 1
        app._flash(f"Added: {name}", 1.5)
        app._save_cfg()
    except Exception as e:
        app._flash(f"Add failed: {e}", 3.5)


def _fav_edit_reorder(app: "App", direction: int) -> None:
    if not app.favorites:
        return
    new_idx = app.fav_edit_idx + direction
    if new_idx < 0 or new_idx >= len(app.favorites):
        return
    fav = app.favorites
    fav[app.fav_edit_idx], fav[new_idx] = fav[new_idx], fav[app.fav_edit_idx]
    app.fav_edit_idx = new_idx
    app._save_cfg()


def _fav_edit_select(app: "App") -> None:
    if not app.favorites:
        return
    f = app.favorites[app.fav_edit_idx]
    try:
        app.view = "current"
        app._apply_location(
            str(f.get("name") or "Favorite"), float(f["lat"]), float(f["lon"])
        )
        app._flash(f"Jumped to: {f.get('name', '—')}", 1.8)
    except (KeyError, TypeError, ValueError):
        app._flash("Favorite is invalid (missing lat/lon).", 2.0)
