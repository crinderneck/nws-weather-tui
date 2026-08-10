# NWS Weather TUI

A terminal-based weather application for the US, powered by the [National Weather Service API](https://www.weather.gov/documentation/services-web-api). Built with Python and curses.

![Python 3](https://img.shields.io/badge/python-3.8+-blue)

## Features

### Current Conditions
- Live temperature, humidity, dew point, wind speed/direction, barometric pressure, and visibility from your nearest NWS station
- Large ASCII weather icons
- Mini sparkline graphs for temperature, humidity, and wind trends
- Embedded radar panel alongside current conditions

### Forecast & Hourly
- Multi-day forecast with day/night periods from NWS (scrollable)
- Hourly forecast with sparkline charts and a tabular breakdown for the next 24 hours (configurable)

### Radar
- **256-color half-block rendering** — high-resolution radar imagery using Unicode half-block characters (▀/▄) with the NWS standard dBZ color scale
- **ASCII fallback** — automatically falls back to an ASCII art ramp on terminals without 256-color support
- **Animated radar** — press `A` to loop through recent MRMS frames; step through manually with `<` / `>`
- **Full-screen radar view** — press `w` for a dedicated radar map
- State boundary overlays and nearby city labels
- Click city labels with the mouse to jump to that location
- **Three radar sources** (automatic fallback):
  1. NOAA MRMS ImageServer (national composite, near real-time)
  2. Iowa State IEM NEXRAD WMS (CONUS composite)
  3. NWS station WMS (per-station)
- dBZ color legend displayed above the radar map
- Press `o` to open weather.gov radar in your browser

### Weather Alerts
- Active NWS alerts for your location, scrollable with `j`/`k`

### Moon Phase
- ASCII art moon rendering showing the current illumination
- Phase name, moon age, lunation number
- Moonrise and moonset times (requires `astral`)
- Upcoming phase dates (new moon, first quarter, full, last quarter)

### Favorites
- Save locations as favorites with `F`
- Cycle between saved favorites with `n`/`b`
- Full favorites editor (`e`) — add, delete, rename, reorder locations
- Search by city name or ZIP code

### Other
- US customary or SI units (`u` to toggle)
- 12-hour or 24-hour clock (`t` to toggle)
- Auto-refresh with configurable interval (default 5 minutes), pause with `p`
- Offline mode — falls back to cached state when the network is unavailable
- Location search by city/state or ZIP code (`l`)
- All settings persisted to `~/.config/nws-weather-tui/config.json`

## Installation

```bash
# Clone the repo
git clone https://github.com/crinderneck/nws-weather-tui.git
cd nws-weather-tui

# Install dependencies
pip install pillow requests numpy

# Optional: for sunrise/sunset and moonrise/moonset times
pip install astral
```

## Usage

```bash
python -m nws_weather_tui
# or (from repo root)
python __main__.py
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `c` | Current conditions |
| `f` | Forecast view |
| `h` | Hourly view |
| `a` | Alerts view |
| `w` | Full-screen radar |
| `m` | Moon phase |
| `l` | Search location |
| `r` | Force refresh |
| `u` | Toggle US / SI units |
| `t` | Toggle 12h / 24h clock |
| `p` | Pause / resume auto-refresh |
| `g` | Toggle mini-graphs |
| `F` | Toggle current location as favorite |
| `n` / `b` | Cycle favorites forward / back |
| `e` | Open favorites editor |
| `A` | Toggle radar animation |
| `<` / `>` | Step radar frames |
| `o` | Open radar in browser |
| `j` / `k` | Scroll (forecast, alerts) |
| `?` | Help |
| `q` | Quit |

## Configuration

Settings are stored at `~/.config/nws-weather-tui/config.json` and are created with defaults on first run. Key options:

| Setting | Default | Description |
|---------|---------|-------------|
| `location_name` | `"Spokane, WA"` | Display name for current location |
| `lat` / `lon` | Spokane coords | Coordinates for weather data |
| `units` | `"us"` | `"us"` or `"si"` |
| `use_24h` | `false` | 24-hour clock |
| `auto_refresh_seconds` | `300` | Auto-refresh interval |
| `hourly_hours` | `24` | Hours shown in hourly view |
| `show_radar_map` | `true` | Show radar on current conditions |
| `radar.animation_frames` | `4` | Number of animation frames |
| `radar.animation_interval_s` | `0.5` | Seconds between animation frames |
| `radar.show_state_lines` | `true` | State boundary overlays |
| `radar.show_city_labels` | `true` | City name labels on radar |

## Requirements

- Python 3.8+
- A terminal with curses support (most Linux/macOS terminals)
- 256-color terminal recommended for best radar display (falls back to ASCII automatically)
- **pillow** — image processing for radar
- **requests** — HTTP client
- **astral** (optional) — sunrise/sunset and moonrise/moonset times

## Data Source

All weather data comes from the [National Weather Service API](https://api.weather.gov), which is free, requires no API key, and covers the United States.
