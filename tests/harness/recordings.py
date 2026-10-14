"""Read the recorded HTTP responses in tests/fixtures/http directly."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Iterator

from harness.locations import HTTP_FIXTURES_DIR


def records() -> Iterator[Dict[str, Any]]:
    """Every recording: {"url", "status", "content_type", and json|text|base64}."""
    for name in sorted(os.listdir(HTTP_FIXTURES_DIR)):
        with open(os.path.join(HTTP_FIXTURES_DIR, name), encoding="utf-8") as f:
            rec = json.load(f)
        rec["file"] = name
        yield rec


def recorded(url_matches: Callable[[str], bool]) -> Any:
    """Body of the first recording whose URL matches (JSON decoded)."""
    for rec in records():
        if url_matches(rec["url"]):
            return rec.get("json") if "json" in rec else json.loads(rec["text"])
    raise LookupError("no matching recording")
