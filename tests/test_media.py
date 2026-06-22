from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.media import best_guess_frame_indices, build_selected_preview_gif, create_video_plate, select_frames


def _make_dense_frame(path: Path, x: int) -> None:
    image = Image.new("RGB", (96, 64), (184, 184, 184))
    draw = ImageDraw.Draw(image)
    draw.rectangle((x, 18, x + 16, 52), fill=(20, 90, 180))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_best_guess_frame_indices_avoids_visual_duplicates(tmp_path: Path) -> None:
    frames = []
    positions = [10, 10, 10, 30, 30, 50, 50, 70, 70, 70]
    for index, x in enumerate(positions, start=1):
        path = tmp_path / f"frame-{index:04d}.png"
        _make_dense_frame(path, x)
        frames.append(path)

    indices = best_guess_frame_indices(frames, 4)

    selected_positions = [positions[index] for index in indices]
    assert len(set(selected_positions)) == 4


def test_select_frames_writes_manifest_and_preview_inputs(tmp_path: Path) -> None:
    dense = tmp_path / "dense"
    for index, x in enumerate(range(0, 50, 5), start=1):
        _make_dense_frame(dense / f"frame-{index:04d}.png", x)

    selected = tmp_path / "selected"
    manifest = selected / "selection.json"
    frames = select_frames(dense, selected, 5, metadata_path=manifest)

    assert [path.name for path in frames] == [f"frame-{index:02d}.png" for index in range(1, 6)]
    data = json.loads(manifest.read_text())
    assert data["selectionMode"] == "auto-cycle-window-nonduplicate"
    assert data["denseFrameCount"] == 10
    assert data["selectedFrameCount"] == 5
    assert data["frames"][0]["output"] == "frame-01.png"
    assert data["frames"][0]["source"] == "frame-0002.png"

    preview = tmp_path / "selected-preview.gif"
    build_selected_preview_gif(selected, preview)
    assert preview.is_file()


def test_wan_27_run_auto_selection_skips_warmup_window(tmp_path: Path) -> None:
    dense = tmp_path / "dense"
    for index, x in enumerate(range(90), start=1):
        _make_dense_frame(dense / f"frame-{index:04d}.png", x)

    selected = tmp_path / "selected"
    manifest = selected / "selection.json"
    select_frames(dense, selected, 10, action="run", video_model_alias="wan-2.7", metadata_path=manifest)

    data = json.loads(manifest.read_text())
    assert data["selectionMode"] == "auto-cycle-window-nonduplicate"
    selected_indices = [frame["sourceIndex"] for frame in data["frames"]]
    assert selected_indices[0] == 45
    assert selected_indices[-1] == 64
    assert all(index >= 45 for index in selected_indices)


def test_cycle_selection_can_use_explicit_window_controls(tmp_path: Path) -> None:
    dense = tmp_path / "dense"
    for index, x in enumerate(range(90), start=1):
        _make_dense_frame(dense / f"frame-{index:04d}.png", x)

    selected = tmp_path / "selected"
    manifest = selected / "selection.json"
    select_frames(
        dense,
        selected,
        8,
        action="walk",
        cycle_start_fraction=0.25,
        cycle_span_factor=6.0,
        metadata_path=manifest,
    )

    data = json.loads(manifest.read_text())
    selected_indices = [frame["sourceIndex"] for frame in data["frames"]]
    assert data["cycleStartFraction"] == 0.25
    assert data["cycleSpanFactor"] == 6.0
    assert selected_indices[0] == 23
    assert selected_indices[-1] == 65


def test_select_frames_from_exclusive_range(tmp_path: Path) -> None:
    dense = tmp_path / "dense"
    for index, x in enumerate(range(0, 120, 5), start=1):
        _make_dense_frame(dense / f"frame-{index:04d}.png", x)

    selected = tmp_path / "selected"
    manifest = selected / "selection.json"
    select_frames(dense, selected, 5, selected_range=(7, 18), metadata_path=manifest)

    data = json.loads(manifest.read_text())
    assert data["selectionMode"] == "auto-range-nonduplicate"
    assert data["frames"][0]["source"] == "frame-0007.png"
    assert data["frames"][-1]["source"] == "frame-0017.png"


def test_transition_selection_uses_full_duration_and_includes_end(tmp_path: Path) -> None:
    dense = tmp_path / "dense"
    for index, x in enumerate(range(60), start=1):
        _make_dense_frame(dense / f"frame-{index:04d}.png", x)

    selected = tmp_path / "selected"
    manifest = selected / "selection.json"
    select_frames(
        dense,
        selected,
        10,
        action="get_up",
        timing="transition",
        selection_policy="full_duration_include_end",
        metadata_path=manifest,
    )

    data = json.loads(manifest.read_text())
    assert data["selectionMode"] == "auto-full-duration-include-end"
    assert data["timing"] == "transition"
    assert data["selectionPolicy"] == "full_duration_include_end"
    assert data["sourceStartFrame"] == 1
    assert data["sourceEndFrame"] == 60
    assert data["includesFinalSourceFrame"] is True
    assert data["frames"][0]["source"] == "frame-0001.png"
    assert data["frames"][-1]["source"] == "frame-0060.png"


def test_manual_transition_selection_warns_when_final_frame_is_missing(tmp_path: Path) -> None:
    dense = tmp_path / "dense"
    for index, x in enumerate(range(60), start=1):
        _make_dense_frame(dense / f"frame-{index:04d}.png", x)

    selected = tmp_path / "selected"
    manifest = selected / "selection.json"
    selected_order = [f"frame-{index:04d}.png" for index in range(1, 31)]
    select_frames(
        dense,
        selected,
        len(selected_order),
        selected_order=selected_order,
        action="get_up",
        timing="transition",
        selection_policy="full_duration_include_end",
        metadata_path=manifest,
    )

    data = json.loads(manifest.read_text())
    assert data["selectionMode"] == "manual"
    assert data["includesFinalSourceFrame"] is False
    assert data["warnings"]
    assert "get_up is a transition" in data["warnings"][0]
    assert "frame-0030.png of frame-0060.png" in data["warnings"][0]


def test_create_video_plate_removes_chroma_background(tmp_path: Path) -> None:
    reference = tmp_path / "anchor.png"
    image = Image.new("RGBA", (1024, 1024), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((430, 220, 594, 900), fill=(90, 40, 180, 255))
    image.save(reference)

    out = tmp_path / "plate.png"
    create_video_plate(reference, out)

    plate = Image.open(out).convert("RGBA")
    assert plate.size == (1024, 1024)
    assert plate.getpixel((0, 0))[:3] == (0, 255, 0)
    assert plate.getpixel((512, 512))[:3] == (90, 40, 180)
    assert plate.getpixel((440, 512))[:3] != (0, 255, 0)
