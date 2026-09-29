#!/usr/bin/env python3
"""
NWS Weather TUI — Area Forecast Discussion (AFD) view.

Laid out like a newspaper: on wide terminals the discussion flows down a
column and on into the next, a page of columns at a time. The column count
is chosen per terminal size to use the fewest pages and fill the height,
while keeping columns a comfortable reading width (and wide enough for any
table, where possible). Room left on the last page is filled with the
Hazardous Weather Outlook, then earlier discussions (dimmed). Very
short terminals fall back to a single scrolling column.
"""

from __future__ import annotations

from functools import lru_cache
from math import ceil
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

import curses

from nws_weather_tui.formatting import fmt_time, parse_iso
from nws_weather_tui.geo import clamp
from nws_weather_tui.helpers import safe_addstr
from nws_weather_tui.text_product import render_text_product, widest_preformatted_line

if TYPE_CHECKING:
    from nws_weather_tui.app import App

COL_GAP = 3        # space, rule, space between columns
MIN_COL_W = 44     # narrowest comfortable reading measure
MAX_COL_W = 90     # widest before lines get hard to track across
MAX_COLS = 6
MIN_COL_H = 6      # any shorter and flowing across columns gets choppy

# Line styles. render_text_product's is_title flag maps onto BODY/TITLE.
BODY, TITLE, PRODUCT, FADED, FADED_TITLE = range(5)
HEADINGS = (TITLE, PRODUCT, FADED_TITLE)

Line = Tuple[str, int]  # (text, style)


@lru_cache(maxsize=8)
def _layout(raw_text: str, cols: int, col_h: int) -> Tuple[int, int]:
    """(number of columns, column width) that best fills the screen.

    Every column count whose width stays readable is tried. The winner
    needs the fewest pages; among those, a table that fits unwrapped is
    preferred, then the fewest columns — fewer, taller columns fill the
    height instead of leaving the bottom of the screen empty.
    """
    if col_h < MIN_COL_H:
        return 1, cols - 1
    table_w = widest_preformatted_line(raw_text)
    best: Optional[Tuple[Tuple[int, bool, int], int, int]] = None
    for n in range(1, MAX_COLS + 1):
        w = (cols - 1 - COL_GAP * (n - 1)) // n
        if w < MIN_COL_W:
            break
        if w > MAX_COL_W:
            continue
        pages = ceil(len(_flow(render_text_product(raw_text, w), col_h)) / n)
        key = (pages, w < table_w, n)
        if best is None or key < best[0]:
            best = (key, n, w)
    if best is None:  # too narrow for even one full-width reading column
        return 1, cols - 1
    return best[1], best[2]


def _flow(lines: Sequence[Line], height: int) -> List[List[Line]]:
    return _flow_at(lines, height)[0]


def _flow_at(lines: Sequence[Line], height: int) -> Tuple[List[List[Line]], List[int]]:
    """Pour lines into columns of at most `height` rows; also returns the
    index into `lines` where each column starts. Columns never open on a
    blank line, and a heading moves to the next column rather than sit at
    the bottom without at least two lines of its text."""
    columns: List[List[Line]] = [[]]
    starts = [0]
    for i, (text, style) in enumerate(lines):
        col = columns[-1]
        if not col and not text:
            continue
        need = 1
        if style in HEADINGS:
            span = 3 if style == PRODUCT else 2  # a product heading, then its first section
            need += sum(1 for t, _ in lines[i + 1:i + 1 + span] if t)
        if height - len(col) < need:
            columns.append([])
            starts.append(i)
            col = columns[-1]
            if not text:
                continue
        col.append((text, style))
    return columns, starts


def _balanced(lines: Sequence[Line], n: int, max_h: int) -> List[List[Line]]:
    """Flow into columns; when everything fits on one page, use the
    shortest height that still fits so the columns come out even."""
    full = _flow(lines, max_h)
    if len(full) > n:
        return full
    for h in range(max(1, ceil(len(lines) / n)), max_h):
        cols = _flow(lines, h)
        if len(cols) <= n:
            return cols
    return full


def _product_lines(
    app: "App", product: Optional[Dict[str, Any]], name: str, w: int, faded: bool,
) -> List[Line]:
    """A whole text product as lines under its own heading, for filling
    spare room after the discussion."""
    if not product or not product.get("text"):
        return []
    issued_dt = parse_iso(product.get("issuance_time"))
    issued = fmt_time(issued_dt, app.use_24h, True) if issued_dt else "—"
    out: List[Line] = [("", BODY), (f"{name} · issued {issued}", PRODUCT)]
    for text, is_title in render_text_product(product["text"], max(1, w)):
        if faded:
            out.append((text, FADED_TITLE if is_title else FADED))
        else:
            out.append((text, TITLE if is_title else BODY))
    return out


def _draw_line(win, y: int, x: int, w: int, text: str, style: int) -> None:
    if style in (BODY, FADED):
        safe_addstr(win, y, x, text[:w], curses.A_DIM if style == FADED else 0)
        return
    attr, rule = {
        TITLE: (curses.color_pair(2) | curses.A_BOLD, "─"),
        PRODUCT: (curses.color_pair(1) | curses.A_BOLD, "═"),
        FADED_TITLE: (curses.A_DIM | curses.A_BOLD, "─"),
    }[style]
    safe_addstr(win, y, x, text[:w], attr)
    if len(text) + 2 <= w:
        safe_addstr(win, y, x + len(text) + 1, rule * (w - len(text) - 1), curses.A_DIM)


def draw_afd(app: "App", win) -> None:
    def filler(w: int) -> List[Line]:
        # Spare room on the last page goes to the Hazardous Weather Outlook,
        # then earlier (dimmed) discussions, cut off once the page is full.
        out = _product_lines(app, app.hwo, "HAZARDOUS WEATHER OUTLOOK", w, faded=False)
        for prod in app.afd_earlier:
            out += _product_lines(app, prod, "EARLIER DISCUSSION", w, faded=True)
        return out

    draw_text_product(app, win, app.afd, "Area Forecast Discussion", "afd_scroll", filler)


def draw_text_product(
    app: "App", win, product: Optional[Dict[str, Any]], title: str, scroll_attr: str,
    filler: Optional[Callable[[int], List[Line]]] = None,
    empty: Optional[Callable[[Any, int, int], None]] = None,
) -> None:
    """Draw a NWS text product in newspaper columns (or one scrolling column
    on small terminals). `scroll_attr` names the App attribute holding the
    page/line position; `empty` draws the screen when there's no product."""
    win.erase()
    rows, cols = win.getmaxyx()

    if not product or not product.get("text"):
        if empty is not None:
            empty(win, rows, cols)
        else:
            safe_addstr(win, 0, 0, f"No {title.lower()} available yet.",
                        curses.color_pair(3) | curses.A_BOLD)
        win.noutrefresh()
        return

    office = product.get("office") or "—"
    issued_dt = parse_iso(product.get("issuance_time"))
    issued_s = fmt_time(issued_dt, app.use_24h, True) if issued_dt else "—"
    header = f"{title} — {office}   Issued {issued_s}"
    safe_addstr(win, 0, 0, header[: cols - 1], curses.color_pair(15) | curses.A_BOLD)
    safe_addstr(win, 1, 0, "═" * (cols - 1), curses.color_pair(15))

    y0 = 2
    col_h = max(1, rows - y0 - 1)
    n, w = _layout(product["text"], cols, col_h)
    lines: List[Line] = [
        (text, TITLE if is_title else BODY)
        for text, is_title in render_text_product(product["text"], max(1, w))
    ]

    if n == 1:
        _draw_single(app, win, lines, y0, rows, cols, scroll_attr)
    else:
        extra = filler(w) if filler is not None else []
        _draw_columns(app, win, lines, extra, n, w, y0, col_h, rows, cols, scroll_attr)
    win.noutrefresh()


def _draw_single(
    app: "App", win, lines: Sequence[Line], y0: int, rows: int, cols: int, scroll_attr: str,
) -> None:
    """One column scrolled line by line (narrow or short terminals)."""
    total = len(lines)
    view_rows = rows - y0 - 1
    scroll = clamp(getattr(app, scroll_attr), 0, max(0, total - max(1, view_rows)))
    setattr(app, scroll_attr, scroll)

    y = y0
    for text, style in lines[scroll:]:
        if y >= rows - 1:
            break
        _draw_line(win, y, 0, cols - 1, text, style)
        y += 1

    scroll_pos = scroll + 1
    scroll_max = max(1, total - max(1, view_rows) + 1)
    safe_addstr(
        win, rows - 1, 0,
        f"Scroll: {scroll_pos}/{scroll_max} (j/k ↑↓)"[: cols - 1],
        curses.A_DIM,
    )


def _draw_columns(
    app: "App", win, lines: Sequence[Line], filler: Sequence[Line], n: int, w: int,
    y0: int, col_h: int, rows: int, cols: int, scroll_attr: str,
) -> None:
    """Newspaper columns, a page at a time; j/k turn the page. `filler`
    only takes up room left on the last page — it never adds a page."""
    # Every page but the last runs full height; the last page's share of
    # discussion + filler is balanced so its columns end level.
    n_pages = ceil(len(_flow(lines, col_h)) / n)
    everything = list(lines) + list(filler)
    flowed, starts = _flow_at(everything, col_h)
    head_n = (n_pages - 1) * n
    rest = everything[starts[head_n]:] if head_n < len(flowed) else []
    tail = _balanced(rest, n, col_h)
    if len(tail) > n:
        tail = tail[:n]
        tail[-1][-1] = ("…", FADED)
    columns = flowed[:head_n] + tail
    pages = [columns[i:i + n] for i in range(0, len(columns), n)]
    page_i = clamp(getattr(app, scroll_attr), 0, len(pages) - 1)
    setattr(app, scroll_attr, page_i)

    page = pages[page_i]
    height = max(len(c) for c in page)
    for k, col in enumerate(page):
        x = k * (w + COL_GAP)
        if k:
            for y in range(y0, y0 + height):
                safe_addstr(win, y, x - COL_GAP // 2 - 1, "│", curses.A_DIM)
        for j, (text, style) in enumerate(col):
            _draw_line(win, y0 + j, x, w, text, style)

    if len(pages) > 1:
        more = " · continued →" if page_i < len(pages) - 1 else ""
        hint = f"Page {page_i + 1}/{len(pages)} · j/k ↑↓ turn page{more}"
        safe_addstr(win, rows - 1, 0, hint[: cols - 1], curses.A_DIM)
