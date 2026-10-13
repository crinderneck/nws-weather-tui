"""Correctness of computed values against independent sources.

Sunrise/sunset: Open-Meteo (8 days) and USNO (around the next DST change).
Moon: USNO phase instants, moonrise/moonset and illumination.
Rain totals: re-derived here from the raw NWS gridpoint QPF in the fixtures by
time-weighted overlap (the app instead spreads each window over its hours),
then checked against the app's numbers and against what the screens show.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import time
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from harness.locations import (
    HTTP_FIXTURES_DIR,
    LOCATIONS,
    MANIFEST_PATH,
    REFERENCE_DIR,
    SNAPSHOT_DIR,
)

SUN_TOLERANCE_S = 120   # Open-Meteo/USNO publish whole minutes; refraction models differ
MOON_TOLERANCE_S = 180


@contextlib.contextmanager
def local_tz(tz: str) -> Iterator[None]:
    """Process-local time zone (the app formats in the machine's zone)."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def _ref(loc: str) -> Dict[str, Any]:
    with open(os.path.join(REFERENCE_DIR, f"{loc}_sun.json"), encoding="utf-8") as f:
        return json.load(f)


def _wall(day: str, hhmm: str) -> dt.datetime:
    """Naive local datetime from '2026-10-13' + '07:08' (or USNO's '07:08  DT')."""
    return dt.datetime.fromisoformat(f"{day}T{hhmm.split()[0][:5]}")


def _naive_local(t: dt.datetime) -> dt.datetime:
    return t.astimezone().replace(tzinfo=None)


def _fixture(predicate: Any) -> Dict[str, Any]:
    for name in sorted(os.listdir(HTTP_FIXTURES_DIR)):
        with open(os.path.join(HTTP_FIXTURES_DIR, name), encoding="utf-8") as f:
            rec = json.load(f)
        if predicate(rec["url"]):
            return rec.get("json") or json.loads(rec["text"])
    raise LookupError("no matching fixture")


def _snapshot(loc: str, size: str, view: str) -> List[str]:
    with open(os.path.join(SNAPSHOT_DIR, loc, size, f"{view}.txt"), encoding="utf-8") as f:
        return f.read().splitlines()


# ---------------------------------------------------------------------------
# Sunrise / sunset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_sun_times_match_open_meteo(loc: str) -> None:
    from nws_weather_tui.helpers import get_sunrise_sunset

    ref = _ref(loc)
    info = LOCATIONS[loc]
    with local_tz(ref["timezone"]):
        for day, want in ref["days"].items():
            rise, sset = get_sunrise_sunset(info["lat"], info["lon"], dt.date.fromisoformat(day))
            for got, key in ((rise, "sunrise"), (sset, "sunset")):
                assert got is not None, f"{loc} {day} {key} missing"
                want_t = dt.datetime.fromisoformat(want[key])
                err = abs((_naive_local(got) - want_t).total_seconds())
                assert err <= SUN_TOLERANCE_S, f"{loc} {day} {key}: {got} vs {want[key]}"


@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_sun_times_across_dst_change(loc: str) -> None:
    """Days either side of a clock change, against USNO. The days straddle
    the change, so whatever today's date, one of them has a different UTC
    offset from now: code that converts with today's fixed offset is an hour
    off there. (Deliberately not under freezegun, whose astimezone() is
    DST-aware and would hide exactly that bug.)"""
    from nws_weather_tui.formatting import fmt_time
    from nws_weather_tui.helpers import get_sunrise_sunset

    ref = _ref(loc)
    info = LOCATIONS[loc]
    with local_tz(ref["timezone"]):
        for day, usno in ref["dst_days"].items():
            rise, sset = get_sunrise_sunset(info["lat"], info["lon"], dt.date.fromisoformat(day))
            for got, phen in ((rise, "Rise"), (sset, "Set")):
                want = _wall(day, usno[phen])
                err = abs((_naive_local(got) - want).total_seconds())
                assert err <= SUN_TOLERANCE_S, f"{loc} {day} {phen}: {got} vs USNO {want}"
                # ...and that's also what gets printed.
                shown = dt.datetime.strptime(f"{day} {fmt_time(got, True)}", "%Y-%m-%d %H:%M")
                assert abs((shown - want).total_seconds()) <= SUN_TOLERANCE_S, (
                    f"{loc} {day} {phen} displayed as {fmt_time(got, True)}, USNO {want:%H:%M}"
                )


_DATE_RE = re.compile(r"([A-Z][a-z]{2}) (\d{1,2})\b")
_SUN_RE = re.compile(r"↑(\d{1,2}:\d{2}[ap]m)\s+↓(\d{1,2}:\d{2}[ap]m)")


@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_forecast_screen_shows_correct_sun_times(loc: str) -> None:
    """End to end: the ↑/↓ times printed under each day on the forecast screen."""
    ref = _ref(loc)
    year = ref["today"][:4]
    lines = _snapshot(loc, "200x60", "forecast")
    dates = [dt.datetime.strptime(f"{m} {d} {year}", "%b %d %Y").date()
             for m, d in _DATE_RE.findall(lines[3])]
    suns = next(_SUN_RE.findall(line) for line in lines if _SUN_RE.search(line))
    assert dates and len(dates) == len(suns), (lines[3], suns)
    for day, (rise_s, set_s) in zip(dates, suns):
        want = ref["days"][day.isoformat()]
        for shown, key in ((rise_s, "sunrise"), (set_s, "sunset")):
            got = dt.datetime.strptime(f"{day} {shown}", "%Y-%m-%d %I:%M%p")
            err = abs((got - dt.datetime.fromisoformat(want[key])).total_seconds())
            assert err <= SUN_TOLERANCE_S, f"{loc} {day} {key} shown {shown}, ref {want[key]}"


# ---------------------------------------------------------------------------
# Moon
# ---------------------------------------------------------------------------

def _usno_phases() -> List[Tuple[str, dt.datetime]]:
    with open(os.path.join(REFERENCE_DIR, "usno_moon_phases.json"), encoding="utf-8") as f:
        return [(p["phase"], dt.datetime.fromisoformat(p["utc"])) for p in json.load(f)["phases"]]


def test_moon_phase_instants_match_usno() -> None:
    from nws_weather_tui.moon import next_moon_phases

    usno = _usno_phases()
    with local_tz("UTC"):
        got: List[Tuple[str, dt.datetime]] = []
        day = usno[0][1].date()
        while len(got) < len(usno):
            for name, when in next_moon_phases(day):
                if not got or when > got[-1][1]:
                    got.append((name, when))
            day = got[-1][1].date() + dt.timedelta(days=1)
    for (name, when), (want_name, want) in zip(got, usno):
        assert name == want_name
        assert abs((when - want).total_seconds()) <= MOON_TOLERANCE_S, f"{name}: {when} vs {want}"


def test_moon_illumination_at_phases() -> None:
    from nws_weather_tui.moon import moon_illumination_at

    expect = {"New Moon": (0.0, 0.01), "Full Moon": (0.99, 1.0),
              "First Quarter": (0.47, 0.53), "Last Quarter": (0.47, 0.53)}
    for name, when in _usno_phases():
        lo, hi = expect[name]
        assert lo <= moon_illumination_at(when) <= hi, f"{name} at {when}"


@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_moonrise_moonset_match_usno(loc: str) -> None:
    from nws_weather_tui.moon import get_moonrise_moonset

    ref = _ref(loc)
    info = LOCATIONS[loc]
    usno = ref["moon_today"]["moon"]
    with local_tz(ref["timezone"]):
        rise, mset = get_moonrise_moonset(info["lat"], info["lon"],
                                          dt.date.fromisoformat(ref["today"]))
        for got, phen in ((rise, "Rise"), (mset, "Set")):
            if phen not in usno:
                assert got is None, f"{loc}: USNO has no moon {phen}, app says {got}"
                continue
            assert got is not None, f"{loc}: moon {phen} missing (USNO {usno[phen]})"
            want = _wall(ref["today"], usno[phen])
            assert abs((_naive_local(got) - want).total_seconds()) <= MOON_TOLERANCE_S


@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_moon_illumination_matches_usno(loc: str) -> None:
    from nws_weather_tui.moon import moon_illumination_at

    ref = _ref(loc)
    day = dt.date.fromisoformat(ref["today"])
    with local_tz(ref["timezone"]):
        # USNO's fraction is for local noon, rounded to a whole percent.
        noon = dt.datetime(day.year, day.month, day.day, 12).astimezone()
        want = float(ref["moon_today"]["fracillum"].rstrip("%")) / 100
        assert abs(moon_illumination_at(noon) - want) <= 0.015


@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_moon_screen_shows_rise_and_set(loc: str) -> None:
    text = "\n".join(_snapshot(loc, "120x40", "moon"))
    assert "install 'astral'" not in text
    assert re.search(r"Moonrise\s+\d{1,2}:\d{2}[ap]m", text), text
    assert re.search(r"Moonset\s+\d{1,2}:\d{2}[ap]m", text), text


# ---------------------------------------------------------------------------
# Rain totals
# ---------------------------------------------------------------------------

_DUR_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?)?$")


def _qpf_windows(grid: Dict[str, Any]) -> List[Tuple[dt.datetime, dt.datetime, float]]:
    out = []
    for v in grid["properties"]["quantitativePrecipitation"]["values"]:
        start_s, dur = v["validTime"].split("/")
        days, hours = (int(x or 0) for x in _DUR_RE.match(dur).groups())  # type: ignore[union-attr]
        start = dt.datetime.fromisoformat(start_s.replace("Z", "+00:00"))
        out.append((start, start + dt.timedelta(days=days, hours=hours), float(v["value"] or 0)))
    return out


def _expected_mm(windows: List[Tuple[dt.datetime, dt.datetime, float]],
                 lo: dt.datetime, hi: dt.datetime) -> float:
    """QPF falling within [lo, hi), assuming a steady rate inside each window."""
    total = 0.0
    for start, end, mm in windows:
        overlap = (min(end, hi) - max(start, lo)).total_seconds()
        if overlap > 0:
            total += mm * overlap / (end - start).total_seconds()
    return total


def _hourly_for(loc: str) -> Tuple[List[Any], List[Tuple[dt.datetime, dt.datetime, float]]]:
    from nws_weather_tui.models import extract_grid_series, extract_hourly, merge_grid_into_hourly

    points = _fixture(lambda u: u.endswith(
        f"/points/{LOCATIONS[loc]['lat']:.4f},{LOCATIONS[loc]['lon']:.4f}"))
    props = points["properties"]
    hourly = extract_hourly(_fixture(lambda u: u.startswith(props["forecastHourly"])))
    grid = _fixture(lambda u: u == props["forecastGridData"])
    merge_grid_into_hourly(hourly, extract_grid_series(grid))
    return hourly, _qpf_windows(grid)


@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_rain_total_matches_gridpoint_qpf(loc: str) -> None:
    hourly, windows = _hourly_for(loc)
    lo, hi = hourly[0].start, hourly[-1].start + dt.timedelta(hours=1)
    want = _expected_mm(windows, lo, hi)
    got = sum(h.precip_mm or 0.0 for h in hourly)
    assert got == pytest.approx(want, abs=0.05), f"{loc}: app {got:.2f} mm vs QPF {want:.2f} mm"


def _local_days(hourly: List[Any]) -> List[dt.date]:
    return sorted({h.start.astimezone().date() for h in hourly})


@pytest.mark.parametrize("loc", sorted(LOCATIONS))
def test_rain_totals_on_hourly_screen(loc: str) -> None:
    """The total in the Precip highlight and each day's 'wet' cell (200x60
    day grid) agree with the QPF, to the 0.01 in the screen shows."""
    hourly, windows = _hourly_for(loc)
    with local_tz(str(LOCATIONS[loc]["tz"])):
        lo, hi = hourly[0].start, hourly[-1].start + dt.timedelta(hours=1)
        total_in = _expected_mm(windows, lo, hi) / 25.4
        days = _local_days(hourly)
        per_day_in = []
        for d in days:
            start = dt.datetime(d.year, d.month, d.day).astimezone()
            end = (dt.datetime(d.year, d.month, d.day) + dt.timedelta(days=1)).astimezone()
            per_day_in.append(_expected_mm(windows, max(start, lo), min(end, hi)) / 25.4)

    lines = _snapshot(loc, "200x60", "hourly")
    precip = next(line for line in lines if line.strip().startswith("Precip"))
    m = re.search(r"· (\d+\.\d\d) in\b", precip)
    if total_in * 25.4 >= 0.25:  # the screen only quotes a total from 0.25 mm up
        assert m, precip
        assert float(m.group(1)) == pytest.approx(total_in, abs=0.006), precip
    else:
        assert m is None, precip

    wet = next(line for line in lines if line.strip().startswith("wet"))
    cells = [c.strip() for c in wet.split("│")[1:]]
    assert len(cells) == len(days), (wet, days)
    for d, cell, want in zip(days, cells, per_day_in):
        if want * 25.4 < 0.25:
            assert cell == "dry", f"{loc} {d}: {cell!r}, QPF {want:.3f} in"
        else:
            shown = float(re.match(r"(\d+\.\d\d) in precip", cell).group(1))  # type: ignore[union-attr]
            assert shown == pytest.approx(want, abs=0.006), f"{loc} {d}: {cell!r} vs {want:.3f}"


def test_fixtures_include_some_rain() -> None:
    """The rain checks above mean little if every location is dry."""
    assert any(
        sum(h.precip_mm or 0 for h in _hourly_for(loc)[0]) >= 2.5 for loc in LOCATIONS
    )


def test_manifest_frozen_after_recording() -> None:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        m = json.load(f)
    assert m["frozen_at"] >= m["recorded_at"]
