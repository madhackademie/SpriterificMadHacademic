"""Shared font discovery for review and contact-sheet rendering.

A single cross-platform candidate list so the macOS-only default cannot
silently reappear across the engine (it previously lived, copy-pasted, in
five places and crashed on Windows where none of the macOS/Linux paths
exist).

Note: the standalone ``runtime_tools/animated_spritesheets/scripts/
build_contact_sheet.py`` subprocess keeps its own inline copy of this list
and fallback, because it runs via ``uv run`` with an isolated dependency
block and cannot import this package. Keep the two in sync.
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

# Bold sans-serif candidates, ordered by platform. First existing path wins.
FONT_CANDIDATES: tuple[Path, ...] = (
    # macOS
    Path("/System/Library/Fonts/Supplemental/Verdana Bold.ttf"),
    # Linux
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    # Windows
    Path("C:/Windows/Fonts/verdanab.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
)


def contact_sheet_font_path() -> str | None:
    """Return the first existing bold-font path, or ``None`` if none exist.

    Returning ``None`` (rather than a non-existent path) lets callers omit the
    ``--font-path`` flag so the subprocess falls back to ``load_default()``.
    """
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def review_font(*, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a bold review font at ``size``, falling back to PIL's default."""
    path = contact_sheet_font_path()
    if path is not None:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()
