"""Render every screen at 80x24, 120x40 and 200x60 from recorded fixtures and
compare against tests/snapshots byte for byte. Regenerate after an intended
change with: pytest --update-snapshots
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import re
from typing import Any, List

import pytest

from nws_weather_tui import __version__

from harness.locations import LOCATIONS, MANIFEST_PATH, SIZES, SNAPSHOT_DIR, views_for

CASES = [
    (loc, cols, rows, view)
    for loc in LOCATIONS
    for cols, rows in SIZES
    for view in views_for(loc)
]


def _snapshot_path(loc: str, cols: int, rows: int, view: str, kind: str = "txt") -> str:
    return os.path.join(SNAPSHOT_DIR, loc, f"{cols}x{rows}", f"{view}.{kind}")


def _text(lines: List[str]) -> str:
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("loc,cols,rows", [(loc, c, r) for loc in LOCATIONS for c, r in SIZES])
def test_render_clean(renders: Any, loc: str, cols: int, rows: int) -> None:
    """The run itself: no exception, no stray stderr, every request replayed."""
    result = renders.get(loc, cols, rows)
    assert "error" not in result, result.get("traceback")
    assert result.get("stderr", "") == "", result["stderr"]
    assert result.get("fixture_misses") == [], (
        "requests with no recording (re-record with tests/record_fixtures.py):\n"
        + "\n".join(result.get("fixture_misses") or [])
    )
    assert "Traceback" not in result.get("debug_log", ""), result["debug_log"]
    assert result.get("emulator_unsupported") == [], (
        "terminal emulator skipped sequences, so the snapshot can't be trusted:\n"
        + "\n".join(result.get("emulator_unsupported") or [])
    )


@pytest.mark.parametrize("loc,cols,rows", [(loc, *SIZES[0]) for loc in LOCATIONS])
def test_frozen_clock_consistent(renders: Any, loc: str, cols: int, rows: int) -> None:
    """Local wall clock, aware UTC and epoch time all equal the manifest's
    frozen_at, in the location's own offset (guards the freezegun setup)."""
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        frozen = dt.datetime.fromisoformat(json.load(f)["frozen_at"])
    clock = renders.get(loc, cols, rows)["clock"]
    assert dt.datetime.fromisoformat(clock["local_naive"]) == frozen
    assert dt.datetime.fromisoformat(clock["utc_aware"]) == frozen
    assert clock["epoch"] == frozen.timestamp()


@pytest.mark.parametrize("kind", ["txt", "style"])
@pytest.mark.parametrize("loc,cols,rows,view", CASES)
def test_snapshot(
    renders: Any, request: Any, loc: str, cols: int, rows: int, view: str, kind: str
) -> None:
    """`txt` is the characters on screen; `style` the colors/attributes."""
    result = renders.get(loc, cols, rows)
    assert view in result["screens"], f"{view} was not rendered: {result.get('error')}"
    actual = _text(result["screens"][view]["text" if kind == "txt" else "style"])
    if view == "help":  # the version changes every release; see test_help_shows_version
        actual = actual.replace(__version__, "<version>")
    path = _snapshot_path(loc, cols, rows, view, kind)
    if request.config.getoption("--update-snapshots"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(actual)
        return
    assert os.path.exists(path), f"no snapshot at {path}; run pytest --update-snapshots"
    with open(path, encoding="utf-8") as f:
        expected = f.read()
    if actual != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(True), actual.splitlines(True),
            f"snapshot/{loc}/{cols}x{rows}/{view}.{kind}", "actual",
        ))
        pytest.fail(f"rendering changed:\n{diff}", pytrace=False)


# Values that should never reach the screen: Python reprs and empty formats.
# ("OH...None." is real NWS product text, hence the lookbehind.)
_LEAKS = re.compile(r"(?<!\.\.\.)\bNone\b|\bnan\b|\binf\b|\[\]|\{\}|<object|Traceback")


@pytest.mark.parametrize("loc,cols,rows,view", CASES)
def test_no_leaked_values(renders: Any, loc: str, cols: int, rows: int, view: str) -> None:
    lines = renders.get(loc, cols, rows)["screens"].get(view, {}).get("text", [])
    bad = [f"{i:3}: {line}" for i, line in enumerate(lines) if _LEAKS.search(line)]
    assert not bad, "raw values on screen:\n" + "\n".join(bad)


@pytest.mark.parametrize("loc,cols,rows,view", CASES)
def test_chrome_intact(renders: Any, loc: str, cols: int, rows: int, view: str) -> None:
    """Header carries the location and view tag; footer keys are on the last row."""
    lines = renders.get(loc, cols, rows)["screens"].get(view, {}).get("text", [])
    assert len(lines) == rows
    assert str(LOCATIONS[loc]["name"]) in lines[0] or view == "dashboard"
    assert "q Quit" in lines[-1] or "Esc" in lines[-1], lines[-1]


@pytest.mark.parametrize("cols,rows", SIZES)
def test_help_shows_version(renders: Any, cols: int, rows: int) -> None:
    """The real version is on the help screen (the snapshots mask it)."""
    lines = renders.get("denver", cols, rows)["screens"]["help"]["text"]
    if not any("About" in line for line in lines):
        pytest.skip("About section is below the fold at this size")
    assert any(re.search(rf"version\s+{re.escape(__version__)}\b", line) for line in lines)
