from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from spriterrific.frame_picker import (
    COLOR_CURRENT,
    COLOR_OFF,
    COLOR_START,
    THUMBNAIL_CARD_SIZE,
    ThumbnailState,
    evenly_spaced_indices,
    next_play_index,
    render_frame_thumbnail,
    thumbnail_columns_for_width,
    write_frame_picker_report,
)


def _make_frames(directory: Path, count: int) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(1, count + 1):
        path = directory / f"frame-{index:04d}.png"
        Image.new("RGBA", (16, 16), (index, 20, 30, 255)).save(path)
        frames.append(path)
    return frames


def test_evenly_spaced_indices_includes_start_and_end() -> None:
    assert evenly_spaced_indices(20, 30, 6) == [20, 22, 24, 26, 28, 30]


def test_evenly_spaced_indices_rejects_too_many_frames() -> None:
    with pytest.raises(ValueError, match="cannot select"):
        evenly_spaced_indices(2, 4, 4)


def test_next_play_index_advances_through_all_frames_by_default() -> None:
    assert next_play_index(current=3, total=10, selected=[2, 5, 8], play_selected=False) == 4
    assert next_play_index(current=9, total=10, selected=[], play_selected=False) == 0


def test_next_play_index_loops_through_selection_when_toggled_on() -> None:
    assert next_play_index(current=2, total=10, selected=[2, 5, 8], play_selected=True) == 5
    assert next_play_index(current=5, total=10, selected=[2, 5, 8], play_selected=True) == 8
    assert next_play_index(current=8, total=10, selected=[2, 5, 8], play_selected=True) == 2


def test_next_play_index_jumps_to_first_selection_when_current_not_in_selection() -> None:
    assert next_play_index(current=4, total=10, selected=[2, 5, 8], play_selected=True) == 2


def test_next_play_index_falls_back_to_all_frames_when_selection_empty() -> None:
    assert next_play_index(current=3, total=10, selected=[], play_selected=True) == 4


def test_thumbnail_columns_expand_to_fill_available_width() -> None:
    assert thumbnail_columns_for_width(320) == 2
    assert thumbnail_columns_for_width(1200) >= 7


def test_render_frame_thumbnail_makes_state_visible() -> None:
    frame = Image.new("RGBA", (64, 64), (20, 40, 120, 255))

    off = render_frame_thumbnail(frame, "f0001", ThumbnailState())
    assert off.size == THUMBNAIL_CARD_SIZE
    assert off.getpixel((0, 0)) == COLOR_OFF

    start = render_frame_thumbnail(frame, "f0001", ThumbnailState(start=True))
    assert start.getpixel((0, 0)) == COLOR_START

    current = render_frame_thumbnail(frame, "f0001", ThumbnailState(current=True, selected_order=1))
    assert current.getpixel((5, 5)) == COLOR_CURRENT


def test_write_frame_picker_report_copies_frames_and_writes_command(tmp_path: Path) -> None:
    frames = _make_frames(tmp_path / "dense", 8)
    run_dir = tmp_path / "runs" / "walk-w"
    reference = run_dir / "input" / "source.png"
    video = run_dir / "fal" / "raw-video.mp4"
    reference.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    reference.write_bytes(b"reference")
    video.write_bytes(b"video")

    report = write_frame_picker_report(
        run_dir=run_dir,
        frames=frames,
        selected_indices=[1, 3, 5],
        out_dir=run_dir / "frame-picker" / "manual",
        action="walk",
        direction="w",
        reference=reference,
        video=video,
        start_index=1,
        end_index=5,
    )

    assert report.is_file()
    assert (report.parent / "report.json").is_file()
    assert (report.parent / "selected" / "frame-01.png").is_file()
    assert (report.parent / "selected-contact.png").is_file()
    assert (report.parent / "selected-preview.gif").is_file()
    assert (report.parent / "review" / "index.md").is_file()
    assert (report.parent / "review" / "selected-contact.png").is_file()
    assert (report.parent / "review" / "selected-preview.gif").is_file()
    assert (report.parent / "selected-order.txt").read_text(encoding="utf-8") == "frame-0002.png,frame-0004.png,frame-0006.png\n"
    index = (report.parent / "review" / "index.md").read_text(encoding="utf-8")
    assert "Selected Contact Sheet" in index
    assert "![Selected Preview GIF](selected-preview.gif)" in index
    data = json.loads((report.parent / "selection.json").read_text(encoding="utf-8"))
    report_data = json.loads((report.parent / "report.json").read_text(encoding="utf-8"))
    assert data["startFrame"] == "frame-0002.png"
    assert data["endFrame"] == "frame-0006.png"
    assert data["selectedOrder"] == "frame-0002.png,frame-0004.png,frame-0006.png"
    assert data["artifacts"]["selectedPreviewGif"] == "selected-preview.gif"
    assert data["artifacts"]["jsonReport"] == "report.json"
    assert report_data == data
    assert "--selected-order frame-0002.png,frame-0004.png,frame-0006.png" in data["command"]
