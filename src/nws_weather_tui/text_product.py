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
from typing import Iterable, List, Optional, Set, Tuple

_SECTION_RE = re.compile(r"^\.(\S.{0,80}?)\.{2,}\s*$")
# HWO-style header with its text on the same line: ".DAY ONE...Today and tonight."
_INLINE_SECTION_RE = re.compile(r"^\.([A-Z][A-Z0-9 /&()-]{1,60}?)\.{3}(\S.*)$")
_COLUMNAR_RE = re.compile(r"\d\s{2,}\d")
_DASH_LIST_RE = re.compile(r"^\S+\s+-\s+\S")
_LABEL_LIST_RE = re.compile(r"^[A-Za-z0-9 /]{1,24}\.\.\.\S")


# A segment's UGC header: zone/county codes ending in a ddhhmm expiry, e.g.
# "INZ050-058-059-066-073>075-080-KYZ089>100-OHZ060>065-" + "088-140800-".
_UGC_START_RE = re.compile(r"^[A-Z]{2}[CZ]\d{3}[->]")
_UGC_END_RE = re.compile(r"\d{6}-\s*$")
_UGC_TOKEN_RE = re.compile(r"^(?:([A-Z]{2}[CZ])?(\d{3})(?:>(\d{3}))?)$")
_SEGMENT_SPLIT_RE = re.compile(r"^\s*\$\$\s*$", re.MULTILINE)
_ISSUED_LINE_RE = re.compile(r"^\d{3,4} [AP]M [A-Z]{3,4} \w{3} \w{3} \d{1,2} \d{4}$")


def ugc_zones(header: str) -> Set[str]:
    """Expand a UGC header into codes: "OHZ051>053-055-140800-" ->
    {"OHZ051", "OHZ052", "OHZ053", "OHZ055"}. Codes without a prefix
    inherit the last one; the trailing ddhhmm expiry is skipped."""
    zones: Set[str] = set()
    prefix = ""
    for token in "".join(header.split()).split("-"):
        m = _UGC_TOKEN_RE.match(token)
        if not m:
            continue  # the 6-digit expiry, or an empty token
        prefix = m.group(1) or prefix
        if not prefix:
            continue
        lo = int(m.group(2))
        hi = int(m.group(3)) if m.group(3) else lo
        zones.update(f"{prefix}{n:03d}" for n in range(lo, hi + 1))
    return zones


def _split_segment(segment: str) -> Tuple[Set[str], str]:
    """(zones, body) for one $$-delimited segment. The body loses the UGC
    header, the place-name lines after it and the issuance-time line."""
    lines = segment.strip("\n").splitlines()
    i = 0
    while i < len(lines) and not _UGC_START_RE.match(lines[i].strip()):
        i += 1
    if i == len(lines):
        return set(), segment
    head_start = i
    while i < len(lines) and not _UGC_END_RE.search(lines[i]):
        i += 1
    zones = ugc_zones(" ".join(lines[head_start:i + 1]))
    i += 1
    while i < len(lines) and lines[i].rstrip().endswith("-"):
        i += 1  # "Hardin-Mercer-Auglaize-..." place names
    if i < len(lines) and _ISSUED_LINE_RE.match(lines[i].strip()):
        i += 1
    return zones, "\n".join(lines[:head_start] + lines[i:])


def segment_for_zones(raw_text: str, zones: Iterable[str]) -> str:
    """The part of a multi-segment product (e.g. an HWO with one segment per
    zone group) that covers any of `zones`. Products with a single segment
    come back unchanged; if no segment matches, every segment is kept but
    their UGC headers are dropped so they don't read as prose."""
    parts = [p for p in _SEGMENT_SPLIT_RE.split(raw_text or "") if p.strip()]
    split = [_split_segment(p) for p in parts]
    if sum(1 for z, _ in split if z) < 2:
        return raw_text
    wanted = {z.upper() for z in zones if z}
    for seg_zones, body in split:
        if seg_zones & wanted:
            return body
    return "\n\n".join(body for _, body in split)


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

    def header(line: str) -> Optional[Tuple[str, str]]:
        """(title, text after the header) if `line` opens a section."""
        stripped = line.strip()
        m = _SECTION_RE.match(stripped)
        if m:
            return m.group(1).strip(), ""
        m = _INLINE_SECTION_RE.match(stripped)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return None

    start: Optional[int] = None
    for i, line in enumerate(lines):
        if header(line):
            start = i
            break
    if start is None:
        body = "\n".join(lines).strip()
        return [("", body)] if body else []

    sections: List[Tuple[str, str]] = []
    title, lead = header(lines[start])  # type: ignore[misc]
    body_lines: List[str] = [lead] if lead else []
    for line in lines[start + 1:]:
        stripped = line.strip()
        h = header(line)
        if h:
            sections.append((title, "\n".join(body_lines).strip()))
            title, lead = h
            body_lines = [lead] if lead else []
            continue
        if stripped in ("&&", "$$"):
            continue
        body_lines.append(line)
    sections.append((title, "\n".join(body_lines).strip()))

    return [(" ".join(t.split()), b) for t, b in sections if b]


def _is_preformatted_para(non_empty: List[str]) -> bool:
    votes = sum(1 for line in non_empty if _is_preformatted_line(line))
    return len(non_empty) > 1 and votes >= max(1, len(non_empty) // 2)


def widest_preformatted_line(raw_text: str) -> int:
    """Length of the longest line in the product's tables/lists — the
    narrowest a column can be without re-wrapping them into mush."""
    widest = 0
    for _, body in parse_sections(raw_text):
        for para in re.split(r"\n\s*\n", body):
            non_empty = [line.rstrip() for line in para.splitlines() if line.strip()]
            if _is_preformatted_para(non_empty):
                widest = max(widest, max(len(line) for line in non_empty))
    return widest


def _wrap_paragraph(text: str, width: int) -> List[str]:
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return []

    if _is_preformatted_para(non_empty):
        out: List[str] = []
        for line in non_empty:
            line = line.rstrip()
            if len(line) <= width:
                out.append(line)
            else:
                out.extend(textwrap.wrap(line, width, subsequent_indent="    ") or [""])
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
