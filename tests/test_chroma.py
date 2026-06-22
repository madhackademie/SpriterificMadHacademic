from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.chroma import (
    despill_chroma,
    despill_chroma_batch,
    is_keyable_fringe_chroma,
    recover_chroma_components_from_sheet,
    remove_chroma,
    remove_chroma_batch,
    remove_chroma_fringe,
    remove_chroma_or_corner_background_batch,
    remove_fringe_batch,
    remove_green_fringe,
)


def test_remove_chroma_makes_green_transparent_and_keeps_sprite() -> None:
    image = Image.new("RGBA", (32, 32), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 23, 31), fill=(200, 80, 20, 255))
    draw.point((1, 1), fill=(10, 10, 10, 255))

    cleaned, metadata = remove_chroma(image, min_component_area=4)

    assert cleaned.getpixel((0, 0))[3] == 0
    assert cleaned.getpixel((1, 1))[3] == 0
    assert cleaned.getpixel((12, 12))[3] == 255
    assert metadata["removedPixels"] > 0


def test_remove_chroma_batch_writes_metadata(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    image = Image.new("RGBA", (32, 32), (0, 255, 0, 255))
    ImageDraw.Draw(image).rectangle((8, 8, 23, 31), fill=(200, 80, 20, 255))
    image.save(src / "frame-01.png")

    out = tmp_path / "out"
    remove_chroma_batch(src, out)

    assert (out / "frame-01.png").is_file()
    assert (out / "chroma-key-metadata.json").is_file()


def test_magenta_chroma_preserves_green_sprite_pixels(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    image = Image.new("RGBA", (32, 32), (255, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 23, 31), fill=(20, 160, 40, 255))
    image.save(src / "frame-01.png")

    out = tmp_path / "out"
    remove_chroma_or_corner_background_batch(src, out, chroma_rgb=(255, 0, 255), min_component_area=4)

    cleaned = Image.open(out / "frame-01.png").convert("RGBA")
    assert cleaned.getpixel((0, 0))[3] == 0
    assert cleaned.getpixel((12, 12)) == (20, 160, 40, 255)
    assert (out / "background-key-metadata.json").is_file()


def test_recover_chroma_components_from_sheet(tmp_path: Path) -> None:
    sheet = tmp_path / "sheet.png"
    image = Image.new("RGBA", (320, 128), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    for index in range(5):
        x = 12 + index * 60
        draw.rectangle((x, 24, x + 30, 110), fill=(220, 80, 20, 255))
    image.save(sheet)

    out = tmp_path / "out"
    frames = recover_chroma_components_from_sheet(sheet, out, rows=1, cols=5)

    assert len(frames) == 5
    assert (out / "frame-metadata.json").is_file()


def test_recover_chroma_components_falls_back_to_grid_when_neighbors_merge(tmp_path: Path) -> None:
    sheet = tmp_path / "sheet.png"
    image = Image.new("RGBA", (200, 200), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    # Top row: two figures that touch across the column boundary at x=100, so
    # whole-sheet detection sees a single merged blob (3 components for 4 cells).
    draw.rectangle((40, 20, 100, 80), fill=(220, 80, 20, 255))
    draw.rectangle((100, 20, 160, 80), fill=(220, 80, 20, 255))
    # Bottom row: two clearly separated figures.
    draw.rectangle((40, 120, 90, 180), fill=(220, 80, 20, 255))
    draw.rectangle((110, 120, 160, 180), fill=(220, 80, 20, 255))
    image.save(sheet)

    out = tmp_path / "out"
    frames = recover_chroma_components_from_sheet(sheet, out, rows=2, cols=2, count=4)

    assert len(frames) == 4
    assert (out / "frame-metadata.json").is_file()


def test_remove_green_fringe_removes_green_edge_pixels_only() -> None:
    image = Image.new("RGBA", (6, 6), (0, 0, 0, 0))
    image.putpixel((2, 2), (0, 180, 0, 255))
    image.putpixel((3, 2), (180, 80, 20, 255))
    image.putpixel((3, 3), (20, 120, 20, 255))

    cleaned, metadata = remove_green_fringe(image, min_green=70, dominance=24)

    assert cleaned.getpixel((2, 2))[3] == 0
    assert cleaned.getpixel((3, 2))[3] == 255
    assert cleaned.getpixel((3, 3))[3] == 0
    assert metadata["removedGreenFringePixels"] == 2


def test_remove_green_fringe_ignores_internal_transparent_holes() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((1, 1, 6, 6), fill=(180, 80, 20, 255))
    image.putpixel((3, 3), (0, 0, 0, 0))
    image.putpixel((3, 4), (20, 160, 20, 255))

    cleaned, metadata = remove_green_fringe(image, min_green=70, dominance=24)

    assert cleaned.getpixel((3, 4)) == (20, 160, 20, 255)
    assert metadata["removedGreenFringePixels"] == 0


def test_remove_chroma_fringe_matches_green_behavior_for_green_matte() -> None:
    image = Image.new("RGBA", (6, 6), (0, 0, 0, 0))
    image.putpixel((2, 2), (0, 180, 0, 255))
    image.putpixel((3, 2), (180, 80, 20, 255))

    cleaned, metadata = remove_chroma_fringe(image, chroma_rgb=(0, 255, 0), min_level=70, dominance=24)

    assert cleaned.getpixel((2, 2))[3] == 0
    assert cleaned.getpixel((3, 2))[3] == 255
    assert metadata["removedFringePixels"] == 1


def test_remove_chroma_fringe_removes_magenta_edge_and_keeps_green_sprite() -> None:
    image = Image.new("RGBA", (6, 6), (0, 0, 0, 0))
    image.putpixel((2, 2), (220, 40, 220, 255))
    image.putpixel((3, 2), (180, 80, 20, 255))
    image.putpixel((3, 3), (20, 160, 20, 255))

    cleaned, metadata = remove_chroma_fringe(image, chroma_rgb=(255, 0, 255), min_level=70, dominance=24)

    assert cleaned.getpixel((2, 2))[3] == 0
    assert cleaned.getpixel((3, 2))[3] == 255
    assert cleaned.getpixel((3, 3)) == (20, 160, 20, 255)
    assert metadata["removedFringePixels"] == 1


def test_is_keyable_fringe_chroma() -> None:
    assert is_keyable_fringe_chroma((0, 255, 0))
    assert is_keyable_fringe_chroma((255, 0, 255))
    assert is_keyable_fringe_chroma((0, 255, 255))
    assert not is_keyable_fringe_chroma((128, 128, 128))
    assert not is_keyable_fringe_chroma((255, 255, 255))
    assert not is_keyable_fringe_chroma((140, 100, 90))


def test_remove_fringe_batch_dispatches_by_matte_color(tmp_path: Path) -> None:
    def build_dir(name: str, fringe_rgb: tuple[int, int, int]) -> Path:
        src = tmp_path / name
        src.mkdir()
        image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((2, 2, 5, 5), fill=(180, 80, 20, 255))
        image.putpixel((2, 2), fringe_rgb + (255,))
        image.save(src / "frame-01.png")
        return src

    green_out = tmp_path / "green-out"
    _, green_meta = remove_fringe_batch(
        build_dir("green-src", (40, 200, 40)), green_out, chroma_rgb=(0, 255, 0), min_component_area=1
    )
    assert green_meta.name == "green-fringe-metadata.json"
    assert green_meta.is_file()

    magenta_out = tmp_path / "magenta-out"
    _, magenta_meta = remove_fringe_batch(
        build_dir("magenta-src", (200, 40, 200)), magenta_out, chroma_rgb=(255, 0, 255), min_component_area=1
    )
    assert magenta_meta.name == "fringe-metadata.json"
    assert magenta_meta.is_file()
    cleaned = Image.open(magenta_out / "frame-01.png").convert("RGBA")
    assert cleaned.getpixel((2, 2))[3] == 0


def test_despill_chroma_neutralizes_green_edge_without_deleting_pixels() -> None:
    image = Image.new("RGBA", (6, 6), (0, 0, 0, 0))
    # Opaque green-tinted edge pixel adjacent to transparency, and a clean interior pixel.
    image.putpixel((1, 1), (120, 220, 80, 255))
    image.putpixel((2, 2), (200, 80, 40, 255))

    cleaned, metadata = despill_chroma(image, chroma_rgb=(0, 255, 0), edge_radius=2)

    edge = cleaned.getpixel((1, 1))
    assert edge[3] == 255, "despill must not delete pixels"
    assert edge[1] == max(edge[0], edge[2]), "green channel clamped to max(r, b)"
    assert edge[1] == 120
    assert cleaned.getpixel((2, 2)) == (200, 80, 40, 255), "non-green pixel untouched"
    assert metadata["despilledPixels"] == 1
    assert metadata["spillRemoved"] > 0


def test_despill_chroma_batch_writes_metadata_and_can_run_in_place(tmp_path: Path) -> None:
    src = tmp_path / "frames"
    src.mkdir()
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((2, 2, 5, 5), fill=(40, 200, 60, 255))
    image.save(src / "frame-01.png")

    outputs = despill_chroma_batch(src, src, chroma_rgb=(0, 255, 0))

    assert len(outputs) == 1
    assert (src / "despill-metadata.json").is_file()
    cleaned = Image.open(src / "frame-01.png").convert("RGBA")
    edge = cleaned.getpixel((2, 2))
    assert edge[3] == 255
    assert edge[1] == max(edge[0], edge[2])


def test_despill_chroma_band_only_skips_interior() -> None:
    image = Image.new("RGBA", (9, 9), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((1, 1, 7, 7), fill=(40, 200, 60, 255))

    cleaned, _metadata = despill_chroma(image, chroma_rgb=(0, 255, 0), edge_radius=1, band_only=True)

    # Center pixel is far from any transparency, so its green tint is preserved.
    assert cleaned.getpixel((4, 4)) == (40, 200, 60, 255)
    # Edge pixel touching transparency is despilled.
    assert cleaned.getpixel((1, 1))[1] == max(cleaned.getpixel((1, 1))[0], cleaned.getpixel((1, 1))[2])


