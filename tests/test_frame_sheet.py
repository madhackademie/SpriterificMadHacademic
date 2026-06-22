from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.frame_sheet import SheetFrameOptions, build_frame_sheet


def _make_frame(path: Path, size: tuple[int, int], fill: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((0, 0, size[0] - 1, size[1] - 1), fill=fill)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_build_frame_sheet_drops_frames_and_pads_final_row(tmp_path: Path) -> None:
    src = tmp_path / "src"
    for index, height in enumerate([40, 30, 40, 30, 40, 38], start=1):
        _make_frame(src / f"frame-{index:02d}.png", (12, height), (20 * index, 40, 120, 255))

    out = tmp_path / "out"
    paths = build_frame_sheet(
        src,
        out,
        options=SheetFrameOptions(cell_size=(64, 64), target_height=64, columns=5, fps=10, drop=("06",), review_upscale=2),
    )

    assert paths["spritesheet"].name == "spritesheet-64x64-5x1.png"
    with Image.open(paths["spritesheet"]) as sheet:
        assert sheet.size == (320, 64)
    with Image.open(out / "frames-64x64" / "frame-02.png") as frame:
        assert frame.getchannel("A").getbbox()[3] == 64
    assert (out / "review" / "preview-5f-64x64.gif").is_file()
    assert (out / "review" / "spritesheet-64x64-5x1-x2.png").is_file()
    index = out / "review" / "index.md"
    assert index.is_file()
    index_text = index.read_text(encoding="utf-8")
    assert "Preview GIF" in index_text
    assert "![Preview GIF](preview-5f-64x64.gif)" in index_text
    assert "![Runtime Spritesheet](../spritesheet-64x64-5x1.png)" in index_text

    metadata = json.loads((out / "sheet-frame-metadata.json").read_text())
    assert metadata["liveFrameCount"] == 5
    assert metadata["paddedFrameCount"] == 5


def test_build_frame_sheet_order_and_blank_padding(tmp_path: Path) -> None:
    src = tmp_path / "src"
    for index in range(1, 5):
        _make_frame(src / f"frame-{index:02d}.png", (8, 16), (30, 50 * index, 90, 255))

    out = tmp_path / "out"
    build_frame_sheet(
        src,
        out,
        options=SheetFrameOptions(cell_size=(32, 32), columns=3, order=("03", "01", "04"), review_upscale=1),
    )

    with Image.open(out / "spritesheet-32x32-3x1.png") as sheet:
        assert sheet.size == (96, 32)
    source_map = (out / "source-map.txt").read_text()
    assert "frame-01.png <-" in source_map
    assert "frame-03.png" in source_map.splitlines()[0]
