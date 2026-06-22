from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.sheet_guides import create_reference_sheet_guide


def make_anchor(path: Path) -> Path:
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((430, 180, 594, 880), fill=(220, 80, 20, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def test_create_reference_sheet_guide_five_frames(tmp_path: Path) -> None:
    out = tmp_path / "guide.png"
    create_reference_sheet_guide(make_anchor(tmp_path / "anchor.png"), out, frame_count=5)

    with Image.open(out).convert("RGBA") as image:
        assert image.size == (1280, 256)
        assert image.getpixel((0, 0)) == (0, 255, 0, 255)
        for col in range(5):
            cell = image.crop((col * 256, 0, (col + 1) * 256, 256))
            data = cell.get_flattened_data() if hasattr(cell, "get_flattened_data") else cell.getdata()
            non_green = [pixel for pixel in data if pixel != (0, 255, 0, 255)]
            assert len(non_green) > 1000


def test_create_reference_sheet_guide_ten_frames(tmp_path: Path) -> None:
    out = tmp_path / "guide.png"
    create_reference_sheet_guide(make_anchor(tmp_path / "anchor.png"), out, frame_count=10)

    with Image.open(out) as image:
        assert image.size == (1280, 512)
