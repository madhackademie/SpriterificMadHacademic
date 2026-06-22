from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.cli import _default_post_selection_layout_mode
from spriterrific.post_selection import (
    PostSelectionOptions,
    _layout_preserve_canvas_frames,
    _remove_green_dominant_in_place,
    process_frame_picker_selection,
)


def test_cli_defaults_preserve_video_motion_for_all_actions() -> None:
    assert _default_post_selection_layout_mode("walk") == "preserve-canvas"
    assert _default_post_selection_layout_mode("run") == "preserve-canvas"
    assert _default_post_selection_layout_mode("attack") == "preserve-canvas"
    assert _default_post_selection_layout_mode("idle") == "preserve-canvas"
    assert _default_post_selection_layout_mode("crouch") == "preserve-canvas"


def _make_selected_frame(path: Path, index: int) -> None:
    image = Image.new("RGBA", (96, 96), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    x = 38 + (index % 3) * 2
    draw.rectangle((x, 22, x + 18, 78), fill=(60, 90 + index, 180, 255))
    draw.rectangle((x + 4, 12, x + 14, 26), fill=(230, 190, 120, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_process_frame_picker_selection_writes_handoff_bundle(tmp_path: Path) -> None:
    picker = tmp_path / "frame-picker" / "manual"
    selected = picker / "selected"
    for index in range(1, 11):
        _make_selected_frame(selected / f"frame-{index:02d}.png", index)
    (picker / "selection.json").write_text(
        json.dumps({"version": 1, "selectedFrameCount": 10, "selectedOrder": "fixture"}) + "\n",
        encoding="utf-8",
    )

    report = process_frame_picker_selection(
        PostSelectionOptions(
            picker_dir=picker,
            out_dir=tmp_path / "processed",
            action="walk",
            direction="w",
            pixel_snap=False,
            target_height=48,
            max_width=48,
            review_upscale=2,
        )
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["cellSize"] == [256, 256]
    assert data["layoutMode"] == "preserve-canvas"
    assert data["heightNormalization"] is False
    assert data["motionPreserved"] is True
    assert data["scaleMode"] == "per-frame"
    assert data["allowUpscale"] is True
    assert data["preserveCanvasResample"] == "LANCZOS"
    assert data["preScaleGreenFringeCleanup"] is True
    assert data["postScaleGreenFringeCleanup"] is False
    assert data["runtimeGreenCleanup"] is False
    assert data["pixelSnap"] is False
    assert data["artifacts"]["runtimeFramesDir"].endswith("frames-256x256")
    assert data["artifacts"]["greenFringeCleanedDir"].endswith("green-fringe-cleaned")
    assert data["artifacts"]["compareRawToCleanupInput"].endswith("compare-01-raw-to-cleanup-input.png")
    assert data["artifacts"]["compareScaledToRuntime"].endswith("compare-06-layout-input-to-runtime-cells.png")
    assert "uv run spriterrific frame-aligner" in data["handoff"]["frameAlignerCommand"]
    assert (report.parent / "export" / "spritesheet.png").is_file()
    assert (report.parent / "export" / "preview.gif").is_file()
    assert (report.parent / "green-fringe-cleaned" / "green-fringe-metadata.json").is_file()
    assert (report.parent / "review" / "index.md").is_file()
    assert (report.parent / "review" / "snapped-native-preview.gif").is_file()
    assert (report.parent / "review" / "compare-01-raw-to-cleanup-input.png").is_file()
    assert (report.parent / "review" / "compare-06-layout-input-to-runtime-cells.png").is_file()
    with Image.open(report.parent / "review" / "raw-selected-preview.gif") as gif:
        assert gif.size == (96, 96)
    review_text = (report.parent / "review" / "index.md").read_text(encoding="utf-8")
    assert "Source frames: `96x96`" in review_text
    assert "Runtime cell: `256x256`" in review_text
    assert "Layout: `5x2`" in review_text
    assert "Spritesheet: `1280x512`" in review_text
    assert "Comparison 01: Raw Selected To Cleanup Input" in review_text
    assert "Comparison 06: Layout Input To Runtime Cells" in review_text
    assert "Source frames are `96x96` each" in review_text
    assert "Sheet size is `1280x512` with `256x256` cells" in review_text
    assert "Layout mode is `preserve-canvas`" in review_text


def test_process_frame_picker_selection_supports_128_runtime_cells(tmp_path: Path) -> None:
    picker = tmp_path / "frame-picker" / "manual"
    selected = picker / "selected"
    for index in range(1, 11):
        _make_selected_frame(selected / f"frame-{index:02d}.png", index)

    report = process_frame_picker_selection(
        PostSelectionOptions(
            picker_dir=picker,
            out_dir=tmp_path / "processed-128",
            action="walk",
            direction="w",
            pixel_snap=False,
            layout_mode="fit-foreground",
            cell_size=(128, 128),
            target_height=104,
            max_width=110,
            ground_y=120,
            center_x=64,
            review_upscale=2,
        )
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["cellSize"] == [128, 128]
    assert data["layoutMode"] == "fit-foreground"
    assert data["heightNormalization"] is True
    assert data["motionPreserved"] is False
    assert data["groundY"] == 120
    assert data["artifacts"]["runtimeFramesDir"].endswith("frames-128x128")
    with Image.open(report.parent / "export" / "spritesheet.png") as sheet:
        assert sheet.size == (640, 256)
    with Image.open(report.parent / "frames-128x128" / "frame-01.png") as frame:
        assert frame.size == (128, 128)
    report_text = (report.parent / "report.md").read_text(encoding="utf-8")
    assert "Runtime cell size: `128x128`" in report_text
    assert "Runtime spritesheet size: `640x256`" in report_text
    review_text = (report.parent / "review" / "index.md").read_text(encoding="utf-8")
    assert "Cleaned frames normalized to `128x128` runtime cells" in review_text


def test_pixel_snapped_preserve_canvas_uses_nearest_and_final_green_cleanup(tmp_path: Path) -> None:
    input_dir = tmp_path / "cleaned"
    output_dir = tmp_path / "frames-256x256"
    input_dir.mkdir()
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 4, 20, 28), fill=(230, 190, 120, 255))
    image.putpixel((16, 20), (19, 123, 17, 255))
    image.save(input_dir / "frame-01.png")

    _layout_preserve_canvas_frames(
        input_dir,
        output_dir,
        cell_size=(256, 256),
        resample=Image.Resampling.NEAREST,
    )
    _remove_green_dominant_in_place(output_dir, min_green=70, dominance=24)

    metadata = json.loads((output_dir / "preserve-canvas-metadata.json").read_text(encoding="utf-8"))
    assert metadata["resample"] == "NEAREST"

    cleanup = json.loads((output_dir / "runtime-green-cleanup.json").read_text(encoding="utf-8"))
    assert cleanup["frames"][0]["removedGreenDominantPixels"] > 0

    with Image.open(output_dir / "frame-01.png").convert("RGBA") as frame:
        greenish = [
            frame.getpixel((x, y))
            for y in range(frame.height)
            for x in range(frame.width)
            if (pixel := frame.getpixel((x, y)))[3]
            and pixel[1] >= 70
            and pixel[1] - max(pixel[0], pixel[2]) >= 24
        ]
    assert greenish == []


def test_process_selection_locked_grid_pixel_snap_keeps_native_sizes_fixed(tmp_path: Path) -> None:
    picker = tmp_path / "frame-picker" / "manual"
    selected = picker / "selected"
    for index in range(1, 5):
        _make_selected_frame(selected / f"frame-{index:02d}.png", index)

    report = process_frame_picker_selection(
        PostSelectionOptions(
            picker_dir=picker,
            out_dir=tmp_path / "processed-locked-grid",
            action="idle",
            direction="w",
            pixel_snap=True,
            pixel_snap_mode="locked-grid",
            pixel_snap_grid_source="frame-02.png",
            pixel_snap_workers=2,
            layout_mode="preserve-canvas",
            columns=2,
            fps=8,
            k_colors=32,
            review_upscale=2,
        )
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["pixelSnap"] is True
    assert data["pixelSnapMode"] == "locked-grid"
    grid_path = Path(data["artifacts"]["pixelSnapGrid"])
    assert grid_path.is_file()
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    assert grid["mode"] == "locked-grid"
    assert grid["gridSource"].endswith("frame-02.png")

    snapped_sizes = []
    for frame in sorted((report.parent / "pixel-snapped" / "native").glob("frame-*.png")):
        with Image.open(frame) as image:
            snapped_sizes.append(image.size)
    assert len(set(snapped_sizes)) == 1

    review_text = (report.parent / "review" / "index.md").read_text(encoding="utf-8")
    assert "Pixel snapping uses `locked-grid`" in review_text
    assert "Pixel Snap Locked Grid JSON" in review_text


def test_process_selection_applies_size_contract_and_writes_audit(tmp_path: Path) -> None:
    picker = tmp_path / "frame-picker" / "manual"
    selected = picker / "selected"
    for index in range(1, 5):
        _make_selected_frame(selected / f"frame-{index:02d}.png", index)
    contract = tmp_path / "size-contract.json"
    contract.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "spriterrific-size-contract",
                "name": "fixture-contract",
                "runtimeCell": [128, 128],
                "targetVisibleHeight": 48,
                "maxVisibleWidth": 48,
                "targetBottomY": 120,
                "targetCenterX": 64,
                "pivot": "foot-center",
                "tolerances": {
                    "maxTargetHeightDriftPct": 0.12,
                    "maxIntraHeightDriftPct": 0.12,
                    "maxBottomDriftPx": 2,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = process_frame_picker_selection(
        PostSelectionOptions(
            picker_dir=picker,
            out_dir=tmp_path / "processed-contract",
            action="attack",
            direction="w",
            layout_mode="fit-foreground",
            scale_mode="shared",
            pixel_snap=False,
            size_contract=contract,
            columns=2,
            fps=8,
            review_upscale=2,
        )
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["sizeContract"] == str(contract)
    assert data["cellSize"] == [128, 128]
    assert data["targetHeight"] == 48
    assert data["maxWidth"] == 48
    assert data["centerX"] == 64
    assert data["groundY"] == 120
    assert data["sizeContractAudit"]["status"] == "pass"
    assert Path(data["artifacts"]["sizeContractAudit"]).is_file()
    assert (report.parent / "frames-128x128" / "frame-01.png").is_file()
    review_text = (report.parent / "review" / "index.md").read_text(encoding="utf-8")
    assert "Size Contract Audit JSON" in review_text
