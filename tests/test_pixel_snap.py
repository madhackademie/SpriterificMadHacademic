from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from spriterrific.cli import main as cli_main
from spriterrific.pixel_snap import (
    PIXEL_SNAPPER_SCRIPT,
    SnapOptions,
    fit_snapped_to_anchor,
    prepare_snapped_anchor_source,
    put_on_chroma,
    snap_user_anchor,
)
from spriterrific.runtime_tools.pixel_snapper.scripts.pixel_snapper import (
    Config as PixelSnapperConfig,
    discover_grid,
    grid_from_dict,
    grid_to_dict,
    resample_with_grid,
)


def _write_fake_pixel_art(path: Path) -> None:
    base = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    draw.rectangle((4, 2, 11, 12), fill=(20, 80, 180, 255))
    draw.rectangle((6, 1, 9, 5), fill=(240, 200, 140, 255))
    draw.rectangle((5, 12, 7, 15), fill=(20, 80, 180, 255))
    draw.rectangle((8, 12, 10, 15), fill=(20, 80, 180, 255))
    base.resize((512, 512), Image.Resampling.NEAREST).save(path)


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_snap_user_anchor_writes_1024_anchor_in_run_folder(tmp_path: Path) -> None:
    source = tmp_path / "fake-pixel.png"
    _write_fake_pixel_art(source)
    run_dir = tmp_path / "runs" / "20260101-000000-snap-fake-pixel"

    result = snap_user_anchor(SnapOptions(source=source, run_dir=run_dir, k_colors=64, chroma=None))

    assert result.run_dir == run_dir
    assert result.anchor == run_dir / "output" / "anchor.png"
    assert result.chroma_anchor is None
    assert not (run_dir / "output" / "anchor-chroma.png").exists()
    assert result.snapped == run_dir / "snapped" / "snapped.png"
    assert (run_dir / "input" / "source.png").exists()
    assert (run_dir / "logs" / "pixel-snap.command.json").exists()
    assert (run_dir / "events.jsonl").exists()

    with Image.open(result.anchor) as anchor:
        assert anchor.size == (1024, 1024)

    with Image.open(result.snapped) as snapped:
        assert snapped.size == result.snapped_size
        assert max(snapped.size) < 512  # actually snapped, not just a copy of the 512 source

    record = json.loads((run_dir / "run.json").read_text())
    assert record["status"] == "completed"
    assert record["targetSize"] == [1024, 1024]
    assert record["snappedSize"] == list(result.snapped_size)
    assert record["kColors"] == 64
    assert record["chromaAnchor"] is None
    assert record["chroma"] is None


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_snap_user_anchor_emits_chroma_variant(tmp_path: Path) -> None:
    source = tmp_path / "fake-pixel.png"
    _write_fake_pixel_art(source)
    run_dir = tmp_path / "runs" / "20260101-000000-snap-chroma"

    result = snap_user_anchor(SnapOptions(source=source, run_dir=run_dir, k_colors=64, chroma="#FF00FF"))

    assert result.chroma_anchor == run_dir / "output" / "anchor-chroma.png"
    assert result.chroma_anchor.exists()
    with Image.open(result.chroma_anchor) as chroma_anchor:
        assert chroma_anchor.size == (1024, 1024)
        assert chroma_anchor.getpixel((0, 0)) == (255, 0, 255, 255)
        colors = chroma_anchor.getcolors(maxcolors=1024 * 1024)
        assert colors is not None
        assert any(pixel[:3] != (255, 0, 255) for _, pixel in colors)

    record = json.loads((run_dir / "run.json").read_text())
    assert record["chromaAnchor"] == str(result.chroma_anchor)
    assert record["chroma"] == "#FF00FF"


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_snap_user_anchor_uses_raw_source_for_pixel_snap(tmp_path: Path) -> None:
    source = tmp_path / "green-source.png"
    image = Image.new("RGBA", (128, 128), (33, 240, 31, 255))
    draw = ImageDraw.Draw(image)
    colors = [
        (28, 18, 8, 255),
        (62, 81, 34, 255),
        (94, 110, 48, 255),
        (139, 82, 35, 255),
        (205, 136, 62, 255),
        (246, 185, 124, 255),
    ]
    for index, color in enumerate(colors):
        x = 42 + (index % 2) * 18
        y = 26 + (index // 2) * 22
        draw.rectangle((x, y, x + 17, y + 21), fill=color)
    image.save(source)
    run_dir = tmp_path / "runs" / "20260101-000000-snap-green-source"

    result = snap_user_anchor(SnapOptions(source=source, run_dir=run_dir, k_colors=64, chroma="#00FF00"))

    command = json.loads((run_dir / "logs" / "pixel-snap.command.json").read_text())
    assert command["args"][2] == str(run_dir / "input" / "source.png")

    record = json.loads((run_dir / "run.json").read_text())
    assert "snapSource" not in record
    assert result.snapped.exists()


def test_fit_snapped_to_anchor_preserves_aspect_ratio() -> None:
    snapped = Image.new("RGBA", (128, 126), (10, 246, 13, 255))
    snapped.putpixel((0, 0), (255, 0, 0, 255))

    anchor, scale, offset = fit_snapped_to_anchor(snapped, (1024, 1024))

    assert anchor.size == (1024, 1024)
    assert scale == 8.0
    assert offset == (0, 8)
    assert anchor.getpixel((0, 0)) == (0, 0, 0, 0)
    assert anchor.getpixel((0, 8)) == (255, 0, 0, 255)


def test_fit_snapped_to_anchor_centers_non_integer_fill() -> None:
    snapped = Image.new("RGBA", (300, 291), (10, 246, 13, 255))

    anchor, scale, offset = fit_snapped_to_anchor(snapped, (1024, 1024))

    assert anchor.size == (1024, 1024)
    assert scale == 3.0
    assert offset == (62, 75)
    assert anchor.getpixel((0, 0)) == (0, 0, 0, 0)
    assert anchor.getpixel((62, 75)) == (10, 246, 13, 255)


def test_prepare_snapped_anchor_source_keys_background_after_snap() -> None:
    snapped = Image.new("RGBA", (8, 8), (10, 246, 13, 255))
    snapped.putpixel((3, 3), (20, 80, 180, 255))

    prepared = prepare_snapped_anchor_source(snapped)

    assert prepared.getpixel((0, 0)) == (0, 0, 0, 0)
    assert prepared.getpixel((3, 3)) == (20, 80, 180, 255)


def test_put_on_chroma_preserves_transparent_black_details(tmp_path: Path) -> None:
    source = tmp_path / "transparent.png"
    image = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    image.putpixel((1, 1), (0, 0, 0, 255))
    image.putpixel((2, 1), (20, 80, 180, 255))
    image.save(source)

    out = put_on_chroma(source, tmp_path / "chroma.png", chroma="#00FF00")

    with Image.open(out) as chroma:
        assert chroma.getpixel((0, 0)) == (0, 255, 0, 255)
        assert chroma.getpixel((1, 1)) == (0, 0, 0, 255)


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_pixel_snapper_clips_palette_values_instead_of_wrapping_green_to_black(tmp_path: Path) -> None:
    source = Image.new("RGBA", (128, 128), (0, 255, 0, 255))
    draw = ImageDraw.Draw(source)
    draw.rectangle((44, 24, 84, 104), fill=(180, 40, 60, 255))
    source_path = tmp_path / "green-source.png"
    out_path = tmp_path / "snapped.png"
    source.save(source_path)

    subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(PIXEL_SNAPPER_SCRIPT),
            str(source_path),
            str(out_path),
            "--k-colors",
            "64",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with Image.open(out_path) as snapped:
        colors = snapped.convert("RGBA").getcolors(maxcolors=snapped.width * snapped.height)
    assert colors is not None
    green_pixels = sum(count for count, color in colors if color == (0, 255, 0, 255))
    black_pixels = sum(count for count, color in colors if color == (0, 0, 0, 255))
    assert green_pixels > black_pixels


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_pixel_snapper_preserves_foreground_palette_with_noisy_chroma_background(tmp_path: Path) -> None:
    native = Image.new("RGBA", (128, 125), (10, 244, 14, 255))
    draw = ImageDraw.Draw(native)
    foreground_colors = [
        (5, 7, 6),
        (119, 59, 24),
        (104, 109, 54),
        (78, 32, 14),
        (86, 79, 79),
        (39, 17, 5),
        (47, 58, 55),
        (185, 119, 57),
        (27, 48, 31),
        (250, 179, 115),
        (167, 54, 34),
        (31, 64, 59),
        (204, 119, 54),
        (70, 29, 12),
    ]
    for index, color in enumerate(foreground_colors):
        x = 20 + (index % 4) * 18
        y = 15 + (index // 4) * 22
        draw.rectangle((x, y, x + 12, y + 16), fill=color + (255,))

    source = native.resize((1024, 1000), Image.Resampling.NEAREST)
    pixels = source.load()
    for y in range(source.height):
        for x in range(source.width):
            r, g, b, a = pixels[x, y]
            if (r, g, b) == (10, 244, 14):
                pixels[x, y] = (10 + (x // 8 + y // 8) % 3, 244 + (x // 8) % 2, 14 + (y // 8) % 2, a)

    source_path = tmp_path / "noisy-chroma-source.png"
    out_path = tmp_path / "snapped.png"
    source.save(source_path)

    subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(PIXEL_SNAPPER_SCRIPT),
            str(source_path),
            str(out_path),
            "--k-colors",
            "16",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with Image.open(out_path) as snapped:
        colors = snapped.convert("RGBA").getcolors(maxcolors=snapped.width * snapped.height)
    assert colors is not None
    foreground = [color for _count, color in colors if not (color[1] > 200 and color[0] < 40 and color[2] < 40)]
    assert len(foreground) >= 12


def test_pixel_snapper_can_reuse_locked_grid_for_sequence_frames(tmp_path: Path) -> None:
    frame_1 = tmp_path / "frame-01.png"
    frame_2 = tmp_path / "frame-02.png"
    out_1 = tmp_path / "snapped-01.png"
    out_2 = tmp_path / "snapped-02.png"

    native_1 = Image.new("RGBA", (16, 16), (0, 255, 0, 255))
    draw_1 = ImageDraw.Draw(native_1)
    draw_1.rectangle((5, 3, 10, 12), fill=(180, 40, 60, 255))
    native_1.resize((128, 128), Image.Resampling.NEAREST).save(frame_1)

    native_2 = Image.new("RGBA", (16, 16), (0, 255, 0, 255))
    draw_2 = ImageDraw.Draw(native_2)
    draw_2.rectangle((5, 4, 10, 13), fill=(180, 55, 60, 255))
    native_2.resize((128, 128), Image.Resampling.NEAREST).save(frame_2)

    cfg = PixelSnapperConfig(k_colors=16)
    grid = discover_grid(frame_1, cfg)
    restored = grid_from_dict(grid_to_dict(grid))

    size_1 = resample_with_grid(frame_1, out_1, cfg, restored)
    size_2 = resample_with_grid(frame_2, out_2, cfg, restored)

    assert size_1 == size_2 == grid.output_size
    with Image.open(out_1) as snapped_1, Image.open(out_2) as snapped_2:
        assert snapped_1.size == snapped_2.size


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_snap_cli_uses_timestamped_run_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "fake-pixel.png"
    _write_fake_pixel_art(source)

    cli_main(["snap", "--reference", str(source), "--k-colors", "64"])

    lines = capsys.readouterr().out.strip().splitlines()
    anchor_path = Path(lines[0])
    chroma_path = Path(lines[1])
    assert anchor_path.name == "anchor.png"
    assert chroma_path.name == "anchor-chroma.png"

    run_dir = anchor_path.parent.parent
    assert run_dir.parent.name == "runs"
    assert re.match(r"^\d{8}-\d{6}-snap-fake-pixel$", run_dir.name)

    with Image.open(anchor_path) as anchor:
        assert anchor.size == (1024, 1024)
    with Image.open(chroma_path) as chroma_anchor:
        assert chroma_anchor.size == (1024, 1024)
        assert chroma_anchor.getpixel((0, 0)) == (0, 255, 0, 255)
