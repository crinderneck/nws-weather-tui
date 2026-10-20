# Regression harness

```bash
pip install -e '.[test]'              # pytest, freezegun, pyte, vermin, uv, pyinstrument, time-machine
pytest                                # fast suite, ~3 s, offline
pytest -m slow                        # Python 3.9 run via uvx + pipx install check
pytest --update-snapshots             # accept an intended rendering change
python tests/profile_app.py           # profile startup, data and every screen (see Profiling)
```

## What runs

| File | Checks |
|------|--------|
| `test_snapshots.py` | Every screen (current + radar, forecast, hourly, alerts, discussion, outlook, moon; help, favorites and dashboard once) for Denver, Columbus OH and Ventura CA at 80x24, 120x40 and 200x60. Text **and** colour/attribute layers must match `snapshots/` exactly. Also: no exception, no stderr, no unrecorded request, no raw `None`/`nan` on screen, header and footer intact, frozen clock consistent. |
| `test_correctness.py` | Sunrise/sunset vs Open-Meteo (8 days) and USNO (days around the next DST change, including what is printed); moon phase instants, rise/set and illumination vs USNO; rain totals re-derived from the raw gridpoint QPF vs the app's numbers and the Hourly screen. |
| `test_units.py` | FIXTURE mode, HWO zone segments, alert hazard windows, radar retry/backoff/age, line raster (every direction), label placement, dashboard wind. |
| `test_scenarios.py` | The real app end to end beyond the snapshots: a keyboard session typed into the terminal (favorites editor, views, clock; checks what's saved to disk), starting with no network and nothing saved, staying online when only the extras (gridpoint data, AFD/HWO, air quality, UV) fail, and restarting offline from the state a first run saved. |
| `test_persistence.py` | Config: first run, partial files merged over defaults, a broken file kept aside rather than overwritten. Saved state: everything a refresh produces survives the round trip with its types; bad or old state loads field by field. |
| `test_input.py` | Every view key the help screen documents, the favorites editor and dashboard keys (bounds, reorder, delete, jump), F/n/b, scrolling, lat/lon entry, radar city clicks. |
| `test_error_paths.py` | Server failures: NWS retries and backoff, failures never cached, AFD/HWO failing quietly, radar falling back MRMS → IEM → station WMS → single frame, location search (ZIP, place names, network errors vs. no match). |
| `test_coverage.py` | Outside NWS coverage: the startup IP check and its notice, every panel's message for a location outside the US (London, end to end), search and favorites refusing such places, and moving back to a US one. |
| `test_conversions.py` | Unit conversions and dew point against exact definitions and standard values. |
| `test_profile.py` | The profiler runs end to end: startup, data phases and every screen are timed, every screen gets a flame graph (fast); the memory pass attributes allocations to the app, not the harness's emulator (slow). |
| `test_compat.py` | `vermin --target=3.9` (fast); the fast suite under Python 3.9, installed from source, and `pipx install --force .` into a throwaway `PIPX_HOME` that then launches, draws and quits cleanly (slow). |

A Claude Code PostToolUse hook (`hooks/run_fast_tests.sh`, wired up in
`.claude/settings.json`) runs the fast suite after edits to `src/` or `tests/`
Python files and reports failures back.

## How rendering is captured

`harness/driver.py` runs the real `App` in its own process: real ncurses draws
into a pseudo-terminal, a [pyte](https://github.com/selectel/pyte) emulator
reads the other side, and an in-band escape sequence after each frame marks
where to read the screen (no sleeps). Time is frozen at the manifest's
`frozen_at` and `TZ` is the location's zone. Two things the emulator would
otherwise get wrong are handled there: ncurses scrolls regions with SU/SD,
which pyte 0.8 ignores (implemented), and any other sequence pyte can't parse
fails the run instead of producing a plausible but wrong picture.

## FIXTURE mode

`NWSClient` reads `NWS_TUI_FIXTURE_DIR` (and `NWS_TUI_FIXTURE_MODE=replay|record`,
default replay), so the app itself can run offline against the recordings:

```bash
NWS_TUI_FIXTURE_DIR=tests/fixtures/http nws-weather-tui
```

Each request is one JSON file in `fixtures/http/` named by a hash of its URL
(query parameters sorted). Replay never touches the network; a missing
recording behaves like being offline.

## Re-recording

```bash
python tests/record_fixtures.py                 # everything, fresh (~1 min)
python tests/record_fixtures.py --missing-only  # after a layout change
python tests/record_fixtures.py --reference-only
pytest --update-snapshots                       # then review the diff
```

Radar requests depend on the radar panel's size, so a change that moves the
layout needs `--missing-only` — soon after the full recording, because the
frames are pinned to the recorded MRMS time extent and MRMS keeps ~2 hours.

## Profiling

```bash
python tests/profile_app.py                        # all passes, locations, sizes (~2 min)
python tests/profile_app.py --passes timing        # just the numbers (~10 s)
python tests/profile_app.py --locations denver --sizes 120x40 --repeat 100
python tests/profile_app.py --live                 # real APIs: network latency included
python tests/profile_app.py --sizes 200x60,large   # big monitors: 266x67 355x90 477x90 533x135 (live)
```

`profile_app.py` runs the real app through the driver (`driver.py --profile`,
`harness/profiling.py`), one process per location, size and pass, and prints
a report. Everything lands in `profile-results/<timestamp>/` (git-ignored):
`results.json` with every number, and with the flame pass `index.html`
linking each run's flame graphs (`.html`, plus `.txt` for a terminal).

| Pass | Measures |
|------|----------|
| `timing` | Startup (importing the app, `App()`, first data in, first draw); each data phase (`weather`/`radar`/`dashboard` fetch on its thread, apply on the UI thread); per screen the time to settle, the first draw, and the median/p95 of `--repeat` redraws. |
| `flame` | pyinstrument flame graphs: startup and each screen's redraws on the UI thread, and each kind of fetch merged across its threads and pool workers. |
| `memory` | tracemalloc: startup peak and what stays allocated, and per screen the peak and net change, with the lines that allocated most. |

Replay (the default) is repeatable, so use it to compare commits. It freezes
the clock with time-machine rather than freezegun: freezegun's pure-Python
datetime made the Hourly screen time 9x slower than it really is. Its data
phases read fixtures from disk, so they show parsing, not the network;
`--live` shows that, but varies run to run (behind a TLS-intercepting proxy,
set `REQUESTS_CA_BUNDLE`). Only 80x24, 120x40 and 200x60 have recordings:
radar is requested at the panel's size (12 px of image per panel row), so
any other size, including the `large` preset (approximate full-screen sizes
on 1080p, 1440p, ultrawide and 4K monitors), runs the whole profile live
rather than replaying it with no radar. Profile runs drain the terminal without emulating
it, so pyte neither competes for the GIL nor shows up in the memory numbers.
