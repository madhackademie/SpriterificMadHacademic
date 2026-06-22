from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.manifest import write_export_manifest
from spriterrific.pack import pack_spritesheet


def _make_frames(root: Path, count: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1, count + 1):
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((96, 96, 160, 255), fill=(220, 40 + index, 40, 255))
        img.save(root / f"frame-{index:02d}.png")


def test_pack_five_frames(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    _make_frames(frames, 5)
    out = tmp_path / "spritesheet.png"
    pack_spritesheet(frames, out, 5)
    with Image.open(out) as img:
        assert img.size == (1280, 256)


def test_pack_ten_frames(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    _make_frames(frames, 10)
    out = tmp_path / "spritesheet.png"
    pack_spritesheet(frames, out, 10)
    with Image.open(out) as img:
        assert img.size == (1280, 512)


def test_manifest_shape(tmp_path: Path) -> None:
    out = tmp_path / "manifest.json"
    write_export_manifest(out=out, run_id="run-test", action="walk", direction="e", mode="video", frame_count=10, fps=10)
    data = json.loads(out.read_text())
    assert data["spritesheet"] == "spritesheet.png"
    assert data["columns"] == 5
    assert data["rows"] == 2
    assert data["anchor"] == {"x": 128, "y": 255}
    assert data["publicAssetReady"] is False
