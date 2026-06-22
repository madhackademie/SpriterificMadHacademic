#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy>=1.26",
#   "pillow>=10.0",
# ]
# ///
"""Python port of Hugo-Dz/spritefusion-pixel-snapper.

Recovers the underlying low-resolution pixel-art grid from an upscaled or
AI-generated image. Pipeline:

  1. K-means quantize the palette.
  2. Compute 1D edge-gradient profiles along x and y.
  3. Estimate the cell pitch as the median peak spacing per axis.
  4. Walk along each axis placing cuts that snap to nearby edge peaks.
  5. Resample: one output pixel per cell, picking the majority color.

Usage:
  uv run scripts/pixel_snapper.py input.png output.png [--k-colors 256]
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Config:
    k_colors: int = 16
    k_seed: int = 42
    max_kmeans_iterations: int = 15
    peak_threshold_multiplier: float = 0.2
    peak_distance_filter: int = 4
    walker_search_window_ratio: float = 0.35
    walker_min_search_window: float = 2.0
    walker_strength_threshold: float = 0.5
    min_cuts_per_axis: int = 4
    fallback_target_segments: int = 64
    max_step_ratio: float = 1.8


@dataclass(frozen=True)
class PixelGrid:
    source_width: int
    source_height: int
    col_cuts: tuple[int, ...]
    row_cuts: tuple[int, ...]
    estimated_step_x: float | None
    estimated_step_y: float | None
    resolved_step_x: float
    resolved_step_y: float

    @property
    def output_size(self) -> tuple[int, int]:
        return (len(self.col_cuts) - 1, len(self.row_cuts) - 1)


def grid_to_dict(grid: PixelGrid) -> dict[str, object]:
    return {
        "sourceSize": [grid.source_width, grid.source_height],
        "outputSize": list(grid.output_size),
        "estimatedStepX": grid.estimated_step_x,
        "estimatedStepY": grid.estimated_step_y,
        "resolvedStepX": grid.resolved_step_x,
        "resolvedStepY": grid.resolved_step_y,
        "colCuts": list(grid.col_cuts),
        "rowCuts": list(grid.row_cuts),
    }


def grid_from_dict(data: dict[str, object]) -> PixelGrid:
    source_size = data.get("sourceSize")
    if not isinstance(source_size, list) or len(source_size) != 2:
        raise ValueError("grid sourceSize must be [width, height]")
    col_cuts = data.get("colCuts")
    row_cuts = data.get("rowCuts")
    if not isinstance(col_cuts, list) or not isinstance(row_cuts, list):
        raise ValueError("grid colCuts and rowCuts must be lists")
    return PixelGrid(
        source_width=int(source_size[0]),
        source_height=int(source_size[1]),
        col_cuts=tuple(int(value) for value in col_cuts),
        row_cuts=tuple(int(value) for value in row_cuts),
        estimated_step_x=_optional_float(data.get("estimatedStepX")),
        estimated_step_y=_optional_float(data.get("estimatedStepY")),
        resolved_step_x=float(data.get("resolvedStepX", 1.0)),
        resolved_step_y=float(data.get("resolvedStepY", 1.0)),
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def quantize(rgba: np.ndarray, cfg: Config) -> np.ndarray:
    """K-means over opaque pixels, returns quantized RGBA."""
    h, w, _ = rgba.shape
    rgb = rgba[..., :3].astype(np.float32)
    alpha = rgba[..., 3]
    opaque_mask = alpha > 0
    opaque_pixels = rgb[opaque_mask]
    if opaque_pixels.size == 0:
        return rgba.copy()

    k = min(cfg.k_colors, len(opaque_pixels))
    rng = np.random.default_rng(cfg.k_seed)

    centers = np.empty((k, 3), dtype=np.float32)
    first_idx = int(rng.integers(0, len(opaque_pixels)))
    centers[0] = opaque_pixels[first_idx]
    distances = np.full(len(opaque_pixels), np.finfo(np.float32).max, dtype=np.float32)
    for i in range(1, k):
        last_center = centers[i - 1]
        dists = np.sum((opaque_pixels - last_center) ** 2, axis=1)
        distances = np.minimum(distances, dists)
        total = float(distances.sum())
        if total <= 0.0 or not np.isfinite(total):
            idx = int(rng.integers(0, len(opaque_pixels)))
        else:
            idx = int(rng.choice(len(opaque_pixels), p=distances / total))
        centers[i] = opaque_pixels[idx]

    prev_centers = centers.copy()
    labels = np.zeros(len(opaque_pixels), dtype=np.intp)
    for iteration in range(cfg.max_kmeans_iterations):
        dists = np.sum((opaque_pixels[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        labels = np.argmin(dists, axis=1)
        new_centers = np.empty_like(centers)
        for i in range(k):
            members = opaque_pixels[labels == i]
            if len(members) == 0:
                new_centers[i] = centers[i]
            else:
                new_centers[i] = members.mean(axis=0)
        centers = new_centers
        if iteration > 0:
            movement = np.sum((centers - prev_centers) ** 2, axis=1).max()
            if movement < 0.01:
                break
        prev_centers = centers.copy()

    if len(opaque_pixels):
        dists = np.sum((opaque_pixels[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        labels = np.argmin(dists, axis=1)
    else:
        labels = np.array([], dtype=np.intp)

    quantized = rgba.copy()
    quantized_rgb = quantized[..., :3]
    flat_quantized_rgb = quantized_rgb.reshape(-1, 3)
    flat_alpha = alpha.reshape(-1)
    flat_opaque_mask = flat_alpha > 0
    opaque_quant = np.clip(np.rint(centers[labels]), 0, 255).astype(np.uint8)
    flat_quantized_rgb[flat_opaque_mask] = opaque_quant
    return quantized


def compute_profiles(rgba: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-column and per-row edge-gradient sums, weighting transparent pixels as 0."""
    rgb = rgba[..., :3].astype(np.float64)
    alpha = rgba[..., 3]
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    luma[alpha == 0] = 0.0

    h, w = luma.shape
    if w < 3 or h < 3:
        raise ValueError("Image too small (minimum 3x3)")

    col_grad = np.abs(luma[:, 2:] - luma[:, :-2])
    col_proj = np.zeros(w, dtype=np.float64)
    col_proj[1:-1] = col_grad.sum(axis=0)

    row_grad = np.abs(luma[2:, :] - luma[:-2, :])
    row_proj = np.zeros(h, dtype=np.float64)
    row_proj[1:-1] = row_grad.sum(axis=1)

    return col_proj, row_proj


def estimate_step_size(profile: np.ndarray, cfg: Config) -> float | None:
    if profile.size == 0:
        return None
    max_val = float(profile.max())
    if max_val == 0.0:
        return None
    threshold = max_val * cfg.peak_threshold_multiplier

    peaks: list[int] = []
    for i in range(1, len(profile) - 1):
        v = profile[i]
        if v > threshold and v > profile[i - 1] and v > profile[i + 1]:
            peaks.append(i)
    if len(peaks) < 2:
        return None

    clean = [peaks[0]]
    for p in peaks[1:]:
        if p - clean[-1] > (cfg.peak_distance_filter - 1):
            clean.append(p)
    if len(clean) < 2:
        return None

    diffs = np.sort(np.diff(clean))
    return float(diffs[len(diffs) // 2])


def resolve_step_sizes(
    sx: float | None, sy: float | None, w: int, h: int, cfg: Config
) -> tuple[float, float]:
    if sx is not None and sy is not None:
        ratio = max(sx, sy) / min(sx, sy)
        if ratio > cfg.max_step_ratio:
            smaller = min(sx, sy)
            return smaller, smaller
        avg = (sx + sy) / 2.0
        return avg, avg
    if sx is not None:
        return sx, sx
    if sy is not None:
        return sy, sy
    fallback = max(min(w, h) / cfg.fallback_target_segments, 1.0)
    return fallback, fallback


def stabilize_both_axes(
    profile_x: np.ndarray,
    profile_y: np.ndarray,
    raw_col_cuts: list[int],
    raw_row_cuts: list[int],
    width: int,
    height: int,
    cfg: Config,
) -> tuple[list[int], list[int]]:
    col_cuts_pass1 = stabilize_cuts(profile_x, raw_col_cuts.copy(), width, raw_row_cuts, height, cfg)
    row_cuts_pass1 = stabilize_cuts(profile_y, raw_row_cuts.copy(), height, raw_col_cuts, width, cfg)

    col_cells = max(len(col_cuts_pass1) - 1, 1)
    row_cells = max(len(row_cuts_pass1) - 1, 1)
    col_step = width / col_cells
    row_step = height / row_cells
    step_ratio = max(col_step, row_step) / min(col_step, row_step)
    if step_ratio <= cfg.max_step_ratio:
        return col_cuts_pass1, row_cuts_pass1

    target_step = min(col_step, row_step)
    final_col_cuts = (
        snap_uniform_cuts(profile_x, width, target_step, cfg, cfg.min_cuts_per_axis)
        if col_step > target_step * 1.2
        else col_cuts_pass1
    )
    final_row_cuts = (
        snap_uniform_cuts(profile_y, height, target_step, cfg, cfg.min_cuts_per_axis)
        if row_step > target_step * 1.2
        else row_cuts_pass1
    )
    return final_col_cuts, final_row_cuts


def stabilize_cuts(
    profile: np.ndarray,
    cuts: list[int],
    limit: int,
    sibling_cuts: list[int],
    sibling_limit: int,
    cfg: Config,
) -> list[int]:
    if limit == 0:
        return [0]
    cuts = sanitize_cuts(cuts, limit)
    min_required = min(max(cfg.min_cuts_per_axis, 2), limit + 1)
    axis_cells = max(len(cuts) - 1, 0)
    sibling_cells = max(len(sibling_cuts) - 1, 0)
    sibling_has_grid = sibling_limit > 0 and sibling_cells >= min_required - 1 and sibling_cells > 0
    steps_skewed = False
    if sibling_has_grid and axis_cells > 0:
        axis_step = limit / axis_cells
        sibling_step = sibling_limit / sibling_cells
        step_ratio = axis_step / sibling_step
        steps_skewed = step_ratio > cfg.max_step_ratio or step_ratio < 1.0 / cfg.max_step_ratio
    has_enough = len(cuts) >= min_required
    if has_enough and not steps_skewed:
        return cuts

    if sibling_has_grid:
        target_step = sibling_limit / sibling_cells
    elif cfg.fallback_target_segments > 1:
        target_step = limit / cfg.fallback_target_segments
    elif axis_cells > 0:
        target_step = limit / axis_cells
    else:
        target_step = float(limit)
    if not np.isfinite(target_step) or target_step <= 0.0:
        target_step = 1.0
    return snap_uniform_cuts(profile, limit, target_step, cfg, min_required)


def snap_uniform_cuts(profile: np.ndarray, limit: int, target_step: float, cfg: Config, min_required: int) -> list[int]:
    if limit == 0:
        return [0]
    if limit == 1:
        return [0, 1]
    desired_cells = round(limit / target_step) if np.isfinite(target_step) and target_step > 0.0 else 0
    desired_cells = min(max(desired_cells, min_required - 1, 1), limit)
    cell_width = limit / desired_cells
    search_window = max(cell_width * cfg.walker_search_window_ratio, cfg.walker_min_search_window)
    mean_val = float(profile.mean()) if profile.size else 0.0

    cuts: list[int] = [0]
    for idx in range(1, desired_cells):
        target = cell_width * idx
        prev = cuts[-1]
        if prev + 1 >= limit:
            break
        start = max(int(np.floor(target - search_window)), prev + 1, 0)
        end = min(int(np.ceil(target + search_window)), limit - 1)
        if end < start:
            start = prev + 1
            end = start
        best_idx = min(start, max(len(profile) - 1, 0))
        best_val = -1.0
        for candidate in range(start, min(end, len(profile) - 1) + 1):
            value = float(profile[candidate]) if 0 <= candidate < len(profile) else 0.0
            if value > best_val:
                best_val = value
                best_idx = candidate
        if best_val < mean_val * cfg.walker_strength_threshold:
            fallback_idx = round(target)
            if fallback_idx <= prev:
                fallback_idx = prev + 1
            if fallback_idx >= limit:
                fallback_idx = max(limit - 1, prev + 1)
            best_idx = fallback_idx
        cuts.append(best_idx)
    if cuts[-1] != limit:
        cuts.append(limit)
    return sanitize_cuts(cuts, limit)


def walk(profile: np.ndarray, step_size: float, limit: int, cfg: Config) -> list[int]:
    if profile.size == 0:
        raise ValueError("Empty profile")
    cuts: list[int] = [0]
    pos = 0.0
    window = max(step_size * cfg.walker_search_window_ratio, cfg.walker_min_search_window)
    mean_val = float(profile.mean())

    while pos < limit:
        target = pos + step_size
        if target >= limit:
            cuts.append(limit)
            break
        start = max(int(target - window), int(pos + 1.0))
        end = min(int(target + window), limit)
        if end <= start:
            pos = target
            continue
        segment = profile[start:end]
        local_max = float(segment.max())
        local_idx = int(start + np.argmax(segment))
        if local_max > mean_val * cfg.walker_strength_threshold:
            cuts.append(local_idx)
            pos = float(local_idx)
        else:
            cuts.append(int(target))
            pos = target
    return cuts


def sanitize_cuts(cuts: list[int], limit: int) -> list[int]:
    seen = sorted(set(c for c in cuts if 0 <= c <= limit))
    if not seen or seen[0] != 0:
        seen = [0] + seen
    if seen[-1] != limit:
        seen.append(limit)
    deduped: list[int] = []
    for c in seen:
        if not deduped or c > deduped[-1]:
            deduped.append(c)
    return deduped


def resample(rgba: np.ndarray, col_cuts: list[int], row_cuts: list[int]) -> np.ndarray:
    out_w = len(col_cuts) - 1
    out_h = len(row_cuts) - 1
    out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    for j in range(out_h):
        y0, y1 = row_cuts[j], row_cuts[j + 1]
        for i in range(out_w):
            x0, x1 = col_cuts[i], col_cuts[i + 1]
            cell = rgba[y0:y1, x0:x1].reshape(-1, 4)
            if cell.size == 0:
                continue
            opaque = cell[cell[:, 3] > 0]
            if len(opaque) == 0:
                out[j, i] = (0, 0, 0, 0)
                continue
            tuples = [tuple(p) for p in opaque]
            counts = Counter(tuples)
            most_common, _ = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
            out[j, i] = most_common
    return out


def discover_grid_from_array(rgba: np.ndarray, cfg: Config) -> PixelGrid:
    h, w, _ = rgba.shape
    quantized = quantize(rgba, cfg)
    col_proj, row_proj = compute_profiles(quantized)
    sx = estimate_step_size(col_proj, cfg)
    sy = estimate_step_size(row_proj, cfg)
    step_x, step_y = resolve_step_sizes(sx, sy, w, h, cfg)

    raw_col_cuts = walk(col_proj, step_x, w, cfg)
    raw_row_cuts = walk(row_proj, step_y, h, cfg)
    col_cuts, row_cuts = stabilize_both_axes(col_proj, row_proj, raw_col_cuts, raw_row_cuts, w, h, cfg)
    return PixelGrid(
        source_width=w,
        source_height=h,
        col_cuts=tuple(col_cuts),
        row_cuts=tuple(row_cuts),
        estimated_step_x=sx,
        estimated_step_y=sy,
        resolved_step_x=step_x,
        resolved_step_y=step_y,
    )


def discover_grid(input_path: Path, cfg: Config) -> PixelGrid:
    img = Image.open(input_path).convert("RGBA")
    return discover_grid_from_array(np.array(img), cfg)


def resample_with_grid(input_path: Path, output_path: Path, cfg: Config, grid: PixelGrid) -> tuple[int, int]:
    img = Image.open(input_path).convert("RGBA")
    if img.size != (grid.source_width, grid.source_height):
        raise ValueError(
            f"{input_path} must match locked grid source size "
            f"{grid.source_width}x{grid.source_height}, got {img.width}x{img.height}"
        )
    quantized = quantize(np.array(img), cfg)
    out = resample(quantized, list(grid.col_cuts), list(grid.row_cuts))
    Image.fromarray(out, mode="RGBA").save(output_path)
    return out.shape[1], out.shape[0]


def snap_image(input_path: Path, output_path: Path, cfg: Config) -> tuple[int, int]:
    img = Image.open(input_path).convert("RGBA")
    rgba = np.array(img)
    grid = discover_grid_from_array(rgba, cfg)
    quantized = quantize(rgba, cfg)
    out = resample(quantized, list(grid.col_cuts), list(grid.row_cuts))

    Image.fromarray(out, mode="RGBA").save(output_path)
    return out.shape[1], out.shape[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--k-colors", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = Config(k_colors=args.k_colors, k_seed=args.seed)
    out_w, out_h = snap_image(args.input, args.output, cfg)
    print(f"Snapped {args.input} -> {args.output} ({out_w}x{out_h})")


if __name__ == "__main__":
    main()
