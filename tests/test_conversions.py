"""Unit conversions against exact definitions and standard values.

The snapshots catch a changed conversion only until someone accepts the new
rendering; these pin the numbers themselves.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("fn,value,want", [
    ("mps_to_mph", 1.0, 3600 / 1609.344),       # international mile, exact
    ("mps_to_mph", 44.704, 100.0),
    ("c_to_f", -40.0, -40.0),
    ("c_to_f", 0.0, 32.0),
    ("c_to_f", 100.0, 212.0),
    ("c_to_f", 37.0, 98.6),
    ("pa_to_inhg", 101325.0, 29.9213),          # standard atmosphere
    ("m_to_mi", 1609.344, 1.0),
    ("m_to_mi", 16093.44, 10.0),                # the usual "10 mi" visibility
    ("mm_to_in", 25.4, 1.0),
    ("mm_to_in", 6.35, 0.25),
])
def test_conversion(fn: str, value: float, want: float) -> None:
    from nws_weather_tui import conversions

    assert getattr(conversions, fn)(value) == pytest.approx(want, abs=1e-4)


@pytest.mark.parametrize("fn", ["mps_to_mph", "c_to_f", "pa_to_inhg", "m_to_mi", "mm_to_in"])
def test_missing_stays_missing(fn: str) -> None:
    """None (no reading) must not turn into 0 or 32°F."""
    from nws_weather_tui import conversions

    assert getattr(conversions, fn)(None) is None


@pytest.mark.parametrize("temp_c,rh,want_c", [
    (20.0, 50.0, 9.3),     # NOAA dewpoint calculator: 9.3 °C
    (30.0, 70.0, 23.9),    # 23.9 °C
    (0.0, 80.0, -3.0),     # -3.0 °C
    (25.0, 100.0, 25.0),   # saturated: dew point is the temperature
])
def test_dewpoint(temp_c: float, rh: float, want_c: float) -> None:
    from nws_weather_tui.conversions import dewpoint_c

    assert dewpoint_c(temp_c, rh) == pytest.approx(want_c, abs=0.15)


@pytest.mark.parametrize("temp_c,rh", [(None, 50.0), (20.0, None), (20.0, 0.0), (20.0, -5.0)])
def test_dewpoint_without_a_valid_reading(temp_c: object, rh: object) -> None:
    from nws_weather_tui.conversions import dewpoint_c

    assert dewpoint_c(temp_c, rh) is None  # type: ignore[arg-type]
