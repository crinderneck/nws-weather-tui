#!/usr/bin/env python3
"""Profile the whole app, every screen, at every harness size and location.

  .venv/bin/python tests/profile_app.py                    # recorded fixtures, all passes
  .venv/bin/python tests/profile_app.py --live             # the real NWS APIs
  .venv/bin/python tests/profile_app.py --passes timing --locations denver --sizes 120x40
  .venv/bin/python tests/profile_app.py --sizes large      # big-monitor sizes (live)

Each (location, size, pass) runs the real app in its own harness driver
process (harness/profiling.py), one after another so runs don't compete for
the CPU. Prints a report and writes to --out:

  results.json            every number from every run
  index.html              links to the flame graphs
  flame/<loc>-<size>/     pyinstrument HTML: startup, screen-<view>, thread-<fetch>

Replay (the default) is repeatable: fixtures from disk and a frozen clock, so
compare runs across commits with it. --live measures real network latency
and varies run to run; behind a TLS-intercepting proxy, set REQUESTS_CA_BUNDLE.

Only the harness sizes have recordings: the radar is requested at the panel's
size, so any other size (including the `large` preset) would replay with no
radar. Those runs go live, all of them, so one report never mixes the two.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harness.locations import LOCATIONS, SIZES  # noqa: E402
from harness.profiling import PASSES  # noqa: E402

DRIVER = os.path.join(HERE, "harness", "driver.py")
REPO = os.path.dirname(HERE)

# Full-screen terminals on big monitors, at a ~12pt monospace font (about
# 7.2 x 16 px per cell): 1920x1080, 2560x1440, 3440x1440 ultrawide, and
# 3840x2160 at 1x. Approximate; `tput cols; tput lines` gives a real one.
LARGE_SIZES: List[Tuple[int, int]] = [(266, 67), (355, 90), (477, 90), (533, 135)]
# Live runs wait on the network: give the app longer to settle than replay
# needs (the radar fetch at large sizes took ~17 s+ on a VPN).
LIVE_IDLE_TIMEOUT_S = "300"


def parse_sizes(text: str) -> List[Tuple[int, int]]:
    """'120x40,large' -> sizes, in order, without duplicates."""
    sizes: List[Tuple[int, int]] = []
    for item in (t.strip().lower() for t in text.split(",")):
        if not item:
            continue
        if item == "large":
            new = LARGE_SIZES
        else:
            cols, rows = item.split("x")
            new = [(int(cols), int(rows))]
        sizes += [s for s in new if s not in sizes]
    return sizes


def needs_live(sizes: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Sizes with no recorded radar, which replay would draw without it."""
    return [s for s in sizes if s not in SIZES]


def _run(location: str, cols: int, rows: int, pass_: str, args: argparse.Namespace,
         flame_dir: str) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.json")
        cmd = [sys.executable, DRIVER, "--location", location, "--cols", str(cols),
               "--rows", str(rows), "--out", out, "--profile", pass_,
               "--profile-dir", flame_dir, "--repeat", str(args.repeat),
               "--mode", "live" if args.live else "replay"]
        env = dict(os.environ)
        if args.live:
            env.setdefault("NWS_TUI_IDLE_TIMEOUT", LIVE_IDLE_TIMEOUT_S)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout, env=env)
        if not os.path.exists(out):
            return {"error": f"driver crashed (rc={proc.returncode})", "traceback": proc.stderr}
        with open(out, encoding="utf-8") as f:
            return json.load(f)


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    cells = [headers] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in
                       enumerate(zip(r, widths))) for r in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _f(x: Any, digits: int = 1) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def report(runs: List[Dict[str, Any]], live: bool) -> str:
    """The console report, built from every run's results."""
    out: List[str] = []
    timing = [r for r in runs if r["pass"] == "timing" and "error" not in r["result"]]
    memory = [r for r in runs if r["pass"] == "memory" and "error" not in r["result"]]
    label = lambda r: f"{r['location']} {r['cols']}x{r['rows']}"  # noqa: E731

    if timing:
        out.append("Startup (ms): import the app, App(), first data in, first draw"
                   + ("" if live else "  [replay: fixtures from disk, no network]"))
        out.append(_table(
            ["run", "import", "App()", "data", "draw", "total"],
            [[label(r)] + [_f(r["result"]["startup"][k]) for k in
                           ("import_ms", "app_init_ms", "data_ms", "first_draw_ms", "total_ms")]
             for r in timing]))

        phases: Dict[str, List[float]] = defaultdict(list)
        for r in timing:
            for e in r["result"]["phases"]:
                phases[e["phase"]].append(e["ms"])
        out.append("\nData phases (ms): fetch runs on a background thread, apply on the UI thread")
        out.append(_table(["phase", "calls", "median", "max", "total"],
                          [[p, len(v), _f(statistics.median(v)), _f(max(v)), _f(sum(v))]
                           for p, v in sorted(phases.items())]))

        sizes = sorted({(r["cols"], r["rows"]) for r in timing})
        for loc in sorted({r["location"] for r in timing}):
            by_size = {(r["cols"], r["rows"]): r["result"]["screens_profile"]
                       for r in timing if r["location"] == loc}
            views = list(next(iter(by_size.values())))
            out.append(f"\nScreens, {loc}: median redraw ms (p95) [first draw]")
            out.append(_table(
                ["screen"] + [f"{c}x{rw}" for c, rw in sizes],
                [[v] + [(f"{_f(s[v]['draws']['median_ms'], 2)} ({_f(s[v]['draws']['p95_ms'], 2)})"
                         f" [{_f(s[v]['first_draw_ms'], 2)}]") if (s := by_size.get(size)) and v in s
                        else "-" for size in sizes]
                 for v in views]))

        slow = sorted(((s["draws"]["median_ms"], v, label(r)) for r in timing
                       for v, s in r["result"]["screens_profile"].items()), reverse=True)[:5]
        out.append("\nSlowest redraws: " + ", ".join(f"{v} {lab} {ms:.2f} ms" for ms, v, lab in slow))

    if memory:
        out.append("\nMemory (KiB): peak above the start of each section, and net change after it")
        rows = []
        for r in memory:
            res = r["result"]
            worst = max(res["screens_profile"].items(), key=lambda kv: kv[1]["memory"]["peak_kib"])
            rows.append([label(r), _f(res["startup"]["memory"]["peak_kib"]),
                         _f(res["startup"]["memory"]["retained_kib"]),
                         f"{worst[0]} {_f(worst[1]['memory']['peak_kib'])}"])
        out.append(_table(["run", "startup peak", "startup net", "biggest screen peak"], rows))
        first = memory[0]["result"]
        sites = first["startup"]["memory"]["top_sites"][:5]
        out.append(f"\nTop startup allocations ({label(memory[0])}): "
                   + ", ".join(f"{s['site']} {s['kib']:.0f}" for s in sites))

    failed = [r for r in runs if "error" in r["result"]]
    for r in failed:
        out.append(f"\nFAILED {label(r)} {r['pass']}: {r['result']['error']}\n"
                   + r["result"].get("traceback", "")[-2000:])
    misses = sorted({m for r in runs for m in r["result"].get("fixture_misses", [])})
    if misses:
        out.append(f"\n{len(misses)} request(s) had no recording and were treated as offline; "
                   "numbers for those screens are incomplete. Recordings cover "
                   + ", ".join(f"{c}x{r}" for c, r in SIZES) + "; use --live for other sizes.")
    return "\n".join(out)


def write_index(path: str, runs: List[Dict[str, Any]]) -> None:
    items = []
    for r in runs:
        files = r["result"].get("flame_files") or {}
        if not files:
            continue
        links = " ".join(
            f'<a href="{html.escape(os.path.relpath(p, os.path.dirname(path)))}">'
            f"{html.escape(name)}</a>" for name, p in files.items())
        items.append(f"<li><b>{r['location']} {r['cols']}x{r['rows']}</b>: {links}</li>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=utf-8><title>nws-weather-tui flame graphs</title>"
                "<h1>Flame graphs</h1><ul>" + "\n".join(items) + "</ul>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="use the real APIs instead of fixtures")
    ap.add_argument("--passes", default=",".join(PASSES),
                    help=f"comma-separated, from {', '.join(PASSES)} (default: all)")
    ap.add_argument("--locations", default=",".join(LOCATIONS),
                    help="comma-separated (default: all harness locations)")
    ap.add_argument("--sizes", default=",".join(f"{c}x{r}" for c, r in SIZES),
                    help="comma-separated COLSxROWS, or `large` for "
                         + ", ".join(f"{c}x{r}" for c, r in LARGE_SIZES)
                         + " (default: the harness sizes; any other size runs live)")
    ap.add_argument("--repeat", type=int, default=30, help="redraws timed per screen (default 30)")
    ap.add_argument("--timeout", type=float, default=600, help="seconds per driver run")
    ap.add_argument("--out", help="output directory (default: profile-results/<timestamp>)")
    args = ap.parse_args()

    passes = [p for p in args.passes.split(",") if p]
    unknown = [p for p in passes if p not in PASSES] + [
        loc for loc in args.locations.split(",") if loc not in LOCATIONS]
    if unknown:
        ap.error(f"unknown: {', '.join(unknown)}")
    sizes = parse_sizes(args.sizes)
    unrecorded = needs_live(sizes)
    if unrecorded and not args.live:
        args.live = True
        print("No recordings at " + ", ".join(f"{c}x{r}" for c, r in unrecorded)
              + ": running everything live (real APIs) so the radar is real.",
              file=sys.stderr)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.abspath(args.out or os.path.join(REPO, "profile-results", stamp))
    os.makedirs(out_dir, exist_ok=True)

    runs: List[Dict[str, Any]] = []
    jobs = [(loc, c, r, p) for p in passes for loc in args.locations.split(",") for c, r in sizes]
    for i, (loc, cols, rows, pass_) in enumerate(jobs, 1):
        print(f"[{i}/{len(jobs)}] {pass_:6} {loc} {cols}x{rows}", file=sys.stderr, flush=True)
        flame_dir = os.path.join(out_dir, "flame", f"{loc}-{cols}x{rows}")
        result = _run(loc, cols, rows, pass_, args, flame_dir)
        runs.append({"location": loc, "cols": cols, "rows": rows, "pass": pass_, "result": result})

    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"live": args.live, "repeat": args.repeat, "runs": runs}, f, indent=1)
    if "flame" in passes:
        write_index(os.path.join(out_dir, "index.html"), runs)
    print(report(runs, args.live))
    print(f"\nResults: {out_dir}" + (f"\nFlame graphs: {os.path.join(out_dir, 'index.html')}"
                                    if "flame" in passes else ""))
    return 1 if any("error" in r["result"] for r in runs) else 0


if __name__ == "__main__":
    sys.exit(main())
