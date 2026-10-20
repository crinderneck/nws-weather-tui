"""Locations outside NWS coverage (anywhere but the US and its territories).

The startup IP check and its notice, every panel's message when the
location itself is outside, refusing such places in search and favorites,
and getting back to a US location. Unit tests first, then the real app
parked in London through the driver.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from conftest import run_driver
from test_error_paths import ScriptedSession, _nws, no_sleep  # noqa: F401

LONDON = {"name": "London, England", "lat": 51.5074, "lon": -0.1278}
WINDSOR = (42.3149, -83.0364)  # Ontario, just across the river from Detroit
NOT_COVERED = (404, {"title": "Data Unavailable For Requested Point",
                     "type": "https://api.weather.gov/problems/InvalidPoint", "status": 404})
IPINFO_LONDON = {"ip": "81.2.69.142", "city": "London", "region": "England", "country": "GB"}


# ---------------------------------------------------------------------------
# The IP lookup
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("country,inside", [
    ("US", True), ("PR", True), ("GU", True), ("VI", True), ("AS", True), ("MP", True),
    ("GB", False), ("CA", False), ("MX", False),
])
def test_ip_country_decides_coverage(country: str, inside: bool) -> None:
    from nws_weather_tui.api.ip_locate import locate_ip

    loc = locate_ip(ScriptedSession({"ipinfo.io": (200, {"country": country})}), 3)
    assert loc is not None and loc.in_nws_area is inside


def test_ip_lookup_names_the_place() -> None:
    from nws_weather_tui.api.ip_locate import IPLocation, locate_ip

    loc = locate_ip(ScriptedSession({"ipinfo.io": (200, IPINFO_LONDON)}), 3)
    assert loc == IPLocation("GB", "London, England")


@pytest.mark.parametrize("answer", [
    (429, {"error": "rate limited"}),
    (200, {"bogon": True}),  # a private address: no country
    (200, {"country": "United Kingdom"}),
    (200, "<html>captive portal</html>"),
])
def test_ip_lookup_that_cant_tell_says_nothing(answer: Any) -> None:
    """Unknown is not "outside": no notice for a failed lookup."""
    from nws_weather_tui.api.ip_locate import locate_ip

    assert locate_ip(ScriptedSession({"ipinfo.io": answer}), 3) is None
    assert locate_ip(ScriptedSession({}), 3) is None  # offline


def _ip_app(loc: Any) -> Any:
    from nws_weather_tui.app import App

    app = SimpleNamespace(_bg_lock=threading.Lock(), _bg_ip_pending=[loc],
                          _ip_wait_until=time.time() + 5, ip_location=None, ip_notice=False)
    App._apply_ip_location(app)  # type: ignore[arg-type]
    return app


def test_ip_outside_the_us_raises_the_notice() -> None:
    from nws_weather_tui.api.ip_locate import IPLocation

    app = _ip_app(IPLocation("GB", "London, England"))
    assert app.ip_notice and app.ip_location.country == "GB"
    assert app._ip_wait_until == 0.0  # the splash stops waiting


@pytest.mark.parametrize("country", ["US", "PR", None])
def test_ip_inside_the_us_or_unknown_raises_nothing(country: Optional[str]) -> None:
    from nws_weather_tui.api.ip_locate import IPLocation

    app = _ip_app(IPLocation(country, "") if country else None)
    assert not app.ip_notice and app._ip_wait_until == 0.0


def test_notice_needs_enter_and_q_quits() -> None:
    from nws_weather_tui.input_handler import handle_key

    app = SimpleNamespace(ip_notice=True, splash=True, view="current")
    for ch in (ord("f"), ord("x"), 27, ord(" ")):  # a stray key can't dismiss it unread
        assert handle_key(app, ch) is True  # type: ignore[arg-type]
        assert app.ip_notice and app.splash and app.view == "current"
    assert handle_key(app, 10) is True  # type: ignore[arg-type]
    assert not app.ip_notice and not app.splash  # and the splash behind it is skipped
    app.ip_notice = True
    assert handle_key(app, ord("q")) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# NWS: the point isn't covered
# ---------------------------------------------------------------------------

def test_points_404_is_outside_coverage(no_sleep: List[float]) -> None:  # noqa: F811
    import requests

    from nws_weather_tui.api.client import OutsideCoverageError

    s = ScriptedSession({"/points/": NOT_COVERED})
    with pytest.raises(OutsideCoverageError) as err:
        _nws(s).points(LONDON["lat"], LONDON["lon"])
    assert isinstance(err.value, requests.HTTPError)  # older callers still catch it
    assert s.count("/points/") == 1 and no_sleep == []


@pytest.mark.parametrize("status", [400, 500])
def test_other_points_errors_are_not_outside_coverage(
    no_sleep: List[float], status: int,  # noqa: F811
) -> None:
    import requests

    from nws_weather_tui.api.client import OutsideCoverageError

    with pytest.raises(requests.HTTPError) as err:
        _nws(ScriptedSession({"/points/": (status, {})})).points(39.7392, -104.9903)
    assert not isinstance(err.value, OutsideCoverageError)


def test_refresh_outside_coverage_stops_at_points(no_sleep: List[float]) -> None:  # noqa: F811
    """No alerts, air quality or UV requests for a point the NWS doesn't know,
    and it comes back as outside, not as an error that takes the app offline."""
    from nws_weather_tui.weather_refresh import _bg_weather_fetch

    s = ScriptedSession({"/points/": NOT_COVERED})
    app = SimpleNamespace(client=_nws(s), _bg_lock=threading.Lock(), _bg_weather_pending=None)
    progress: Dict[str, Any] = {}
    ctx = {
        "lat": LONDON["lat"], "lon": LONDON["lon"], "units": "us", "points_data": None,
        "forecast_url": None, "hourly_url": None, "stations_url": None, "station_id": None,
        "hourly_hours": 0, "office_id": None, "grid_data_url": None, "state_code": None,
        "allow_offline": True, "progress": progress,
    }
    _bg_weather_fetch(app, ctx, 0)  # type: ignore[arg-type]
    result = app._bg_weather_pending
    assert result["outside"] is True and not result["ok"] and "error" not in result
    assert progress["location"] == ("fail", "outside NWS coverage")
    assert s.calls == [f"https://api.weather.gov/points/{LONDON['lat']},{LONDON['lon']}"]


def _applied(result: Dict[str, Any]) -> Any:
    from nws_weather_tui.weather_refresh import apply_bg_weather

    flashes: List[str] = []
    loads: List[int] = []
    app = SimpleNamespace(
        _bg_lock=threading.Lock(), _bg_weather_pending=dict(result, _gen=0),
        _bg_generation=0, _bg_weather_running=True, _is_loading=True,
        location_name=LONDON["name"], auto_refresh_seconds=300,
        last_refresh=0.0, next_refresh=0.0, offline_mode=True, offline_reason="earlier",
        outside_coverage=False, splash_data_in=False, startup_warning=None,
        # The last location's data, which mustn't be shown as London's.
        current=object(), forecast_periods=[object()], hourly_periods=[object()],
        alerts=[object()], area_alerts=[object()], air_quality=object(), uv_index=object(),
        afd={"text": "x"}, afd_earlier=[{"text": "y"}], hwo={"text": "z"},
        _flash=lambda msg, seconds=2.0: flashes.append(msg),
        _load_state=lambda: loads.append(1) or True,
    )
    apply_bg_weather(app)  # type: ignore[arg-type]
    app.flashes, app.loads = flashes, loads
    return app


def test_applying_outside_coverage_clears_data_and_isnt_offline() -> None:
    app = _applied({"ok": False, "outside": True})
    assert app.outside_coverage and not app.offline_mode and app.offline_reason == ""
    assert app.loads == []  # no saved data from elsewhere standing in for it
    assert app.current is None and app.air_quality is None and app.uv_index is None
    assert app.forecast_periods == app.hourly_periods == app.alerts == app.area_alerts == []
    assert app.afd is None and app.afd_earlier == [] and app.hwo is None
    assert app.next_refresh - time.time() > 250  # the usual interval, not the 60 s retry
    assert app.splash_data_in
    assert app.flashes == ["London, England is outside NWS coverage. Press l for a US location."]


def test_dashboard_marks_a_favorite_outside_coverage(no_sleep: List[float]) -> None:  # noqa: F811
    from nws_weather_tui.dashboard import _fetch_one

    app = SimpleNamespace(client=_nws(ScriptedSession({"/points/": NOT_COVERED})), units="us")
    assert _fetch_one(app, dict(LONDON)) == {"error": "outside NWS coverage"}  # type: ignore[arg-type]


def test_no_radar_fetch_outside_coverage() -> None:
    from test_units import _RadarApp

    from nws_weather_tui.radar.state import maybe_refresh_radar

    app = _RadarApp()
    app.outside_coverage = True
    app.radar.last = 0.0
    maybe_refresh_radar(app, 60, 20)  # type: ignore[arg-type]
    assert not app._bg_radar_running


# ---------------------------------------------------------------------------
# Search and favorites refuse places outside coverage
# ---------------------------------------------------------------------------

class _SearchApp:
    def __init__(self, covers: Any) -> None:
        self.flashes: List[str] = []
        self.jumps: List[Any] = []
        self.favorites: List[Dict[str, Any]] = []
        self.fav_edit_idx = 0
        self._dash_data: Dict[int, Any] = {}
        self.saves = 0
        self.covers = covers

    def _flash(self, msg: str, seconds: float = 2.0) -> None:
        self.flashes.append(msg)

    def _apply_location(self, name: str, lat: float, lon: float) -> None:
        self.jumps.append((name, lat, lon))

    def _save_cfg(self) -> None:
        self.saves += 1


@pytest.fixture
def search(monkeypatch: Any) -> Any:
    """search(typed, covers, geocoded=None) -> the app after `l` + Enter + y.
    `covers` is True/False, or an exception for NWS being unreachable."""
    from nws_weather_tui import input_handler

    def run(typed: str, covers: Any, geocoded: Any = None, fav: bool = False) -> _SearchApp:
        app = _SearchApp(covers)
        answers = iter([typed, "y"])
        monkeypatch.setattr(input_handler, "prompt_line", lambda *a, **k: next(answers))
        monkeypatch.setattr(input_handler, "geocode_with_spinner", lambda a, q: geocoded)

        def nws_covers(a: Any, lat: float, lon: float) -> bool:
            if isinstance(covers, Exception):
                raise covers
            return covers

        monkeypatch.setattr(input_handler, "nws_covers", nws_covers)
        if fav:
            from nws_weather_tui.favorites import _fav_edit_add
            _fav_edit_add(app)  # type: ignore[arg-type]
        else:
            input_handler.search_location(app)  # type: ignore[arg-type]
        return app

    return run


@pytest.mark.parametrize("typed,name", [
    ("51.5074,-0.1278", "51.5074, -0.1278"),  # London
    (f"{WINDSOR[0]},{WINDSOR[1]}", "42.3149, -83.0364"),
    ("-33.8688 151.2093", "-33.8688, 151.2093"),  # Sydney
])
def test_search_refuses_coordinates_outside_coverage(search: Any, typed: str, name: str) -> None:
    app = search(typed, covers=False)
    assert app.jumps == []
    assert app.flashes == [f"{name} is outside NWS coverage (US and territories only). "
                           "Location unchanged."]


def test_search_accepts_a_covered_point(search: Any) -> None:
    app = search("42.3314,-83.0458", covers=True)  # Detroit
    assert app.jumps == [("42.3314, -83.0458", 42.3314, -83.0458)]


def test_search_refuses_when_coverage_cant_be_checked(search: Any) -> None:
    import requests

    app = search("51.5074,-0.1278", covers=requests.ConnectionError("no route"))
    assert app.jumps == []
    assert app.flashes == ["Couldn't reach NWS to check 51.5074, -0.1278: no route. "
                           "Location unchanged."]


def test_search_for_a_foreign_name_says_us_only(search: Any) -> None:
    app = search("London", covers=True, geocoded=None)
    assert app.jumps == []
    assert app.flashes == ["No US match for 'London'. Only US places, ZIP codes and "
                           "coordinates work."]


def test_search_checks_a_geocoded_place_too(search: Any) -> None:
    """The geocoder only searches the US, but the NWS has the last word."""
    app = search("Somewhere", covers=False, geocoded=("Somewhere, XX", 10.0, 10.0))
    assert app.jumps == [] and "outside NWS coverage" in app.flashes[0]


def test_favorite_outside_coverage_isnt_added(search: Any) -> None:
    app = search("whatever", covers=False, geocoded=("Windsor, Ontario", *WINDSOR), fav=True)
    assert app.favorites == [] and app.saves == 0
    assert app.flashes == ["Windsor, Ontario is outside NWS coverage (US and territories "
                           "only). Not added."]


def test_favorite_inside_coverage_is_added(search: Any) -> None:
    app = search("San Juan", covers=True, geocoded=("San Juan, Puerto Rico", 18.4655, -66.1057),
                 fav=True)
    assert [f["name"] for f in app.favorites] == ["San Juan, Puerto Rico"]


# ---------------------------------------------------------------------------
# The real app, in London
# ---------------------------------------------------------------------------

def _fixtures(tmp_path: Any, extra: Dict[str, Any]) -> str:
    """Every recording, plus `extra` ({url: (status, json body)})."""
    from harness.recordings import records

    from nws_weather_tui.api.fixtures import fixture_name

    d = tmp_path / "http"
    d.mkdir()
    for rec in records():
        name = rec.pop("file")
        (d / name).write_text(json.dumps(rec), encoding="utf-8")
    for url, (status, body) in extra.items():
        rec = {"url": url, "status": status, "content_type": "application/json", "json": body}
        (d / fixture_name(url)).write_text(json.dumps(rec), encoding="utf-8")
    return str(d)


LONDON_POINTS = f"https://api.weather.gov/points/{LONDON['lat']:.4f},{LONDON['lon']:.4f}"


def _clean(result: Dict[str, Any]) -> None:
    assert "error" not in result, result.get("traceback")
    assert result.get("stderr", "") == "", result["stderr"]
    assert "Traceback" not in result.get("debug_log", ""), result["debug_log"]
    assert result.get("fixture_misses") == [], result.get("fixture_misses")


def _text(result: Dict[str, Any], view: str) -> str:
    return "\n".join(result["screens"][view]["text"])


PANELS = {
    "current": "current conditions or radar",
    "forecast": "forecast",
    "hourly": "hourly forecast",
    "alerts": "NWS alerts",
    "afd": "forecast discussion",
    "hwo": "hazardous weather outlook",
    "moon": "moon phase",
}


def test_every_panel_says_london_is_outside_coverage(tmp_path: Any) -> None:
    from harness.locations import favorites

    config = {"location_name": LONDON["name"], "lat": LONDON["lat"], "lon": LONDON["lon"],
              "favorites": favorites() + [dict(LONDON)]}
    result = run_driver("denver", 120, 40,
                        "--fixture-dir", _fixtures(tmp_path, {LONDON_POINTS: NOT_COVERED}),
                        "--config", json.dumps(config),
                        "--views", ",".join(list(PANELS) + ["dashboard", "splash"]),
                        timeout=120)
    _clean(result)
    for view, what in PANELS.items():
        text = _text(result, view)
        header = result["screens"][view]["text"][0]
        assert "[OUTSIDE US]" in header and "[OFFLINE]" not in header, (view, header)
        assert f"✗ No {what} for London, England" in text, (view, text)
        assert "51.5074, -0.1278 is outside National Weather Service" in text, (view, text)
        assert "Press l to choose a US location, or n for your next favorite." in text
        assert "None" not in text and "nan" not in text, (view, text)
    assert "illuminated" not in _text(result, "moon")
    dash = result["screens"]["dashboard"]["text"]
    london = next(line for line in dash[1:] if "London" in line)  # not the header
    assert "outside NWS coverage" in london
    assert any("Denver" in line and "°F" in line for line in dash)  # the rest still load
    # The splash's sky, sunrise and moon give way to the same error.
    splash = _text(result, "splash")
    assert "✗ No weather, sky or moon for London, England" in splash, splash
    assert "Press l" not in splash  # keys only skip the splash
    assert "London, England · outside NWS coverage" in splash, splash
    assert "sunrise" not in splash and "sunset" not in splash and "%" not in splash, splash
    assert "✗ location    outside NWS coverage" in splash, splash
    assert "radar       outside NWS coverage" in splash, splash


def test_ip_outside_the_us_shows_the_notice_instead_of_the_splash(tmp_path: Any) -> None:
    result = run_driver("denver", 80, 24,
                        "--fixture-dir", _fixtures(tmp_path, {
                            "https://ipinfo.io/json": (200, IPINFO_LONDON)}),
                        "--config", json.dumps({"detect_location": True, "splash": True}),
                        "--views", "splash", timeout=120)
    _clean(result)
    text = _text(result, "splash")
    assert "✗  You appear to be outside the US" in text
    assert "Your IP address places you in London, England (GB)." in text
    assert "Location: Denver, CO" in text
    assert "Enter  continue        q  quit" in text
    assert '"detect_location": false' in text


def test_ip_inside_the_us_shows_the_splash(tmp_path: Any) -> None:
    result = run_driver("denver", 80, 24,
                        "--fixture-dir", _fixtures(tmp_path, {
                            "https://ipinfo.io/json": (200, {"country": "US", "city": "Denver"})}),
                        "--config", json.dumps({"detect_location": True, "splash": True}),
                        "--views", "splash", timeout=120)
    _clean(result)
    text = _text(result, "splash")
    assert "outside the US" not in text and "any key to skip" in text


def test_enter_moves_past_the_notice(tmp_path: Any) -> None:
    """A stray key leaves the notice up; Enter goes on to the app."""
    result = run_driver("denver", 120, 40,
                        "--fixture-dir", _fixtures(tmp_path, {
                            "https://ipinfo.io/json": (200, IPINFO_LONDON)}),
                        "--config", json.dumps({"detect_location": True}),
                        "--keys", "f<enter>q", timeout=120)
    _clean(result)
    assert result["final"]["view"] == "current"  # the f went to the notice, not the app
    final = _text(result, "final")
    assert "outside the US" not in final and "Denver, CO" in final


def test_moving_from_london_to_the_us_brings_the_panels_back(tmp_path: Any) -> None:
    """n jumps to a US favorite (search is covered above: typing ahead of its
    spinner loses the keys, which is on purpose)."""
    from harness.locations import favorites

    config = {"location_name": LONDON["name"], "lat": LONDON["lat"], "lon": LONDON["lon"]}
    result = run_driver("denver", 120, 40,
                        "--fixture-dir", _fixtures(tmp_path, {LONDON_POINTS: NOT_COVERED}),
                        "--config", json.dumps(config),
                        "--keys", "nq", timeout=120)
    _clean(result)
    final = _text(result, "final")
    assert "outside NWS coverage" not in final and "[OUTSIDE US]" not in final, final
    us = {(f["lat"], f["lon"]) for f in favorites()}
    assert (result["config"]["lat"], result["config"]["lon"]) in us
