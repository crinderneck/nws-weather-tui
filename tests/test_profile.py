"""The profiler (tests/profile_app.py) runs end to end and reports every screen."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict

import pytest

from harness.locations import views_for

PROFILE_APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_app.py")


def _profile(tmp_path: Any, passes: str) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, PROFILE_APP, "--passes", passes, "--locations", "denver",
         "--sizes", "80x24", "--repeat", "3", "--out", str(tmp_path)],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with open(tmp_path / "results.json", encoding="utf-8") as f:
        return {r["pass"]: r["result"] for r in json.load(f)["runs"]}


def test_timing_and_flame_cover_startup_phases_and_every_screen(tmp_path: Any) -> None:
    runs = _profile(tmp_path, "timing,flame")
    views = views_for("denver")

    timing = runs["timing"]
    assert timing["startup"]["total_ms"] > 0
    assert timing["fixture_misses"] == []
    assert {"weather.fetch", "weather.apply", "radar.fetch"} <= {e["phase"] for e in timing["phases"]}
    assert list(timing["screens_profile"]) == views
    for view, screen in timing["screens_profile"].items():
        assert screen["draws"]["n"] == 3, view
        assert 0 < screen["draws"]["min_ms"] <= screen["draws"]["median_ms"], view

    flame = runs["flame"]["flame_files"]
    assert {"startup", "thread-weather.fetch"} | {f"screen-{v}" for v in views} <= set(flame)
    for path in flame.values():
        assert os.path.getsize(path) > 0
    # Session durations are real time, not the replay's frozen clock.
    with open(flame["startup"].replace(".html", ".txt"), encoding="utf-8") as f:
        assert "0.000 run" not in f.read()
    assert (tmp_path / "index.html").exists()


def test_large_sizes_preset_and_which_sizes_must_run_live() -> None:
    from profile_app import LARGE_SIZES, needs_live, parse_sizes

    assert parse_sizes("120x40,large,120x40") == [(120, 40)] + LARGE_SIZES
    assert all(c > 200 and r > 60 for c, r in LARGE_SIZES)
    assert needs_live(parse_sizes("80x24,120x40,200x60")) == []  # recorded
    assert needs_live(parse_sizes("200x60,large")) == LARGE_SIZES  # radar never recorded there


@pytest.mark.slow
def test_memory_pass_attributes_allocations_to_the_app(tmp_path: Any) -> None:
    memory = _profile(tmp_path, "memory")["memory"]
    assert memory["startup"]["memory"]["peak_kib"] > 0
    sites = [s["site"] for v in memory["screens_profile"].values()
             for s in v["memory"]["top_sites"]]
    assert not [s for s in sites if "pyte" in s], "harness emulator allocations leaked in"
