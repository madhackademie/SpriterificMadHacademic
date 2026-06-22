from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont, ImageStat

from .commands import run_command
from .fonts import review_font
from .presets import VIDEO_PLATE_SIZE


def foreground_bbox(image: Image.Image, threshold: int = 30) -> tuple[int, int, int, int]:
    rgba = image.convert("RGBA")
    alpha_bbox = rgba.getchannel("A").getbbox()
    if alpha_bbox and alpha_bbox != (0, 0, rgba.width, rgba.height):
        return alpha_bbox

    px = rgba.load()
    corners = [px[0, 0][:3], px[rgba.width - 1, 0][:3], px[0, rgba.height - 1][:3], px[rgba.width - 1, rgba.height - 1][:3]]
    bg = tuple(round(sum(c[i] for c in corners) / len(corners)) for i in range(3))
    min_x, min_y = rgba.width, rgba.height
    max_x = max_y = -1
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, _ = px[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > threshold:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return (0, 0, rgba.width, rgba.height)
    return (min_x, min_y, max_x + 1, max_y + 1)


def create_video_plate(reference: Path, out: Path, bg: str = "#00FF00") -> Path:
    canvas_w, canvas_h = VIDEO_PLATE_SIZE
    source = Image.open(reference).convert("RGBA")
    alpha_bbox = source.getchannel("A").getbbox()
    if alpha_bbox == (0, 0, source.width, source.height):
        source = remove_corner_background(source)
    crop = source.crop(foreground_bbox(source))
    max_w = round(canvas_w * 0.60)
    max_h = round(canvas_h * 0.78)
    scale = min(max_w / crop.width, max_h / crop.height, 1.0)
    new_size = (max(1, int(round(crop.width * scale))), max(1, int(round(crop.height * scale))))
    sprite = crop.resize(new_size, Image.Resampling.NEAREST)

    canvas = Image.new("RGBA", VIDEO_PLATE_SIZE, ImageColor.getrgb(bg) + (255,))
    x = (canvas_w - sprite.width) // 2
    y = canvas_h - round(canvas_h * 0.11) - sprite.height
    canvas.alpha_composite(sprite, (x, y))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def extract_video_frames(video: Path, out_dir: Path, *, run_dir: Path, events_path: Path, fps: int | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()
    command = ["ffmpeg", "-y", "-i", str(video)]
    if fps is not None:
        command.extend(["-vf", f"fps={fps}"])
    command.append(str(out_dir / "frame-%04d.png"))
    run_command(
        command,
        stage="extract-video-frames",
        run_dir=run_dir,
        events_path=events_path,
    )
    return sorted(out_dir.glob("frame-*.png"))


def select_frames(
    dense_dir: Path,
    selected_dir: Path,
    frame_count: int,
    selected_order: list[str] | None = None,
    selected_range: tuple[int, int] | None = None,
    *,
    action: str | None = None,
    timing: str = "loop",
    selection_policy: str = "cycle",
    video_model_alias: str | None = None,
    cycle_start_fraction: float | None = None,
    cycle_span_factor: float | None = None,
    metadata_path: Path | None = None,
) -> list[Path]:
    selected_dir.mkdir(parents=True, exist_ok=True)
    for old in selected_dir.glob("frame-*.png"):
        old.unlink()

    dense = sorted(dense_dir.glob("frame-*.png"))
    if selected_order and selected_range:
        raise ValueError("selected_order and selected_range cannot both be set")
    if selected_order:
        selection_mode = "manual"
    elif selected_range:
        selection_mode = _range_selection_mode(selection_policy)
    else:
        selection_mode = _auto_selection_mode(selection_policy)
    resolved_cycle_start_fraction: float | None = None
    resolved_cycle_span_factor: float | None = None
    if selection_policy == "cycle":
        resolved_cycle_start_fraction = (
            cycle_start_fraction
            if cycle_start_fraction is not None
            else _auto_cycle_start_fraction(action=action, video_model_alias=video_model_alias)
        )
        resolved_cycle_span_factor = (
            cycle_span_factor
            if cycle_span_factor is not None
            else _auto_cycle_span_factor(action=action, video_model_alias=video_model_alias)
        )

    if selected_order:
        lookup = {path.name: path for path in dense}
        source_frames = []
        for item in selected_order:
            name = Path(item).name
            if name not in lookup:
                raise ValueError(f"selected frame not found in dense frames: {item}")
            source_frames.append(lookup[name])
    elif selected_range:
        start, end_exclusive = selected_range
        if start < 1 or end_exclusive <= start:
            raise ValueError("selected range must be START:END_EXCLUSIVE with START >= 1 and END_EXCLUSIVE > START")
        pool = dense[start - 1 : end_exclusive - 1]
        if len(pool) < frame_count:
            raise ValueError(
                f"selected range {start}:{end_exclusive} has {len(pool)} frames, need at least {frame_count}"
            )
        indices = best_guess_frame_indices(pool, frame_count)
        source_frames = [pool[index] for index in indices]
    else:
        if len(dense) < frame_count:
            raise ValueError(f"need at least {frame_count} dense frames, found {len(dense)}")
        indices = _select_indices_for_policy(
            dense,
            frame_count,
            selection_policy=selection_policy,
            action=action,
            video_model_alias=video_model_alias,
            cycle_start_fraction=cycle_start_fraction,
            cycle_span_factor=cycle_span_factor,
        )
        source_frames = [dense[index] for index in indices]

    if len(source_frames) != frame_count:
        raise ValueError(f"selected order must contain {frame_count} frames")

    out = []
    for index, frame in enumerate(source_frames, start=1):
        dest = selected_dir / f"frame-{index:02d}.png"
        shutil.copy2(frame, dest)
        out.append(dest)
    if metadata_path is not None:
        write_selection_manifest(
            metadata_path,
            dense_frames=dense,
            source_frames=source_frames,
            output_frames=out,
            selection_mode=selection_mode,
            action=action,
            timing=timing,
            selection_policy=selection_policy,
            cycle_start_fraction=resolved_cycle_start_fraction,
            cycle_span_factor=resolved_cycle_span_factor,
        )
    return out


def _select_indices_for_policy(
    frames: list[Path],
    frame_count: int,
    *,
    selection_policy: str,
    action: str | None,
    video_model_alias: str | None,
    cycle_start_fraction: float | None = None,
    cycle_span_factor: float | None = None,
) -> list[int]:
    if selection_policy == "cycle":
        return best_guess_cycle_frame_indices(
            frames,
            frame_count,
            start_fraction=(
                cycle_start_fraction
                if cycle_start_fraction is not None
                else _auto_cycle_start_fraction(action=action, video_model_alias=video_model_alias)
            ),
            span_factor=(
                cycle_span_factor
                if cycle_span_factor is not None
                else _auto_cycle_span_factor(action=action, video_model_alias=video_model_alias)
            ),
        )
    if selection_policy in {"action_window", "full_duration_include_end", "hold_pose"}:
        return best_guess_frame_indices(frames, frame_count)
    raise ValueError(f"unknown selection policy: {selection_policy}")


def _auto_selection_mode(selection_policy: str) -> str:
    if selection_policy == "cycle":
        return "auto-cycle-window-nonduplicate"
    if selection_policy == "full_duration_include_end":
        return "auto-full-duration-include-end"
    if selection_policy == "action_window":
        return "auto-action-window"
    if selection_policy == "hold_pose":
        return "auto-hold-pose"
    return f"auto-{selection_policy}"


def _range_selection_mode(selection_policy: str) -> str:
    if selection_policy == "cycle":
        return "auto-range-nonduplicate"
    if selection_policy == "full_duration_include_end":
        return "auto-range-full-duration-include-end"
    if selection_policy == "action_window":
        return "auto-range-action-window"
    if selection_policy == "hold_pose":
        return "auto-range-hold-pose"
    return f"auto-range-{selection_policy}"


def best_guess_cycle_frame_indices(
    frames: list[Path],
    frame_count: int,
    *,
    duplicate_threshold: float = 2.0,
    start_fraction: float = 0.0,
    span_factor: float = 4.25,
) -> list[int]:
    if frame_count < 2:
        raise ValueError("frame_count must be at least 2")
    if len(frames) < frame_count:
        raise ValueError(f"need at least {frame_count} frames, found {len(frames)}")

    start = math.ceil((len(frames) - 1) * start_fraction) if start_fraction > 0 else 1 if len(frames) > frame_count else 0
    span = round((frame_count - 1) * span_factor)
    end = min(len(frames) - 1, start + span)
    if end - start + 1 < frame_count:
        start = max(0, len(frames) - frame_count)
        end = len(frames) - 1

    indices = _evenly_spaced_indices(start, end, frame_count)
    signatures = [_frame_signature(path) for path in frames]
    if _has_near_duplicate_sequence(indices, signatures, duplicate_threshold=duplicate_threshold):
        pool = frames[start : end + 1]
        local_indices = best_guess_frame_indices(pool, frame_count, duplicate_threshold=duplicate_threshold)
        return [start + index for index in local_indices]
    return indices


def _auto_cycle_start_fraction(*, action: str | None, video_model_alias: str | None) -> float:
    if _is_wan_27_motion(action=action, video_model_alias=video_model_alias):
        return 0.5
    return 0.0


def _auto_cycle_span_factor(*, action: str | None, video_model_alias: str | None) -> float:
    if _is_wan_27_motion(action=action, video_model_alias=video_model_alias):
        return 2.15 if str(action or "").lower() == "run" else 3.0
    return 4.25


def _is_wan_27_motion(*, action: str | None, video_model_alias: str | None) -> bool:
    return str(video_model_alias or "").lower() == "wan-2.7" and str(action or "").lower() in {"run", "walk"}


def best_guess_frame_indices(frames: list[Path], frame_count: int, *, duplicate_threshold: float = 2.0) -> list[int]:
    if frame_count < 1:
        raise ValueError("frame_count must be >= 1")
    if len(frames) < frame_count:
        raise ValueError(f"need at least {frame_count} frames, found {len(frames)}")
    if frame_count == 1:
        return [0]

    signatures = [_frame_signature(path) for path in frames]
    step = (len(frames) - 1) / (frame_count - 1)
    selected: list[int] = []

    for slot in range(frame_count):
        ideal = int(round(slot * step))
        remaining = frame_count - slot - 1
        low = selected[-1] + 1 if selected else 0
        high = len(frames) - remaining - 1
        window_low = max(low, int(round((slot - 0.5) * step)))
        window_high = min(high, int(round((slot + 0.5) * step)))
        candidates = list(range(window_low, window_high + 1))
        if not candidates:
            candidates = list(range(low, high + 1))
        if not candidates:
            break
        if not selected:
            chosen = min(candidates, key=lambda index: abs(index - ideal))
        else:
            previous = selected[-1]
            non_duplicate = [
                index
                for index in candidates
                if _signature_distance(signatures[index], signatures[previous]) >= duplicate_threshold
            ]
            pool = non_duplicate or candidates
            chosen = min(pool, key=lambda index: abs(index - ideal))
        selected.append(chosen)

    if len(selected) != frame_count:
        raise ValueError(f"could only select {len(selected)} unique frames from {len(frames)} dense frames")
    return selected


def _evenly_spaced_indices(start: int, end: int, count: int) -> list[int]:
    if count < 2:
        raise ValueError("count must be at least 2")
    if start == end:
        raise ValueError("start and end frames must be different")
    step = (end - start) / (count - 1)
    indices = [round(start + step * slot) for slot in range(count)]
    if len(set(indices)) != len(indices):
        raise ValueError("selection produced duplicate frame indices")
    return indices


def _has_near_duplicate_sequence(indices: list[int], signatures: list[Image.Image], *, duplicate_threshold: float) -> bool:
    return any(
        _signature_distance(signatures[left], signatures[right]) < duplicate_threshold
        for left, right in zip(indices, indices[1:])
    )


def write_selection_manifest(
    out: Path,
    *,
    dense_frames: list[Path],
    source_frames: list[Path],
    output_frames: list[Path],
    selection_mode: str,
    action: str | None = None,
    timing: str = "loop",
    selection_policy: str = "cycle",
    cycle_start_fraction: float | None = None,
    cycle_span_factor: float | None = None,
) -> Path:
    lookup = {path.name: index for index, path in enumerate(dense_frames)}
    records = []
    for output, source in zip(output_frames, source_frames):
        records.append(
            {
                "output": output.name,
                "source": source.name,
                "sourceIndex": lookup[source.name],
            }
        )
    selected_indices = [lookup[source.name] for source in source_frames]
    includes_final_source_frame = bool(selected_indices) and (len(dense_frames) - 1) in selected_indices
    warnings = _selection_semantic_warnings(
        action=action,
        timing=timing,
        selection_policy=selection_policy,
        selection_mode=selection_mode,
        dense_frames=dense_frames,
        selected_indices=selected_indices,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "version": 1,
                "selectionMode": selection_mode,
                "action": action,
                "timing": timing,
                "selectionPolicy": selection_policy,
                "cycleStartFraction": cycle_start_fraction,
                "cycleSpanFactor": cycle_span_factor,
                "denseFrameCount": len(dense_frames),
                "selectedFrameCount": len(source_frames),
                "sourceStartFrame": min(selected_indices) + 1 if selected_indices else None,
                "sourceEndFrame": max(selected_indices) + 1 if selected_indices else None,
                "includesFinalSourceFrame": includes_final_source_frame,
                "warnings": warnings,
                "frames": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def _selection_semantic_warnings(
    *,
    action: str | None,
    timing: str,
    selection_policy: str,
    selection_mode: str,
    dense_frames: list[Path],
    selected_indices: list[int],
) -> list[str]:
    if not dense_frames or not selected_indices:
        return []
    if selection_mode != "manual":
        return []
    if timing != "transition" and selection_policy != "full_duration_include_end":
        return []
    if len(dense_frames) - 1 in selected_indices:
        return []

    selected_end = max(selected_indices) + 1
    action_label = action or "selected action"
    return [
        (
            f"{action_label} is a transition, but selected frames end at "
            f"{dense_frames[selected_end - 1].name} of {dense_frames[-1].name}. "
            "The final source frame is not included, so the export may omit the final pose."
        )
    ]


def build_selected_contact_sheet(input_dir: Path, out: Path, *, glob: str = "frame-*.png", thumb_height: int = 160) -> Path:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no selected frames found in {input_dir}")
    thumbs = []
    for path in frames:
        image = Image.open(path).convert("RGBA")
        scale = thumb_height / image.height
        thumb = image.resize((max(1, int(round(image.width * scale))), thumb_height), Image.Resampling.NEAREST)
        thumbs.append((path, thumb))

    label_h = 28
    gutter = 8
    width = sum(thumb.width for _path, thumb in thumbs) + gutter * (len(thumbs) + 1)
    height = thumb_height + label_h + gutter * 2
    sheet = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(sheet)
    font = _review_font(size=16)
    x = gutter
    for path, thumb in thumbs:
        sheet.alpha_composite(thumb, (x, gutter))
        draw.text((x, gutter + thumb_height + 4), path.stem, fill=(238, 238, 238, 255), font=font)
        x += thumb.width + gutter
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def build_native_size_contact_sheet(input_dir: Path, out: Path, *, glob: str = "frame-*.png", scale: int = 4) -> Path:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no selected frames found in {input_dir}")
    if scale < 1:
        raise ValueError("scale must be >= 1")

    items = []
    for path in frames:
        image = Image.open(path).convert("RGBA")
        scaled = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
        items.append((path, image.size, scaled))

    label_h = 44
    gutter = 10
    width = sum(image.width for _path, _size, image in items) + gutter * (len(items) + 1)
    height = max(image.height for _path, _size, image in items) + label_h + gutter * 2
    sheet = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(sheet)
    font = _review_font(size=13)
    x = gutter
    for path, source_size, image in items:
        sheet.alpha_composite(image, (x, gutter))
        label = f"{path.stem}\n{source_size[0]}x{source_size[1]} x{scale}"
        draw.text((x, gutter + image.height + 4), label, fill=(238, 238, 238, 255), font=font)
        x += image.width + gutter
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def build_before_after_contact_sheet(
    before_dir: Path,
    after_dir: Path,
    out: Path,
    *,
    glob: str = "frame-*.png",
    before_label: str = "Before",
    after_label: str = "After",
    thumb_height: int = 120,
) -> Path:
    before_frames = sorted(before_dir.glob(glob))
    after_lookup = {path.name: path for path in sorted(after_dir.glob(glob))}
    pairs = [(path, after_lookup[path.name]) for path in before_frames if path.name in after_lookup]
    if not pairs:
        raise ValueError(f"no matching frames found between {before_dir} and {after_dir}")

    columns = []
    for before_path, after_path in pairs:
        before_image = Image.open(before_path).convert("RGBA")
        after_image = Image.open(after_path).convert("RGBA")
        before_thumb = _thumbnail_to_height(before_image, thumb_height)
        after_thumb = _thumbnail_to_height(after_image, thumb_height)
        columns.append((before_path, before_thumb, after_thumb, max(before_thumb.width, after_thumb.width)))

    label_h = 28
    frame_label_h = 24
    gutter = 8
    width = sum(column_w for _path, _before, _after, column_w in columns) + gutter * (len(columns) + 1)
    height = label_h + thumb_height + label_h + thumb_height + frame_label_h + gutter * 4
    sheet = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(sheet)
    label_font = _review_font(size=16)
    frame_font = _review_font(size=14)

    y_before_label = gutter
    y_before = y_before_label + label_h
    y_after_label = y_before + thumb_height + gutter
    y_after = y_after_label + label_h
    y_frame = y_after + thumb_height + 4
    draw.text((gutter, y_before_label), before_label, fill=(238, 238, 238, 255), font=label_font)
    draw.text((gutter, y_after_label), after_label, fill=(238, 238, 238, 255), font=label_font)

    x = gutter
    for path, before_thumb, after_thumb, column_w in columns:
        before_x = x + (column_w - before_thumb.width) // 2
        after_x = x + (column_w - after_thumb.width) // 2
        sheet.alpha_composite(before_thumb, (before_x, y_before))
        sheet.alpha_composite(after_thumb, (after_x, y_after))
        draw.text((x, y_frame), path.stem, fill=(238, 238, 238, 255), font=frame_font)
        x += column_w + gutter

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def build_selected_preview_gif(
    input_dir: Path,
    out: Path,
    *,
    glob: str = "frame-*.png",
    duration_ms: int = 100,
    max_size: tuple[int, int] = (256, 256),
) -> Path:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no selected frames found in {input_dir}")
    images = []
    for path in frames:
        image = Image.open(path).convert("RGBA")
        image.thumbnail(max_size, Image.Resampling.NEAREST)
        canvas = Image.new("RGBA", max_size, (240, 240, 240, 255))
        canvas.alpha_composite(image, ((max_size[0] - image.width) // 2, (max_size[1] - image.height) // 2))
        images.append(canvas.convert("P", palette=Image.Palette.ADAPTIVE))
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, save_all=True, append_images=images[1:], duration=duration_ms, loop=0, disposal=2)
    return out


def _thumbnail_to_height(image: Image.Image, thumb_height: int) -> Image.Image:
    scale = thumb_height / image.height
    return image.resize((max(1, int(round(image.width * scale))), thumb_height), Image.Resampling.NEAREST)


def _frame_signature(path: Path) -> Image.Image:
    return Image.open(path).convert("L").resize((16, 16), Image.Resampling.BILINEAR)


def _signature_distance(left: Image.Image, right: Image.Image) -> float:
    diff = ImageChops.difference(left, right)
    mean = ImageStat.Stat(diff).mean
    return float(sum(mean) / len(mean))


def _review_font(*, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return review_font(size=size)


def crop_video_foreground_frames(input_dir: Path, out_dir: Path, threshold: int = 30) -> list[Path]:
    frames = sorted(input_dir.glob("frame-*.png"))
    if not frames:
        raise ValueError(f"no selected frames found in {input_dir}")

    images = [Image.open(path).convert("RGBA") for path in frames]
    bboxes = [foreground_bbox(image, threshold=threshold) for image in images]
    left = min(bbox[0] for bbox in bboxes)
    top = min(bbox[1] for bbox in bboxes)
    right = max(bbox[2] for bbox in bboxes)
    bottom = max(bbox[3] for bbox in bboxes)

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    output = []
    for path, image in zip(frames, images):
        cropped = image.crop((left, top, right, bottom))
        transparent = remove_corner_background(cropped, threshold=threshold)
        dest = out_dir / path.name
        transparent.save(dest)
        output.append(dest)
    return output


def remove_corner_background(image: Image.Image, threshold: int = 30) -> Image.Image:
    rgba = image.convert("RGBA")
    px = rgba.load()
    corners = [px[0, 0][:3], px[rgba.width - 1, 0][:3], px[0, rgba.height - 1][:3], px[rgba.width - 1, rgba.height - 1][:3]]
    bg = tuple(round(sum(c[i] for c in corners) / len(corners)) for i in range(3))
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out_px = out.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = px[x, y]
            if a and abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > threshold:
                out_px[x, y] = (r, g, b, a)
    return out
