from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import write_json
from .presets import FRAME_HEIGHT, FRAME_WIDTH, SHEET_COLUMNS, TARGET_BOTTOM_Y, TARGET_CENTER_X, sheet_rows


def write_export_manifest(
    *,
    out: Path,
    run_id: str,
    action: str,
    direction: str,
    mode: str,
    frame_count: int,
    fps: int,
) -> dict[str, Any]:
    manifest = {
        "version": 1,
        "action": action,
        "direction": direction,
        "mode": mode,
        "spritesheet": "spritesheet.png",
        "previewGif": "preview.gif",
        "frameWidth": FRAME_WIDTH,
        "frameHeight": FRAME_HEIGHT,
        "columns": SHEET_COLUMNS,
        "rows": sheet_rows(frame_count),
        "frames": frame_count,
        "fps": fps,
        "anchor": {"x": TARGET_CENTER_X, "y": TARGET_BOTTOM_Y},
        "sourceRun": run_id,
        "publicAssetReady": False,
    }
    write_json(out, manifest)
    return manifest
