from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .commands import run_command
from .chroma import despill_chroma, is_keyable_fringe_chroma, remove_chroma
from .events import append_event, now_iso, write_json
from .fonts import review_font
from .guides import copy_anchor_guide
from .media import remove_corner_background
from .paths import create_run_paths
from .pipeline import FAL_IMAGE_SCRIPT
from .pixel_snap import SnapOptions, put_on_chroma, snap_user_anchor
from .presets import DIRECTIONS, REFERENCE_SIZE, get_direction, resolve_anchor_game_view, resolve_anchor_role
from .prompts import render_anchor_prompt
from .validate import require_file, validate_reference


@dataclass(frozen=True)
class AnchorOptions:
    reference: Path
    run_dir: Path
    directions: tuple[str, ...] = ("n", "s", "e", "w")
    dry_fal: bool = False
    model_alias: str = "gpt-image-2-edit"
    preprocess: bool = True
    preprocess_padding: int = 48
    pixel_snap_long_edge: int = 256
    chroma: str = "#00FF00"
    k_colors: int = 256
    game_view: str = "platformer"
    anchor_role: str = "character"
    anchor_context: str | None = None
    on_anchor_generated: Callable[[str, Path], None] | None = None


def generate_anchors(options: AnchorOptions) -> Path:
    require_file(options.reference, "reference image")
    unknown = [direction for direction in options.directions if direction not in DIRECTIONS]
    if unknown:
        raise ValueError(f"unknown directions: {', '.join(unknown)}")
    game_view = resolve_anchor_game_view(options.game_view)
    anchor_role = resolve_anchor_role(options.anchor_role)

    paths = create_run_paths(options.run_dir)
    shutil.copy2(options.reference, paths.raw_source_image)
    snap_result = None
    if options.preprocess:
        snap_result = snap_user_anchor(
            SnapOptions(
                source=options.reference,
                run_dir=paths.root / "pixel-snap",
                k_colors=options.k_colors,
            )
        )
        put_on_chroma(snap_result.anchor, paths.source_image, chroma=options.chroma)
    else:
        shutil.copy2(options.reference, paths.source_image)
        validate_reference(paths.source_image)

    guide = paths.guide_dir / "alternating-1024x1024.png"
    run_record = {
        "version": 1,
        "runId": paths.run_id,
        "createdAt": now_iso(),
        "status": "running",
        "type": "anchors",
        "directions": list(options.directions),
        "reference": str(paths.source_image),
        "rawReference": str(paths.raw_source_image),
        "preprocess": options.preprocess,
        "preprocessMetadata": None,
        "preprocessPadding": options.preprocess_padding,
        "pixelSnapLongEdge": options.pixel_snap_long_edge,
        "chroma": options.chroma,
        "kColors": options.k_colors,
        "gameView": game_view,
        "anchorRole": anchor_role,
        "anchorContext": options.anchor_context,
        "pixelSnapRun": str(snap_result.run_dir) if snap_result else None,
        "pixelSnapped": str(snap_result.snapped) if snap_result else None,
        "pixelSnappedUpscaled": str(snap_result.anchor) if snap_result else None,
        "pixelSnappedChroma": str(paths.source_image) if options.preprocess else None,
        "guide": str(guide),
        "dryFal": options.dry_fal,
        "modelAlias": options.model_alias,
    }
    write_json(paths.run_json, run_record)
    append_event(paths.events_jsonl, "anchor_run_started", directions=list(options.directions))

    try:
        copy_anchor_guide(guide)
        append_event(paths.events_jsonl, "anchor_guide_copied", path=str(guide), size=list(REFERENCE_SIZE))

        for direction_id in options.directions:
            direction = get_direction(direction_id)
            prompt = render_anchor_prompt(
                direction,
                game_view=game_view,
                anchor_role=anchor_role,
                anchor_context=options.anchor_context,
            )
            prompt_path = paths.anchors_dir / f"prompt-{direction_id}.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            fal_dir = paths.fal_dir / f"anchor-{direction_id}"
            fal_dir.mkdir(parents=True, exist_ok=True)
            args = [
                sys.executable,
                str(FAL_IMAGE_SCRIPT),
                "--model-alias",
                options.model_alias,
                "--prompt-file",
                str(prompt_path),
                "--image-file",
                str(paths.source_image),
                "--image-file",
                str(guide),
                "--out-dir",
                str(fal_dir),
                "--filename-prefix",
                f"anchor-{direction_id}",
                "--task-slug",
                f"{paths.run_id}-anchor-{direction_id}",
                "--image-size",
                "square_hd",
                "--output-format",
                "png",
                "--quality",
                "high",
            ]
            if options.dry_fal:
                args.append("--dry-run")
            run_command(args, stage=f"fal-anchor-{direction_id}", run_dir=paths.root, events_path=paths.events_jsonl)

            outputs = sorted(fal_dir.glob(f"anchor-{direction_id}-output-*.png"))
            if outputs:
                raw_anchor = paths.anchors_dir / f"character-{direction_id}-raw.png"
                clean_anchor = paths.anchors_dir / f"character-{direction_id}.png"
                chroma_anchor = paths.anchors_dir / f"character-{direction_id}-chroma.png"
                shutil.copy2(outputs[0], raw_anchor)
                cleaned, _metadata = remove_chroma(Image.open(outputs[0]), threshold=110.0, min_component_area=500)
                if cleaned.getchannel("A").getbbox() is None:
                    cleaned = remove_corner_background(Image.open(outputs[0]))
                anchor_chroma_rgb = ImageColor.getrgb(options.chroma)[:3]
                if is_keyable_fringe_chroma(anchor_chroma_rgb):
                    cleaned, _despill_meta = despill_chroma(cleaned, chroma_rgb=anchor_chroma_rgb)
                cleaned.save(clean_anchor)
                _save_chroma_copy(cleaned, chroma_anchor, chroma=options.chroma)
                append_event(
                    paths.events_jsonl,
                    "anchor_generated",
                    direction=direction_id,
                    input=str(raw_anchor),
                    chroma=str(chroma_anchor),
                )
                if options.on_anchor_generated is not None:
                    options.on_anchor_generated(direction_id, chroma_anchor)

        run_record["status"] = "completed"
        run_record["completedAt"] = now_iso()
        write_json(paths.run_json, run_record)
        append_event(paths.events_jsonl, "anchor_run_completed")
        return paths.root
    except Exception as exc:
        run_record["status"] = "failed"
        run_record["failedAt"] = now_iso()
        run_record["error"] = str(exc)
        write_json(paths.run_json, run_record)
        append_event(paths.events_jsonl, "anchor_run_failed", error=str(exc))
        raise


def build_anchor_comparison_sheet(
    pairs: list[tuple[str, Path, Path]],
    out: Path,
    *,
    chroma: str = "#00FF00",
    thumb_size: int = 256,
) -> Path:
    if not pairs:
        raise ValueError("at least one anchor pair is required")

    label_h = 42
    header_h = 34
    cols = len(pairs)
    width = cols * thumb_size
    height = header_h + 2 * (thumb_size + label_h)
    sheet = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(sheet)
    font = _comparison_font(size=24)
    small_font = _comparison_font(size=18)

    draw.text((12, 6), "Generated anchors: raw vs pixel-snapped 1024x1024 chroma", fill=(238, 238, 238, 255), font=small_font)
    row_labels = [("raw", 0), ("pixel-snapped", 1)]
    for col, (direction, _raw, _snapped) in enumerate(pairs):
        x = col * thumb_size
        direction_label = direction.upper()
        draw.text((x + 10, header_h + 8), f"{direction_label} raw", fill=(238, 238, 238, 255), font=font)
        draw.text((x + 10, header_h + thumb_size + label_h + 8), f"{direction_label} snapped", fill=(238, 238, 238, 255), font=font)

    for _, row in row_labels:
        y = header_h + label_h + row * (thumb_size + label_h)
        for col, (_, raw, snapped) in enumerate(pairs):
            path = raw if row == 0 else snapped
            resample = Image.Resampling.LANCZOS if row == 0 else Image.Resampling.NEAREST
            thumb = _anchor_thumbnail(path, thumb_size=thumb_size, chroma=chroma, resample=resample)
            sheet.alpha_composite(thumb, (col * thumb_size, y))

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def build_anchor_detail_sheet(
    pairs: list[tuple[str, Path, Path]],
    out: Path,
    *,
    chroma: str = "#00FF00",
    crop_size: int = 96,
    zoom: int = 3,
) -> Path:
    if not pairs:
        raise ValueError("at least one anchor pair is required")

    cell = crop_size * zoom
    label_h = 42
    header_h = 34
    width = len(pairs) * cell
    height = header_h + 2 * (cell + label_h)
    sheet = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(sheet)
    font = _comparison_font(size=24)
    small_font = _comparison_font(size=18)
    draw.text((12, 6), "Direction anchor detail: raw crop vs snapped crop", fill=(238, 238, 238, 255), font=small_font)

    chroma_rgb = ImageColor.getrgb(chroma)
    for col, (direction, raw, snapped) in enumerate(pairs):
        x = col * cell
        draw.text((x + 10, header_h + 8), f"{direction.upper()} raw", fill=(238, 238, 238, 255), font=font)
        draw.text((x + 10, header_h + cell + label_h + 8), f"{direction.upper()} snapped", fill=(238, 238, 238, 255), font=font)
        for row, path in enumerate((raw, snapped)):
            image = Image.open(path).convert("RGBA")
            crop = _detail_crop(image, crop_size=crop_size, chroma_rgb=chroma_rgb)
            crop = crop.resize((cell, cell), Image.Resampling.NEAREST)
            y = header_h + label_h + row * (cell + label_h)
            sheet.alpha_composite(crop, (x, y))

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def _anchor_thumbnail(
    path: Path,
    *,
    thumb_size: int,
    chroma: str,
    resample: Image.Resampling = Image.Resampling.NEAREST,
) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    if image.size != REFERENCE_SIZE:
        image = image.resize(REFERENCE_SIZE, Image.Resampling.NEAREST)
    image.thumbnail((thumb_size, thumb_size), resample)
    thumb = Image.new("RGBA", (thumb_size, thumb_size), ImageColor.getrgb(chroma) + (255,))
    x = (thumb_size - image.width) // 2
    y = (thumb_size - image.height) // 2
    thumb.alpha_composite(image, (x, y))
    return thumb


def _detail_crop(image: Image.Image, *, crop_size: int, chroma_rgb: tuple[int, int, int]) -> Image.Image:
    bbox = _foreground_bbox(image, chroma_rgb=chroma_rgb)
    if bbox is None:
        cx = image.width // 2
        cy = image.height // 2
    else:
        left, top, right, bottom = bbox
        cx = (left + right) // 2
        cy = top + max(1, (bottom - top) // 3)
    left = max(0, min(image.width - crop_size, cx - crop_size // 2))
    top = max(0, min(image.height - crop_size, cy - crop_size // 2))
    return image.crop((left, top, left + crop_size, top + crop_size))


def _foreground_bbox(image: Image.Image, *, chroma_rgb: tuple[int, int, int]) -> tuple[int, int, int, int] | None:
    min_x = image.width
    min_y = image.height
    max_x = -1
    max_y = -1
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = image.getpixel((x, y))
            if a == 0 or _is_green_background((r, g, b), chroma_rgb):
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def _is_green_background(rgb: tuple[int, int, int], chroma_rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    cr, cg, cb = chroma_rgb
    if abs(r - cr) <= 8 and abs(g - cg) <= 8 and abs(b - cb) <= 8:
        return True
    return g >= 190 and r <= 60 and b <= 60


def _save_chroma_copy(image: Image.Image, out: Path, *, chroma: str) -> Path:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, ImageColor.getrgb(chroma) + (255,))
    canvas.alpha_composite(rgba, (0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def _comparison_font(*, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return review_font(size=size)
