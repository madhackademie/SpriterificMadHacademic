from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.scale import scale_frame_crops


def test_scale_frame_crops_uses_one_shared_downscale(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for index, height in enumerate([360, 300], start=1):
        image = Image.new("RGBA", (180, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 0, 160, height - 1), fill=(200, 80, 40, 255))
        image.save(src / f"frame-{index:02d}.png")

    out = tmp_path / "out"
    scale_frame_crops(src, out, target_height=210, max_width=220)

    with Image.open(out / "frame-01.png") as image:
        assert image.size == (82, 210)
    with Image.open(out / "frame-02.png") as image:
        assert image.size == (82, 175)

    metadata = json.loads((out / "scale-metadata.json").read_text())
    assert metadata["scale"] == 210 / 360


def test_scale_frame_crops_does_not_upscale(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    image = Image.new("RGBA", (80, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 0, 70, 99), fill=(20, 90, 180, 255))
    image.save(src / "frame-01.png")

    out = tmp_path / "out"
    scale_frame_crops(src, out, target_height=210, max_width=220)

    with Image.open(out / "frame-01.png") as result:
        assert result.size == (61, 100)
