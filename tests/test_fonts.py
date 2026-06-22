from __future__ import annotations

from pathlib import Path

import pytest
from PIL import ImageFont

from spriterrific import fonts, pipeline
from spriterrific.pipeline import _contact_sheet_font_args


def test_contact_sheet_font_path_returns_existing_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # When a candidate exists, the returned path must actually exist on disk
    # (regression: the old helper returned a non-existent macOS path on Windows).
    path = fonts.contact_sheet_font_path()
    assert path is None or Path(path).exists()


def test_contact_sheet_font_path_none_when_no_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fonts.Path, "exists", lambda self: False)
    assert fonts.contact_sheet_font_path() is None


def test_contact_sheet_font_args_omits_flag_when_no_font(monkeypatch: pytest.MonkeyPatch) -> None:
    # On a font-less OS the pipeline must NOT pass a bogus --font-path; it omits
    # the flag so the subprocess falls back to load_default() instead of crashing.
    monkeypatch.setattr(fonts.Path, "exists", lambda self: False)
    assert _contact_sheet_font_args() == []


def test_contact_sheet_font_args_passes_flag_when_font_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # pipeline imports the function by name, so patch it on the pipeline module.
    monkeypatch.setattr(pipeline, "contact_sheet_font_path", lambda: "/fake/font.ttf")
    assert _contact_sheet_font_args() == ["--font-path", "/fake/font.ttf"]


def test_review_font_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fonts.Path, "exists", lambda self: False)
    font = fonts.review_font(size=14)
    assert isinstance(font, (ImageFont.FreeTypeFont, ImageFont.ImageFont))


def test_candidates_include_windows_paths() -> None:
    paths = [str(p) for p in fonts.FONT_CANDIDATES]
    assert any(p.startswith("C:/Windows/Fonts/") for p in paths)
