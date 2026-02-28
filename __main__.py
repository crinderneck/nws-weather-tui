#!/usr/bin/env python3
"""
NWS Weather TUI — Entry point (can run as: python __main__.py or python -m nws_weather)
"""

from __future__ import annotations

import curses
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import main

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
