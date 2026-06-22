from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from .frame_aligner import FrameOffset, apply_frame_offset
from .presets import FRAME_HEIGHT, FRAME_WIDTH, RuntimeAnchorPolicy, resolve_runtime_anchor_policy


@dataclass(frozen=True)
class FinalizeRuntimeOptions:
    animation_dirs: tuple[Path, ...]
    anchor_policy: RuntimeAnchorPolicy = "auto"
    target_bottom_y: int | None = None
    target_center_x: int | None = None


def finalize_runtime_animation_dirs(options: FinalizeRuntimeOptions) -> list[Path]:
    if not options.animation_dirs:
        raise ValueError("at least one animation directory is required")
    reports = []
    for animation_dir in options.animation_dirs:
        reports.append(
            finalize_runtime_animation_dir(
                animation_dir,
                anchor_policy=options.anchor_policy,
                target_bottom_y=options.target_bottom_y,
                target_center_x=options.target_center_x,
            )
        )
    return reports


def finalize_runtime_animation_dir(
    animation_dir: Path,
    *,
    anchor_policy: RuntimeAnchorPolicy = "auto",
    target_bottom_y: int | None = None,
    target_center_x: int | None = None,
) -> Path:
    manifest_path = animation_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"animation manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    sheet_path = animation_dir / str(manifest.get("spritesheet", "spritesheet.png"))
    preview_path = animation_dir / str(manifest.get("previewGif", "preview.gif"))
    if not sheet_path.is_file():
        raise ValueError(f"runtime spritesheet does not exist: {sheet_path}")

    action = str(manifest.get("action", ""))
    resolved_policy = resolve_runtime_anchor_policy(action, anchor_policy)
    frame_count = int(manifest["frames"])
    columns = int(manifest.get("columns", 5))
    fps = int(manifest.get("fps", 10))
    cell_size = (int(manifest.get("frameWidth", FRAME_WIDTH)), int(manifest.get("frameHeight", FRAME_HEIGHT)))
    target_bottom = target_bottom_y if target_bottom_y is not None else cell_size[1] - 1
    target_center = target_center_x if target_center_x is not None else cell_size[0] // 2

    source_frames = split_runtime_spritesheet(sheet_path, frame_count=frame_count, columns=columns, cell_size=cell_size)
    finalized_frames = []
    records = []
    for index, frame in enumerate(source_frames, start=1):
        finalized, record = finalize_runtime_frame(
            frame,
            policy=resolved_policy,
            target_bottom_y=target_bottom,
            target_center_x=target_center,
        )
        finalized_frames.append(finalized)
        records.append({"frame": f"frame-{index:02d}.png", **record})

    pack_runtime_frames(finalized_frames, sheet_path, columns=columns)
    save_runtime_gif(finalized_frames, preview_path, fps=fps)

    changed = sum(1 for record in records if record["dx"] or record["dy"])
    report = {
        "version": 1,
        "kind": "runtime-finalization",
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "animationDir": str(animation_dir),
        "action": action,
        "direction": manifest.get("direction"),
        "requestedAnchorPolicy": anchor_policy,
        "anchorPolicy": resolved_policy,
        "targetBottomY": target_bottom,
        "targetCenterX": target_center,
        "cellSize": list(cell_size),
        "columns": columns,
        "frames": frame_count,
        "fps": fps,
        "framesAdjusted": changed,
        "maxAbsDx": max((abs(int(record["dx"])) for record in records), default=0),
        "maxAbsDy": max((abs(int(record["dy"])) for record in records), default=0),
        "publicAssetReady": True,
        "records": records,
    }
    report_path = animation_dir / "finalize-runtime.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    manifest["runtimeFinalization"] = {
        "anchorPolicy": resolved_policy,
        "requestedAnchorPolicy": anchor_policy,
        "targetBottomY": target_bottom,
        "targetCenterX": target_center,
        "framesAdjusted": changed,
        "report": report_path.name,
    }
    manifest["publicAssetReady"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return report_path


def split_runtime_spritesheet(
    sheet_path: Path,
    *,
    frame_count: int,
    columns: int,
    cell_size: tuple[int, int],
) -> list[Image.Image]:
    if frame_count <= 0:
        raise ValueError("frame count must be positive")
    if columns <= 0:
        raise ValueError("columns must be positive")
    cell_w, cell_h = cell_size
    expected_rows = math.ceil(frame_count / columns)
    expected_size = (columns * cell_w, expected_rows * cell_h)
    sheet = Image.open(sheet_path).convert("RGBA")
    if sheet.size != expected_size:
        raise ValueError(f"{sheet_path} must be {expected_size[0]}x{expected_size[1]}, got {sheet.size[0]}x{sheet.size[1]}")

    frames = []
    for index in range(frame_count):
        col = index % columns
        row = index // columns
        x = col * cell_w
        y = row * cell_h
        frames.append(sheet.crop((x, y, x + cell_w, y + cell_h)))
    return frames


def finalize_runtime_frame(
    image: Image.Image,
    *,
    policy: RuntimeAnchorPolicy,
    target_bottom_y: int,
    target_center_x: int,
) -> tuple[Image.Image, dict[str, Any]]:
    src = image.convert("RGBA")
    bbox = src.getchannel("A").getbbox()
    dx = 0
    dy = 0
    if bbox is not None:
        if policy == "grounded":
            dy = (target_bottom_y + 1) - bbox[3]
        elif policy == "centered":
            dx = target_center_x - ((bbox[0] + bbox[2]) // 2)
            dy = (src.height // 2) - ((bbox[1] + bbox[3]) // 2)
        elif policy == "preserve-motion":
            pass
        elif policy == "auto":
            raise ValueError("runtime anchor policy must be resolved before finalizing frames")
        else:
            raise ValueError(f"unknown runtime anchor policy: {policy}")
    out = apply_frame_offset(src, FrameOffset(dx=dx, dy=dy))
    out_bbox = out.getchannel("A").getbbox()
    return out, {
        "policy": policy,
        "sourceBBox": list(bbox) if bbox else None,
        "outputBBox": list(out_bbox) if out_bbox else None,
        "dx": dx,
        "dy": dy,
    }


def pack_runtime_frames(frames: list[Image.Image], out: Path, *, columns: int) -> Path:
    if not frames:
        raise ValueError("cannot pack an empty frame list")
    if columns <= 0:
        raise ValueError("columns must be positive")
    cell_size = frames[0].size
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGBA", (columns * cell_size[0], rows * cell_size[1]), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        if frame.size != cell_size:
            raise ValueError(f"all frames must have size {cell_size[0]}x{cell_size[1]}")
        col = index % columns
        row = index // columns
        sheet.alpha_composite(frame.convert("RGBA"), (col * cell_size[0], row * cell_size[1]))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def save_runtime_gif(frames: list[Image.Image], out: Path, *, fps: int) -> Path:
    if not frames:
        raise ValueError("cannot build GIF without frames")
    if fps <= 0:
        raise ValueError("fps must be positive")
    duration_ms = round(1000 / fps)
    out.parent.mkdir(parents=True, exist_ok=True)
    rgba_frames = [frame.convert("RGBA") for frame in frames]
    rgba_frames[0].save(
        out,
        save_all=True,
        append_images=rgba_frames[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
    )
    return out
