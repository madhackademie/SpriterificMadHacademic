from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.anchors import AnchorOptions, build_anchor_comparison_sheet, build_anchor_detail_sheet, generate_anchors
from spriterrific.guides import copy_anchor_guide


def make_reference(path: Path) -> Path:
    img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((392, 260, 632, 900), fill=(42, 120, 210, 255))
    draw.rectangle((452, 160, 572, 300), fill=(240, 210, 150, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def make_user_input(path: Path) -> Path:
    img = Image.new("RGBA", (420, 320), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((160, 90, 260, 285), fill=(42, 120, 210, 255))
    draw.rectangle((185, 45, 235, 110), fill=(240, 210, 150, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def test_anchor_dry_run_writes_prompts_guide_and_manifests(tmp_path: Path) -> None:
    reference = make_user_input(tmp_path / "reference.png")
    run_dir = tmp_path / "runs" / "anchors"

    generate_anchors(
        AnchorOptions(
            reference=reference,
            run_dir=run_dir,
            directions=("s", "e"),
            dry_fal=True,
        )
    )

    assert (run_dir / "input" / "source-original.png").is_file()
    assert (run_dir / "pixel-snap" / "input" / "source.png").is_file()
    assert (run_dir / "pixel-snap" / "snapped" / "snapped.png").is_file()
    assert (run_dir / "pixel-snap" / "output" / "anchor.png").is_file()
    with Image.open(run_dir / "input" / "source.png").convert("RGBA") as processed:
        assert processed.size == (1024, 1024)
        assert processed.getpixel((0, 0)) == (0, 255, 0, 255)

    assert (run_dir / "guide" / "alternating-1024x1024.png").is_file()
    assert (run_dir / "anchors" / "prompt-s.txt").is_file()
    assert (run_dir / "anchors" / "prompt-e.txt").is_file()
    assert "front-facing" in (run_dir / "anchors" / "prompt-s.txt").read_text()
    prompt_e = (run_dir / "anchors" / "prompt-e.txt").read_text()
    assert "screen-right" in prompt_e
    assert "side-scrolling / side-view platformer" in prompt_e
    assert "top-down 2D action game" not in prompt_e
    assert "handheld weapon" not in prompt_e

    s_manifest = json.loads((run_dir / "fal" / "anchor-s" / "anchor-s-run.json").read_text())
    e_manifest = json.loads((run_dir / "fal" / "anchor-e" / "anchor-e-run.json").read_text())
    assert s_manifest["status"] == "dry_run"
    assert e_manifest["status"] == "dry_run"

    run_record = json.loads((run_dir / "run.json").read_text())
    assert run_record["status"] == "completed"
    assert run_record["directions"] == ["s", "e"]
    assert run_record["gameView"] == "platformer"
    assert run_record["anchorRole"] == "character"
    assert run_record["preprocess"] is True
    assert Path(run_record["pixelSnapped"]).as_posix().endswith("pixel-snap/snapped/snapped.png")
    assert Path(run_record["pixelSnappedUpscaled"]).as_posix().endswith("pixel-snap/output/anchor.png")
    assert Path(run_record["pixelSnappedChroma"]).as_posix().endswith("input/source.png")


def test_anchor_can_skip_preprocess_for_existing_1024_anchor(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "reference.png")
    run_dir = tmp_path / "runs" / "anchors-no-preprocess"

    generate_anchors(
        AnchorOptions(
            reference=reference,
            run_dir=run_dir,
            directions=("s",),
            dry_fal=True,
            preprocess=False,
        )
    )

    run_record = json.loads((run_dir / "run.json").read_text())
    assert run_record["preprocess"] is False
    assert not (run_dir / "input" / "preprocess-metadata.json").exists()


def test_bundled_anchor_guide_is_1024_square(tmp_path: Path) -> None:
    out = copy_anchor_guide(tmp_path / "guide.png")
    with Image.open(out) as image:
        assert image.size == (1024, 1024)


def test_build_anchor_comparison_sheet(tmp_path: Path) -> None:
    pairs = []
    for index, direction in enumerate(("n", "s", "e", "w")):
        raw = tmp_path / f"{direction}-raw.png"
        snapped = tmp_path / f"{direction}-snapped.png"
        raw_image = Image.new("RGBA", (1024, 1024), (0, 255, 0, 255))
        snapped_image = Image.new("RGBA", (1024, 1024), (0, 255, 0, 255))
        raw_draw = ImageDraw.Draw(raw_image)
        snapped_draw = ImageDraw.Draw(snapped_image)
        raw_draw.rectangle((420, 220, 580, 880), fill=(40 + index, 80, 180, 255))
        snapped_draw.rectangle((390, 180, 610, 930), fill=(180, 80, 40 + index, 255))
        raw_image.save(raw)
        snapped_image.save(snapped)
        pairs.append((direction, raw, snapped))

    out = build_anchor_comparison_sheet(pairs, tmp_path / "comparison.png")

    with Image.open(out) as image:
        assert image.size == (1024, 630)


def test_build_anchor_detail_sheet(tmp_path: Path) -> None:
    pairs = []
    for index, direction in enumerate(("e", "w")):
        raw = tmp_path / f"{direction}-raw.png"
        snapped = tmp_path / f"{direction}-snapped.png"
        raw_image = Image.new("RGBA", (1024, 1024), (0, 255, 0, 255))
        snapped_image = Image.new("RGBA", (1024, 1024), (0, 255, 0, 255))
        ImageDraw.Draw(raw_image).rectangle((420, 220, 580, 880), fill=(40 + index, 80, 180, 255))
        ImageDraw.Draw(snapped_image).rectangle((390, 180, 610, 930), fill=(180, 80, 40 + index, 255))
        raw_image.save(raw)
        snapped_image.save(snapped)
        pairs.append((direction, raw, snapped))

    out = build_anchor_detail_sheet(pairs, tmp_path / "detail.png", crop_size=96, zoom=3)

    with Image.open(out) as image:
        assert image.size == (576, 694)
