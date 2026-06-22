from __future__ import annotations

from pathlib import Path

from PIL import Image

from .media import foreground_bbox
from .presets import FRAME_HEIGHT, FRAME_WIDTH, SHEET_COLUMNS, TARGET_BOTTOM_Y, sheet_rows


CHROMA_GREEN = (0, 255, 0, 255)


def create_reference_sheet_guide(
    reference: Path,
    out: Path,
    *,
    frame_count: int,
    target_height: int = 210,
    max_width: int = 180,
) -> Path:
    rows = sheet_rows(frame_count)
    sheet = Image.new("RGBA", (SHEET_COLUMNS * FRAME_WIDTH, rows * FRAME_HEIGHT), CHROMA_GREEN)
    source = Image.open(reference).convert("RGBA")
    crop = source.crop(foreground_bbox(source))
    scale = min(1.0, target_height / crop.height, max_width / crop.width)
    sprite = crop.resize(
        (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
        Image.Resampling.NEAREST,
    )

    for index in range(frame_count):
        col = index % SHEET_COLUMNS
        row = index // SHEET_COLUMNS
        cell_left = col * FRAME_WIDTH
        cell_top = row * FRAME_HEIGHT
        x = cell_left + (FRAME_WIDTH - sprite.width) // 2
        y = cell_top + TARGET_BOTTOM_Y - sprite.height + 1
        sheet.alpha_composite(sprite, (x, y))

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out)
    return out
