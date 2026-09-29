#!/usr/bin/env python3
"""loc_to_paper.py - How many sheets of paper would this project take to print?

Counts lines of code in a live git repo (this project by default) and converts
that to an estimated sheet count for printing on standard letter/A4 paper. As a
bonus, it shallow-clones the real Apollo 11 Guidance Computer (AGC) source code
(chrislgarry/Apollo-11 on GitHub, the actual assembly listings released by MIT)
and compares live numbers rather than a hardcoded figure.

Usage:
    python tools/loc_to_paper.py [path-to-project]

Requires `git` on PATH and network access for the Apollo 11 comparison; the
project line count works offline against the local repo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# --- Config ---

# Typical code printout: ~10-11pt monospace font, 1" margins, single-spaced.
LINES_PER_PAGE = 60
# Set to 2 if you'd print duplex (double-sided) and want sheets rather than pages.
PAGES_PER_SHEET = 1

APOLLO_REPO_URL = "https://github.com/chrislgarry/Apollo-11.git"

EXCLUDE_DIRS = {".git", "__pycache__", ".ruff_cache", "node_modules", ".venv", "venv"}


def is_probably_binary(path: Path) -> bool:
    """Heuristic: a NUL byte in the first KB means treat the file as binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
        return b"\0" in chunk
    except OSError:
        return True


def list_repo_files(root: Path) -> list:
    """Prefer `git ls-files` (live, respects .gitignore); fall back to a walk."""
    if (root / ".git").exists() and shutil.which("git"):
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files"],
                capture_output=True, text=True, check=True,
            ).stdout
            files = [root / line for line in out.splitlines() if line.strip()]
            if files:
                return files
        except subprocess.CalledProcessError:
            pass

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            files.append(Path(dirpath) / fn)
    return files


def count_lines_in_repo(root: Path) -> Tuple[int, int]:
    """Return (total_lines, total_files) for text files in a repo."""
    total_lines = 0
    total_files = 0
    for f in list_repo_files(root):
        if not f.is_file() or is_probably_binary(f):
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                total_lines += sum(1 for _ in fh)
            total_files += 1
        except OSError:
            continue
    return total_lines, total_files


def fetch_apollo11_lines() -> Optional[Tuple[int, int]]:
    """Shallow-clone the real Apollo 11 AGC source repo and count its lines live."""
    if not shutil.which("git"):
        print("  git not found; skipping live Apollo 11 comparison.")
        return None

    with tempfile.TemporaryDirectory(prefix="apollo11_") as tmp:
        tmp_path = Path(tmp)
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", APOLLO_REPO_URL, str(tmp_path)],
                check=True, capture_output=True, text=True, timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"  Could not clone {APOLLO_REPO_URL} live: {e}")
            return None
        return count_lines_in_repo(tmp_path)


def sheets_for(lines: int) -> float:
    return (lines / LINES_PER_PAGE) / PAGES_PER_SHEET


def report(label: str, lines: int, files: int) -> float:
    sheets = sheets_for(lines)
    print(f"  {label}: {files:,} files, {lines:,} lines")
    print(f"  ≈ {sheets:,.1f} sheets of paper "
          f"(at {LINES_PER_PAGE} lines/page, {PAGES_PER_SHEET} page/sheet)")
    return sheets


def main() -> None:
    project_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()

    print(f"Counting lines in {project_path} (live from git) ...")
    proj_lines, proj_files = count_lines_in_repo(project_path)
    proj_sheets = report("This project", proj_lines, proj_files)

    print("\nFetching the real Apollo 11 AGC source (chrislgarry/Apollo-11) live for comparison...")
    agc = fetch_apollo11_lines()
    if agc is None:
        print("\n(Skipping the Apollo 11 comparison - no live data available.)")
        return
    agc_lines, agc_files = agc
    agc_sheets = report("Apollo 11 AGC", agc_lines, agc_files)

    print("\n--- Bonus stat ---")
    if agc_lines == 0 or proj_lines == 0:
        print("Not enough data to compare.")
        return

    pct = proj_lines / agc_lines * 100
    print(f"This project is {pct:.2f}% the size of the Apollo 11 Guidance Computer source code.")
    if proj_lines < agc_lines:
        print(f"The AGC that flew Apollo 11 to the Moon has {agc_lines / proj_lines:,.1f}x more lines "
              f"({agc_sheets - proj_sheets:,.0f} more sheets) than this project.")
    else:
        print(f"This project has {proj_lines / agc_lines:,.1f}x more lines "
              f"({proj_sheets - agc_sheets:,.0f} more sheets) than the AGC that flew Apollo 11 to the Moon.")


if __name__ == "__main__":
    main()
