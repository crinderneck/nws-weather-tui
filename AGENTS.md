# AGENTS.md - NWS Weather TUI

## Build/Lint/Test Commands

### Running the Application
```bash
python -m nws_weather_tui
# or
python -m nws_weather_tui --help
```

### Linting
```bash
# Run ruff linter
ruff check .

# Fix auto-fixable issues
ruff check --fix .
```

### Testing
- **No tests currently exist** - Test framework can be added (pytest recommended)
- To add tests, create a `tests/` directory with `test_*.py` files

### Code Style Guidelines

#### Imports
- Use `from __future__ import annotations` for forward references
- Organize imports in three sections (separated by blank lines):
  1. Standard library (`import os`, `import re`, etc.)
  2. Third-party packages (`import curses`, `import requests`, etc.)
  3. Local modules (`from client import NWSClient`, `from helpers import ...`)
- Sort alphabetically within each group
- Use explicit imports (`from x import y, z`) rather than `import x`

#### Type Hints
- Always use type hints for function arguments and return types
- Use `Optional[X]` instead of `X | None` for Python 3.9 compatibility
- Use `Dict[str, Any]` for dict types, not `dict[str, Any]`
- Example: `def func(arg: str) -> Optional[bool]:`

#### Naming Conventions
- **Classes**: PascalCase (e.g., `class App`, `class NWSClient`)
- **Functions/Variables**: snake_case (e.g., `def _handle_key`, `self.location_name`)
- **Constants**: SCREAMING_SNAKE_CASE (e.g., `CONFIG_PATH`, `MIN_COLS`)
- **Private methods**: Prefix with underscore (e.g., `_load_points`, `_set_view`)

#### Dataclasses
- Use `@dataclass` for simple data containers
- Use `@dataclass` with `frozen=True` for immutable types when appropriate
- Order: class definition, then dataclass fields

#### Error Handling
- Use bare `except Exception` sparingly; prefer specific exceptions
- Always include context in error messages
- Use `_flash()` to display user-facing errors in the TUI
- Log debug info with `dbg()` helper for development

#### Key Handler Methods (Important!)
- **CRITICAL**: All methods called from `_handle_key` MUST return `bool`
- Return `True` to continue the application
- Return `False` to quit the application
- Methods that return `None` will cause the app to exit unexpectedly!

Example:
```python
# CORRECT
def _refresh(self) -> bool:
    self._show_loading("Refreshing now...")
    return True

# WRONG - will cause crash!
def _refresh(self) -> None:
    self._show_loading("Refreshing now...")
    # returns None implicitly
```

#### TUI/UI Guidelines
- Use `_flash(message, duration)` for temporary status messages
- Use `_show_loading(message)` for long-running operations
- Use `safe_addstr(stdscr, y, x, text)` instead of `stdscr.addstr()` to prevent crashes
- Use `clamp()` helper for value bounds

#### Code Formatting
- Maximum line length: 100 characters (ruff default)
- Use 4 spaces for indentation
- No trailing whitespace
- One blank line between top-level definitions

#### File Organization
- `app.py` - Main application class and entry point
- `client.py` - NWS API client
- `models.py` - Data models and extraction functions
- `views.py` - View/draw functions for each screen
- `views_chrome.py` - Header and footer chrome
- `views_radar.py` - Radar panel and full-screen radar view
- `views_current.py` - Current conditions view
- `views_forecast.py` - Multi-day forecast view
- `views_hourly.py` - Hourly forecast view
- `views_alerts.py` - Weather alerts view
- `views_help.py` - Help screen
- `views_moon.py` - Moon phase view
- `views_favorites.py` - Favorites editor
- `helpers.py` - Utility functions
- `constants.py` - Constants and configuration
- `cache.py` - Simple in-memory cache
- `icons.py` - Weather icons
- `sparklines.py` - ASCII sparkline generation

#### Git Conventions
- Use conventional commit messages
- Do not commit secrets, credentials, or API keys
- Do not commit `__pycache__/` or `.ruff_cache/`
