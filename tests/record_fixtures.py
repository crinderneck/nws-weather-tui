#!/usr/bin/env python3
"""Re-record the HTTP fixtures, second-source reference data and manifest.

  .venv/bin/python tests/record_fixtures.py                 # full re-record
  .venv/bin/python tests/record_fixtures.py --missing-only  # after a layout change
  .venv/bin/python tests/record_fixtures.py --reference-only  # second-source values only

A full run wipes tests/fixtures/http, drives the real app against the live APIs for every
location and terminal size (so radar requests match each layout), fetches
Open-Meteo sunrise/sunset as an independent reference for the sun tests, and
freezes replay time at the end of the recording. Snapshots will need
regenerating afterwards: pytest --update-snapshots.

--missing-only keeps every existing response, the manifest and the reference
data, and fetches just the requests the current code makes that have no
recording yet (e.g. radar frames for a panel size that changed). Run it soon
after the full recording: the radar frames it fetches are pinned to the
recorded MRMS time extent, which only covers the past ~2 hours.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness.locations import (  # noqa: E402
    HTTP_FIXTURES_DIR,
    LOCATIONS,
    MANIFEST_PATH,
    REFERENCE_DIR,
    SIZES,
)

REFERENCE_DAYS = 8  # covers the ~156h hourly forecast


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def record_http(missing_only: bool = False) -> None:
    if not missing_only:
        shutil.rmtree(HTTP_FIXTURES_DIR, ignore_errors=True)
    os.makedirs(HTTP_FIXTURES_DIR, exist_ok=True)
    driver = os.path.join(HERE, "harness", "driver.py")
    for location in LOCATIONS:
        for cols, rows in SIZES:
            with tempfile.NamedTemporaryFile(suffix=".json") as out:
                print(f"recording {location} {cols}x{rows}", flush=True)
                proc = subprocess.run(
                    [sys.executable, driver, "--mode", "record", "--location", location,
                     "--cols", str(cols), "--rows", str(rows), "--out", out.name],
                    timeout=600,
                )
                result = json.load(open(out.name, encoding="utf-8"))
                if proc.returncode != 0:
                    sys.exit(f"recording failed: {result.get('traceback') or result}")


USNO = "https://aa.usno.navy.mil/api"
# USNO rejects requests without a browser-like or descriptive User-Agent.
USNO_HEADERS = {"User-Agent": "nws-weather-tui test fixtures (reference data)"}
STANDARD_OFFSET_H = {"America/Denver": -7, "America/New_York": -5, "America/Los_Angeles": -8}


def _in_tz(tz: str, fn):  # type: ignore[no-untyped-def]
    """Run fn() with the process local zone set to `tz` (no zoneinfo needed)."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def _local_date(tz: str, instant: dt.datetime) -> dt.date:
    return _in_tz(tz, lambda: instant.astimezone().date())


def _next_dst_change(tz: str, start: dt.date) -> dt.date:
    """First local day on or after `start` whose noon is on the other side of
    a DST switch from the day before."""
    def find() -> dt.date:
        def isdst(d: dt.date) -> int:
            noon = time.mktime((d.year, d.month, d.day, 12, 0, 0, 0, 0, -1))
            return time.localtime(noon).tm_isdst
        d = start
        while isdst(d) == isdst(d - dt.timedelta(days=1)):
            d += dt.timedelta(days=1)
        return d
    return _in_tz(tz, find)


def _usno_oneday(loc: Dict[str, Any], day: dt.date) -> Dict[str, Any]:
    r = requests.get(
        f"{USNO}/rstt/oneday",
        params={"date": day.isoformat(), "coords": f"{loc['lat']},{loc['lon']}",
                "tz": STANDARD_OFFSET_H[str(loc["tz"])], "dst": "true"},
        headers=USNO_HEADERS, timeout=30,
    )
    r.raise_for_status()
    data = r.json()["properties"]["data"]
    def events(key: str) -> Dict[str, str]:
        return {e["phen"]: e["time"] for e in data.get(key, [])}
    return {"sun": events("sundata"), "moon": events("moondata"),
            "curphase": data.get("curphase"), "fracillum": data.get("fracillum")}


def record_reference(frozen_at: dt.datetime) -> None:
    """Second-source values for the correctness tests."""
    os.makedirs(REFERENCE_DIR, exist_ok=True)
    for name, loc in LOCATIONS.items():
        tz = str(loc["tz"])
        today = _local_date(tz, frozen_at)
        end = today + dt.timedelta(days=REFERENCE_DAYS - 1)
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["lat"], "longitude": loc["lon"],
                "daily": "sunrise,sunset", "timezone": tz,
                "start_date": today.isoformat(), "end_date": end.isoformat(),
            },
            timeout=20,
        )
        r.raise_for_status()
        daily = r.json()["daily"]
        change = _next_dst_change(tz, today)
        ref = {
            "source": "Open-Meteo daily sunrise/sunset; USNO for the DST days and the moon",
            "timezone": tz,
            "today": today.isoformat(),
            "days": {
                d: {"sunrise": rise, "sunset": sset}
                for d, rise, sset in zip(daily["time"], daily["sunrise"], daily["sunset"])
            },
            # Local wall-clock times from USNO with US DST rules applied.
            "dst_change": change.isoformat(),
            "dst_days": {
                d.isoformat(): _usno_oneday(loc, d)["sun"]
                for d in (change - dt.timedelta(days=1), change, change + dt.timedelta(days=1))
            },
            "moon_today": _usno_oneday(loc, today),
        }
        with open(os.path.join(REFERENCE_DIR, f"{name}_sun.json"), "w") as f:
            json.dump(ref, f, indent=1, sort_keys=True)
            f.write("\n")

    r = requests.get(f"{USNO}/moon/phases/date",
                     params={"date": frozen_at.date().isoformat(), "nump": 8},
                     headers=USNO_HEADERS, timeout=30)
    r.raise_for_status()
    phases = [
        {"phase": p["phase"],
         "utc": f"{p['year']:04d}-{p['month']:02d}-{p['day']:02d}T{p['time']}:00+00:00"}
        for p in r.json()["phasedata"]
    ]
    with open(os.path.join(REFERENCE_DIR, "usno_moon_phases.json"), "w") as f:
        json.dump({"source": "USNO moon phases API", "phases": phases}, f, indent=1)
        f.write("\n")


def main() -> None:
    if "--reference-only" in sys.argv[1:]:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            record_reference(dt.datetime.fromisoformat(json.load(f)["frozen_at"]))
        print("reference data refreshed")
        return
    if "--missing-only" in sys.argv[1:]:
        before = len(os.listdir(HTTP_FIXTURES_DIR))
        record_http(missing_only=True)
        print(f"recorded {len(os.listdir(HTTP_FIXTURES_DIR)) - before} missing responses")
        return
    recorded_at = _utc_now()
    record_http()
    frozen_at = _utc_now()
    record_reference(dt.datetime.fromisoformat(frozen_at))
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "recorded_at": recorded_at,
            # Replay freezes the clock here: after every recorded response, so
            # nothing (radar frames, observations) appears to be from the future.
            "frozen_at": frozen_at,
            "locations": LOCATIONS,
        }, f, indent=1, sort_keys=True)
        f.write("\n")
    n = len(os.listdir(HTTP_FIXTURES_DIR))
    size = sum(os.path.getsize(os.path.join(HTTP_FIXTURES_DIR, p))
               for p in os.listdir(HTTP_FIXTURES_DIR))
    print(f"recorded {n} responses ({size / 1e6:.1f} MB), frozen_at={frozen_at}")


if __name__ == "__main__":
    main()
