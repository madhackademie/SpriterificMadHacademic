from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.frame_aligner import (
    FrameOffset,
    apply_frame_offset,
    pack_aligned_spritesheet,
    render_guided_frame,
    write_alignment_export,
)


def _make_runtime_frame(path: Path, color: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((6, 6, 9, 12), fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_apply_frame_offset_moves_pixels_without_resizing() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    image.putpixel((2, 3), (255, 0, 0, 255))

    moved = apply_frame_offset(image, FrameOffset(dx=2, dy=-1))

    assert moved.size == (8, 8)
    assert moved.getpixel((4, 2)) == (255, 0, 0, 255)
    assert moved.getpixel((2, 3)) == (0, 0, 0, 0)


def test_pack_aligned_spritesheet_uses_source_frame_size(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    for index in range(1, 4):
        _make_runtime_frame(frames / f"frame-{index:02d}.png", (30 * index, 20, 40, 255))

    out = tmp_path / "sheet.png"
    pack_aligned_spritesheet(sorted(frames.glob("frame-*.png")), out, columns=2)

    with Image.open(out) as sheet:
        assert sheet.size == (32, 32)


def test_render_guided_frame_draws_center_lines() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))

    guided = render_guided_frame(image, scale=1)

    assert guided.getpixel((4, 0))[3] == 255
    assert guided.getpixel((0, 4))[3] == 255
    assert guided.getpixel((0, 7))[3] == 255


def test_render_guided_frame_can_overlay_tinted_ghost_layers() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    ghost = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    ghost.putpixel((2, 2), (255, 255, 255, 255))

    guided = render_guided_frame(
        image,
        scale=1,
        ghost_layers=[(ghost, FrameOffset(dx=1, dy=0), (255, 0, 0, 255))],
        ghost_opacity=0.5,
    )

    r, g, b, a = guided.getpixel((3, 2))
    assert r > g
    assert r > b
    assert a == 255


def test_write_alignment_export_writes_frames_sheet_gif_and_report(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    for index in range(1, 4):
        _make_runtime_frame(frames / f"frame-{index:02d}.png", (30 * index, 20, 40, 255))

    export = write_alignment_export(
        input_dir=frames,
        out_dir=tmp_path / "align",
        offsets={"frame-02.png": FrameOffset(dx=1, dy=-2)},
        columns=2,
        fps=8,
    )

    assert export.report.is_file()
    assert export.metadata.is_file()
    assert export.review_index.is_file()
    assert export.before_preview_gif.is_file()
    assert export.before_after_preview_gif.is_file()
    assert (export.frames_dir / "frame-02.png").is_file()
    with Image.open(export.spritesheet) as sheet:
        assert sheet.size == (32, 32)
    with Image.open(export.preview_gif) as gif:
        assert getattr(gif, "n_frames", 1) == 3
    data = json.loads(export.metadata.read_text(encoding="utf-8"))
    assert data["frames"][1]["dx"] == 1
    assert data["frames"][1]["dy"] == -2
    review = export.review_index.read_text(encoding="utf-8")
    assert "Guided Contact Sheet" in review
    assert "Before Preview GIF" in review
    assert "Before/After Preview GIF" in review
    assert "Runtime Spritesheet" in review
