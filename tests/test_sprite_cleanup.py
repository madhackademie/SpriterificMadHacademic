from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.sprite_cleanup import (
    apply_pixel_edit,
    cleanup_frame_paths,
    pack_cleanup_spritesheet,
    render_cleanup_preview,
    write_cleanup_export,
)


def _make_frame(path: Path, color: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 5, 6), fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_apply_pixel_edit_paints_and_erases_pixels() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))

    painted = apply_pixel_edit(image, 3, 4, color=(255, 0, 128, 255), brush_size=1)
    erased = apply_pixel_edit(painted, 3, 4, color=(255, 0, 128, 255), brush_size=1, erase=True)

    assert painted.getpixel((3, 4)) == (255, 0, 128, 255)
    assert erased.getpixel((3, 4)) == (0, 0, 0, 0)


def test_apply_pixel_edit_supports_square_brushes() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))

    painted = apply_pixel_edit(image, 3, 3, color=(10, 20, 30, 255), brush_size=3)

    assert painted.getpixel((2, 2)) == (10, 20, 30, 255)
    assert painted.getpixel((4, 4)) == (10, 20, 30, 255)
    assert painted.getpixel((5, 5)) == (0, 0, 0, 0)


def test_cleanup_frame_paths_sorts_matching_frames(tmp_path: Path) -> None:
    _make_frame(tmp_path / "frame-02.png", (20, 20, 20, 255))
    _make_frame(tmp_path / "frame-01.png", (10, 10, 10, 255))

    frames = cleanup_frame_paths(tmp_path)

    assert [path.name for path in frames] == ["frame-01.png", "frame-02.png"]


def test_pack_cleanup_spritesheet_uses_frame_size(tmp_path: Path) -> None:
    images = [Image.new("RGBA", (8, 8), (index, 0, 0, 255)) for index in range(3)]

    out = pack_cleanup_spritesheet(images, tmp_path / "sheet.png", columns=2)

    with Image.open(out) as sheet:
        assert sheet.size == (16, 16)


def test_write_cleanup_export_for_frames_writes_bundle(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    for index in range(1, 4):
        _make_frame(frames / f"frame-{index:02d}.png", (30 * index, 20, 40, 255))
    paths = cleanup_frame_paths(frames)
    originals = [Image.open(path).convert("RGBA") for path in paths]
    edited = [image.copy() for image in originals]
    edited[1] = apply_pixel_edit(edited[1], 0, 0, color=(255, 0, 0, 255))

    export = write_cleanup_export(
        source_paths=paths,
        originals=originals,
        images=edited,
        out_dir=tmp_path / "cleanup",
        source_kind="frames",
        columns=2,
        fps=8,
    )

    assert export.frames_dir is not None
    assert (export.frames_dir / "frame-02.png").is_file()
    assert export.preview_gif is not None
    assert export.preview_gif.is_file()
    assert export.before_after.is_file()
    assert export.metadata.is_file()
    assert export.review_index.is_file()
    with Image.open(export.spritesheet) as sheet:
        assert sheet.size == (16, 16)
    data = json.loads(export.metadata.read_text(encoding="utf-8"))
    assert data["sourceKind"] == "frames"
    assert len(data["frames"]) == 3


def test_write_cleanup_export_for_sheet_writes_cleaned_sheet(tmp_path: Path) -> None:
    source = tmp_path / "spritesheet.png"
    _make_frame(source, (20, 40, 60, 255))
    original = Image.open(source).convert("RGBA")
    edited = apply_pixel_edit(original, 0, 0, color=(255, 255, 0, 255))

    export = write_cleanup_export(
        source_paths=[source],
        originals=[original],
        images=[edited],
        out_dir=tmp_path / "cleanup-sheet",
        source_kind="sheet",
    )

    assert export.frames_dir is None
    assert export.preview_gif is None
    assert export.spritesheet.name == "spritesheet-cleaned.png"
    with Image.open(export.spritesheet) as sheet:
        assert sheet.getpixel((0, 0)) == (255, 255, 0, 255)
    data = json.loads(export.metadata.read_text(encoding="utf-8"))
    assert data["sourceKind"] == "sheet"


def test_render_cleanup_preview_preserves_nearest_pixel_scale() -> None:
    image = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    image.putpixel((1, 1), (255, 0, 0, 255))

    preview = render_cleanup_preview(image, scale=4)

    assert preview.size == (8, 8)
    assert preview.getpixel((7, 7)) == (255, 0, 0, 255)
