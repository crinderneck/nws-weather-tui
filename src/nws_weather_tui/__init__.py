"""
NWS Weather TUI — a terminal weather app powered by the National Weather Service API.

Kept free of imports so ``import nws_weather_tui.<module>`` (e.g. from tests)
doesn't pull in curses and the whole app. The entry point is
``nws_weather_tui.__main__:run``.
"""

__version__ = "0.2.2"
