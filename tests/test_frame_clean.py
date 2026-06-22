from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.frame_clean import CleanFrameOptions, clean_frame, clean_frame_batch


def test_clean_frame_removes_neutral_edge_speckles_and_keeps_warm_highlight() -> None:
    image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 4, 15, 20), fill=(80, 35, 140, 255))
    draw.point((7, 10), fill=(180, 180, 180, 255))
    draw.point((16, 10), fill=(240, 210, 170, 255))
    draw.point((1, 1), fill=(230, 230, 230, 255))
    draw.point((1, 2), fill=(120, 35, 20, 255))

    cleaned, metadata = clean_frame(image, CleanFrameOptions(min_component_area=2))

    assert cleaned.getchannel("A").getbbox() == (0, 0, 9, 17)
    assert metadata["removedNeutralEdgePixels"] == 2
    assert metadata["removedComponents"] == 1
    assert cleaned.getpixel((0, 6)) == (80, 35, 140, 255)
    assert cleaned.getpixel((8, 6)) == (240, 210, 170, 255)
    assert all(cleaned.getpixel((x, y)) != (180, 180, 180, 255) for y in range(cleaned.height) for x in range(cleaned.width))


def test_clean_frame_batch_writes_metadata(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((4, 2, 11, 14), fill=(60, 40, 130, 255))
    image.save(src / "frame-01.png")

    out = tmp_path / "out"
    outputs = clean_frame_batch(src, out)

    assert [path.name for path in outputs] == ["frame-01.png"]
    data = json.loads((out / "clean-frame-metadata.json").read_text())
    assert data[0]["output"].endswith("frame-01.png")
