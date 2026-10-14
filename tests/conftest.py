from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Tuple

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)

from harness.locations import LOCATIONS, SIZES  # noqa: E402

DRIVER = os.path.join(TESTS_DIR, "harness", "driver.py")


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--update-snapshots", action="store_true",
        help="rewrite tests/snapshots from the current rendering instead of comparing",
    )


def run_driver(location: str, cols: int, rows: int, *extra: str,
               timeout: float = 300) -> Dict[str, Any]:
    """Run harness/driver.py once; `extra` are further driver arguments
    (--views, --keys, --home, --fixture-dir)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.json")
        proc = subprocess.run(
            [sys.executable, DRIVER, "--location", location,
             "--cols", str(cols), "--rows", str(rows), "--out", out, *extra],
            capture_output=True, text=True, timeout=timeout,
        )
        if not os.path.exists(out):
            return {"error": f"driver crashed (rc={proc.returncode})",
                    "traceback": proc.stderr, "screens": {}}
        with open(out, encoding="utf-8") as f:
            return json.load(f)


class Renders:
    """Every (location, size) rendered once per session, in parallel."""

    def __init__(self) -> None:
        self._results: Dict[Tuple[str, int, int], Dict[str, Any]] = {}

    def prime(self) -> None:
        jobs = [(loc, c, r) for loc in LOCATIONS for c, r in SIZES]
        with ThreadPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 4)) as pool:
            for key, result in zip(jobs, pool.map(lambda j: run_driver(*j), jobs)):
                self._results[key] = result

    def get(self, location: str, cols: int, rows: int) -> Dict[str, Any]:
        key = (location, cols, rows)
        if key not in self._results:
            self.prime()
        return self._results[key]


@pytest.fixture(scope="session")
def renders() -> Renders:
    return Renders()
