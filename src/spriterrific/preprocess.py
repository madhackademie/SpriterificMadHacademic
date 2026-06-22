from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor

from .media import foreground_bbox, remove_corner_background
from .presets import REFERENCE_SIZE


@dataclass(frozen=True)
class PreprocessResult:
    output: Path
    metadata: dict[str, object]


def preprocess_user_anchor(
    source: Path,
    out: Path,
    *,
    metadata_out: Path | None = None,
    target_size: tuple[int, int] = REFERENCE_SIZE,
    chroma: str = "#00FF00",
    padding: int = 48,
    snap_long_edge: int = 256,
    background_threshold: int = 30,
) -> PreprocessResult:
    if padding < 0:
        raise ValueError("padding must be >= 0")
    if snap_long_edge < 16:
        raise ValueError("snap_long_edge must be >= 16")

    source_image = Image.open(source).convert("RGBA")
    transparent = _extract_foreground(source_image, threshold=background_threshold)
    bbox = foreground_bbox(transparent, threshold=background_threshold)
    crop = transparent.crop(bbox)
    if crop.getchannel("A").getbbox() is None:
        raise ValueError(f"could not find foreground in {source}")

    snapped = _pixel_snap(crop, snap_long_edge=snap_long_edge)
    fitted_size = _fit_size(snapped.size, target_size=target_size, padding=padding)
    fitted = snapped.resize(fitted_size, Image.Resampling.NEAREST)

    chroma_rgba = ImageColor.getrgb(chroma) + (255,)
    canvas = Image.new("RGBA", target_size, chroma_rgba)
    x = (target_size[0] - fitted.width) // 2
    y = target_size[1] - padding - fitted.height
    if y < 0:
        y = (target_size[1] - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)

    metadata: dict[str, object] = {
        "source": str(source),
        "output": str(out),
        "sourceSize": list(source_image.size),
        "foregroundBox": list(bbox),
        "cropSize": list(crop.size),
        "snapLongEdge": snap_long_edge,
        "snappedSize": list(snapped.size),
        "targetSize": list(target_size),
        "padding": padding,
        "fittedSize": list(fitted.size),
        "placement": {"x": x, "y": y},
        "chroma": chroma,
        "backgroundThreshold": background_threshold,
    }
    if metadata_out is not None:
        metadata_out.parent.mkdir(parents=True, exist_ok=True)
        metadata_out.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return PreprocessResult(output=out, metadata=metadata)


def _extract_foreground(image: Image.Image, *, threshold: int) -> Image.Image:
    alpha_bbox = image.getchannel("A").getbbox()
    if alpha_bbox and alpha_bbox != (0, 0, image.width, image.height):
        return image
    return remove_corner_background(image, threshold=threshold)


def _pixel_snap(crop: Image.Image, *, snap_long_edge: int) -> Image.Image:
    long_edge = max(crop.size)
    if long_edge <= snap_long_edge:
        return crop
    scale = snap_long_edge / long_edge
    snapped_size = (
        max(1, int(round(crop.width * scale))),
        max(1, int(round(crop.height * scale))),
    )
    return crop.resize(snapped_size, Image.Resampling.NEAREST)


def _fit_size(
    size: tuple[int, int],
    *,
    target_size: tuple[int, int],
    padding: int,
) -> tuple[int, int]:
    max_w = max(1, target_size[0] - padding * 2)
    max_h = max(1, target_size[1] - padding * 2)
    scale = min(max_w / size[0], max_h / size[1])
    return (
        max(1, min(max_w, int(round(size[0] * scale)))),
        max(1, min(max_h, int(round(size[1] * scale)))),
    )
