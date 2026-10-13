#!/usr/bin/env python3
"""
NWS Weather TUI — FIXTURE mode: record real HTTP responses to JSON files and
replay them later, so the app (and its tests) can run offline and deterministically.

Enabled with environment variables (or ``NWSClient(fixture_dir=..., fixture_mode=...)``):

  NWS_TUI_FIXTURE_DIR=<dir>      directory holding one JSON file per request
  NWS_TUI_FIXTURE_MODE=replay    serve responses from <dir>; never touch the network (default)
  NWS_TUI_FIXTURE_MODE=record    fetch URLs missing from <dir> over the network and save them

Every sub-client shares one session object, so swapping the session here covers
NWS, Open-Meteo, geocoding, radar and boundary requests alike.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from requests.structures import CaseInsensitiveDict

FIXTURE_DIR_ENV = "NWS_TUI_FIXTURE_DIR"
FIXTURE_MODE_ENV = "NWS_TUI_FIXTURE_MODE"
MODES = ("replay", "record")


class FixtureMissError(requests.ConnectionError):
    """A replayed request has no recorded response. Subclasses ConnectionError
    so the app treats it exactly like being offline."""


def canonical_url(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    """URL with `params` merged in, sorted so dict order never changes the key."""
    if not params:
        return url
    query = urlencode(sorted((str(k), str(v)) for k, v in params.items()))
    return url + ("&" if "?" in url else "?") + query


def fixture_name(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".json"


class FixtureResponse:
    """The slice of requests.Response the clients use."""

    def __init__(self, url: str, status_code: int, headers: Dict[str, str], content: bytes):
        self.url = url
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers)
        self.content = content

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} for url: {self.url}", response=None)


def _encode_body(content: bytes, content_type: str) -> Dict[str, Any]:
    if "json" in content_type:
        try:
            return {"json": json.loads(content.decode("utf-8"))}
        except ValueError:
            pass
    if content_type.startswith("text/") or "xml" in content_type:
        try:
            return {"text": content.decode("utf-8")}
        except UnicodeDecodeError:
            pass
    return {"base64": base64.b64encode(content).decode("ascii")}


def _decode_body(rec: Dict[str, Any]) -> bytes:
    if "json" in rec:
        return json.dumps(rec["json"]).encode("utf-8")
    if "text" in rec:
        return rec["text"].encode("utf-8")
    return base64.b64decode(rec.get("base64", ""))


class FixtureSession:
    """Drop-in for the client session's ``get``/``headers``.

    replay: answer from `directory`, raising FixtureMissError for unknown URLs.
    record: delegate to `inner` (the real session) and save each response.
    """

    def __init__(self, directory: str, mode: str, inner: Any = None) -> None:
        if mode not in MODES:
            raise ValueError(f"fixture mode must be one of {MODES}, got {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode needs a real session to delegate to")
        self.directory = directory
        self.mode = mode
        self._inner = inner
        self._lock = threading.Lock()
        self.misses: List[str] = []
        self.hits: List[str] = []
        if mode == "record":
            os.makedirs(directory, exist_ok=True)

    @property
    def headers(self) -> Dict[str, str]:
        return self._inner.headers if self._inner is not None else {"User-Agent": "fixture"}

    def get(self, url: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any):
        key = canonical_url(url, params)
        path = os.path.join(self.directory, fixture_name(key))
        # Record mode only fetches URLs not yet on disk, so several runs into
        # one directory stay consistent with each other (e.g. radar frame URLs
        # built from an earlier run's MRMS time extent). Start from an empty
        # directory to re-record everything.
        if self.mode == "record" and not os.path.exists(path):
            r = self._inner.get(url, params=params, **kwargs)
            ct = (r.headers.get("Content-Type") or "").lower()
            rec = {"url": key, "status": r.status_code, "content_type": ct}
            rec.update(_encode_body(r.content, ct))
            tmp = f"{path}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, indent=1, sort_keys=True)
                f.write("\n")
            os.replace(tmp, path)
            with self._lock:
                self.hits.append(key)
            return r
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except FileNotFoundError:
            with self._lock:
                self.misses.append(key)
            raise FixtureMissError(f"no fixture recorded for {key}") from None
        with self._lock:
            self.hits.append(key)
        ct = rec.get("content_type", "")
        return FixtureResponse(
            rec.get("url", key), int(rec.get("status", 200)),
            {"Content-Type": ct} if ct else {}, _decode_body(rec),
        )


def fixture_settings_from_env() -> Optional[Dict[str, str]]:
    """{'directory', 'mode'} when FIXTURE mode is switched on in the environment."""
    directory = os.environ.get(FIXTURE_DIR_ENV, "").strip()
    if not directory:
        return None
    mode = os.environ.get(FIXTURE_MODE_ENV, "replay").strip().lower() or "replay"
    return {"directory": os.path.abspath(directory), "mode": mode}
