from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from spriterrific.cells import crop_exact_cells


def test_crop_exact_cells_requires_expected_size(tmp_path: Path) -> None:
    sheet = tmp_path / "bad.png"
    Image.new("RGBA", (1024, 1024), (0, 255, 0, 255)).save(sheet)

    with pytest.raises(ValueError, match="requires sheet size 1280x256"):
        crop_exact_cells(sheet, tmp_path / "out", rows=1, cols=5)


def test_crop_exact_cells_writes_ordered_frames(tmp_path: Path) -> None:
    sheet = tmp_path / "sheet.png"
    image = Image.new("RGBA", (1280, 256), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    for col in range(5):
        draw.rectangle((col * 256 + 10, 10, col * 256 + 30, 30), fill=(col + 1, 0, 0, 255))
    image.save(sheet)

    frames = crop_exact_cells(sheet, tmp_path / "out", rows=1, cols=5)

    assert len(frames) == 5
    assert Image.open(frames[0]).getpixel((10, 10)) == (1, 0, 0, 255)
    assert Image.open(frames[4]).getpixel((10, 10)) == (5, 0, 0, 255)
    assert (tmp_path / "out" / "frame-cell-metadata.json").is_file()
