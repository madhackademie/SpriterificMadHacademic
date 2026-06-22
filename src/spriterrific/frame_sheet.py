from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .review_index import write_frame_sheet_review_index


@dataclass(frozen=True)
class SheetFrameOptions:
    cell_size: tuple[int, int] = (256, 256)
    target_height: int | None = None
    columns: int = 5
    fps: int = 10
    review_upscale: int = 4
    order: tuple[str, ...] | None = None
    drop: tuple[str, ...] = ()


def build_frame_sheet(input_dir: Path, out_dir: Path, *, glob: str = "frame-*.png", options: SheetFrameOptions) -> dict[str, Path]:
    source_frames = _resolve_frame_order(input_dir, glob=glob, order=options.order, drop=options.drop)
    if not source_frames:
        raise ValueError("no source frames selected")

    cell_w, cell_h = options.cell_size
    if cell_w <= 0 or cell_h <= 0:
        raise ValueError("cell size must be positive")
    target_height = options.target_height or cell_h
    if target_height <= 0:
        raise ValueError("target height must be positive")
    columns = options.columns
    if columns <= 0:
        raise ValueError("columns must be positive")
    if options.fps <= 0:
        raise ValueError("fps must be positive")
    if options.review_upscale < 1:
        raise ValueError("review upscale must be >= 1")
    rows = math.ceil(len(source_frames) / columns)
    padded_count = rows * columns

    frames_dir = out_dir / f"frames-{cell_w}x{cell_h}"
    review_dir = out_dir / "review"
    frames_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    records: list[dict[str, object]] = []
    for index, source in enumerate(source_frames, start=1):
        normalized, record = _normalize_source_frame(source, cell_size=options.cell_size, target_height=target_height)
        dest = frames_dir / f"frame-{index:02d}.png"
        normalized.save(dest)
        outputs.append(dest)
        records.append({"output": str(dest), **record})

    for index in range(len(outputs) + 1, padded_count + 1):
        blank = frames_dir / f"frame-{index:02d}-blank.png"
        Image.new("RGBA", options.cell_size, (0, 0, 0, 0)).save(blank)
        outputs.append(blank)
        records.append({"input": None, "output": str(blank), "blank": True, "outputSize": [cell_w, cell_h]})

    sheet = Image.new("RGBA", (columns * cell_w, rows * cell_h), (0, 0, 0, 0))
    for index, frame in enumerate(outputs):
        image = Image.open(frame).convert("RGBA")
        col = index % columns
        row = index // columns
        sheet.alpha_composite(image, (col * cell_w, row * cell_h))

    sheet_path = out_dir / f"spritesheet-{cell_w}x{cell_h}-{columns}x{rows}.png"
    sheet.save(sheet_path)

    gif_path = review_dir / f"preview-{len(source_frames)}f-{cell_w}x{cell_h}.gif"
    _save_gif([Image.open(path).convert("RGBA") for path in outputs[: len(source_frames)]], gif_path, fps=options.fps)

    review_sheet_path: Path | None = None
    review_gif_path: Path | None = None
    if options.review_upscale > 1:
        scale = options.review_upscale
        review_frames = [
            Image.open(path).convert("RGBA").resize((cell_w * scale, cell_h * scale), Image.Resampling.NEAREST)
            for path in outputs
        ]
        review_sheet = Image.new("RGBA", (columns * cell_w * scale, rows * cell_h * scale), (0, 0, 0, 0))
        for index, image in enumerate(review_frames):
            col = index % columns
            row = index // columns
            review_sheet.alpha_composite(image, (col * cell_w * scale, row * cell_h * scale))
        review_sheet_path = review_dir / f"spritesheet-{cell_w}x{cell_h}-{columns}x{rows}-x{scale}.png"
        review_sheet.save(review_sheet_path)

        review_gif_path = review_dir / f"preview-{len(source_frames)}f-{cell_w}x{cell_h}-x{scale}.gif"
        _save_gif(review_frames[: len(source_frames)], review_gif_path, fps=options.fps)

    source_map = out_dir / "source-map.txt"
    source_map.write_text(
        "".join(
            f"{Path(str(record['output'])).name} <- {record['input'] if record.get('input') else 'blank'}\n"
            for record in records
        ),
        encoding="utf-8",
    )

    metadata = {
        "cellSize": [cell_w, cell_h],
        "targetHeight": target_height,
        "columns": columns,
        "rows": rows,
        "fps": options.fps,
        "reviewUpscale": options.review_upscale,
        "liveFrameCount": len(source_frames),
        "paddedFrameCount": padded_count,
        "frames": records,
        "spritesheet": str(sheet_path),
        "previewGif": str(gif_path),
        "reviewSpritesheet": str(review_sheet_path) if review_sheet_path else None,
        "reviewPreviewGif": str(review_gif_path) if review_gif_path else None,
    }
    metadata_path = out_dir / "sheet-frame-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    paths = {"spritesheet": sheet_path, "preview": gif_path, "metadata": metadata_path, "source_map": source_map}
    if review_sheet_path is not None:
        paths["review_spritesheet"] = review_sheet_path
    if review_gif_path is not None:
        paths["review_preview"] = review_gif_path
    paths["review_index"] = write_frame_sheet_review_index(
        out_dir,
        sheet_path=sheet_path,
        preview_path=gif_path,
        metadata_path=metadata_path,
        source_map_path=source_map,
        review_sheet_path=review_sheet_path,
        review_preview_path=review_gif_path,
    )
    return paths


def _resolve_frame_order(input_dir: Path, *, glob: str, order: tuple[str, ...] | None, drop: tuple[str, ...]) -> list[Path]:
    lookup = {path.name: path for path in sorted(input_dir.glob(glob))}
    if not lookup:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    selected_names = [_frame_name(item) for item in order] if order else sorted(lookup)
    drop_names = {_frame_name(item) for item in drop}
    selected = []
    for name in selected_names:
        if name in drop_names:
            continue
        if name not in lookup:
            raise ValueError(f"frame not found: {name}")
        selected.append(lookup[name])
    return selected


def _frame_name(value: str) -> str:
    text = Path(value.strip()).name
    if text.isdigit():
        return f"frame-{int(text):02d}.png"
    if text.startswith("frame-") and text.endswith(".png"):
        return text
    if text.startswith("frame-") and text[6:].isdigit():
        return f"{text}.png"
    raise ValueError(f"frame id must be NN, frame-NN, or frame-NN.png, got {value!r}")


def _normalize_source_frame(source: Path, *, cell_size: tuple[int, int], target_height: int) -> tuple[Image.Image, dict[str, object]]:
    image = Image.open(source).convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        crop = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        source_size = [0, 0]
    else:
        crop = image.crop(bbox)
        source_size = [bbox[2] - bbox[0], bbox[3] - bbox[1]]

    cell_w, cell_h = cell_size
    if crop.height > 0:
        scale = target_height / crop.height
        if round(crop.width * scale) > cell_w:
            scale = cell_w / crop.width
        if round(crop.height * scale) > cell_h:
            scale = cell_h / crop.height
        new_size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        crop = crop.resize(new_size, Image.Resampling.NEAREST)
    else:
        scale = 1.0

    canvas = Image.new("RGBA", cell_size, (0, 0, 0, 0))
    x = (cell_w - crop.width) // 2
    y = cell_h - crop.height
    canvas.alpha_composite(crop, (x, y))
    return canvas, {
        "input": str(source),
        "sourceBBox": list(bbox) if bbox else None,
        "sourceVisibleSize": source_size,
        "scale": scale,
        "normalizedVisibleSize": [crop.width, crop.height],
        "outputSize": [cell_w, cell_h],
        "anchor": {"x": x + crop.width // 2, "bottomY": cell_h - 1},
    }


def _save_gif(frames: list[Image.Image], out: Path, *, fps: int) -> None:
    if not frames:
        raise ValueError("cannot build GIF without frames")
    duration_ms = round(1000 / fps)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
    )
