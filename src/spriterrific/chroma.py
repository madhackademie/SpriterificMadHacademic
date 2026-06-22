from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


HIGH_GREEN_FRINGE_REMOVAL_RATIO = 0.02


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((a[index] - b[index]) ** 2 for index in range(3)) ** 0.5


def is_green_screen_pixel(
    pixel: tuple[int, int, int, int],
    *,
    min_green: int = 120,
    dominance: int = 35,
) -> bool:
    red, green, blue, alpha = pixel
    if alpha == 0:
        return False
    return green >= min_green and green - max(red, blue) >= dominance


def keep_largest_components(image: Image.Image, min_area: int) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    width, height = rgba.size
    px = rgba.load()
    seen: set[tuple[int, int]] = set()
    components: list[list[tuple[int, int]]] = []

    for y in range(height):
        for x in range(width):
            if (x, y) in seen or alpha.getpixel((x, y)) == 0:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            points: list[tuple[int, int]] = []
            while queue:
                cx, cy = queue.popleft()
                points.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen and alpha.getpixel((nx, ny)) > 0:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            components.append(points)

    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()
    for component in components:
        if len(component) >= min_area:
            for x, y in component:
                out_px[x, y] = px[x, y]
    return out


def has_transparent_neighbor(alpha, x: int, y: int, width: int, height: int, *, radius: int = 1) -> bool:
    for ny in range(max(0, y - radius), min(height, y + radius + 1)):
        for nx in range(max(0, x - radius), min(width, x + radius + 1)):
            if nx == x and ny == y:
                continue
            if alpha[nx, ny] == 0:
                return True
    return False


def background_reachable_transparency(alpha, width: int, height: int) -> bytearray:
    reachable = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        index = y * width + x
        if reachable[index] or alpha[x, y] != 0:
            return
        reachable[index] = 1
        queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= nx < width and 0 <= ny < height:
                enqueue(nx, ny)
    return reachable


def has_background_transparent_neighbor(
    reachable_alpha: bytearray,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    radius: int = 1,
) -> bool:
    for ny in range(max(0, y - radius), min(height, y + radius + 1)):
        for nx in range(max(0, x - radius), min(width, x + radius + 1)):
            if nx == x and ny == y:
                continue
            if reachable_alpha[ny * width + nx]:
                return True
    return False


def is_green_matte_rgb(rgb: tuple[int, int, int]) -> bool:
    """Return True when the matte color is strongly green-dominant (legacy green path)."""
    red, green, blue = rgb
    return green >= 180 and green - max(red, blue) >= 80


def chroma_fringe_channels(chroma_rgb: tuple[int, int, int]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Split RGB channel indices into matte-dominant and matte-suppressed groups.

    Raises ValueError when the matte color cannot be split (e.g. gray or white),
    because fringe detection needs at least one high and one low channel.
    """
    dominant = tuple(index for index in range(3) if chroma_rgb[index] >= 128)
    suppressed = tuple(index for index in range(3) if chroma_rgb[index] < 128)
    if not dominant or not suppressed:
        raise ValueError(
            f"chroma {chroma_rgb} cannot be split into dominant/suppressed channels; "
            "fringe cleanup needs a saturated matte color such as #00FF00 or #FF00FF"
        )
    return dominant, suppressed


def is_keyable_fringe_chroma(chroma_rgb: tuple[int, int, int]) -> bool:
    """Return True when the matte color is saturated enough for fringe cleanup."""
    try:
        dominant, suppressed = chroma_fringe_channels(chroma_rgb)
    except ValueError:
        return False
    low = min(chroma_rgb[index] for index in dominant)
    high = max(chroma_rgb[index] for index in suppressed)
    return low >= 180 and low - high >= 80


def green_fringe_warning(removed: int, kept: int) -> str | None:
    total = removed + kept
    if total <= 0:
        return None
    ratio = removed / total
    if ratio >= HIGH_GREEN_FRINGE_REMOVAL_RATIO:
        return (
            "high green-fringe removal ratio; green foreground details may have been removed. "
            "Use a non-green matte such as #FF00FF or pass --no-green-fringe-cleanup."
        )
    return None


def fringe_warning(removed: int, kept: int, *, chroma_rgb: tuple[int, int, int]) -> str | None:
    """Return a warning when fringe cleanup removed a suspiciously large share of pixels."""
    if is_green_matte_rgb(chroma_rgb):
        return green_fringe_warning(removed, kept)
    total = removed + kept
    if total <= 0:
        return None
    if removed / total >= HIGH_GREEN_FRINGE_REMOVAL_RATIO:
        return (
            "high fringe removal ratio; foreground details close to the matte color may have "
            "been removed. Use a matte color absent from the sprite or pass --no-green-fringe-cleanup."
        )
    return None


def remove_chroma_fringe(
    image: Image.Image,
    *,
    chroma_rgb: tuple[int, int, int] = (0, 255, 0),
    min_level: int = 70,
    dominance: int = 24,
    edge_radius: int = 1,
) -> tuple[Image.Image, dict[str, object]]:
    """Remove matte-tinted fringe pixels that touch background-reachable transparency.

    A pixel is treated as fringe when every matte-dominant channel is at least
    ``min_level`` and exceeds every matte-suppressed channel by ``dominance``.
    For a green matte this reduces exactly to the legacy green-fringe test.
    """
    dominant, suppressed = chroma_fringe_channels(chroma_rgb)
    rgba = image.convert("RGBA")
    width, height = rgba.size
    px = rgba.load()
    alpha = rgba.getchannel("A").load()
    reachable_alpha = background_reachable_transparency(alpha, width, height)
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()
    removed = 0
    kept = 0
    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            rgb = (r, g, b)
            low = min(rgb[index] for index in dominant)
            high = max(rgb[index] for index in suppressed)
            if (
                has_background_transparent_neighbor(reachable_alpha, x, y, width, height, radius=edge_radius)
                and low >= min_level
                and low - high >= dominance
            ):
                removed += 1
                continue
            out_px[x, y] = (r, g, b, a)
            kept += 1
    bbox = out.getchannel("A").getbbox()
    warning = fringe_warning(removed, kept, chroma_rgb=chroma_rgb)
    return out, {
        "chromaRgb": list(chroma_rgb),
        "removedFringePixels": removed,
        "keptPixels": kept,
        "removedToKeptRatio": removed / max(1, kept),
        "minLevel": min_level,
        "dominance": dominance,
        "edgeRadius": edge_radius,
        "bbox": list(bbox) if bbox else None,
        "warning": warning,
    }


def remove_green_fringe(
    image: Image.Image,
    *,
    min_green: int = 70,
    dominance: int = 24,
    edge_radius: int = 1,
) -> tuple[Image.Image, dict[str, object]]:
    """Green-matte wrapper around remove_chroma_fringe with legacy metadata keys."""
    cleaned, record = remove_chroma_fringe(
        image,
        chroma_rgb=(0, 255, 0),
        min_level=min_green,
        dominance=dominance,
        edge_radius=edge_radius,
    )
    return cleaned, {
        "removedGreenFringePixels": record["removedFringePixels"],
        "keptPixels": record["keptPixels"],
        "removedToKeptRatio": record["removedToKeptRatio"],
        "minGreen": min_green,
        "dominance": dominance,
        "edgeRadius": edge_radius,
        "bbox": record["bbox"],
        "warning": record["warning"],
    }


def remove_fringe(
    image: Image.Image,
    *,
    chroma_rgb: tuple[int, int, int],
    min_level: int = 70,
    dominance: int = 24,
    edge_radius: int = 1,
) -> tuple[Image.Image, dict[str, object]]:
    """Dispatch fringe cleanup for any keyable matte; green mattes keep legacy metadata keys."""
    if is_green_matte_rgb(chroma_rgb):
        return remove_green_fringe(image, min_green=min_level, dominance=dominance, edge_radius=edge_radius)
    return remove_chroma_fringe(
        image,
        chroma_rgb=chroma_rgb,
        min_level=min_level,
        dominance=dominance,
        edge_radius=edge_radius,
    )


def _near_transparent_mask(alpha: np.ndarray, radius: int) -> np.ndarray:
    """Return a boolean mask of pixels within `radius` (4-connected) of a transparent pixel."""
    near = alpha == 0
    for _ in range(max(0, radius)):
        grown = near.copy()
        grown[1:, :] |= near[:-1, :]
        grown[:-1, :] |= near[1:, :]
        grown[:, 1:] |= near[:, :-1]
        grown[:, :-1] |= near[:, 1:]
        near = grown
    return near


def despill_chroma(
    image: Image.Image,
    *,
    chroma_rgb: tuple[int, int, int],
    edge_radius: int = 2,
    band_only: bool = True,
) -> tuple[Image.Image, dict[str, object]]:
    """Neutralize matte-color spill by clamping matte-dominant channels toward the suppressed level.

    For a green matte this is the classic despill ``g = min(g, max(r, b))``. The
    generalized form clamps every matte-dominant channel down to the maximum of
    the matte-suppressed channels, which removes the matte tint without deleting
    pixels or altering geometry. When ``band_only`` is set, only opaque pixels
    within ``edge_radius`` of a transparent pixel are touched, so interior
    matte-colored detail is left intact.
    """
    dominant, suppressed = chroma_fringe_channels(chroma_rgb)
    rgba = image.convert("RGBA")
    arr = np.asarray(rgba).astype(np.int16)
    rgb = arr[..., :3]
    alpha = arr[..., 3]

    high = rgb[..., list(suppressed)].max(axis=2)
    foreground = alpha > 0
    region = foreground
    if band_only:
        region = foreground & _near_transparent_mask(alpha, edge_radius)

    new_rgb = rgb.copy()
    for channel in dominant:
        clamped = np.minimum(rgb[..., channel], high)
        new_rgb[..., channel] = np.where(region, clamped, rgb[..., channel])

    changed = region & (new_rgb != rgb).any(axis=2)
    spill_removed = int((rgb - new_rgb)[changed].sum()) if changed.any() else 0

    out_arr = arr.copy()
    out_arr[..., :3] = new_rgb
    out = Image.fromarray(out_arr.astype(np.uint8), "RGBA")
    return out, {
        "chromaRgb": list(chroma_rgb),
        "edgeRadius": edge_radius,
        "bandOnly": band_only,
        "despilledPixels": int(changed.sum()),
        "spillRemoved": spill_removed,
    }


def despill_chroma_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    chroma_rgb: tuple[int, int, int],
    glob: str = "frame-*.png",
    edge_radius: int = 2,
    band_only: bool = True,
) -> list[Path]:
    """Despill every frame in a directory (in place when out_dir == input_dir) and write metadata."""
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    in_place = out_dir.resolve() == input_dir.resolve()
    if not in_place:
        for old in out_dir.glob("frame-*.png"):
            old.unlink()

    outputs: list[Path] = []
    metadata: list[dict[str, object]] = []
    for frame in frames:
        cleaned, record = despill_chroma(
            Image.open(frame),
            chroma_rgb=chroma_rgb,
            edge_radius=edge_radius,
            band_only=band_only,
        )
        out = out_dir / frame.name
        cleaned.save(out)
        outputs.append(out)
        metadata.append({"input": str(frame), "output": str(out), **record})

    (out_dir / "despill-metadata.json").write_text(
        json.dumps(
            {
                "chromaRgb": list(chroma_rgb),
                "edgeRadius": edge_radius,
                "bandOnly": band_only,
                "frames": metadata,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return outputs


def remove_green_fringe_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    glob: str = "frame-*.png",
    min_green: int = 70,
    dominance: int = 24,
    edge_radius: int = 1,
    min_component_area: int = 8,
) -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    metadata: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    for frame in frames:
        cleaned, record = remove_green_fringe(
            Image.open(frame),
            min_green=min_green,
            dominance=dominance,
            edge_radius=edge_radius,
        )
        cleaned = keep_largest_components(cleaned, min_component_area)
        out = out_dir / frame.name
        cleaned.save(out)
        outputs.append(out)
        metadata.append({"input": str(frame), "output": str(out), **record})
        if record.get("warning"):
            warnings.append(
                {
                    "frame": frame.name,
                    "warning": record["warning"],
                    "removedGreenFringePixels": record["removedGreenFringePixels"],
                    "keptPixels": record["keptPixels"],
                    "removedToKeptRatio": record["removedToKeptRatio"],
                }
            )

    (out_dir / "green-fringe-metadata.json").write_text(
        json.dumps(
            {
                "minGreen": min_green,
                "dominance": dominance,
                "edgeRadius": edge_radius,
                "minComponentArea": min_component_area,
                "highRemovalRatioThreshold": HIGH_GREEN_FRINGE_REMOVAL_RATIO,
                "warnings": warnings,
                "frames": metadata,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return outputs


def remove_chroma_fringe_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    chroma_rgb: tuple[int, int, int],
    glob: str = "frame-*.png",
    min_level: int = 70,
    dominance: int = 24,
    edge_radius: int = 1,
    min_component_area: int = 8,
) -> list[Path]:
    """Run chroma-aware fringe cleanup over a frame directory and write fringe-metadata.json."""
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    metadata: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    for frame in frames:
        cleaned, record = remove_chroma_fringe(
            Image.open(frame),
            chroma_rgb=chroma_rgb,
            min_level=min_level,
            dominance=dominance,
            edge_radius=edge_radius,
        )
        cleaned = keep_largest_components(cleaned, min_component_area)
        out = out_dir / frame.name
        cleaned.save(out)
        outputs.append(out)
        metadata.append({"input": str(frame), "output": str(out), **record})
        if record.get("warning"):
            warnings.append(
                {
                    "frame": frame.name,
                    "warning": record["warning"],
                    "removedFringePixels": record["removedFringePixels"],
                    "keptPixels": record["keptPixels"],
                    "removedToKeptRatio": record["removedToKeptRatio"],
                }
            )

    (out_dir / "fringe-metadata.json").write_text(
        json.dumps(
            {
                "chromaRgb": list(chroma_rgb),
                "minLevel": min_level,
                "dominance": dominance,
                "edgeRadius": edge_radius,
                "minComponentArea": min_component_area,
                "highRemovalRatioThreshold": HIGH_GREEN_FRINGE_REMOVAL_RATIO,
                "warnings": warnings,
                "frames": metadata,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return outputs


def remove_fringe_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    chroma_rgb: tuple[int, int, int],
    glob: str = "frame-*.png",
    min_level: int = 70,
    dominance: int = 24,
    edge_radius: int = 1,
    min_component_area: int = 8,
) -> tuple[list[Path], Path]:
    """Dispatch batch fringe cleanup for any keyable matte and return (outputs, metadata path).

    Green mattes go through the legacy green batch so existing filenames and
    metadata keys stay stable; other keyable mattes use the chroma-aware batch.
    """
    if is_green_matte_rgb(chroma_rgb):
        outputs = remove_green_fringe_batch(
            input_dir,
            out_dir,
            glob=glob,
            min_green=min_level,
            dominance=dominance,
            edge_radius=edge_radius,
            min_component_area=min_component_area,
        )
        return outputs, out_dir / "green-fringe-metadata.json"
    outputs = remove_chroma_fringe_batch(
        input_dir,
        out_dir,
        chroma_rgb=chroma_rgb,
        glob=glob,
        min_level=min_level,
        dominance=dominance,
        edge_radius=edge_radius,
        min_component_area=min_component_area,
    )
    return outputs, out_dir / "fringe-metadata.json"


def remove_chroma(
    image: Image.Image,
    *,
    chroma_rgb: tuple[int, int, int] = (0, 255, 0),
    threshold: float = 90.0,
    min_component_area: int = 80,
) -> tuple[Image.Image, dict[str, object]]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    px = rgba.load()
    removed = 0
    kept = 0
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()

    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if color_distance((r, g, b), chroma_rgb) <= threshold:
                removed += 1
            else:
                out_px[x, y] = (r, g, b, a)
                kept += 1

    cleaned = keep_largest_components(out, min_component_area)
    bbox = cleaned.getchannel("A").getbbox()
    return cleaned, {
        "chromaRgb": list(chroma_rgb),
        "threshold": threshold,
        "minComponentArea": min_component_area,
        "removedPixels": removed,
        "keptPixelsBeforeDespeckle": kept,
        "bbox": list(bbox) if bbox else None,
    }


def remove_chroma_or_corner_background(
    image: Image.Image,
    *,
    chroma_rgb: tuple[int, int, int] = (0, 255, 0),
    threshold: float = 90.0,
    corner_threshold: float = 30.0,
    min_component_area: int = 80,
) -> tuple[Image.Image, dict[str, object]]:
    keyed, chroma_record = remove_chroma(
        image,
        chroma_rgb=chroma_rgb,
        threshold=threshold,
        min_component_area=min_component_area,
    )
    bbox = keyed.getchannel("A").getbbox()
    if bbox is not None and bbox != (0, 0, keyed.width, keyed.height):
        return keyed, {"method": "chroma", **chroma_record}

    cleaned, corner_record = remove_corner_connected_background(
        image,
        threshold=corner_threshold,
        min_component_area=min_component_area,
    )
    return cleaned, {
        "method": "corner-connected-background",
        "chromaAttempt": chroma_record,
        **corner_record,
    }


def remove_corner_connected_background(
    image: Image.Image,
    *,
    threshold: float = 30.0,
    min_component_area: int = 80,
) -> tuple[Image.Image, dict[str, object]]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    px = rgba.load()
    corners = [
        px[0, 0][:3],
        px[width - 1, 0][:3],
        px[0, height - 1][:3],
        px[width - 1, height - 1][:3],
    ]
    bg = tuple(round(sum(c[index] for c in corners) / len(corners)) for index in range(3))
    background: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()
    for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        x, y = point
        r, g, b, a = px[x, y]
        if a and color_distance((r, g, b), bg) <= threshold:
            background.add(point)
            queue.append(point)

    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in background:
                continue
            r, g, b, a = px[nx, ny]
            if a and color_distance((r, g, b), bg) <= threshold:
                background.add((nx, ny))
                queue.append((nx, ny))

    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()
    kept = 0
    for y in range(height):
        for x in range(width):
            if (x, y) in background:
                continue
            r, g, b, a = px[x, y]
            if a:
                out_px[x, y] = (r, g, b, a)
                kept += 1

    cleaned = keep_largest_components(out, min_component_area)
    bbox = cleaned.getchannel("A").getbbox()
    return cleaned, {
        "cornerBackgroundRgb": list(bg),
        "cornerThreshold": threshold,
        "minComponentArea": min_component_area,
        "removedPixels": len(background),
        "keptPixelsBeforeDespeckle": kept,
        "bbox": list(bbox) if bbox else None,
    }


def remove_green_screen(
    image: Image.Image,
    *,
    min_green: int = 120,
    dominance: int = 35,
    min_component_area: int = 4,
) -> tuple[Image.Image, dict[str, object]]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    px = rgba.load()
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()
    removed = 0
    kept = 0
    hidden_transparent_cleared = 0

    for y in range(height):
        for x in range(width):
            pixel = px[x, y]
            if pixel[3] == 0:
                if pixel[:3] != (0, 0, 0):
                    hidden_transparent_cleared += 1
                continue
            if is_green_screen_pixel(pixel, min_green=min_green, dominance=dominance):
                removed += 1
                continue
            out_px[x, y] = pixel
            kept += 1

    cleaned = keep_largest_components(out, min_component_area)
    bbox = cleaned.getchannel("A").getbbox()
    return cleaned, {
        "method": "green-screen",
        "minGreen": min_green,
        "dominance": dominance,
        "minComponentArea": min_component_area,
        "removedPixels": removed,
        "keptPixelsBeforeDespeckle": kept,
        "hiddenTransparentPixelsCleared": hidden_transparent_cleared,
        "bbox": list(bbox) if bbox else None,
    }


def remove_green_screen_or_corner_background(
    image: Image.Image,
    *,
    min_green: int = 120,
    dominance: int = 35,
    corner_threshold: float = 30.0,
    min_component_area: int = 4,
) -> tuple[Image.Image, dict[str, object]]:
    keyed, green_record = remove_green_screen(
        image,
        min_green=min_green,
        dominance=dominance,
        min_component_area=min_component_area,
    )
    bbox = keyed.getchannel("A").getbbox()
    if bbox is not None and bbox != (0, 0, keyed.width, keyed.height):
        return keyed, green_record

    cleaned, corner_record = remove_corner_connected_background(
        image,
        threshold=corner_threshold,
        min_component_area=min_component_area,
    )
    return cleaned, {
        "method": "corner-connected-background",
        "greenScreenAttempt": green_record,
        **corner_record,
    }


def remove_green_screen_or_corner_background_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    glob: str = "frame-*.png",
    min_green: int = 120,
    dominance: int = 35,
    corner_threshold: float = 30.0,
    min_component_area: int = 4,
) -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    metadata = []
    for frame in frames:
        cleaned, record = remove_green_screen_or_corner_background(
            Image.open(frame),
            min_green=min_green,
            dominance=dominance,
            corner_threshold=corner_threshold,
            min_component_area=min_component_area,
        )
        out = out_dir / frame.name
        cleaned.save(out)
        outputs.append(out)
        metadata.append({"input": str(frame), "output": str(out), **record})

    (out_dir / "video-background-key-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs


def remove_chroma_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    glob: str = "frame-*.png",
    chroma_rgb: tuple[int, int, int] = (0, 255, 0),
    threshold: float = 90.0,
    min_component_area: int = 80,
) -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    metadata = []
    for frame in frames:
        cleaned, record = remove_chroma(
            Image.open(frame),
            chroma_rgb=chroma_rgb,
            threshold=threshold,
            min_component_area=min_component_area,
        )
        out = out_dir / frame.name
        cleaned.save(out)
        outputs.append(out)
        metadata.append({"input": str(frame), "output": str(out), **record})

    (out_dir / "chroma-key-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs


def remove_chroma_or_corner_background_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    glob: str = "frame-*.png",
    chroma_rgb: tuple[int, int, int] = (0, 255, 0),
    threshold: float = 90.0,
    corner_threshold: float = 30.0,
    min_component_area: int = 80,
) -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    metadata = []
    for frame in frames:
        cleaned, record = remove_chroma_or_corner_background(
            Image.open(frame),
            chroma_rgb=chroma_rgb,
            threshold=threshold,
            corner_threshold=corner_threshold,
            min_component_area=min_component_area,
        )
        out = out_dir / frame.name
        cleaned.save(out)
        outputs.append(out)
        metadata.append({"input": str(frame), "output": str(out), **record})

    (out_dir / "background-key-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs


def _collect_chroma_components(
    alpha: Image.Image,
    *,
    min_component_area: int,
    region: tuple[int, int, int, int] | None = None,
) -> list[dict[str, object]]:
    """Flood-fill non-transparent connected components in an alpha channel.

    When ``region`` is provided as ``(x0, y0, x1, y1)``, detection is confined to
    that rectangle so figures bleeding across the region edge are split there.
    Returns components with ``area``, ``bbox``, ``center``, and ``points`` keys.
    """
    width, height = alpha.size
    x_start, y_start, x_end, y_end = region or (0, 0, width, height)
    x_start = max(0, x_start)
    y_start = max(0, y_start)
    x_end = min(width, x_end)
    y_end = min(height, y_end)
    seen: set[tuple[int, int]] = set()
    components: list[dict[str, object]] = []

    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            if (x, y) in seen or alpha.getpixel((x, y)) == 0:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            points: list[tuple[int, int]] = []
            min_x = max_x = x
            min_y = max_y = y
            while queue:
                cx, cy = queue.popleft()
                points.append((cx, cy))
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if x_start <= nx < x_end and y_start <= ny < y_end and (nx, ny) not in seen and alpha.getpixel((nx, ny)) > 0:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(points) >= min_component_area:
                components.append(
                    {
                        "area": len(points),
                        "bbox": [min_x, min_y, max_x + 1, max_y + 1],
                        "center": [(min_x + max_x + 1) / 2, (min_y + max_y + 1) / 2],
                        "points": points,
                    }
                )

    return components


def _collect_grid_cell_components(
    alpha: Image.Image,
    *,
    rows: int,
    cols: int,
    min_component_area: int,
) -> list[dict[str, object]]:
    """Recover one foreground component per filled grid cell.

    Splits the sheet into ``rows`` x ``cols`` cells and keeps the largest
    qualifying component inside each non-empty cell. This is the robust fallback
    when whole-sheet detection merges touching neighbors; cells without a
    qualifying figure (blank pose-board slots) are skipped.
    """
    width, height = alpha.size
    cell_w = width / cols
    cell_h = height / rows
    cell_components: list[dict[str, object]] = []
    for row in range(rows):
        for col in range(cols):
            region = (
                int(round(col * cell_w)),
                int(round(row * cell_h)),
                int(round((col + 1) * cell_w)),
                int(round((row + 1) * cell_h)),
            )
            found = _collect_chroma_components(alpha, min_component_area=min_component_area, region=region)
            if not found:
                continue
            found.sort(key=lambda item: int(item["area"]), reverse=True)
            cell_components.append(found[0])
    return cell_components


def recover_chroma_components_from_sheet(
    sheet: Path,
    out_dir: Path,
    *,
    rows: int,
    cols: int,
    count: int | None = None,
    prefix: str = "frame",
    min_component_area: int = 500,
) -> list[Path]:
    keyed, key_meta = remove_chroma(Image.open(sheet), min_component_area=min_component_area)
    width, height = keyed.size
    alpha = keyed.getchannel("A")
    components = _collect_chroma_components(alpha, min_component_area=min_component_area)

    wanted = count or rows * cols
    if len(components) < wanted:
        # Whole-sheet connected components can merge when posed characters in
        # neighboring grid cells touch, yielding fewer blobs than frames. Fall
        # back to per-cell detection: the grid boundaries separate touching
        # neighbors and empty cells are skipped, so each filled cell maps to one
        # frame regardless of how the pose board distributed the figures.
        cell_components = _collect_grid_cell_components(
            alpha,
            rows=rows,
            cols=cols,
            min_component_area=min_component_area,
        )
        if len(cell_components) >= wanted:
            components = cell_components
        else:
            raise ValueError(
                f"expected at least {wanted} chroma components, found {len(components)} "
                f"(per-cell fallback found {len(cell_components)})"
            )

    components.sort(key=lambda item: int(item["area"]), reverse=True)
    selected = components[:wanted]
    selected = order_components_by_grid(selected, rows=rows, cols=cols, sheet_size=(width, height))

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{prefix}-*.png"):
        old.unlink()

    outputs: list[Path] = []
    metadata = {
        "sheet": str(sheet),
        "rows": rows,
        "cols": cols,
        "count": wanted,
        "keying": key_meta,
        "frames": [],
    }
    for index, component in enumerate(selected, start=1):
        x0, y0, x1, y1 = component["bbox"]  # type: ignore[misc]
        crop = keyed.crop((x0, y0, x1, y1))
        out = out_dir / f"{prefix}-{index:02d}.png"
        crop.save(out)
        outputs.append(out)
        metadata["frames"].append(
            {
                "frame": f"{index:02d}",
                "bbox": [x0, y0, x1, y1],
                "area": component["area"],
                "center": component["center"],
                "path": str(out),
            }
        )

    (out_dir / f"{prefix}-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs


def order_components_by_grid(
    components: list[dict[str, object]],
    *,
    rows: int,
    cols: int | None = None,
    sheet_size: tuple[int, int] | None = None,
) -> list[dict[str, object]]:
    if rows <= 1:
        return sorted(components, key=lambda item: float(item["center"][0]))  # type: ignore[index]

    if cols is not None and sheet_size is not None:
        width, height = sheet_size
        cell_w = width / cols
        cell_h = height / rows
        return sorted(
            components,
            key=lambda item: (
                min(rows - 1, max(0, int(float(item["center"][1]) // cell_h))),  # type: ignore[index]
                min(cols - 1, max(0, int(float(item["center"][0]) // cell_w))),  # type: ignore[index]
                float(item["center"][0]),  # type: ignore[index]
            ),
        )

    by_y = sorted(components, key=lambda item: float(item["center"][1]))  # type: ignore[index]
    row_size = max(1, len(components) // rows)
    ordered: list[dict[str, object]] = []
    for start in range(0, len(by_y), row_size):
        row = by_y[start : start + row_size]
        ordered.extend(sorted(row, key=lambda item: float(item["center"][0])))  # type: ignore[index]
    return ordered
