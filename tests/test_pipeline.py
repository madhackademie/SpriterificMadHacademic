from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from spriterrific.action_batch import ActionBatchOptions, run_action_batch
from spriterrific.paths import create_run_paths
from spriterrific.chroma import remove_green_fringe_batch, remove_green_screen_or_corner_background_batch
from spriterrific.pipeline import (
    FAL_VIDEO_SCRIPT,
    RunOptions,
    _effective_video_duration,
    _layout_video_canvas_frames,
    _run_fal_video,
    _video_preserve_canvas_default,
    run_pipeline,
)
from spriterrific.pixel_snap import PIXEL_SNAPPER_SCRIPT
from spriterrific.presets import (
    IMAGE_POSE_BOARD_CELL_HEIGHT,
    IMAGE_POSE_BOARD_CELL_WIDTH,
    IMAGE_POSE_BOARD_COLUMNS,
    IMAGE_POSE_BOARD_HEIGHT,
    IMAGE_POSE_BOARD_WIDTH,
    resolve_video_model_preset,
    resolve_pose_board_preset,
)


def make_reference(path: Path) -> Path:
    img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((392, 260, 632, 900), fill=(42, 120, 210, 255))
    draw.rectangle((452, 160, 572, 300), fill=(240, 210, 150, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def make_generated_sheet(path: Path, frames: int, *, pose_board_id: str = "standard") -> Path:
    pose_board = resolve_pose_board_preset(pose_board_id)
    img = Image.new("RGBA", (pose_board.width, pose_board.height), (0, 255, 0, 255))
    draw = ImageDraw.Draw(img)
    for index in range(frames):
        col = index % pose_board.columns
        row = index // pose_board.columns
        x = col * pose_board.cell_width
        y = row * pose_board.cell_height
        sway = (index % 3) * 8
        scale = pose_board.cell_width / IMAGE_POSE_BOARD_CELL_WIDTH
        draw.rectangle(
            (
                x + round((148 + sway) * scale),
                y + round(110 * scale),
                x + round((236 + sway) * scale),
                y + round(310 * scale),
            ),
            fill=(180, 40 + index * 6, 60, 255),
        )
        draw.rectangle(
            (
                x + round((168 + sway) * scale),
                y + round(60 * scale),
                x + round((216 + sway) * scale),
                y + round(130 * scale),
            ),
            fill=(240, 210, 120, 255),
        )
        draw.rectangle(
            (
                x + round((128 + sway) * scale),
                y + round(248 * scale),
                x + round((256 + sway) * scale),
                y + round(350 * scale),
            ),
            fill=(80, 90, 160, 255),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def make_generated_sheet_with_row_spill(path: Path) -> Path:
    img = Image.new("RGBA", (IMAGE_POSE_BOARD_WIDTH, IMAGE_POSE_BOARD_HEIGHT), (0, 255, 0, 255))
    draw = ImageDraw.Draw(img)
    for index in range(10):
        col = index % IMAGE_POSE_BOARD_COLUMNS
        row = index // IMAGE_POSE_BOARD_COLUMNS
        x = col * IMAGE_POSE_BOARD_CELL_WIDTH
        y = row * IMAGE_POSE_BOARD_CELL_HEIGHT
        if index == 0:
            # This intentionally crosses the first row boundary. A naive 384px
            # grid crop would slice the lower half off the frame.
            draw.rectangle((x + 150, y + 320, x + 230, y + 440), fill=(210, 60, 40, 255))
        else:
            draw.rectangle((x + 150, y + 120, x + 230, y + 300), fill=(180, 40 + index * 6, 60, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def make_video(path: Path, tmp_frames: Path) -> Path:
    tmp_frames.mkdir(parents=True, exist_ok=True)
    for index in range(1, 17):
        img = Image.new("RGB", (1280, 720), (184, 184, 184))
        draw = ImageDraw.Draw(img)
        x = 600 + ((index % 4) - 2) * 4
        y = 210 + (index % 2) * 6
        draw.rectangle((x, y, x + 96, y + 330), fill=(40, 130, 220))
        draw.rectangle((x + 20, y - 58, x + 76, y + 12), fill=(240, 210, 130))
        img.save(tmp_frames / f"frame-{index:04d}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "12",
            "-i",
            str(tmp_frames / "frame-%04d.png"),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def non_green_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    rgba = image.convert("RGBA")
    px = rgba.load()
    min_x, min_y = rgba.width, rgba.height
    max_x = max_y = -1
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = px[x, y]
            if a and (r, g, b) != (0, 255, 0):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < min_x:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    return image.convert("RGBA").getchannel("A").getbbox()


def assert_no_hidden_or_fringe_green(image: Image.Image) -> None:
    rgba = image.convert("RGBA")
    pixels = rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata()
    for pixel in pixels:
        red, green, blue, alpha = pixel
        assert not (alpha == 0 and green), f"transparent pixel retained green RGB: {pixel}"
        assert not (0 < alpha < 255 and green - max(red, blue) >= 24), f"green fringe survived: {pixel}"


def assert_successful_run(run_dir: Path, expected_size: tuple[int, int]) -> None:
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "review" / "contact.png").is_file()
    assert (run_dir / "review" / "index.md").is_file()
    assert (run_dir / "export" / "preview.gif").is_file()
    assert (run_dir / "export" / "manifest.json").is_file()
    assert (run_dir / "export" / "baseline-report.json").is_file()
    with Image.open(run_dir / "export" / "spritesheet.png") as img:
        assert img.size == expected_size
    review_index = (run_dir / "review" / "index.md").read_text(encoding="utf-8")
    assert "Runtime Spritesheet" in review_index
    assert "![Normalized Preview GIF](preview.gif)" in review_index
    if (run_dir / "review" / "recovered-native-preview.gif").exists():
        assert "Recovered Native Preview GIF" in review_index
        assert "![Recovered Native Preview GIF](recovered-native-preview.gif)" in review_index


def test_fixture_image_pipeline(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-e.png")
    sheet = make_generated_sheet(tmp_path / "fixtures" / "attack-e.png", 10)
    run_dir = tmp_path / "runs" / "dev-attack-e-image"

    run_pipeline(
        RunOptions(
            action="attack",
            direction="e",
            mode="image",
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
        )
    )

    assert_successful_run(run_dir, (1280, 512))
    assert (run_dir / "sheet-cells" / "grid-review" / "frame-01.png").is_file()
    assert (run_dir / "recovered-native" / "frames" / "frame-01.png").is_file()
    assert (run_dir / "recovered-native" / "metadata.json").is_file()
    assert (run_dir / "review" / "grid-review-cell-contact.png").is_file()
    assert (run_dir / "review" / "recovered-component-contact.png").is_file()
    assert (run_dir / "review" / "recovered-native-contact.png").is_file()
    assert (run_dir / "review" / "recovered-native-preview.gif").is_file()
    assert (run_dir / "review" / "compare-01-grid-review-to-recovered-components.png").is_file()
    assert (run_dir / "review" / "compare-02-recovered-to-native-layout.png").is_file()
    assert (run_dir / "review" / "compare-02-cleaned-to-scaled.png").is_file()
    assert (run_dir / "review" / "compare-03-scaled-to-normalized.png").is_file()


def test_jump_is_supported_as_image_preset(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = make_generated_sheet(tmp_path / "fixtures" / "jump-w.png", 6)
    run_dir = tmp_path / "runs" / "dev-jump-w-image"

    run_pipeline(
        RunOptions(
            action="jump",
            direction="w",
            mode="image",
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
            frame_count=6,
        )
    )

    assert_successful_run(run_dir, (1280, 512))


def test_image_pipeline_supports_hires_pose_board_preset(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = make_generated_sheet(tmp_path / "fixtures" / "idle-w-hires.png", 10, pose_board_id="hires")
    run_dir = tmp_path / "runs" / "dev-idle-w-hires"

    run_pipeline(
        RunOptions(
            action="idle",
            direction="w",
            mode="image",
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
            pose_board_preset="hires",
        )
    )

    assert_successful_run(run_dir, (1280, 512))
    run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_json["imagePoseBoardPreset"] == "hires"
    assert run_json["imageGenerationCanvas"] == [2048, 1536]
    assert run_json["imageGenerationCellSize"] == [512, 512]
    with Image.open(run_dir / "sheet-cells" / "grid-review" / "frame-01.png") as cell:
        assert cell.size == (512, 512)


def test_image_pose_board_recovers_components_instead_of_trusting_grid_crop(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = make_generated_sheet_with_row_spill(tmp_path / "fixtures" / "idle-w-spill.png")
    run_dir = tmp_path / "runs" / "dev-idle-w-spill"

    run_pipeline(
        RunOptions(
            action="idle",
            direction="w",
            mode="image",
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
        )
    )

    rough = Image.open(run_dir / "sheet-cells" / "grid-review" / "frame-01.png").convert("RGBA")
    recovered = Image.open(run_dir / "recovered" / "frame-01.png").convert("RGBA")
    native = Image.open(run_dir / "recovered-native" / "frames" / "frame-01.png").convert("RGBA")
    rough_bbox = non_green_bbox(rough)
    recovered_bbox = recovered.getchannel("A").getbbox()
    native_bbox = native.getchannel("A").getbbox()

    assert rough_bbox is not None
    assert recovered_bbox is not None
    assert native_bbox is not None
    assert rough_bbox[3] - rough_bbox[1] < 80
    assert recovered_bbox[3] - recovered_bbox[1] > 100
    assert native.size[0] >= 384
    assert native.size[1] >= 448
    assert native_bbox[3] - native_bbox[1] == recovered_bbox[3] - recovered_bbox[1]


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_image_pipeline_can_pixel_snap_recovered_components_before_runtime_normalization(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = make_generated_sheet(tmp_path / "fixtures" / "attack-w.png", 6)
    run_dir = tmp_path / "runs" / "dev-attack-w-pixel-snap"

    run_pipeline(
        RunOptions(
            action="attack",
            direction="w",
            mode="image",
            frame_count=6,
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
            pixel_snap=True,
            k_colors=64,
        )
    )

    assert_successful_run(run_dir, (1280, 512))
    assert (run_dir / "pixel-snapped" / "native" / "frame-01.png").is_file()
    assert (run_dir / "review" / "pixel-snapped-raw-contact.png").is_file()
    assert (run_dir / "review" / "compare-03-recovered-to-pixel-snapped-raw.png").is_file()
    assert (run_dir / "review" / "compare-04-pixel-snap-to-runtime.png").is_file()

    review_index = (run_dir / "review" / "index.md").read_text(encoding="utf-8")
    assert "Pixel-Snapped Raw Contact Sheet" in review_index
    assert "Pixel Snap To Runtime Comparison" in review_index


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_image_pipeline_can_pixel_snap_chroma_layout_before_runtime_normalization(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = make_generated_sheet(tmp_path / "fixtures" / "hurt-w.png", 5)
    run_dir = tmp_path / "runs" / "dev-hurt-w-pixel-snap-chroma-layout"

    run_pipeline(
        RunOptions(
            action="hurt",
            direction="w",
            mode="image",
            frame_count=5,
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
            pixel_snap=True,
            pixel_snap_source="chroma-layout",
            k_colors=64,
        )
    )

    assert_successful_run(run_dir, (1280, 256))
    assert (run_dir / "pixel-snapped" / "source" / "frame-01.png").is_file()
    assert (run_dir / "pixel-snapped" / "native" / "frame-01.png").is_file()
    assert (run_dir / "pixel-snapped" / "keyed" / "frame-01.png").is_file()
    source_sizes = {
        Image.open(path).size
        for path in sorted((run_dir / "pixel-snapped" / "source").glob("frame-*.png"))
    }
    assert source_sizes == {(384, 448)}
    source_metadata = json.loads((run_dir / "pixel-snapped" / "source" / "metadata.json").read_text(encoding="utf-8"))
    canvas_w, canvas_h = source_metadata["canvasSize"]
    for frame in source_metadata["frames"]:
        x, y = frame["offset"]
        w, h = frame["placedSize"]
        assert x >= 0
        assert y >= 0
        assert x + w <= canvas_w
        assert y + h <= canvas_h
    native_sizes = [
        Image.open(path).size
        for path in sorted((run_dir / "pixel-snapped" / "native").glob("frame-*.png"))
    ]
    assert native_sizes
    assert any(size != (96, 112) for size in native_sizes)
    keyed = Image.open(run_dir / "pixel-snapped" / "keyed" / "frame-01.png").convert("RGBA")
    assert keyed.getchannel("A").getbbox() != (0, 0, keyed.width, keyed.height)
    assert (run_dir / "review" / "pixel-snap-chroma-source-contact.png").is_file()
    assert (run_dir / "review" / "pixel-snapped-raw-contact.png").is_file()
    assert (run_dir / "review" / "compare-04-pixel-snapped-chroma-to-keyed.png").is_file()
    assert (run_dir / "review" / "compare-04-pixel-snap-to-runtime.png").is_file()

    review_index = (run_dir / "review" / "index.md").read_text(encoding="utf-8")
    assert "Pixel Snap Source Canvas" in review_index
    assert "Comparison 04: Raw Pixel Snap To Background-Cleaned" in review_index


def test_pixel_snap_layout_uses_native_canvas_without_presnap_downscale(tmp_path: Path) -> None:
    from spriterrific.pipeline import _build_pixel_snap_layout_frames

    input_dir = tmp_path / "recovered"
    out_dir = tmp_path / "pixel-snapped" / "source"
    input_dir.mkdir(parents=True)

    tall = Image.new("RGBA", (207, 568), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tall)
    draw.rectangle((0, 0, 206, 567), fill=(180, 60, 80, 255))
    tall.save(input_dir / "frame-01.png")

    _build_pixel_snap_layout_frames(
        input_dir,
        out_dir,
        1,
        canvas_size=(512, 592),
        transparent=False,
    )

    source = Image.open(out_dir / "frame-01.png").convert("RGBA")
    data = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    frame = data["frames"][0]

    assert source.size == (512, 592)
    assert data["sharedScale"] == 1.0
    assert frame["sourceSize"] == [207, 568]
    assert frame["placedSize"] == [207, 568]


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_idle_pixel_snap_chroma_layout_equalizes_runtime_height(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = Image.new("RGBA", (IMAGE_POSE_BOARD_WIDTH, IMAGE_POSE_BOARD_HEIGHT), (0, 255, 0, 255))
    draw = ImageDraw.Draw(sheet)
    for index in range(10):
        col = index % IMAGE_POSE_BOARD_COLUMNS
        row = index // IMAGE_POSE_BOARD_COLUMNS
        x = col * IMAGE_POSE_BOARD_CELL_WIDTH
        y = row * IMAGE_POSE_BOARD_CELL_HEIGHT
        height = 300 if index < 5 else 260
        draw.rectangle((x + 170, y + 40, x + 220, y + 40 + height), fill=(180, 60, 80, 255))
    sheet_path = tmp_path / "fixtures" / "idle-w-height-drift.png"
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path)
    run_dir = tmp_path / "runs" / "dev-idle-w-height-drift"

    run_pipeline(
        RunOptions(
            action="idle",
            direction="w",
            mode="image",
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet_path,
            dry_fal=True,
            pixel_snap=True,
            pixel_snap_source="chroma-layout",
            k_colors=64,
        )
    )

    heights = []
    for path in sorted((run_dir / "normalized").glob("frame-*.png")):
        image = Image.open(path).convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        assert bbox is not None
        heights.append(bbox[3] - bbox[1])

    assert len(set(heights)) == 1


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_non_idle_pixel_snap_chroma_layout_upscales_runtime_frames(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = make_generated_sheet(tmp_path / "fixtures" / "attack-w.png", 6)
    run_dir = tmp_path / "runs" / "dev-attack-w-upscaled-pixel-snap"

    run_pipeline(
        RunOptions(
            action="attack",
            direction="w",
            mode="image",
            frame_count=6,
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
            pixel_snap=True,
            pixel_snap_source="chroma-layout",
            k_colors=64,
        )
    )

    native_heights = []
    normalized_heights = []
    for path in sorted((run_dir / "pixel-snapped" / "keyed").glob("frame-*.png")):
        image = Image.open(path).convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        assert bbox is not None
        native_heights.append(bbox[3] - bbox[1])
    for path in sorted((run_dir / "normalized").glob("frame-*.png")):
        image = Image.open(path).convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        assert bbox is not None
        normalized_heights.append(bbox[3] - bbox[1])

    assert max(normalized_heights) == 210
    assert max(normalized_heights) > max(native_heights)


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_image_pipeline_can_pixel_snap_transparent_layout(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet = make_generated_sheet(tmp_path / "fixtures" / "attack-w.png", 6)
    run_dir = tmp_path / "runs" / "dev-attack-w-transparent-layout"

    run_pipeline(
        RunOptions(
            action="attack",
            direction="w",
            mode="image",
            frame_count=6,
            reference=reference,
            run_dir=run_dir,
            existing_sheet=sheet,
            dry_fal=True,
            pixel_snap=True,
            pixel_snap_source="transparent-layout",
            k_colors=64,
        )
    )

    assert_successful_run(run_dir, (1280, 512))
    source_metadata = json.loads((run_dir / "pixel-snapped" / "source" / "metadata.json").read_text(encoding="utf-8"))
    assert source_metadata["background"] == "transparent"
    assert (run_dir / "pixel-snapped" / "native" / "frame-01.png").is_file()
    assert not (run_dir / "pixel-snapped" / "keyed" / "frame-01.png").exists()
    review_index = (run_dir / "review" / "index.md").read_text(encoding="utf-8")
    assert "Pixel Snap Source Canvas" in review_index
    assert "Comparison 04: Pixel-Snapped Chroma To Chroma-Keyed" not in review_index


def test_action_batch_runs_actions_and_writes_master_review(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    sheet_root = tmp_path / "sheet-root"
    make_generated_sheet(sheet_root / "attack-w" / "generated" / "sheet.png", 8)
    make_generated_sheet(sheet_root / "hurt-w" / "generated" / "sheet.png", 6)
    run_dir = tmp_path / "runs" / "batch"

    outputs = run_action_batch(
        ActionBatchOptions(
            actions=("attack", "hurt"),
            direction="w",
            reference=reference,
            run_dir=run_dir,
            existing_sheet_root=sheet_root,
            dry_fal=True,
        )
    )

    assert outputs == [run_dir / "attack-w", run_dir / "hurt-w"]
    assert (run_dir / "attack-w" / "export" / "manifest.json").is_file()
    assert (run_dir / "hurt-w" / "export" / "manifest.json").is_file()
    master = run_dir / "review" / "index.md"
    assert master.is_file()
    text = master.read_text(encoding="utf-8")
    assert "attack-w Runtime Preview" in text
    assert "hurt-w Runtime Preview" in text


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for video fixture tests")
def test_fixture_video_pipeline(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-e.png")
    video = make_video(tmp_path / "fixtures" / "walk-e.mp4", tmp_path / "video-src")
    run_dir = tmp_path / "runs" / "dev-walk-e-video"

    run_pipeline(
        RunOptions(
            action="walk",
            direction="e",
            mode="video",
            reference=reference,
            run_dir=run_dir,
            existing_video=video,
            dry_fal=True,
        )
    )

    assert_successful_run(run_dir, (1280, 512))
    preserve_metadata = json.loads((run_dir / "normalized" / "preserve-canvas-metadata.json").read_text(encoding="utf-8"))
    assert preserve_metadata["layoutMode"] == "preserve-canvas"
    assert preserve_metadata["heightNormalization"] is False
    assert preserve_metadata["motionPreserved"] is True
    assert preserve_metadata["videoRecovery"] == "preserve-canvas"
    assert preserve_metadata["backgroundCleanup"]["keyedToTransparentBlack"] is True
    assert preserve_metadata["backgroundCleanup"]["postScaleGreenFringeCleanup"] is False
    assert (run_dir / "export" / "preserve-canvas.json").is_file()
    assert (run_dir / "review" / "compare-01-selected-to-canvas-cleaned.png").is_file()
    assert (run_dir / "review" / "compare-02-canvas-cleaned-to-runtime.png").is_file()
    baseline_report = json.loads((run_dir / "export" / "baseline-report.json").read_text(encoding="utf-8"))
    assert baseline_report["status"] == "skipped"
    assert baseline_report["layoutMode"] == "preserve-canvas"
    review_index = (run_dir / "review" / "index.md").read_text(encoding="utf-8")
    assert "Preserve-canvas video frames" in review_index


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for video fixture tests")
def test_existing_video_manual_selected_order_can_drive_frame_count(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    video = make_video(tmp_path / "fixtures" / "manual-walk-w.mp4", tmp_path / "manual-video-src")
    run_dir = tmp_path / "runs" / "manual-walk-w-video"
    selected_order = [f"frame-{index:04d}.png" for index in range(1, 13)]

    run_pipeline(
        RunOptions(
            action="walk",
            direction="w",
            mode="video",
            reference=reference,
            run_dir=run_dir,
            existing_video=video,
            selected_order=selected_order,
            dry_fal=True,
        )
    )

    assert_successful_run(run_dir, (1280, 768))
    run_record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_record["frameCount"] == 12
    assert run_record["frameCountOverrideAllowed"] is True
    assert run_record["manualFrameRecovery"] is True
    assert run_record["animationTiming"] == "loop"
    assert run_record["selectionPolicy"] == "cycle"
    selection = json.loads((run_dir / "selected" / "selection.json").read_text(encoding="utf-8"))
    assert selection["timing"] == "loop"
    assert selection["selectionPolicy"] == "cycle"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for video fixture tests")
def test_transition_end_reference_uses_wan27_and_records_metadata(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "knockdown-final-w.png")
    end_reference = make_reference(tmp_path / "fixtures" / "standing-anchor-w.png")
    video = make_video(tmp_path / "fixtures" / "get-up-w.mp4", tmp_path / "get-up-video-src")
    run_dir = tmp_path / "runs" / "manual-get-up-w-video"

    run_pipeline(
        RunOptions(
            action="get_up",
            direction="w",
            mode="video",
            reference=reference,
            end_reference=end_reference,
            run_dir=run_dir,
            existing_video=video,
            dry_fal=True,
        )
    )

    assert_successful_run(run_dir, (1280, 768))
    run_record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_record["videoModelAlias"] == "wan-2.7"
    assert run_record["videoModelSupportsEndImage"] is True
    assert run_record["videoInputImageField"] == "image_url"
    assert run_record["videoEndImageField"] == "end_image_url"
    assert run_record["transitionConstrainedByEndReference"] is True
    assert run_record["endReference"] == str(run_dir / "input" / "end-reference.png")
    assert (run_dir / "direction" / "end-plate-1024x1024.png").is_file()
    selection = json.loads((run_dir / "selected" / "selection.json").read_text(encoding="utf-8"))
    assert selection["timing"] == "transition"
    assert selection["includesFinalSourceFrame"] is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for video fixture tests")
def test_video_run_records_fps_and_cycle_window_overrides(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "character-w.png")
    video = make_video(tmp_path / "fixtures" / "walk-w.mp4", tmp_path / "walk-video-src")
    run_dir = tmp_path / "runs" / "manual-walk-w-video"

    run_pipeline(
        RunOptions(
            action="walk",
            direction="w",
            mode="video",
            reference=reference,
            run_dir=run_dir,
            existing_video=video,
            fps=7,
            cycle_start_fraction=0.25,
            cycle_span_factor=2.0,
            dry_fal=True,
        )
    )

    assert_successful_run(run_dir, (1280, 512))
    run_record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_record["fps"] == 7
    assert run_record["fpsOverride"] == 7
    assert run_record["cycleStartFraction"] == 0.25
    assert run_record["cycleSpanFactor"] == 2.0
    manifest = json.loads((run_dir / "export" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fps"] == 7
    selection = json.loads((run_dir / "selected" / "selection.json").read_text(encoding="utf-8"))
    assert selection["cycleStartFraction"] == 0.25
    assert selection["cycleSpanFactor"] == 2.0


def test_end_reference_requires_compatible_video_model(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "knockdown-final-w.png")
    end_reference = make_reference(tmp_path / "fixtures" / "standing-anchor-w.png")

    with pytest.raises(ValueError, match="does not support --end-reference"):
        run_pipeline(
            RunOptions(
                action="get_up",
                direction="w",
                mode="video",
                reference=reference,
                end_reference=end_reference,
                run_dir=tmp_path / "runs" / "bad-end-reference-model",
                video_model_alias="grok-imagine-video-i2v",
                dry_fal=True,
            )
        )


def test_frame_count_override_requires_manual_video_recovery(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only supported for video runs"):
        run_pipeline(
            RunOptions(
                action="walk",
                direction="w",
                mode="video",
                reference=tmp_path / "missing.png",
                run_dir=tmp_path / "runs" / "bad-override",
                frame_count=13,
                allow_frame_count_override=True,
                dry_fal=True,
            )
        )


def test_fal_video_uses_square_short_seedance_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = create_run_paths(tmp_path / "runs" / "video-settings")
    captured: dict[str, list[str]] = {}

    def fake_run_command(args: list[str], **_kwargs: object) -> None:
        captured["args"] = args

    monkeypatch.setattr("spriterrific.pipeline.run_command", fake_run_command)

    _run_fal_video(paths, "walk prompt", False, "seedance-2.0-i2v")

    args = captured["args"]
    assert args[args.index("--duration") + 1] == "4"
    assert args[args.index("--resolution") + 1] == "720p"
    assert args[args.index("--aspect-ratio") + 1] == "1:1"
    assert args[args.index("--generate-audio") + 1] == "false"


def test_fal_video_passes_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = create_run_paths(tmp_path / "runs" / "video-seed")
    captured: dict[str, list[str]] = {}

    def fake_run_command(args: list[str], **_kwargs: object) -> None:
        captured["args"] = args

    monkeypatch.setattr("spriterrific.pipeline.run_command", fake_run_command)

    _run_fal_video(paths, "walk prompt", False, "grok-imagine-video-i2v", seed=1234)

    args = captured["args"]
    assert args[args.index("--seed") + 1] == "1234"


def test_video_preserve_canvas_is_default_for_all_actions() -> None:
    assert _video_preserve_canvas_default("walk") is True
    assert _video_preserve_canvas_default("attack") is True
    assert _video_preserve_canvas_default("crouch") is True
    assert _video_preserve_canvas_default("attack", "fit-foreground") is False
    assert _video_preserve_canvas_default("attack", "preserve-canvas") is True


def test_preserve_canvas_cleanup_skips_post_scale_green_sweep(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    keyed = tmp_path / "chroma-keyed"
    pre_scale_cleaned = tmp_path / "recovered"
    normalized = tmp_path / "normalized"
    selected.mkdir()

    image = Image.new("RGBA", (64, 64), (0, 255, 0, 255))
    pixels = image.load()
    for y in range(22, 42):
        for x in range(24, 40):
            pixels[x, y] = (20, 80, 220, 255)
        pixels[23, y] = (20, 100, 20, 255)
        pixels[40, y] = (20, 110, 20, 255)
    pixels[0, 0] = (0, 255, 0, 0)
    pixels[63, 63] = (0, 180, 0, 0)
    image.save(selected / "frame-01.png")

    remove_green_screen_or_corner_background_batch(selected, keyed)
    remove_green_fringe_batch(keyed, pre_scale_cleaned, min_green=70, dominance=24, min_component_area=4)
    _layout_video_canvas_frames(
        pre_scale_cleaned,
        normalized,
        green_fringe_cleanup=True,
        green_fringe_min_green=70,
        green_fringe_dominance=24,
        green_fringe_edge_radius=1,
        source_key_metadata=keyed / "video-background-key-metadata.json",
        source_fringe_metadata=pre_scale_cleaned / "green-fringe-metadata.json",
    )

    output = Image.open(normalized / "frame-01.png")
    assert output.size == (256, 256)
    assert output.getchannel("A").getbbox() is not None
    metadata = json.loads((normalized / "preserve-canvas-metadata.json").read_text(encoding="utf-8"))
    assert metadata["backgroundCleanup"]["keyedToTransparentBlack"] is True
    assert metadata["backgroundCleanup"]["postScaleGreenFringeCleanup"] is True
    frame_record = metadata["frames"][0]
    assert frame_record["postScaleGreenFringeCleanup"]["removedGreenFringePixels"] >= 0
    assert frame_record["greenTransparencyAudit"]["hiddenGreenAlphaZeroPixels"] == 0
    assert frame_record["greenTransparencyAudit"]["semiTransparentGreenFringePixels"] == 0

    _layout_video_canvas_frames(
        pre_scale_cleaned,
        tmp_path / "normalized-no-post-scale",
        green_fringe_cleanup=False,
        source_key_metadata=keyed / "video-background-key-metadata.json",
        source_fringe_metadata=pre_scale_cleaned / "green-fringe-metadata.json",
    )
    no_post = json.loads((tmp_path / "normalized-no-post-scale" / "preserve-canvas-metadata.json").read_text(encoding="utf-8"))
    assert no_post["backgroundCleanup"]["postScaleGreenFringeCleanup"] is False
    assert no_post["frames"][0]["postScaleGreenFringeCleanup"] is None


def test_preserve_canvas_layout_does_not_recenter_i2v_frames(tmp_path: Path) -> None:
    source = tmp_path / "source"
    out = tmp_path / "normalized"
    source.mkdir()
    for name, left in (("frame-01.png", 6), ("frame-02.png", 30)):
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((left, 20, left + 12, 44), fill=(30, 80, 220, 255))
        image.save(source / name)

    _layout_video_canvas_frames(source, out, green_fringe_cleanup=True)

    first_bbox = alpha_bbox(Image.open(out / "frame-01.png"))
    second_bbox = alpha_bbox(Image.open(out / "frame-02.png"))
    assert first_bbox is not None
    assert second_bbox is not None
    assert first_bbox[0] < second_bbox[0]
    metadata = json.loads((out / "preserve-canvas-metadata.json").read_text(encoding="utf-8"))
    assert metadata["heightNormalization"] is False
    assert metadata["motionPreserved"] is True


def test_wan_turbo_video_duration_override_uses_frame_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = create_run_paths(tmp_path / "runs" / "video-duration-override")
    captured: dict[str, list[str]] = {}

    def fake_run_command(args: list[str], **_kwargs: object) -> None:
        captured["args"] = args

    monkeypatch.setattr("spriterrific.pipeline.run_command", fake_run_command)

    _run_fal_video(paths, "walk prompt", False, "wan-2.2-a14b-i2v-turbo", "3")

    args = captured["args"]
    assert "--duration" not in args
    extra_json = args[args.index("--extra-json") + 1]
    assert '"num_frames":48' in extra_json
    assert '"frames_per_second":16' in extra_json


def test_seedance_rejects_below_minimum_duration(tmp_path: Path) -> None:
    paths = create_run_paths(tmp_path / "runs" / "bad-seedance-duration")

    with pytest.raises(ValueError, match="seedance-2.0-i2v supports video durations"):
        _run_fal_video(paths, "walk prompt", False, "seedance-2.0-i2v", "1")


def test_grok_imagine_accepts_one_second_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = create_run_paths(tmp_path / "runs" / "grok-video-settings")
    captured: dict[str, list[str]] = {}

    def fake_run_command(args: list[str], **_kwargs: object) -> None:
        captured["args"] = args

    monkeypatch.setattr("spriterrific.pipeline.run_command", fake_run_command)

    _run_fal_video(paths, "walk prompt", False, "grok-imagine-video-i2v")

    args = captured["args"]
    assert args[args.index("--endpoint-id") + 1] == "xai/grok-imagine-video/image-to-video"
    assert args[args.index("--duration") + 1] == "1"
    assert args[args.index("--resolution") + 1] == "720p"
    assert args[args.index("--aspect-ratio") + 1] == "1:1"


def test_grok_imagine_walk_defaults_to_two_seconds_in_pipeline() -> None:
    preset = resolve_video_model_preset("grok-imagine-video-i2v")

    assert _effective_video_duration("walk", preset, None) == "2"
    assert _effective_video_duration("run", preset, None) is None
    assert _effective_video_duration("walk", preset, "1") == "1"


def test_grok_imagine_rejects_too_long_duration(tmp_path: Path) -> None:
    paths = create_run_paths(tmp_path / "runs" / "bad-grok-duration")

    with pytest.raises(ValueError, match="grok-imagine-video-i2v supports video durations"):
        _run_fal_video(paths, "walk prompt", False, "grok-imagine-video-i2v", "16")


def test_fal_video_uses_maximum_quality_and_detail_negative_prompt_for_wan27(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = create_run_paths(tmp_path / "runs" / "wan-video-settings")
    captured: dict[str, list[str]] = {}

    def fake_run_command(args: list[str], **_kwargs: object) -> None:
        captured["args"] = args

    monkeypatch.setattr("spriterrific.pipeline.run_command", fake_run_command)

    _run_fal_video(paths, "walk prompt", False, "wan-2.7")

    args = captured["args"]
    extra_json = args[args.index("--extra-json") + 1]
    assert args[args.index("--duration") + 1] == "2"
    assert '"duration"' not in extra_json
    assert '"video_quality":"maximum"' in extra_json
    assert '"video_write_mode":"balanced"' in extra_json
    assert "palette drift" in extra_json
    assert "simplified boots" in extra_json
    assert args[args.index("--resolution") + 1] == "1080p"
    assert args[args.index("--aspect-ratio") + 1] == "1:1"


def test_fal_video_passes_end_image_for_seedance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = create_run_paths(tmp_path / "runs" / "seedance-end-image-settings")
    end_image = make_reference(tmp_path / "fixtures" / "standing-anchor-w.png")
    captured: dict[str, list[str]] = {}

    def fake_run_command(args: list[str], **_kwargs: object) -> None:
        captured["args"] = args

    monkeypatch.setattr("spriterrific.pipeline.run_command", fake_run_command)

    _run_fal_video(paths, "get up prompt", False, "seedance-2.0-i2v", end_image=end_image)

    args = captured["args"]
    assert args[args.index("--model-alias") + 1] == "seedance-2.0-i2v"
    assert "--endpoint-id" not in args
    assert args[args.index("--duration") + 1] == "4"
    assert args[args.index("--end-image-file") + 1] == str(end_image)
    assert args[args.index("--end-image-field") + 1] == "end_image_url"


def test_fal_video_passes_end_image_for_wan27(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = create_run_paths(tmp_path / "runs" / "wan-end-image-settings")
    end_image = make_reference(tmp_path / "fixtures" / "standing-anchor-w.png")
    captured: dict[str, list[str]] = {}

    def fake_run_command(args: list[str], **_kwargs: object) -> None:
        captured["args"] = args

    monkeypatch.setattr("spriterrific.pipeline.run_command", fake_run_command)

    _run_fal_video(paths, "get up prompt", False, "wan-2.7", end_image=end_image)

    args = captured["args"]
    assert args[args.index("--endpoint-id") + 1] == "fal-ai/wan/v2.7/image-to-video"
    assert args[args.index("--end-image-file") + 1] == str(end_image)
    assert args[args.index("--end-image-field") + 1] == "end_image_url"


def test_fal_video_runner_preserves_numeric_duration_override_for_wan27(tmp_path: Path) -> None:
    reference = make_reference(tmp_path / "fixtures" / "standing-anchor-w.png")
    out_dir = tmp_path / "fal-video-dry-run"

    subprocess.run(
        [
            sys.executable,
            str(FAL_VIDEO_SCRIPT),
            "--model-alias",
            "wan-2.7",
            "--prompt",
            "stand up",
            "--image-file",
            str(reference),
            "--out-dir",
            str(out_dir),
            "--filename-prefix",
            "wan",
            "--task-slug",
            "wan-duration-type",
            "--duration",
            "2",
            "--dry-run",
        ],
        check=True,
    )

    manifest = json.loads((out_dir / "wan-run.json").read_text(encoding="utf-8"))
    assert manifest["resolved_arguments"]["duration"] == 2
    assert manifest["explicit_overrides"]["duration"] == 2


def test_bad_reference_size_is_rejected(tmp_path: Path) -> None:
    bad = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    bad_path = tmp_path / "bad.png"
    bad.save(bad_path)

    with pytest.raises(ValueError, match="reference image must be 1024x1024"):
        run_pipeline(
            RunOptions(
                action="idle",
                direction="s",
                mode="image",
                reference=bad_path,
                run_dir=tmp_path / "runs" / "bad",
                dry_fal=True,
            )
        )
