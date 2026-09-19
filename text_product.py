#!/usr/bin/env python3
"""
NWS Weather TUI — Raw NWS text product cleanup (AFD, HWO, etc.).

Text products from api.weather.gov arrive as a single hard-wrapped blob
with WMO/product boilerplate, ``.SECTION NAME...`` headers, ``&&`` section
dividers, and a trailing ``$$`` marker. This module strips the noise,
splits the product into titled sections, and reflows each section's prose
into natural paragraphs — while leaving columnar data (e.g. a temps/PoPs
table) and short list-style lines alone instead of mangling them into one
run-on line.
"""

from __future__ import annotations

import re
import textwrap
from functools import lru_cache
from typing import List, Optional, Tuple

_SECTION_RE = re.compile(r"^\.(\S.{0,80}?)\.{2,}\s*$")
_COLUMNAR_RE = re.compile(r"\d\s{2,}\d")
_DASH_LIST_RE = re.compile(r"^\S+\s+-\s+\S")
_LABEL_LIST_RE = re.compile(r"^[A-Za-z0-9 /]{1,24}\.\.\.\S")


def _is_preformatted_line(line: str) -> bool:
    return bool(
        _COLUMNAR_RE.search(line)
        or _DASH_LIST_RE.match(line.strip())
        or _LABEL_LIST_RE.match(line.strip())
    )


def parse_sections(raw_text: str) -> List[Tuple[str, str]]:
    """Split a raw NWS text product into (title, body) sections.

    Discards the WMO/product boilerplate before the first ``.TITLE...``
    header and the ``&&``/``$$`` section markers.
    """
    lines = (raw_text or "").splitlines()

    start: Optional[int] = None
    for i, line in enumerate(lines):
        if _SECTION_RE.match(line.strip()):
            start = i
            break
    if start is None:
        body = "\n".join(lines).strip()
        return [("", body)] if body else []

    sections: List[Tuple[str, str]] = []
    title = _SECTION_RE.match(lines[start].strip()).group(1).strip()
    body_lines: List[str] = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        m = _SECTION_RE.match(stripped)
        if m:
            sections.append((title, "\n".join(body_lines).strip()))
            title = m.group(1).strip()
            body_lines = []
            continue
        if stripped in ("&&", "$$"):
            continue
        body_lines.append(line)
    sections.append((title, "\n".join(body_lines).strip()))

    return [(" ".join(t.split()), b) for t, b in sections if b]


def _wrap_paragraph(text: str, width: int) -> List[str]:
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return []

    preformatted_votes = sum(1 for line in non_empty if _is_preformatted_line(line))
    if len(non_empty) > 1 and preformatted_votes >= max(1, len(non_empty) // 2):
        out: List[str] = []
        for line in non_empty:
            line = line.rstrip()
            if len(line) <= width:
                out.append(line)
            else:
                out.extend(textwrap.wrap(line, width) or [""])
        return out

    flat = " ".join(line.strip() for line in lines).strip()
    return textwrap.wrap(flat, width) or [""]


def format_body(body: str, width: int) -> List[str]:
    """Reflow a section body into display lines.

    Blank-line separated chunks are treated as paragraphs; columnar/list
    content is preserved verbatim instead of being merged into flowing
    prose.
    """
    out: List[str] = []
    for para in re.split(r"\n\s*\n", body):
        wrapped = _wrap_paragraph(para, width)
        if not wrapped:
            continue
        if out:
            out.append("")
        out.extend(wrapped)
    return out


@lru_cache(maxsize=8)
def render_text_product(raw_text: str, width: int) -> Tuple[Tuple[str, bool], ...]:
    """Render a raw NWS text product into (line, is_title) tuples.

    Ready for direct line-based scrolling/drawing: bold the lines where
    ``is_title`` is True, draw the rest normally. Cached, since the same
    product text is re-rendered on every draw tick while its view is open.
    """
    out: List[Tuple[str, bool]] = []
    for title, body in parse_sections(raw_text):
        if out:
            out.append(("", False))
        if title:
            out.append((title, True))
        out.extend((line, False) for line in format_body(body, width))
    return tuple(out)
