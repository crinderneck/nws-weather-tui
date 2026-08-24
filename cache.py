#!/usr/bin/env python3
"""
NWS Weather TUI — Cache implementation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    _SWEEP_INTERVAL = 100  # sweep expired entries every N inserts

    def __init__(self):
        self._d: Dict[str, CacheEntry] = {}
        self._sets_since_sweep = 0

    def get(self, key: str) -> Optional[Any]:
        e = self._d.get(key)
        if not e:
            return None
        if time.time() >= e.expires_at:
            self._d.pop(key, None)
            return None
        return e.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
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
        """
        self._sets_since_sweep = 0
        now = time.time()
        expired = [k for k, e in self._d.items() if now >= e.expires_at]
        for k in expired:
            self._d.pop(k, None)

    def clear(self) -> None:
        self._d.clear()
        self._sets_since_sweep = 0
