# Regression harness

```bash
pip install -e '.[test]'              # pytest, freezegun, pyte, vermin, uv
pytest                                # fast suite, ~3 s, offline
pytest -m slow                        # Python 3.9 run via uvx + pipx install check
pytest --update-snapshots             # accept an intended rendering change
```

## What runs

| File | Checks |
|------|--------|
| `test_snapshots.py` | Every screen (current + radar, forecast, hourly, alerts, discussion, outlook, moon; help, favorites and dashboard once) for Denver, Columbus OH and Ventura CA at 80x24, 120x40 and 200x60. Text **and** colour/attribute layers must match `snapshots/` exactly. Also: no exception, no stderr, no unrecorded request, no raw `None`/`nan` on screen, header and footer intact, frozen clock consistent. |
| `test_correctness.py` | Sunrise/sunset vs Open-Meteo (8 days) and USNO (days around the next DST change, including what is printed); moon phase instants, rise/set and illumination vs USNO; rain totals re-derived from the raw gridpoint QPF vs the app's numbers and the Hourly screen. |
| `test_units.py` | FIXTURE mode, HWO zone segments, alert hazard windows, radar retry/backoff/age, line raster, label placement, dashboard wind. |
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
