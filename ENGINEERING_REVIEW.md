# NWS Weather TUI — Engineering Review

Three simulated engineering perspectives (QA, UX, Input) reviewed the entire
codebase. This document compiles all findings organized by engineer, with a
cross-cutting summary of the highest-priority items.

**Date:** 2026-03-13
**Codebase:** NWS Weather TUI (Python 3 / curses)

---

## Executive Summary

| Engineer | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| QA       | 3        | 3    | 5      | 9   | 20    |
| UX       | 0        | 5    | 16     | 16  | 37    |
| Input    | 0        | 5    | 7      | 10  | 22    |
| **Total**| **3**    | **13** | **28** | **35** | **79** |

### Top 10 Cross-Cutting Issues

Issues flagged by 2+ engineers, ranked by combined severity:

| # | Issue | Engineers | Combined Severity |
|---|-------|-----------|-------------------|
| 1 | Help screen not scrollable — bottom ~30 lines silently truncated | UX (2.5, 8.4), Input (2) | HIGH |
| 2 | Footer help bar is a wall of 157 chars, truncated on <160-col terminals | UX (4.1), Input (13) | HIGH |
| 3 | Location search blocks main thread via `getstr` — UI freezes during geocode | UX (10.4), Input (5, 11) | HIGH |
| 4 | `LEFT`/`RIGHT` arrow keys step radar frames globally, even outside radar view | Input (1), UX (implied in 2.4) | HIGH |
| 5 | Alert scroll skips entire alerts, not rows — long alerts can't be read | QA (7), UX (7.2), Input (6) | MEDIUM |
| 6 | Color pair semantics overloaded — same colors for temperature, alerts, sparklines | UX (3.1), QA (implied in #10) | HIGH |
| 7 | Scroll positions not reset after data refresh — stale position possible | UX (10.3), Input (21) | MEDIUM |
| 8 | `h` key conflicts with vim "move left" convention | UX (4.3), Input (10) | MEDIUM |
| 9 | `q` in favorites editor quits entire app instead of closing editor | QA (18), Input (15) | LOW |
| 10 | Forecast `fc_scroll` conflates scroll offset and selection | UX (9.4, 2.3), Input (7) | MEDIUM |

---

## QA Engineer Findings

### CRITICAL

**QA-1. Race condition: shared `requests.Session` accessed across threads without locking**
- **Files:** `weather_refresh.py:26-40`, `radar_state.py:152-179`
- **Severity:** Critical
- `refresh_all()` reads/writes shared app state, then spawns background threads
  that call `app.client.*` concurrently with the main thread. `requests.Session`
  is not thread-safe for concurrent use without a lock. The only lock
  (`app._bg_lock`) covers `_bg_weather_pending`/`_bg_radar_pending` writes only.

**QA-2. Division by zero in `radar_frames_png` when `n_frames == 1`**
- **File:** `radar_client.py:308`
- **Severity:** Critical
- `step_ms = max(60_000, span_ms // (n_frames - 1))` — if a user sets
  `animation_frames = 1` in config, this is `span_ms // 0`, raising
  `ZeroDivisionError` in the background radar fetch thread.

**QA-3. Daemon state-save thread killed on quit before write completes**
- **File:** `app.py:237-246`
- **Severity:** Critical (data loss)
- `threading.Thread(target=self._write_state_bg, …, daemon=True)`. Daemon
  threads are killed immediately when the main thread exits. If the user presses
  `q` before the write finishes, `state.json` is either stale or only the `.tmp`
  file remains.

### HIGH

**QA-4. `derwin()` crash on terminal resize race (SIGWINCH)**
- **File:** `app.py:338`
- **Severity:** High
- `win = self.stdscr.derwin(body_h, body_w, body_top, 1)` — if the terminal
  is resized between `getmaxyx()` and `derwin()`, this can fail with an
  unhandled `curses.error`.

**QA-5. Concurrent `.tmp` file writes from two threads**
- **Files:** `constants.py:98-103`, `persistence.py:33`
- **Severity:** High
- `save_json` writes to `path + ".tmp"` then `os.replace`. Two threads writing
  the same path simultaneously can corrupt each other's `.tmp` file.

**QA-6. Error swallowing in `_bg_weather_fetch`**
- **File:** `weather_refresh.py:102-108`
- **Severity:** High
- Entire fetch body under `except Exception`; errors logged but their string
  representation is the only surface. Can mask unexpected failures.

### MEDIUM

**QA-7. No intra-alert scrolling — long alerts truncated**
- **File:** `views_alerts.py:39-91`
- **Severity:** Medium
- Scroll unit is per-alert index. Long alert descriptions that fill the entire
  visible area cannot be scrolled within.

**QA-8. `lru_cache(2048)` on large alert text can grow to tens of MB**
- **File:** `helpers.py:80-98`
- **Severity:** Medium
- `wrap_lines` caches (text, width) pairs. Large alert texts + terminal resizes
  cause unbounded cache growth.

**QA-9. `float(None)` if Zippopotam returns null lat/lon**
- **File:** `geocode.py:55-56`
- **Severity:** Medium
- Silently caught by outer `except Exception` block, degrades gracefully but
  silently.

**QA-10. Hardcoded Nominatim User-Agent ignores app config**
- **File:** `geocode.py:77`
- **Severity:** Medium
- `_geocode_nominatim` sends `nws-weather-tui/1.0` instead of the configured
  user agent. Nominatim ToS violation risk.

**QA-11. Startup crash on permission error opening debug log**
- **File:** `__main__.py:23-25`
- **Severity:** Medium
- `open(DEBUG_LOG_PATH)` fails with raw traceback if directory creation fails
  (e.g., read-only filesystem).

### LOW

**QA-12.** Dead code: `parse_iso` branch in `DayCard.start_dt` never executes — `views_forecast.py:68-71`

**QA-13.** Code smell: `seen.add(l)` side-effect in list comprehension — `radar_client.py:211`

**QA-14.** Performance: all N animation frames saved to disk, only last survives — `radar_state.py:195-201`

**QA-15.** UX: dew point shows `"— °F"` instead of `"—"` when humidity missing — `views_current.py:69-71`

**QA-16.** UX: current-day moon phase not shown in "upcoming" list — `moon.py:80-82`

**QA-17.** Display: wind column truncated 1 char early — `views_hourly.py:97`

**QA-18.** UX: pressing `q` in favorites editor quits app without confirmation — `input_handler.py:59`

**QA-19.** Display: title and right-side header overlap on narrow terminals — `views_chrome.py:43-48`

**QA-20.** Display: nearest-neighbor sparkline resampling skips some values — `sparklines.py:25-27`

---

## UX Engineer Findings

### HIGH

**UX-1. Temperature not visually dominant**
- **File:** `views_current.py:81-107`
- **Severity:** High
- Text description rendered first at same `A_BOLD` weight as temperature.
  Temperature shares `color_pair(3)` with "Active Alerts: 0" — identical
  visual weight for the most and least important data points.

**UX-2. Hourly column positions hard-coded and non-responsive**
- **File:** `views_hourly.py:60-65`
- **Severity:** High
- Fixed pixel positions (`x_time=0, x_icon=8, x_temp=12, x_wind=21, x_pop=40,
  x_fc=46`) waste space at wide terminals and squeeze forecast text at narrow ones.

**UX-3. Color pair semantics overloaded**
- **File:** `curses_init.py:20-34`
- **Severity:** High
- `color_pair(3)` (green) used for temperature, "no alerts", and moon art.
  `color_pair(4)` (red) used for errors, alerts, AND temperature sparkline.

**UX-4. Footer help bar unreadable**
- **File:** `views_chrome.py:77-82`
- **Severity:** High
- 157-char pipe-separated string with no grouping. Truncated at ~80 cols.
  No visual hierarchy or indication of modal vs global keys.

**UX-5. Radar 256-color mode relies entirely on color for dBZ intensity**
- **File:** `radar_renderer.py`, `radar_palette.py`
- **Severity:** High
- Half-block mode uses only color to encode intensity — no character-density
  dimension. Inaccessible for color-blind users. ASCII fallback does use
  character density (` .:-=+*#%@`).

### MEDIUM

**UX-6.** Temperature and dew point crammed on one line — `views_current.py:85`

**UX-7.** Data hard-left at wide terminals, no centering — `views_current.py:40-41`

**UX-8.** No visual card separator in forecast view — `views_forecast.py:124-125`

**UX-9.** Forecast scroll/select conflation (`fc_scroll` serves dual purpose) — `views_forecast.py:129-160`

**UX-10.** Help screen not scrollable; ~30 lines truncated at 24 rows — `views_help.py:81-89`

**UX-11.** Inconsistent `A_BOLD` use across views — multiple files

**UX-12.** Hourly headers use `A_DIM` instead of `A_BOLD` — `views_hourly.py:68-73`

**UX-13.** `h` key collision with help convention — `input_handler.py:35`

**UX-14.** Favorites cycling has no visible position indicator — `views_chrome.py:37-48`

**UX-15.** Loading spinner not visually prominent — `views_chrome.py:51-53`

**UX-16.** Empty state for forecast uses error-red color — `views_forecast.py:112-115`

**UX-17.** Offline mode not indicated per-view — `views_chrome.py:66-72`

**UX-18.** Alert severity not visually hierarchical — `views_alerts.py:44-46`

**UX-19.** Minimum terminal size (70x22) clips data lines — `views_current.py`

**UX-20.** Forecast cards waste vertical space on icon padding — `views_forecast.py:169-178`

**UX-21.** No PoP in forecast day cards — `views_forecast.py`, `models.py`

---

*(UX-10 and UX-19 are counted once each above; their §8.4 restatements are the same finding)*

### LOW

**UX-22.** Wind direction in raw degrees only, no cardinal — `views_current.py:91`

**UX-23.** Moon title gap inconsistency — `views_moon.py:128-131`

**UX-24.** Sparklines lack min/max context label — `views_current.py:138-152`

**UX-25.** Inline hints missing for most features — `views_current.py`

**UX-26.** Mouse support undiscoverable — `views_radar.py:52-55`

**UX-27.** Radar error message truncated to map width — `views_radar.py:133-138`

**UX-28.** Time format mixes ISO date and 12h time — formatting functions

**UX-29.** Forecast cards lack temperature unit label — `views_forecast.py:182-189`

**UX-30.** `PoP :` label has extra space before colon — `views_hourly.py:51`

**UX-31.** Unknown icon visually too dense (uses `#`) — `icons.py:84-91`

**UX-32.** `partly_cloudy_day` icon has literal `""` rendering artifact — `icons.py:28-31`

**UX-33.** "Active Alerts: 0" same color as temperature — `views_current.py:125`

**UX-34.** Only 2 forecast cards visible at 70 cols — `views_forecast.py:128-133`

**UX-35.** Radar map can become very narrow with extreme geo-aspect ratios — `views_radar.py:70-79`

**UX-36.** Sunrise/sunset arrows unlabeled — `views_forecast.py:215`

**UX-37.** Empty-state flash on view switch, animation frame counter in header not map, scroll not reset on view switch — `input_handler.py`, `views_radar.py`, `app.py`

---

## Input Engineer Findings

### HIGH

**IN-1. `LEFT`/`RIGHT` keys step radar frames globally, even outside radar view**
- **File:** `input_handler.py:60-65`
- **Severity:** High
- Arrow keys are bound to `step_radar_frame` on all views. A user pressing left
  on the hourly view silently steps a radar frame they cannot see.

**IN-2. Help screen not scrollable — bottom ~30 lines cut off**
- **File:** `views_help.py:81-89`
- **Severity:** High
- Renders until `y >= rows` then stops. No `app.help_scroll` state, no scroll
  handler branch for help view.

**IN-3. No autocomplete or candidate list for city search**
- **File:** `input_handler.py`, `geocode.py`, `cities.py`
- **Severity:** High
- `MAJOR_CITIES` (153 entries) exists but is unused during search. No fuzzy
  matching, no multi-result disambiguation (e.g., "Springfield" picks first hit).

**IN-4. Location applied immediately with no confirm step**
- **File:** `input_handler.py:136-138`
- **Severity:** High
- `_apply_location` immediately clears cache, resets radar, and triggers full
  refresh. Flash message shows Nominatim result for 1.8s with no "confirm?"
  step. Wrong city → full re-fetch needed.

**IN-5. `prompt_line` uses blocking `getstr` — no Escape cancel, no live feedback**
- **File:** `input_handler.py:98-122`
- **Severity:** High
- Blocking raw read. No real-time feedback, no Escape cancellation (accidentally
  works via empty string). Terminal state risk if exception between
  `curses.echo()` and `curses.noecho()`. `max_input` can be 1 on narrow
  terminals.

### MEDIUM

**IN-6.** Alert scroll skips entire alerts, not screen rows — `views_alerts.py:39-85`

**IN-7.** Forecast `j/k` scrolls cards (horizontal) via vertical keys — `views_forecast.py:129-142`

**IN-8.** `w` toggle always returns to "current", not previous view — `input_handler.py:197-204`

**IN-9.** `a` key overloaded: "Alerts" globally vs "Add favorite" in modal — `input_handler.py:37`, `favorites.py:69`

**IN-10.** No Escape key in global handler as "return to safety" — `input_handler.py`

**IN-11.** Geocode/add-favorite blocks main thread, spinner frozen — `input_handler.py:131`, `favorites.py:119`

**IN-12.** No keybinding configuration in `DEFAULT_CONFIG` — `constants.py`

### LOW

**IN-13.** Footer hint bar truncates on <157-col terminals — `views_chrome.py:77-82`

**IN-14.** No scroll-wheel mouse support (events captured but ignored) — `input_handler.py:69-95`

**IN-15.** `q` in favorites editor quits app instead of closing editor — `favorites.py:59-60`

**IN-16.** No Escape key in global handler — `input_handler.py`

**IN-17.** `mouseinterval(0)` makes `BUTTON1_DOUBLE_CLICKED` dead code — `curses_init.py:40`

**IN-18.** `xdg-open` Linux-only, silently fails on macOS — `input_handler.py:212-221`

**IN-19.** No `Home`/`End`/`g`/`G` jump-to-top/bottom in any view — `input_handler.py`

**IN-20.** No `+`/`-` keys for radar animation speed — `constants.py`

**IN-21.** Scroll positions not reset after refresh — `app.py`

**IN-22.** No page-down acceleration (`PgDn`/`Ctrl+D`) in long views — `input_handler.py`

---

## Cross-Cutting Priority Matrix

Issues flagged by 2+ engineers, sorted by combined severity and breadth of impact.

| Priority | Issue | QA | UX | Input | Files |
|----------|-------|----|----|-------|-------|
| **P0** | Help screen not scrollable | — | UX-10 (M) | IN-2 (H) | `views_help.py` |
| **P0** | Location search blocks UI via `getstr` | — | UX-21 (M) | IN-5 (H), IN-11 (M) | `input_handler.py` |
| **P0** | Footer help bar unreadable/truncated | — | UX-4 (H) | IN-13 (M) | `views_chrome.py` |
| **P0** | `LEFT`/`RIGHT` step radar globally | — | — | IN-1 (H) | `input_handler.py` |
| **P1** | Alert scroll by index, not row | QA-7 (M) | UX-18 (M) | IN-6 (M) | `views_alerts.py` |
| **P1** | Color pair semantics overloaded | QA-10 (L) | UX-3 (H) | — | `curses_init.py`, views |
| **P1** | `h` key conflicts with vim convention | — | UX-13 (M) | IN-10 (M) | `input_handler.py` |
| **P1** | Forecast `fc_scroll` conflation | — | UX-9 (M) | IN-7 (M) | `views_forecast.py` |
| **P2** | Scroll positions stale after refresh | — | UX-37 (L) | IN-21 (L) | `app.py` |
| **P2** | `q` in favorites quits app | QA-18 (L) | — | IN-15 (L) | `favorites.py` |

**P0** = Address before next release. **P1** = Address soon. **P2** = Address when convenient.
