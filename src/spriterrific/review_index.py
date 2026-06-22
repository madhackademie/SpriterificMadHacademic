from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .paths import RunPaths


@dataclass(frozen=True)
class ReviewAsset:
    title: str
    path: Path
    description: str
    embed: bool = True


def write_review_index(review_dir: Path, *, title: str, summary: str, assets: list[ReviewAsset], notes: list[str] | None = None) -> Path:
    review_dir.mkdir(parents=True, exist_ok=True)
    out = review_dir / "index.md"
    lines = [f"# {title}", "", summary.strip(), ""]
    if notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
        lines.append("")

    lines.extend(["## Review Assets", ""])
    for asset in assets:
        relative = _relative_link(asset.path, review_dir)
        lines.extend([f"### {asset.title}", "", asset.description.strip(), ""])
        if asset.embed:
            lines.extend([f"![{asset.title}]({relative})", ""])
        lines.extend([f"[Open file]({relative})", ""])

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def write_run_review_index(paths: RunPaths) -> Path:
    run = _read_json(paths.run_json)
    manifest = _read_json(paths.export_manifest)
    selection = _read_json(paths.selection_manifest)

    action = str(run.get("action", manifest.get("action", "unknown")))
    direction = str(run.get("direction", manifest.get("direction", "unknown")))
    mode = str(run.get("mode", manifest.get("mode", "unknown")))
    frame_count = str(run.get("frameCount", manifest.get("frames", "unknown")))
    fps = str(manifest.get("fps", "unknown"))
    generation_canvas = _format_list_size(run.get("imageGenerationCanvas"))
    generation_grid = _format_grid(run.get("imageGenerationGrid"))
    generation_cell = _format_list_size(run.get("imageGenerationCellSize"))
    title = f"{paths.run_id} Review"
    summary = (
        f"Quick review page for the `{direction}` facing `{action}` animation. "
        f"Mode: `{mode}`. Frames: `{frame_count}`. FPS: `{fps}`."
    )

    notes = []
    if selection:
        mode_text = selection.get("selectionMode", "unknown")
        dense_count = selection.get("denseFrameCount", "unknown")
        selected_count = selection.get("selectedFrameCount", "unknown")
        notes.append(f"Video selection: `{mode_text}`, {selected_count} selected from {dense_count} extracted frames.")
        mapped = []
        for frame in selection.get("frames", []):
            if isinstance(frame, dict):
                mapped.append(f"{frame.get('output')} <- {frame.get('source')}")
        if mapped:
            notes.append("Selected frame map: " + ", ".join(mapped))

    image_pipeline_assets = [
        ReviewAsset(
            "Generated Sheet",
            paths.generated_sheet,
            f"Full opaque pose board produced by the image model. Image size: `{_format_size(_image_size(paths.generated_sheet))}`. Expected generation canvas: `{generation_canvas}`.",
            embed=True,
        ),
        ReviewAsset(
            "Rough Grid Review Crops",
            paths.review_dir / "grid-review-cell-contact.png",
            f"First `{frame_count}` implied grid cells cropped from the pose board for review only. These are not the runtime source of truth. Generation grid: `{generation_grid}`. Cell size: `{generation_cell}`. Review image size: `{_format_size(_image_size(paths.review_dir / 'grid-review-cell-contact.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Rough Grid Review GIF",
            paths.review_dir / "grid-review-cell-preview.gif",
            f"Implied grid crops looped for geometry review only. GIF canvas: `{_format_size(_image_size(paths.review_dir / 'grid-review-cell-preview.gif'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Recovered Component Contact Sheet",
            paths.review_dir / "recovered-component-contact.png",
            f"Foreground components recovered from the full pose board and ordered by the declared grid. These recovered components are the runtime source. Review image size: `{_format_size(_image_size(paths.review_dir / 'recovered-component-contact.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Recovered Native Contact Sheet",
            paths.review_dir / "recovered-native-contact.png",
            f"Recovered components placed on a shared padded native review canvas without scaling. This is the first animation review checkpoint before pixel snap or 256x256 runtime normalization. Review image size: `{_format_size(_image_size(paths.review_dir / 'recovered-native-contact.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Recovered Native Preview GIF",
            paths.review_dir / "recovered-native-preview.gif",
            f"Recovered components looped on the padded native review canvas before runtime normalization. GIF canvas: `{_format_size(_image_size(paths.review_dir / 'recovered-native-preview.gif'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Pixel-Snapped Raw Contact Sheet",
            paths.review_dir / "pixel-snapped-raw-contact.png",
            f"Raw real pixel-snapper outputs shown without padding; labels show discovered native frame sizes. This is diagnostic output, not runtime-ready. In chroma-layout runs the input canvas uses the run's configured chroma matte, but pixel snapper may remap the flat background to another solid color such as black during palette/resampling. Review image size: `{_format_size(_image_size(paths.review_dir / 'pixel-snapped-raw-contact.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Pixel Snap Source Canvas",
            paths.review_dir / "pixel-snap-chroma-source-contact.png",
            f"Recovered components fit with one shared scale and placed on shared `{generation_cell}` canvases before real pixel-snapper processing. In chroma-layout this source canvas uses the run's configured opaque chroma matte; in transparent-layout it is transparent. This is the last intentional chroma-background stage. Review image size: `{_format_size(_image_size(paths.review_dir / 'pixel-snap-chroma-source-contact.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Pixel Snap To Runtime Comparison",
            paths.review_dir / "compare-04-pixel-snap-to-runtime.png",
            f"Single frame-by-frame comparison from source to runtime. For chroma-layout, read the rows as: recovered transparent component, chroma source canvas, raw pixel-snap output, background-cleaned snapped output, optional green-fringe-cleaned output when the matte is green, then final normalized transparent `256x256` runtime frame. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-04-pixel-snap-to-runtime.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 01: Grid Review To Recovered Components",
            paths.review_dir / "compare-01-grid-review-to-recovered-components.png",
            f"Before/after comparison showing why implied grid crops are review artifacts only. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-01-grid-review-to-recovered-components.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 02: Recovered Components To Native Layout",
            paths.review_dir / "compare-02-recovered-to-native-layout.png",
            f"Before/after comparison showing variable-size recovered components padded to a shared native review canvas without scaling. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-02-recovered-to-native-layout.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 03: Recovered To Raw Pixel Snap",
            paths.review_dir / "compare-03-recovered-to-pixel-snapped-raw.png",
            f"Before/after comparison showing recovered components against raw variable-size pixel snap outputs. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-03-recovered-to-pixel-snapped-raw.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 04: Raw Pixel Snap To Background-Cleaned",
            paths.review_dir / "compare-04-pixel-snapped-chroma-to-keyed.png",
            f"Before/after comparison for chroma-layout mode: raw snapped output has its solid background removed before runtime normalization. If the green chroma survives the snap, Spriterrific removes green; if pixel snapper remaps the chroma background to another solid color, Spriterrific removes the connected corner background instead. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-04-pixel-snapped-chroma-to-keyed.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 05: Background-Cleaned To Green-Fringe-Cleaned",
            paths.review_dir / "compare-05-background-cleaned-to-green-fringe-cleaned.png",
            f"Targeted edge sweep for leftover chroma pixels after background cleaning. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-05-background-cleaned-to-green-fringe-cleaned.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 06: Cleaned To Scaled",
            paths.review_dir / "compare-02-cleaned-to-scaled.png",
            f"Before/after comparison for cleanup output to shared-scale layout input. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-02-cleaned-to-scaled.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 07: Scaled To Normalized",
            paths.review_dir / "compare-03-scaled-to-normalized.png",
            f"Before/after comparison for final placement into runtime cells. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-03-scaled-to-normalized.png'))}`.",
            embed=True,
        ),
    ]
    preserve_canvas = mode == "video" and (paths.normalized_dir / "preserve-canvas-metadata.json").exists()
    video_pipeline_assets = [
        ReviewAsset("Selected Frame Contact Sheet", paths.review_selected_contact, "Raw selected video frames before cleanup.", embed=True),
        ReviewAsset("Selected Frame GIF", paths.review_selected_preview, "Raw selected frames looped for quick motion review.", embed=True),
        ReviewAsset(
            "Comparison 01: Selected To Canvas-Cleaned",
            paths.review_dir / "compare-01-selected-to-canvas-cleaned.png",
            f"Before/after comparison for selected video frames to full-canvas background cleanup. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-01-selected-to-canvas-cleaned.png'))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Comparison 02: Canvas-Cleaned To Runtime",
            paths.review_dir / "compare-02-canvas-cleaned-to-runtime.png",
            f"Before/after comparison for preserve-canvas placement into fixed runtime cells. Review image size: `{_format_size(_image_size(paths.review_dir / 'compare-02-canvas-cleaned-to-runtime.png'))}`.",
            embed=True,
        ),
    ]
    pipeline_assets = image_pipeline_assets if mode == "image" else video_pipeline_assets
    normalized_description = (
        "Preserve-canvas video frames scaled into fixed runtime cells without per-frame foreground height normalization or baseline recentering."
        if preserve_canvas
        else "Final normalized frames after cleanup, scaling, and baseline alignment."
    )

    assets = [
        *pipeline_assets,
        ReviewAsset("Normalized Contact Sheet", paths.review_contact, normalized_description, embed=True),
        ReviewAsset("Normalized Preview GIF", paths.review_preview, "Final runtime-cell animation preview.", embed=True),
        ReviewAsset(
            "Runtime Spritesheet",
            paths.export_sheet,
            f"Game-facing transparent spritesheet export. Image size: `{_format_size(_image_size(paths.export_sheet))}`.",
            embed=True,
        ),
        ReviewAsset(
            "Runtime Preview GIF",
            paths.export_preview,
            f"Copy of the final preview GIF bundled with the export. GIF canvas: `{_format_size(_image_size(paths.export_preview))}`.",
            embed=True,
        ),
        ReviewAsset("Export Manifest", paths.export_manifest, "Machine-readable export metadata.", embed=False),
        ReviewAsset("Baseline Report", paths.baseline_report, "Baseline and center audit from the final spritesheet.", embed=False),
    ]
    existing_assets = [asset for asset in assets if asset.path.exists()]
    return write_review_index(paths.review_dir, title=title, summary=summary, assets=existing_assets, notes=notes)


def write_frame_sheet_review_index(
    out_dir: Path,
    *,
    sheet_path: Path,
    preview_path: Path,
    metadata_path: Path,
    source_map_path: Path,
    review_sheet_path: Path | None = None,
    review_preview_path: Path | None = None,
) -> Path:
    metadata = _read_json(metadata_path)
    cell_size = metadata.get("cellSize", ["?", "?"])
    live_frames = metadata.get("liveFrameCount", "?")
    columns = metadata.get("columns", "?")
    rows = metadata.get("rows", "?")
    fps = metadata.get("fps", "?")
    summary = (
        f"Review page for a stitched frame sheet. "
        f"Frames: `{live_frames}`. Cell: `{cell_size[0]}x{cell_size[1]}`. "
        f"Layout: `{columns}x{rows}`. FPS: `{fps}`."
    )

    assets = [
        ReviewAsset("Preview GIF", preview_path, "Looped preview at runtime cell size.", embed=True),
        ReviewAsset("Runtime Spritesheet", sheet_path, "Transparent spritesheet intended for runtime use.", embed=True),
    ]
    if review_preview_path is not None:
        assets.append(ReviewAsset("Upscaled Preview GIF", review_preview_path, "Nearest-neighbor enlarged preview for easier inspection.", embed=True))
    if review_sheet_path is not None:
        assets.append(ReviewAsset("Upscaled Spritesheet", review_sheet_path, "Nearest-neighbor enlarged spritesheet for review.", embed=True))
    assets.extend(
        [
            ReviewAsset("Source Map", source_map_path, "Mapping from output frame slots to source frames.", embed=False),
            ReviewAsset("Sheet Metadata", metadata_path, "Machine-readable frame normalization metadata.", embed=False),
        ]
    )
    existing_assets = [asset for asset in assets if asset.path.exists()]
    return write_review_index(
        out_dir / "review",
        title=f"{out_dir.name} Review",
        summary=summary,
        assets=existing_assets,
    )


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except FileNotFoundError:
        return None


def _format_size(size: tuple[int, int] | None) -> str:
    if size is None:
        return "unknown"
    return f"{size[0]}x{size[1]}"


def _format_list_size(value: object) -> str:
    if isinstance(value, list) and len(value) == 2:
        return f"{value[0]}x{value[1]}"
    return "unknown"


def _format_grid(value: object) -> str:
    if isinstance(value, list) and len(value) == 2:
        return f"{value[0]}x{value[1]}"
    return "unknown"


def _relative_link(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path.resolve(), start.resolve())).as_posix()
