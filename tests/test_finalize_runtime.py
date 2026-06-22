from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.finalize_runtime import finalize_runtime_animation_dir


def _make_animation_dir(path: Path, *, action: str, frames: int = 2, bottom_margin: int = 12) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    columns = 5
    cell = 256
    sheet = Image.new("RGBA", (columns * cell, cell), (0, 0, 0, 0))
    for index in range(frames):
        frame = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((100, 80, 140, cell - bottom_margin - 1), fill=(200, 80, 40, 255))
        sheet.alpha_composite(frame, (index * cell, 0))
    sheet.save(path / "spritesheet.png")
    Image.new("RGBA", (cell, cell), (0, 0, 0, 0)).save(path / "preview.gif")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "action": action,
                "direction": "w",
                "mode": "video",
                "spritesheet": "spritesheet.png",
                "previewGif": "preview.gif",
                "frameWidth": cell,
                "frameHeight": cell,
                "columns": columns,
                "rows": 1,
                "frames": frames,
                "fps": 10,
                "anchor": {"x": 128, "y": 255},
                "sourceRun": "fixture",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _frame_bottom_margin(sheet_path: Path, *, frame_index: int = 0) -> int:
    with Image.open(sheet_path) as sheet:
        frame = sheet.convert("RGBA").crop((frame_index * 256, 0, (frame_index + 1) * 256, 256))
    bbox = frame.getchannel("A").getbbox()
    assert bbox is not None
    return 256 - bbox[3]


def test_finalize_runtime_grounds_walk_frames(tmp_path: Path) -> None:
    animation_dir = _make_animation_dir(tmp_path / "walk", action="walk", bottom_margin=18)

    report = finalize_runtime_animation_dir(animation_dir)

    assert report.is_file()
    assert _frame_bottom_margin(animation_dir / "spritesheet.png") == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["anchorPolicy"] == "grounded"
    assert data["framesAdjusted"] == 2
    assert data["publicAssetReady"] is True
    manifest = json.loads((animation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runtimeFinalization"]["anchorPolicy"] == "grounded"
    assert manifest["publicAssetReady"] is True


def test_finalize_runtime_auto_preserves_jump_motion(tmp_path: Path) -> None:
    animation_dir = _make_animation_dir(tmp_path / "jump", action="jump", bottom_margin=18)

    report = finalize_runtime_animation_dir(animation_dir)

    assert _frame_bottom_margin(animation_dir / "spritesheet.png") == 18
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["anchorPolicy"] == "preserve-motion"
    assert data["framesAdjusted"] == 0
