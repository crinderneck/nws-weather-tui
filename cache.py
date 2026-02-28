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
    def __init__(self):
        self._d: Dict[str, CacheEntry] = {}

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

    def clear(self) -> None:
        self._d.clear()
