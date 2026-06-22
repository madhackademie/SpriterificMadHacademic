from __future__ import annotations

from pathlib import Path

from PIL import Image

from .presets import FRAME_HEIGHT, FRAME_WIDTH, REFERENCE_SIZE, SHEET_COLUMNS, sheet_rows


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label} does not exist or is not a file: {path}")


def validate_reference(path: Path) -> None:
    require_file(path, "reference image")
    with Image.open(path) as image:
        if image.size != REFERENCE_SIZE:
            raise ValueError(f"reference image must be {REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]}, got {image.size[0]}x{image.size[1]}")


def validate_frame_count(frame_count: int) -> None:
    if frame_count not in {5, 6, 8, 10}:
        raise ValueError("frame count must be 5, 6, 8, or 10")


def validate_export_sheet(path: Path, frame_count: int) -> None:
    require_file(path, "export spritesheet")
    rows = sheet_rows(frame_count)
    expected = (SHEET_COLUMNS * FRAME_WIDTH, rows * FRAME_HEIGHT)
    with Image.open(path) as image:
        if image.size != expected:
            raise ValueError(f"export spritesheet must be {expected[0]}x{expected[1]}, got {image.size[0]}x{image.size[1]}")
