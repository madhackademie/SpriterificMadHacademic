from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.preprocess import preprocess_user_anchor


def test_preprocess_user_anchor_pixel_snaps_and_places_on_chroma(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    image = Image.new("RGBA", (300, 220), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 40, 180, 190), fill=(20, 80, 180, 255))
    draw.rectangle((136, 20, 164, 60), fill=(240, 200, 140, 255))
    image.save(source)

    out = tmp_path / "processed.png"
    metadata = tmp_path / "metadata.json"
    preprocess_user_anchor(source, out, metadata_out=metadata, padding=32, snap_long_edge=64)

    with Image.open(out).convert("RGBA") as processed:
        assert processed.size == (1024, 1024)
        assert processed.getpixel((0, 0)) == (0, 255, 0, 255)
        assert processed.getchannel("A").getbbox() == (0, 0, 1024, 1024)
        assert processed.getbbox() is not None
        colors = processed.getcolors(maxcolors=1024 * 1024)
        assert colors is not None
        assert any(pixel[:3] != (0, 255, 0) for _, pixel in colors)

    data = json.loads(metadata.read_text())
    assert data["sourceSize"] == [300, 220]
    assert data["targetSize"] == [1024, 1024]
    assert data["snapLongEdge"] == 64
    assert data["chroma"] == "#00FF00"
