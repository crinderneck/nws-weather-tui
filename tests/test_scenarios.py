"""End-to-end runs of the real app that the snapshot pass doesn't cover:
driving it from the keyboard, and starting without the network.

Each runs harness/driver.py once in its own process, like the snapshots.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from conftest import run_driver


def _clean(result: Dict[str, Any]) -> None:
    assert "error" not in result, result.get("traceback")
    assert result.get("stderr", "") == "", result["stderr"]
    assert "Traceback" not in result.get("debug_log", ""), result["debug_log"]


def test_keyboard_session() -> None:
    """Keys typed into the terminal, through curses and the real main loop:
    edit the favorites, switch views, toggle the clock, quit. What was
    changed must be on disk afterwards."""
    keys = (
        "e"        # favorites editor (Denver, Columbus, Ventura; cursor on Denver)
        "<down>"   # cursor to Columbus: an escape sequence curses has to decode
        "K"        # move Columbus up       -> Columbus, Denver, Ventura
        "jj"       # cursor to Ventura
        "d"        # delete it              -> Columbus, Denver
        "e"        # leave the editor
        "f"        # forecast
        "t"        # 24-hour clock
        "?"        # help
        "q"
    )
    result = run_driver("denver", 120, 40, "--keys", keys, timeout=120)
    _clean(result)
    assert result.get("fixture_misses") == []
    final = result["final"]
    assert final["view"] == "help"
    assert final["use_24h"] is True
    assert final["favorites"] == ["Columbus, OH", "Denver, CO"]
    saved = result["config"]
    assert [f["name"] for f in saved["favorites"]] == ["Columbus, OH", "Denver, CO"]
    assert saved["use_24h"] is True
    screen = "\n".join(result["screens"]["final"]["text"])
    assert "Favorites editor" in screen  # the help page is what was on screen


def test_offline_start_without_saved_state(tmp_path: Any) -> None:
    """No network and nothing cached: every screen still draws, marked
    offline, instead of crashing or printing raw values."""
    empty = tmp_path / "no-recordings"
    empty.mkdir()
    result = run_driver("denver", 120, 40, "--fixture-dir", str(empty), timeout=120)
    _clean(result)
    assert result["fixture_misses"], "expected every request to miss"
    for view, screen in result["screens"].items():
        text = "\n".join(screen["text"])
        assert "[OFFLINE]" in screen["text"][0], (view, screen["text"][0])
        assert "None" not in text and "nan" not in text, (view, text)


def test_supplementary_failures_stay_online(tmp_path: Any) -> None:
    """Gridpoint data, forecast discussions/outlooks, air quality and UV are
    extras: when only they fail, the app stays online and draws the rest."""
    from harness.recordings import records

    def supplementary(url: str) -> bool:
        return bool(re.search(r"/gridpoints/\w+/\d+,\d+$", url)  # raw grid data
                    or "/products" in url                         # AFD, HWO
                    or "open-meteo.com" in url)                   # air quality, UV

    partial = tmp_path / "partial"
    partial.mkdir()
    kept = 0
    for rec in records():
        if supplementary(rec["url"]):
            continue
        name = rec.pop("file")
        with open(partial / name, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        kept += 1
    assert kept > 0
    result = run_driver("denver", 120, 40, "--fixture-dir", str(partial),
                        "--views", "current,forecast,hourly,afd,hwo", timeout=120)
    _clean(result)
    # Without the AQ/UV rows the radar panel is a different size, so its
    # requests aren't in the recording either; radar failures are reported
    # separately and never mark the app offline.
    radar_hosts = ("mapservices.weather.noaa.gov", "mesonet.agron.iastate.edu",
                   "opengeo.ncep.noaa.gov")
    missed = [u for u in result["fixture_misses"] if not any(h in u for h in radar_hosts)]
    assert missed and all(supplementary(u) for u in missed), missed
    for view, screen in result["screens"].items():
        assert "[OFFLINE]" not in screen["text"][0], (view, screen["text"][0])
    forecast = "\n".join(result["screens"]["forecast"]["text"])
    assert "Today" in forecast or "Tonight" in forecast, forecast


def test_offline_restart_shows_saved_state(tmp_path: Any) -> None:
    """Run once online (which saves state.json), then again with no
    network from the same HOME: the saved forecast and alerts come back.
    Ventura has alerts with onset/ends, which have to survive the trip."""
    home = str(tmp_path / "home")
    first = run_driver("ventura", 120, 40, "--home", home, "--views", "alerts", timeout=120)
    _clean(first)
    assert os.path.exists(os.path.join(home, ".config", "nws-weather-tui", "state.json"))
    online_alerts = first["screens"]["alerts"]["text"]

    empty = tmp_path / "no-recordings"
    empty.mkdir()
    second = run_driver("ventura", 120, 40, "--home", home, "--fixture-dir", str(empty),
                        "--views", "current,forecast,alerts", timeout=120)
    _clean(second)
    for view in ("current", "forecast", "alerts"):
        assert "[OFFLINE]" in second["screens"][view]["text"][0], view
    # Same alerts, same hazard windows, as when they were fetched.
    assert second["screens"]["alerts"]["text"][1:-1] == online_alerts[1:-1]
