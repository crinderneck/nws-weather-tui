#!/usr/bin/env python3
"""
NWS Weather TUI — Entry point (can run as: python __main__.py or python -m nws_weather)
"""

from __future__ import annotations

import curses
import sys
import os
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import DEBUG_LOG_PATH, ensure_dir
from app import main

# Suppress DeprecationWarnings (e.g. datetime.utcfromtimestamp) and redirect
# stderr to the debug log so stray output never corrupts the curses display.
warnings.filterwarnings("ignore", category=DeprecationWarning)

if __name__ == "__main__":
    try:
        ensure_dir(os.path.dirname(DEBUG_LOG_PATH))
        _log = open(DEBUG_LOG_PATH, "a", encoding="utf-8", buffering=1)
    except Exception:
        _log = None
    if _log is not None:
        sys.stderr = _log
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stderr = sys.__stderr__
        if _log is not None:
            _log.close()
