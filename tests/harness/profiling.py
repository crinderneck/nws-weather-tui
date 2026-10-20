"""Profile the real app from inside the harness driver (driver.py --profile).

One location, one terminal size and one pass per process, so the passes
don't skew each other and each run starts cold:

  timing  startup (importing the app, App(), first data in, first draw), every
          data phase (fetch on its own thread, apply on the UI thread), and per
          screen the time to settle, the first draw and --repeat more draws
  flame   pyinstrument flame graphs: startup and each screen's draws (UI
          thread), plus each kind of fetch merged across its threads
  memory  tracemalloc: startup peak and what stays allocated, and per screen
          the peak and growth over its draws, with the top allocation sites

tests/profile_app.py runs the passes and prints the report. Timings from the
flame and memory passes are recorded but skewed by the profilers; the report
takes its times from the timing pass.
"""

from __future__ import annotations

import functools
import importlib
import os
import statistics
import threading
import time
import tracemalloc
from typing import Any, Callable, Dict, List

PASSES = ("timing", "flame", "memory")

# Replay freezes the wall clock with time-machine (driver.py), which leaves
# perf_counter running, so it times everything here. pyinstrument still reads
# the frozen time.time() for a session's duration (its samples use their own
# clock), so _real() puts that back.
_clock = time.perf_counter

# Each runs either as a fetch thread's target or on the UI thread from
# App._tick, and every caller looks it up on the module when calling, so
# replacing the module attribute catches every call.
PHASES = (
    ("nws_weather_tui.weather_refresh", "_bg_weather_fetch", "weather.fetch"),
    ("nws_weather_tui.weather_refresh", "apply_bg_weather", "weather.apply"),
    ("nws_weather_tui.radar.state", "_bg_radar_fetch", "radar.fetch"),
    ("nws_weather_tui.radar.state", "apply_bg_radar", "radar.apply"),
    ("nws_weather_tui.dashboard", "_bg_dashboard_fetch", "dashboard.fetch"),
    ("nws_weather_tui.dashboard", "apply_bg_dashboard", "dashboard.apply"),
)
# Fetches that fan their requests out to a ThreadPoolExecutor; the workers do
# the HTTP and parsing, so the flame pass profiles them too.
POOLS = {
    "nws_weather_tui.weather_refresh": "weather.fetch",
    "nws_weather_tui.dashboard": "dashboard.fetch",
}
TOP_SITES = 8


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 3)


class _Recorder:
    """Times each phase call and, in the flame pass, profiles the threads
    the main-thread profiler can't see (pyinstrument samples one thread)."""

    def __init__(self, t0: float, flame: bool) -> None:
        self.t0 = t0
        self.flame = flame
        self.events: List[Dict[str, Any]] = []
        self.sessions: Dict[str, Any] = {}  # phase -> merged pyinstrument Session
        self._lock = threading.Lock()

    def install(self) -> None:
        for module, name, phase in PHASES:
            mod = importlib.import_module(module)
            setattr(mod, name, self._timed(getattr(mod, name), phase))
        if self.flame:
            for module, phase in POOLS.items():
                mod = importlib.import_module(module)
                mod.ThreadPoolExecutor = self._pool(mod.ThreadPoolExecutor, phase)

    def _timed(self, fn: Callable[..., Any], phase: str) -> Callable[..., Any]:
        @functools.wraps(fn)
        def timed(*args: Any, **kwargs: Any) -> Any:
            ui = threading.current_thread() is threading.main_thread()
            start = _clock()
            try:
                if ui:  # already inside the UI thread's own profile
                    return fn(*args, **kwargs)
                return self.profiled(phase, fn, *args, **kwargs)
            finally:
                end = _clock()
                with self._lock:
                    self.events.append({
                        "phase": phase, "thread": "ui" if ui else "background",
                        "start_ms": _ms(start - self.t0), "ms": _ms(end - start),
                    })
        return timed

    def _pool(self, base: Any, phase: str) -> Any:
        recorder = self

        class ProfiledPool(base):  # type: ignore[misc, valid-type]
            def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
                return super().submit(recorder.profiled, phase, fn, *args, **kwargs)

        return ProfiledPool

    def profiled(self, phase: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self.flame:
            return fn(*args, **kwargs)
        from pyinstrument import Profiler
        from pyinstrument.session import Session

        profiler = Profiler(interval=0.001, async_mode="disabled")
        profiler.start()
        start = _clock()
        try:
            return fn(*args, **kwargs)
        finally:
            profiler.stop()
            session = _real(profiler.last_session, _clock() - start)
            if session is not None:
                with self._lock:
                    prev = self.sessions.get(phase)
                    self.sessions[phase] = session if prev is None else Session.combine(prev, session)


class _Flame:
    """UI-thread flame graphs, one HTML file per section."""

    def __init__(self, out_dir: str) -> None:
        self.out_dir = out_dir
        self.files: Dict[str, str] = {}
        self._profiler: Any = None
        self._start = 0.0
        os.makedirs(out_dir, exist_ok=True)

    def start(self) -> None:
        from pyinstrument import Profiler

        self._profiler = Profiler(interval=0.001, async_mode="disabled")
        self._profiler.start()
        self._start = _clock()

    def stop(self, name: str) -> None:
        self._profiler.stop()
        self.write(name, _real(self._profiler.last_session, _clock() - self._start))
        self._profiler = None

    def write(self, name: str, session: Any) -> None:
        """<name>.html to explore in a browser, <name>.txt to read in a terminal."""
        from pyinstrument.renderers import ConsoleRenderer, HTMLRenderer

        path = os.path.join(self.out_dir, f"{name}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(HTMLRenderer().render(session))
        with open(os.path.join(self.out_dir, f"{name}.txt"), "w", encoding="utf-8") as f:
            f.write(ConsoleRenderer(unicode=True, color=False, short_mode=True).render(session))
        self.files[name] = path


class _Memory:
    """tracemalloc around a section: peak above the starting point, what's
    still allocated at the end, and the lines that allocated it."""

    def __init__(self) -> None:
        tracemalloc.start(1)  # the report only groups by the allocating line
        self._base = 0
        self._snap: Any = None

    def begin(self) -> None:
        # Snapshots are traced allocations too: drop the last one before
        # taking the baseline, or freeing it later reads as negative growth.
        self._snap = None
        self._snap = tracemalloc.take_snapshot()
        tracemalloc.reset_peak()
        self._base = tracemalloc.get_traced_memory()[0]

    def end(self) -> Dict[str, Any]:
        current, peak = tracemalloc.get_traced_memory()
        filters = [tracemalloc.Filter(False, tracemalloc.__file__)]
        after = tracemalloc.take_snapshot().filter_traces(filters)
        growth = after.compare_to(self._snap.filter_traces(filters), "lineno")
        return {
            "peak_kib": round((peak - self._base) / 1024, 1),
            "retained_kib": round((current - self._base) / 1024, 1),
            "top_sites": [
                {"site": f"{_short(s.traceback[0].filename)}:{s.traceback[0].lineno}",
                 "kib": round(s.size_diff / 1024, 1), "blocks": s.count_diff}
                for s in growth[:TOP_SITES] if s.size_diff > 0
            ],
        }


def _real(session: Any, elapsed: float) -> Any:
    if session is not None:
        session.duration = elapsed
    return session


def _short(path: str) -> str:
    for marker in ("/site-packages/", "/src/", "/lib/python"):
        i = path.rfind(marker)
        if i >= 0:
            return path[i + len(marker):]
    return path


def _stats(samples: List[float]) -> Dict[str, Any]:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {"n": len(ordered), "median_ms": _ms(statistics.median(ordered)),
            "p95_ms": _ms(p95), "min_ms": _ms(ordered[0]), "max_ms": _ms(ordered[-1])}


def _steady(app: Any) -> None:
    """No "Updated." flash or spinner, as in driver._run's screenshots."""
    app.status_msg = ""
    app.status_until = 0.0
    app._is_loading = False


def run(stdscr: Any, args: Any, out: Dict[str, Any], settle: Callable[[Any], None],
        config: Callable[[str], Dict[str, Any]]) -> None:
    from harness.locations import views_for

    clock = _clock
    t0 = clock()
    flame = _Flame(args.profile_dir) if args.profile == "flame" else None
    memory = _Memory() if args.profile == "memory" else None
    recorder = _Recorder(t0, flame is not None)
    out["profile"] = {"pass": args.profile, "mode": args.mode, "repeat": args.repeat}

    # Startup: what the user waits through before the first screen with data.
    if flame:
        flame.start()
    if memory:
        memory.begin()
    import nws_weather_tui.app as app_module

    t_import = clock()
    recorder.install()
    stdscr.timeout(0)
    app = app_module.App(stdscr, config(args.location))
    t_app = clock()
    views = args.views.split(",") if args.views else views_for(args.location)
    app.view = views[0]
    app.splash = views[0] == "splash"
    settle(app)
    t_data = clock()
    _steady(app)
    app._draw()
    t_drawn = clock()
    if flame:
        flame.stop("startup")
    out["startup"] = {
        "import_ms": _ms(t_import - t0), "app_init_ms": _ms(t_app - t_import),
        "data_ms": _ms(t_data - t_app), "first_draw_ms": _ms(t_drawn - t_data),
        "total_ms": _ms(t_drawn - t0), "first_view": views[0],
    }
    if memory:
        out["startup"]["memory"] = memory.end()

    screens: Dict[str, Any] = {}
    for view in views:
        if memory:
            memory.begin()
        app.view = view
        app.splash = view == "splash"
        start = clock()
        settle(app)  # may fetch, e.g. radar sized to this screen's panel
        settled = clock()
        _steady(app)
        app._draw()
        first = clock() - settled
        if flame:
            flame.start()
        draws = []
        for _ in range(args.repeat):
            s = clock()
            app._draw()
            draws.append(clock() - s)
        if flame:
            flame.stop(f"screen-{view}")
        screens[view] = {"settle_ms": _ms(settled - start), "first_draw_ms": _ms(first),
                         "draws": _stats(draws)}
        if memory:
            screens[view]["memory"] = memory.end()
    out["screens_profile"] = screens
    out["phases"] = sorted(recorder.events, key=lambda e: e["start_ms"])

    if flame:
        for phase, session in recorder.sessions.items():
            flame.write(f"thread-{phase}", session)
        out["flame_files"] = flame.files
    fx = app.client.fixtures
    if fx is not None:
        out["fixture_misses"] = sorted(set(fx.misses))
    if app._state_thread is not None:
        app._state_thread.join(timeout=5)
