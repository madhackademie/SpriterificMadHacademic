from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor

from .commands import run_command
from .events import append_event, now_iso, write_json
from .media import remove_corner_background
from .presets import REFERENCE_SIZE
from .validate import require_file


RUNTIME_TOOLS = Path(__file__).resolve().parent / "runtime_tools"
PIXEL_SNAPPER_SCRIPT = RUNTIME_TOOLS / "pixel_snapper" / "scripts" / "pixel_snapper.py"


@dataclass(frozen=True)
class SnapOptions:
    source: Path
    run_dir: Path
    target_size: tuple[int, int] = REFERENCE_SIZE
    k_colors: int = 256
    chroma: str | None = "#00FF00"


@dataclass(frozen=True)
class SnapResult:
    run_dir: Path
    source: Path
    snapped: Path
    anchor: Path
    chroma_anchor: Path | None
    snapped_size: tuple[int, int]
    target_size: tuple[int, int]


def snap_user_anchor(options: SnapOptions) -> SnapResult:
    require_file(options.source, "input image")
    require_file(PIXEL_SNAPPER_SCRIPT, "pixel-snapper script")

    run_dir = options.run_dir
    input_dir = run_dir / "input"
    snapped_dir = run_dir / "snapped"
    output_dir = run_dir / "output"
    logs_dir = run_dir / "logs"
    for directory in (input_dir, snapped_dir, output_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    source_copy = input_dir / "source.png"
    shutil.copy2(options.source, source_copy)

    snapped_path = snapped_dir / "snapped.png"
    anchor_path = output_dir / "anchor.png"
    chroma_anchor_path = output_dir / "anchor-chroma.png" if options.chroma else None
    events_path = run_dir / "events.jsonl"

    run_record = {
        "version": 1,
        "runId": run_dir.name,
        "createdAt": now_iso(),
        "type": "snap",
        "source": str(source_copy),
        "originalSource": str(options.source),
        "snapped": str(snapped_path),
        "anchor": str(anchor_path),
        "chromaAnchor": str(chroma_anchor_path) if chroma_anchor_path else None,
        "targetSize": list(options.target_size),
        "kColors": options.k_colors,
        "chroma": options.chroma,
        "status": "running",
    }
    write_json(run_dir / "run.json", run_record)
    append_event(events_path, "snap_run_started", source=str(options.source))

    try:
        run_command(
            [
                sys.executable,
                str(PIXEL_SNAPPER_SCRIPT),
                str(source_copy),
                str(snapped_path),
                "--k-colors",
                str(options.k_colors),
            ],
            stage="pixel-snap",
            run_dir=run_dir,
            events_path=events_path,
        )
        require_file(snapped_path, "snapped output")

        with Image.open(snapped_path) as snapped_image:
            snapped_size = snapped_image.size
            anchor_source = prepare_snapped_anchor_source(snapped_image)
            upscaled, anchor_scale, anchor_offset = fit_snapped_to_anchor(anchor_source, options.target_size)
        upscaled.save(anchor_path)

        if chroma_anchor_path is not None and options.chroma is not None:
            put_on_chroma(anchor_path, chroma_anchor_path, chroma=options.chroma)

        append_event(
            events_path,
            "snap_run_completed",
            snappedSize=list(snapped_size),
            targetSize=list(options.target_size),
            anchorScale=anchor_scale,
            anchorOffset=list(anchor_offset),
        )
        run_record.update(
            {
                "status": "completed",
                "snappedSize": list(snapped_size),
                "anchorScale": anchor_scale,
                "anchorOffset": list(anchor_offset),
                "completedAt": now_iso(),
            }
        )
        write_json(run_dir / "run.json", run_record)
    except Exception as exc:
        append_event(events_path, "snap_run_failed", error=str(exc))
        run_record.update({"status": "failed", "error": str(exc), "failedAt": now_iso()})
        write_json(run_dir / "run.json", run_record)
        raise

    return SnapResult(
        run_dir=run_dir,
        source=source_copy,
        snapped=snapped_path,
        anchor=anchor_path,
        chroma_anchor=chroma_anchor_path,
        snapped_size=snapped_size,
        target_size=options.target_size,
    )


def prepare_snapped_anchor_source(snapped: Image.Image) -> Image.Image:
    rgba = snapped.convert("RGBA")
    alpha_bbox = rgba.getchannel("A").getbbox()
    if alpha_bbox == (0, 0, rgba.width, rgba.height):
        return remove_corner_background(rgba)
    return rgba


def fit_snapped_to_anchor(snapped: Image.Image, target_size: tuple[int, int]) -> tuple[Image.Image, float, tuple[int, int]]:
    target_w, target_h = target_size
    if target_w < 1 or target_h < 1:
        raise ValueError("target size must be positive")
    rgba = snapped.convert("RGBA")
    if rgba.width < 1 or rgba.height < 1:
        raise ValueError("snapped image must be positive")

    if rgba.width <= target_w and rgba.height <= target_h:
        scale = max(1, min(target_w // rgba.width, target_h // rgba.height))
        scaled_size = (rgba.width * scale, rgba.height * scale)
        scale_value: float = float(scale)
    else:
        scale_value = min(target_w / rgba.width, target_h / rgba.height)
        scaled_size = (
            max(1, min(target_w, round(rgba.width * scale_value))),
            max(1, min(target_h, round(rgba.height * scale_value))),
        )

    scaled = rgba.resize(scaled_size, Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
    offset = ((target_w - scaled.width) // 2, (target_h - scaled.height) // 2)
    canvas.alpha_composite(scaled, offset)
    return canvas, scale_value, offset


def put_on_chroma(source: Path, out: Path, *, chroma: str = "#00FF00") -> Path:
    image = Image.open(source).convert("RGBA")
    alpha_bbox = image.getchannel("A").getbbox()
    if alpha_bbox is None:
        raise ValueError(f"could not find foreground in {source}")
    if alpha_bbox == (0, 0, image.width, image.height):
        image = remove_corner_background(image)
    canvas = Image.new("RGBA", image.size, ImageColor.getrgb(chroma) + (255,))
    canvas.alpha_composite(image, (0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out
