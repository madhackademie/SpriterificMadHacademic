from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class CleanFrameOptions:
    alpha_threshold: int = 24
    neutral_delta: int = 18
    neutral_min_mean: float = 112.0
    min_component_area: int = 6
    edge_radius: int = 1
    trim: bool = True


def clean_frame(image: Image.Image, options: CleanFrameOptions = CleanFrameOptions()) -> tuple[Image.Image, dict[str, object]]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    px = rgba.load()
    alpha = rgba.getchannel("A").load()
    stage = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    stage_px = stage.load()

    removed_low_alpha = 0
    removed_neutral_edge = 0
    kept_before_components = 0

    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if a <= options.alpha_threshold:
                if a:
                    removed_low_alpha += 1
                continue

            spread = max(r, g, b) - min(r, g, b)
            mean = (r + g + b) / 3
            if (
                _has_transparent_neighbor(alpha, x, y, width, height, options.edge_radius)
                and spread <= options.neutral_delta
                and mean >= options.neutral_min_mean
            ):
                removed_neutral_edge += 1
                continue

            stage_px[x, y] = (r, g, b, 255)
            kept_before_components += 1

    cleaned, component_record = _keep_components(stage, min_area=options.min_component_area)
    bbox = cleaned.getchannel("A").getbbox()
    if options.trim and bbox:
        cleaned = cleaned.crop(bbox)

    return cleaned, {
        "alphaThreshold": options.alpha_threshold,
        "neutralDelta": options.neutral_delta,
        "neutralMinMean": options.neutral_min_mean,
        "minComponentArea": options.min_component_area,
        "edgeRadius": options.edge_radius,
        "trim": options.trim,
        "removedLowAlphaPixels": removed_low_alpha,
        "removedNeutralEdgePixels": removed_neutral_edge,
        "keptPixelsBeforeComponents": kept_before_components,
        "keptComponents": component_record["keptComponents"],
        "removedComponents": component_record["removedComponents"],
        "bbox": list(bbox) if bbox else None,
        "outputSize": [cleaned.width, cleaned.height],
    }


def clean_frame_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    glob: str = "frame-*.png",
    options: CleanFrameOptions = CleanFrameOptions(),
) -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    metadata: list[dict[str, object]] = []
    for frame in frames:
        cleaned, record = clean_frame(Image.open(frame), options)
        out = out_dir / frame.name
        cleaned.save(out)
        outputs.append(out)
        metadata.append({"input": str(frame), "output": str(out), **record})

    (out_dir / "clean-frame-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs


def _has_transparent_neighbor(alpha, x: int, y: int, width: int, height: int, radius: int) -> bool:
    for ny in range(max(0, y - radius), min(height, y + radius + 1)):
        for nx in range(max(0, x - radius), min(width, x + radius + 1)):
            if nx == x and ny == y:
                continue
            if alpha[nx, ny] == 0:
                return True
    return False


def _keep_components(image: Image.Image, *, min_area: int) -> tuple[Image.Image, dict[str, int]]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    px = rgba.load()
    seen: set[tuple[int, int]] = set()
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()
    kept_components = 0
    removed_components = 0

    for y in range(height):
        for x in range(width):
            if (x, y) in seen or px[x, y][3] == 0:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            points: list[tuple[int, int]] = []
            while queue:
                cx, cy = queue.popleft()
                points.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen and px[nx, ny][3] > 0:
                        seen.add((nx, ny))
                        queue.append((nx, ny))

            if len(points) >= min_area:
                kept_components += 1
                for nx, ny in points:
                    r, g, b, _a = px[nx, ny]
                    out_px[nx, ny] = (r, g, b, 255)
            else:
                removed_components += 1

    return out, {"keptComponents": kept_components, "removedComponents": removed_components}
