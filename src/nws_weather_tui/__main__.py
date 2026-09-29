"""
NWS Weather TUI — Entry point for ``nws-weather-tui`` and ``python -m nws_weather_tui``.
"""

from __future__ import annotations

import curses
import os
import sys
import warnings

from nws_weather_tui.app import main
from nws_weather_tui.constants import DEBUG_LOG_PATH, ensure_dir


def run() -> None:
    # Suppress DeprecationWarnings (e.g. datetime.utcfromtimestamp) and redirect
    # stderr to the debug log so stray output never corrupts the curses display.
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    try:
        ensure_dir(os.path.dirname(DEBUG_LOG_PATH))
        log = open(DEBUG_LOG_PATH, "a", encoding="utf-8", buffering=1)
    except Exception:
        log = None
    if log is not None:
        sys.stderr = log
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stderr = sys.__stderr__
        if log is not None:
            log.close()


if __name__ == "__main__":
    run()
