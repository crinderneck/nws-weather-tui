#!/usr/bin/env python3
"""
NWS Weather TUI — Attention signals when a new alert appears.

Methods (config ``alert_notify``, a list):
  * ``bell``    — terminal bell; Konsole/Yakuake can turn it into a taskbar
                  mark or desktop popup via *Configure Notifications*.
  * ``desktop`` — ``notify-send`` popup.
  * ``tab``     — when running inside Yakuake, retitle this tab to
                  ``⚠ <event>`` while alerts are active, restoring it after.
"""

from __future__ import annotations

import curses
import os
import shutil
import subprocess
import threading
from typing import List, Optional, Sequence, Set, Tuple

from nws_weather_tui.helpers import dbg
from nws_weather_tui.models import AlertItem

ALERT_NOTIFY_METHODS = ("bell", "desktop", "tab")
YAKUAKE_SERVICE = "org.kde.yakuake"
DBUS_TIMEOUT_S = 2.0


def alert_key(a: AlertItem) -> str:
    return a.id or f"{a.event}|{a.sent}|{a.headline}"


def _dbus_call(dest: str, path: str, method: str, *args: str) -> Optional[str]:
    """Call a session-bus method via ``dbus-send``; return its literal reply."""
    try:
        out = subprocess.run(
            ["dbus-send", "--session", "--print-reply=literal", f"--dest={dest}",
             path, method, *args],
            capture_output=True, text=True, timeout=DBUS_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        dbg(f"dbus-send {method} failed: {e}")
        return None
    if out.returncode != 0:
        dbg(f"dbus-send {method} failed: {out.stderr.strip()}")
        return None
    return out.stdout.strip()


class _YakuakeTab:
    """Retitles the Yakuake tab hosting this process."""

    def __init__(self) -> None:
        self.session_id: Optional[int] = None
        self.original_title: Optional[str] = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("KONSOLE_DBUS_SESSION")) and bool(
            shutil.which("dbus-send")
        )

    def _resolve_session(self) -> Optional[int]:
        if self.session_id is not None:
            return self.session_id
        # Only act when the Konsole part hosting us belongs to Yakuake.
        owner = _dbus_call(
            "org.freedesktop.DBus", "/", "org.freedesktop.DBus.GetNameOwner",
            f"string:{YAKUAKE_SERVICE}",
        )
        if not owner or owner != os.environ.get("KONSOLE_DBUS_SERVICE"):
            return None
        # Konsole session /Sessions/N is Yakuake terminal N-1 (Konsole counts from 1).
        try:
            terminal_id = int(os.environ["KONSOLE_DBUS_SESSION"].rsplit("/", 1)[-1]) - 1
        except (KeyError, ValueError):
            return None
        reply = _dbus_call(
            YAKUAKE_SERVICE, "/yakuake/sessions", "org.kde.yakuake.sessionIdForTerminalId",
            f"int32:{terminal_id}",
        )
        try:
            sid = int((reply or "").split()[-1])
        except (IndexError, ValueError):
            return None
        if sid < 0:
            return None
        self.session_id = sid
        return sid

    def _set(self, title: str) -> None:
        _dbus_call(
            YAKUAKE_SERVICE, "/yakuake/tabs", "org.kde.yakuake.setTabTitle",
            f"int32:{self.session_id}", f"string:{title}",
        )

    def flag(self, title: str) -> None:
        with self._lock:
            if self._resolve_session() is None:
                return
            if self.original_title is None:
                self.original_title = _dbus_call(
                    YAKUAKE_SERVICE, "/yakuake/tabs", "org.kde.yakuake.tabTitle",
                    f"int32:{self.session_id}",
                )
                if self.original_title is None:
                    return
            self._set(title)

    def restore(self) -> None:
        with self._lock:
            if self.original_title is None or self.session_id is None:
                return
            self._set(self.original_title)
            self.original_title = None


class AlertNotifier:
    def __init__(self, methods: Sequence[str]) -> None:
        self.methods: Set[str] = {m for m in methods if m in ALERT_NOTIFY_METHODS}
        self._seen: Optional[Set[str]] = None
        self._loc: Optional[Tuple[float, float]] = None
        self._tab: Optional[_YakuakeTab] = (
            _YakuakeTab() if "tab" in self.methods and _YakuakeTab.available() else None
        )
        self._tab_title: Optional[str] = None
        self._tab_thread: Optional[threading.Thread] = None

    def update(self, alerts: List[AlertItem], lat: float, lon: float) -> None:
        """Main-thread: called with each fresh alert list for the current location.

        The first list for a location only seeds what's been seen, so startup
        and location switches stay quiet; the tab still reflects active alerts.
        """
        loc = (round(lat, 4), round(lon, 4))
        keys = {alert_key(a) for a in alerts}
        if self._seen is None or loc != self._loc:
            new: List[AlertItem] = []
        else:
            new = [a for a in alerts if alert_key(a) not in self._seen]
        self._seen = keys
        self._loc = loc

        if new:
            if "bell" in self.methods:
                try:
                    curses.beep()
                except curses.error:
                    pass
            if "desktop" in self.methods:
                self._desktop(new)
        self._update_tab(alerts)

    def _desktop(self, new: List[AlertItem]) -> None:
        if not shutil.which("notify-send"):
            return
        severe = any(a.severity in ("Extreme", "Severe") for a in new)
        summary = new[0].event if len(new) == 1 else f"{len(new)} new weather alerts"
        body = "\n".join(a.headline for a in new[:3])
        try:
            subprocess.Popen(
                ["notify-send", "-a", "NWS Weather", "-i", "weather-severe-alert",
                 "-u", "critical" if severe else "normal", summary, body],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as e:
            dbg(f"notify-send failed: {e}")

    def _update_tab(self, alerts: List[AlertItem]) -> None:
        if self._tab is None:
            return
        title = f"⚠ {alerts[0].event}" if alerts else None
        if title == self._tab_title:
            return
        self._tab_title = title
        tab = self._tab
        # dbus-send round trips would stall the UI; do them off-thread.
        target = (lambda: tab.flag(title)) if title else tab.restore
        self._tab_thread = threading.Thread(target=target, daemon=True)
        self._tab_thread.start()

    def restore(self) -> None:
        """Put the tab title back; call on exit."""
        if self._tab is None:
            return
        if self._tab_thread is not None:
            self._tab_thread.join(timeout=2 * DBUS_TIMEOUT_S)
        self._tab.restore()
