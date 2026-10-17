#!/usr/bin/env python3
"""
NWS Weather TUI — Cache implementation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


# Pass as `default` to get() to tell a cached None apart from a missing key.
MISSING = object()


class TTLCache:
    """A dict with per-key expiry, safe to share between threads: the main
    loop, the weather thread and the radar/dashboard pools all use one."""

    _SWEEP_INTERVAL = 100  # sweep expired entries every N inserts

    def __init__(self):
        self._d: Dict[str, CacheEntry] = {}
        self._sets_since_sweep = 0
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        """The live value for `key`, else `default` (None unless given, so a
        cached None reads as missing: pass MISSING to see the difference)."""
        with self._lock:
            e = self._d.get(key)
            if not e:
                return default
            if time.time() >= e.expires_at:
                self._d.pop(key, None)
                return default
            return e.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        with self._lock:
            self._d[key] = CacheEntry(value=value, expires_at=time.time() + ttl_seconds)
            self._sets_since_sweep += 1
            if self._sets_since_sweep >= self._SWEEP_INTERVAL:
                self._sweep_expired()

    def _sweep_expired(self) -> None:
        """Drop expired entries that were never re-fetched via get().

        Without this, keys with high cardinality (e.g. radar tile URLs that
        embed exact bbox floats) accumulate for the life of the process even
        after they expire, since expiry is otherwise only checked lazily on
        the next get() for that exact key.

        Called with the lock held.
        """
        self._sets_since_sweep = 0
        now = time.time()
        expired = [k for k, e in self._d.items() if now >= e.expires_at]
        for k in expired:
            self._d.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self._sets_since_sweep = 0
