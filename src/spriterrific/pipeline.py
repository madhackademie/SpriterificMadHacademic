from __future__ import annotations

import shutil
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .bria import remove_background_batch
from .chroma import (
    despill_chroma,
    despill_chroma_batch,
    is_keyable_fringe_chroma,
    recover_chroma_components_from_sheet,
    remove_chroma_batch,
    remove_chroma_or_corner_background_batch,
    remove_fringe,
    remove_fringe_batch,
)
from .commands import run_command
from .events import append_event, now_iso, write_json
from .fonts import contact_sheet_font_path, review_font
from .manifest import write_export_manifest
from .media import (
    build_before_after_contact_sheet,
    build_native_size_contact_sheet,
    build_selected_contact_sheet,
    build_selected_preview_gif,
    create_video_plate,
    crop_video_foreground_frames,
    extract_video_frames,
    select_frames,
)
from .pack import pack_spritesheet
from .pixel_snap import PIXEL_SNAPPER_SCRIPT
from .paths import RunPaths, create_run_paths
from .presets import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    NATIVE_REVIEW_FRAME_HEIGHT,
    NATIVE_REVIEW_FRAME_WIDTH,
    PoseBoardPreset,
    SHEET_COLUMNS,
    TARGET_BOTTOM_Y,
    TARGET_CENTER_X,
    VideoModelPreset,
    WAN_TURBO_FRAMES_PER_SECOND,
    WAN_TURBO_SHORT_NUM_FRAMES,
    get_action,
    get_direction,
    resolve_video_model_for_run,
    resolve_video_model_preset,
    resolve_frame_count_resolution,
    resolve_mode,
    resolve_pose_board_preset,
    validate_video_end_reference_support,
    sheet_rows,
)
from .prompts import render_prompt
from .review_index import write_run_review_index
from .scale import scale_frame_crops
from .size_contract import append_size_contract_prompt, load_size_contract
from .validate import require_file, validate_export_sheet, validate_reference


PACKAGE_ROOT = Path(__file__).resolve().parent
RUNTIME_TOOLS = PACKAGE_ROOT / "runtime_tools"
ANIMATED_SCRIPTS = RUNTIME_TOOLS / "animated_spritesheets" / "scripts"
GAMEDEV_SCRIPTS = RUNTIME_TOOLS / "gamedev_assets" / "scripts"
FAL_IMAGE_SCRIPT = RUNTIME_TOOLS / "fal_ai_image" / "scripts" / "fal_queue_image_run.py"
FAL_VIDEO_SCRIPT = RUNTIME_TOOLS / "fal_ai_video" / "scripts" / "fal_queue_video_run.py"


@dataclass(frozen=True)
class RunOptions:
    action: str
    direction: str
    reference: Path
    run_dir: Path
    end_reference: Path | None = None
    mode: str | None = None
    frame_count: int | None = None
    frame_count_profile: str = "platformer"
    animation_template: str = "platformer"
    allow_frame_count_override: bool = False
    strict_frame_counts: bool = False
    dry_fal: bool = False
    existing_sheet: Path | None = None
    existing_video: Path | None = None
    selected_order: list[str] | None = None
    selected_range: tuple[int, int] | None = None
    fps: int | None = None
    cycle_start_fraction: float | None = None
    cycle_span_factor: float | None = None
    bg_remove: str = "auto"
    pixel_snap: bool = False
    pixel_snap_source: str = "recovered"
    k_colors: int = 256
    chroma: str = "#00FF00"
    video_model_alias: str | None = None
    video_duration: str | None = None
    action_context: str | None = None
    size_contract: Path | None = None
    pose_board_preset: str = "standard"
    frame_prompt_style: str = "specific"
    green_fringe_cleanup: bool = True
    green_fringe_min_green: int = 70
    green_fringe_dominance: int = 24
    green_fringe_edge_radius: int = 1
    video_layout_mode: str | None = None
    seed: int | None = None


def run_pipeline(options: RunOptions) -> RunPaths:
    action = get_action(options.action)
    direction = get_direction(options.direction)
    mode = resolve_mode(action, options.mode)
    if options.end_reference is not None and mode != "video":
        raise ValueError("--end-reference is only supported for video runs")
    manual_frame_recovery = mode == "video" and (
        options.existing_video is not None
        or options.selected_order is not None
        or options.selected_range is not None
    )
    implicit_selected_order_count = (
        options.frame_count is None
        and options.selected_order is not None
        and manual_frame_recovery
    )
    requested_frame_count = len(options.selected_order) if implicit_selected_order_count and options.selected_order else options.frame_count
    allow_frame_count_override = options.allow_frame_count_override or implicit_selected_order_count
    if allow_frame_count_override and not manual_frame_recovery:
        raise ValueError("--allow-frame-count-override is only supported for video runs with --existing-video, --selected-order, or --selected-range")
    frame_resolution = resolve_frame_count_resolution(
        action,
        requested_frame_count,
        profile=options.frame_count_profile,
        allow_override=allow_frame_count_override,
        strict=options.strict_frame_counts,
        override_context=" with --existing-video, --selected-order, or --selected-range",
    )
    frame_count = frame_resolution.resolved
    pose_board = resolve_pose_board_preset(options.pose_board_preset)
    validate_reference(options.reference)
    if options.end_reference is not None:
        validate_reference(options.end_reference)
    size_contract = load_size_contract(options.size_contract) if options.size_contract else None
    effective_fps = options.fps if options.fps is not None else action.fps
    if effective_fps <= 0:
        raise ValueError("--fps must be positive")
    if options.cycle_start_fraction is not None and not 0 <= options.cycle_start_fraction <= 1:
        raise ValueError("--cycle-start-fraction must be between 0 and 1")
    if options.cycle_span_factor is not None and options.cycle_span_factor <= 0:
        raise ValueError("--cycle-span-factor must be positive")
    chroma_rgb = _chroma_rgb(options.chroma)

    paths = create_run_paths(options.run_dir)
    image_generation_frame_count = pose_board.total_cells if mode == "image" else frame_count
    prompt = append_size_contract_prompt(
        _with_action_context(
            render_prompt(
                action,
                direction,
                frame_count,
                mode,
                generation_frame_count=image_generation_frame_count,
                pose_board=pose_board,
                frame_prompt_style=options.frame_prompt_style,
                chroma=options.chroma,
            ),
            options.action_context,
        ),
        size_contract,
    )
    shutil.copy2(options.reference, paths.source_image)
    shutil.copy2(options.reference, paths.direction_anchor)
    if options.end_reference is not None:
        shutil.copy2(options.end_reference, paths.end_reference)
    paths.prompt_text.write_text(prompt, encoding="utf-8")
    if options.size_contract:
        shutil.copy2(options.size_contract, paths.input_dir / "size-contract.json")

    video_model_alias = resolve_video_model_for_run(action, options.video_model_alias, end_reference=options.end_reference is not None)
    video_preset = resolve_video_model_preset(video_model_alias) if mode == "video" else None
    if mode == "video" and options.end_reference is not None and video_preset is not None:
        validate_video_end_reference_support(video_preset, model_alias=video_model_alias)
    effective_video_duration = _effective_video_duration(action.id, video_preset, options.video_duration) if video_preset else None
    video_frame_payload = (
        _wan_turbo_frame_payload(effective_video_duration, video_preset) if video_preset and _is_wan_turbo_preset(video_preset) else None
    )

    run_record: dict[str, Any] = {
        "version": 1,
        "runId": paths.run_id,
        "createdAt": now_iso(),
        "status": "running",
        "action": action.id,
        "direction": direction.id,
        "mode": mode,
        "animationTiming": action.timing,
        "loopable": action.loopable,
        "selectionPolicy": action.selection_policy if mode == "video" else None,
        "frameCount": frame_count,
        "requestedFrameCount": frame_resolution.requested,
        "frameCountSource": frame_resolution.source,
        "frameCountAllowed": list(frame_resolution.allowed_frames),
        "frameCountCoerced": frame_resolution.coerced,
        "frameCountWarning": frame_resolution.warning,
        "fps": effective_fps,
        "fpsOverride": options.fps,
        "cycleStartFraction": options.cycle_start_fraction if mode == "video" else None,
        "cycleSpanFactor": options.cycle_span_factor if mode == "video" else None,
        "frameCountProfile": options.frame_count_profile,
        "animationTemplate": options.animation_template,
        "frameCountOverrideAllowed": allow_frame_count_override,
        "strictFrameCounts": options.strict_frame_counts,
        "manualFrameRecovery": manual_frame_recovery,
        "imageGenerationFrameCount": image_generation_frame_count if mode == "image" else None,
        "imagePoseBoardPreset": pose_board.id if mode == "image" else None,
        "imageGenerationCanvas": [pose_board.width, pose_board.height] if mode == "image" else None,
        "imageGenerationGrid": [pose_board.columns, pose_board.rows] if mode == "image" else None,
        "imageGenerationCellSize": [pose_board.cell_width, pose_board.cell_height] if mode == "image" else None,
        "frameWidth": FRAME_WIDTH,
        "frameHeight": FRAME_HEIGHT,
        "columns": SHEET_COLUMNS,
        "rows": sheet_rows(frame_count),
        "reference": str(paths.source_image),
        "startReference": str(paths.source_image),
        "endReference": str(paths.end_reference) if options.end_reference is not None else None,
        "prompt": str(paths.prompt_text),
        "dryFal": options.dry_fal,
        "bgRemove": _resolve_bg_remove_option(options.bg_remove, mode),
        "pixelSnap": options.pixel_snap,
        "pixelSnapSource": _resolve_pixel_snap_source(options.pixel_snap_source),
        "kColors": options.k_colors,
        "chroma": options.chroma,
        "chromaRgb": list(chroma_rgb),
        "videoModelAlias": video_model_alias if mode == "video" else None,
        "videoModelSupportsEndImage": video_preset.supports_end_image if video_preset else None,
        "videoInputImageField": video_preset.input_image_field if video_preset else None,
        "videoEndImageField": video_preset.end_image_field if video_preset else None,
        "transitionConstrainedByEndReference": bool(options.end_reference is not None and action.timing == "transition"),
        "videoDuration": _run_record_video_duration(video_preset, effective_video_duration),
        "videoFrameCount": video_frame_payload.get("num_frames") if video_frame_payload else None,
        "videoFramesPerSecond": video_frame_payload.get("frames_per_second") if video_frame_payload else None,
        "videoResolution": video_preset.resolution if video_preset else None,
        "actionContext": options.action_context,
        "sizeContract": str(options.size_contract) if options.size_contract else None,
        "sizeContractResolved": _size_contract_run_record(size_contract),
        "framePromptStyle": options.frame_prompt_style,
        "greenFringeCleanup": options.green_fringe_cleanup,
        "greenFringeCleanupEffective": options.green_fringe_cleanup and is_keyable_fringe_chroma(_chroma_rgb(options.chroma)),
        "greenFringeMinGreen": options.green_fringe_min_green,
        "greenFringeDominance": options.green_fringe_dominance,
        "greenFringeEdgeRadius": options.green_fringe_edge_radius,
        "seed": options.seed,
    }
    write_json(paths.run_json, run_record)
    append_event(paths.events_jsonl, "run_started", action=action.id, direction=direction.id, mode=mode)
    if frame_resolution.coerced:
        append_event(
            paths.events_jsonl,
            "frame_count_coerced",
            action=action.id,
            requested=frame_resolution.requested,
            resolved=frame_resolution.resolved,
            allowed=list(frame_resolution.allowed_frames),
        )

    try:
        if mode == "image":
            _run_image_pipeline(paths, action.id, direction.id, frame_count, prompt, options, pose_board=pose_board)
        else:
            _run_video_pipeline(paths, action.id, direction.id, frame_count, prompt, options, fps=effective_fps)
        validate_export_sheet(paths.export_sheet, frame_count)
        write_export_manifest(
            out=paths.export_manifest,
            run_id=paths.run_id,
            action=action.id,
            direction=direction.id,
            mode=mode,
            frame_count=frame_count,
            fps=effective_fps,
        )
        run_record["status"] = "completed"
        run_record["completedAt"] = now_iso()
        write_json(paths.run_json, run_record)
        write_run_review_index(paths)
        append_event(paths.events_jsonl, "run_completed")
        return paths
    except Exception as exc:
        run_record["status"] = "failed"
        run_record["failedAt"] = now_iso()
        run_record["error"] = str(exc)
        write_json(paths.run_json, run_record)
        append_event(paths.events_jsonl, "run_failed", error=str(exc))
        raise


def _run_image_pipeline(
    paths: RunPaths,
    action: str,
    direction: str,
    frame_count: int,
    prompt: str,
    options: RunOptions,
    *,
    pose_board: PoseBoardPreset,
) -> None:
    sheet_size = f"{pose_board.width}x{pose_board.height}"
    guide = paths.guide_dir / f"alternating-{sheet_size}-{pose_board.columns}x{pose_board.rows}-pose-board.png"
    run_command(
        [sys.executable, str(ANIMATED_SCRIPTS / "make_alternating_sheet.py"), "--size", sheet_size, "--out", str(guide)],
        stage="make-alternating-guide",
        run_dir=paths.root,
        events_path=paths.events_jsonl,
    )

    if options.existing_sheet:
        require_file(options.existing_sheet, "existing sheet")
        shutil.copy2(options.existing_sheet, paths.generated_sheet)
    else:
        _run_fal_image(paths, prompt, guide, sheet_size, options.dry_fal, get_action(action).image_model_alias, seed=options.seed)
        outputs = sorted(paths.fal_dir.glob("fal-image-output-*.png"))
        if not outputs:
            raise ValueError("fal image run did not produce a downloaded PNG")
        shutil.copy2(outputs[0], paths.generated_sheet)

    _recover_normalize_review_export(paths, frame_count, pose_board=pose_board)


def _run_video_pipeline(
    paths: RunPaths,
    action: str,
    direction: str,
    frame_count: int,
    prompt: str,
    options: RunOptions,
    *,
    fps: int,
) -> None:
    action_preset = get_action(action)
    create_video_plate(paths.direction_anchor, paths.video_plate, bg=options.chroma)
    if options.end_reference is not None:
        create_video_plate(paths.end_reference, paths.end_video_plate, bg=options.chroma)
    if options.existing_video:
        require_file(options.existing_video, "existing video")
        shutil.copy2(options.existing_video, paths.raw_video)
    else:
        video_model_alias = resolve_video_model_for_run(action_preset, options.video_model_alias, end_reference=options.end_reference is not None)
        _run_fal_video(
            paths,
            prompt,
                options.dry_fal,
                video_model_alias,
                _effective_video_duration(
                action,
                resolve_video_model_preset(video_model_alias),
                options.video_duration,
                ),
                seed=options.seed,
                end_image=paths.end_video_plate if options.end_reference is not None else None,
            )
        outputs = sorted(paths.fal_dir.glob("fal-video-output-*"))
        if not outputs:
            raise ValueError("fal video run did not produce a downloaded media file")
        shutil.copy2(outputs[0], paths.raw_video)

    video_model_alias = resolve_video_model_for_run(action_preset, options.video_model_alias, end_reference=options.end_reference is not None)
    extract_video_frames(paths.raw_video, paths.extracted_dense_dir, run_dir=paths.root, events_path=paths.events_jsonl)
    select_frames(
        paths.extracted_dense_dir,
        paths.selected_dir,
        frame_count,
        options.selected_order,
        options.selected_range,
        action=action,
        timing=action_preset.timing,
        selection_policy=action_preset.selection_policy,
        video_model_alias=video_model_alias,
        cycle_start_fraction=options.cycle_start_fraction,
        cycle_span_factor=options.cycle_span_factor,
        metadata_path=paths.selection_manifest,
    )
    build_selected_contact_sheet(paths.selected_dir, paths.review_selected_contact)
    build_selected_preview_gif(paths.selected_dir, paths.review_selected_preview, duration_ms=round(1000 / fps))
    if _video_preserve_canvas_default(action, options.video_layout_mode):
        _preserve_video_canvas_review_export(paths, frame_count, options)
    else:
        crop_video_foreground_frames(paths.selected_dir, paths.recovered_dir)
        _normalize_review_export(paths, paths.recovered_dir, frame_count, source_glob="frame-*.png")


def _video_preserve_canvas_default(action: str, layout_mode: str | None = None) -> bool:
    if layout_mode == "preserve-canvas":
        return True
    if layout_mode == "fit-foreground":
        return False
    return True


def _preserve_video_canvas_review_export(paths: RunPaths, frame_count: int, options: RunOptions) -> None:
    rows = sheet_rows(frame_count)
    order = ",".join(f"{index:02d}" for index in range(1, frame_count + 1))
    durations = ",".join(["120"] * frame_count)

    chroma_keyed_dir = paths.root / "chroma-keyed"
    paths.recovered_dir.mkdir(parents=True, exist_ok=True)
    remove_chroma_or_corner_background_batch(
        paths.selected_dir,
        chroma_keyed_dir,
        chroma_rgb=_chroma_rgb(options.chroma),
        min_component_area=4,
    )
    cleanup_source = chroma_keyed_dir
    chroma_rgb = _chroma_rgb(options.chroma)
    fringe_cleanup = options.green_fringe_cleanup and is_keyable_fringe_chroma(chroma_rgb)
    fringe_metadata_path: Path | None = None
    if fringe_cleanup:
        _, fringe_metadata_path = remove_fringe_batch(
            chroma_keyed_dir,
            paths.recovered_dir,
            chroma_rgb=chroma_rgb,
            min_level=options.green_fringe_min_green,
            dominance=options.green_fringe_dominance,
            edge_radius=options.green_fringe_edge_radius,
            min_component_area=4,
        )
        cleanup_source = paths.recovered_dir
    else:
        for frame in sorted(chroma_keyed_dir.glob("frame-*.png")):
            shutil.copy2(frame, paths.recovered_dir / frame.name)
    if fringe_cleanup:
        despill_chroma_batch(cleanup_source, cleanup_source, chroma_rgb=chroma_rgb)
    build_before_after_contact_sheet(
        paths.selected_dir,
        cleanup_source,
        paths.review_dir / "compare-01-selected-to-canvas-cleaned.png",
        before_label="Before: selected video frames",
        after_label="After: full-canvas background cleanup",
    )
    _layout_video_canvas_frames(
        cleanup_source,
        paths.normalized_dir,
        chroma=options.chroma,
        chroma_rgb=chroma_rgb,
        green_fringe_cleanup=False,
        green_fringe_min_green=options.green_fringe_min_green,
        green_fringe_dominance=options.green_fringe_dominance,
        green_fringe_edge_radius=options.green_fringe_edge_radius,
        source_key_metadata=chroma_keyed_dir / "background-key-metadata.json",
        source_fringe_metadata=fringe_metadata_path,
    )
    build_before_after_contact_sheet(
        cleanup_source,
        paths.normalized_dir,
        paths.review_dir / "compare-02-canvas-cleaned-to-runtime.png",
        before_label="Before: cleaned full video canvas",
        after_label=f"After: preserve-canvas runtime cells {FRAME_WIDTH}x{FRAME_HEIGHT}",
    )

    pack_spritesheet(paths.normalized_dir, paths.export_sheet_raw, frame_count)
    shutil.copy2(paths.export_sheet_raw, paths.export_sheet)
    write_json(
        paths.baseline_report,
        {
            "status": "skipped",
            "reason": "video preserve-canvas export keeps source video framing and does not recenter foreground bboxes",
            "layoutMode": "preserve-canvas",
            "targetFrame": [FRAME_WIDTH, FRAME_HEIGHT],
        },
    )
    append_event(
        paths.events_jsonl,
        "baseline_fix_skipped",
        layoutMode="preserve-canvas",
        reason="top-level video preserves source framing",
    )

    run_command(
        [
            sys.executable,
            str(ANIMATED_SCRIPTS / "build_contact_sheet.py"),
            "--input-dir",
            str(paths.normalized_dir),
            "--glob",
            "frame-*.png",
            "--rows",
            str(rows),
            "--cols",
            str(SHEET_COLUMNS),
            "--out",
            str(paths.review_contact),
            *_contact_sheet_font_args(),
        ],
        stage="build-contact-sheet",
        run_dir=paths.root,
        events_path=paths.events_jsonl,
    )
    run_command(
        [
            sys.executable,
            str(ANIMATED_SCRIPTS / "build_sequence_gif.py"),
            "--input-dir",
            str(paths.normalized_dir),
            "--pattern",
            "frame-{id}.png",
            "--order",
            order,
            "--durations-ms",
            durations,
            "--flat-bg",
            "#f0f0f0",
            "--out",
            str(paths.review_preview),
        ],
        stage="build-review-gif",
        run_dir=paths.root,
        events_path=paths.events_jsonl,
    )
    shutil.copy2(paths.review_preview, paths.export_preview)
    shutil.copy2(paths.normalized_dir / "preserve-canvas-metadata.json", paths.export_dir / "preserve-canvas.json")


def _layout_video_canvas_frames(
    input_dir: Path,
    out_dir: Path,
    *,
    chroma: str = "#00FF00",
    chroma_rgb: tuple[int, int, int] = (0, 255, 0),
    green_fringe_cleanup: bool = True,
    green_fringe_min_green: int = 70,
    green_fringe_dominance: int = 24,
    green_fringe_edge_radius: int = 1,
    source_key_metadata: Path | None = None,
    source_fringe_metadata: Path | None = None,
) -> None:
    frames = sorted(input_dir.glob("frame-*.png"))
    if not frames:
        raise ValueError(f"no frames found in {input_dir}")

    images = [(path, Image.open(path).convert("RGBA")) for path in frames]
    max_w = max(image.width for _path, image in images)
    max_h = max(image.height for _path, image in images)
    scale = min(FRAME_WIDTH / max(1, max_w), FRAME_HEIGHT / max(1, max_h))
    scaled_w = max(1, round(max_w * scale))
    scaled_h = max(1, round(max_h * scale))
    paste_x = (FRAME_WIDTH - scaled_w) // 2
    paste_y = (FRAME_HEIGHT - scaled_h) // 2

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    metadata: dict[str, Any] = {
        "layoutMode": "preserve-canvas",
        "heightNormalization": False,
        "motionPreserved": True,
        "sourceMaxCanvas": [max_w, max_h],
        "cellSize": [FRAME_WIDTH, FRAME_HEIGHT],
        "scale": scale,
        "scaledCanvas": [scaled_w, scaled_h],
        "paste": [paste_x, paste_y],
        "resample": "LANCZOS",
        "videoRecovery": "preserve-canvas",
        "backgroundCleanup": {
            "keyedToTransparentBlack": True,
            "chroma": chroma,
            "chromaRgb": list(chroma_rgb),
            "sourceKeyMetadata": str(source_key_metadata) if source_key_metadata else None,
            "sourceFringeMetadata": str(source_fringe_metadata) if source_fringe_metadata else None,
            "postScaleGreenFringeCleanup": green_fringe_cleanup,
            "minGreen": green_fringe_min_green,
            "dominance": green_fringe_dominance,
            "edgeRadius": green_fringe_edge_radius,
        },
        "frames": [],
    }
    despill = is_keyable_fringe_chroma(chroma_rgb)
    metadata["backgroundCleanup"]["postScaleDespill"] = despill
    for path, image in images:
        scaled = image.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
        post_scale_despill: dict[str, object] | None = None
        if despill:
            scaled, post_scale_despill = despill_chroma(scaled, chroma_rgb=chroma_rgb)
        post_scale_cleanup: dict[str, object] | None = None
        if green_fringe_cleanup:
            scaled, post_scale_cleanup = remove_fringe(
                scaled,
                chroma_rgb=chroma_rgb,
                min_level=green_fringe_min_green,
                dominance=green_fringe_dominance,
                edge_radius=green_fringe_edge_radius,
            )
        canvas = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0, 0))
        canvas.alpha_composite(scaled, (paste_x, paste_y))
        dest = out_dir / path.name
        canvas.save(dest)
        green_audit = _green_transparency_audit(canvas, dominance=green_fringe_dominance) if _is_green_rgb(chroma_rgb) else None
        metadata["frames"].append(
            {
                "input": str(path),
                "output": str(dest),
                "sourceSize": [image.width, image.height],
                "postScaleDespill": post_scale_despill,
                "postScaleGreenFringeCleanup": post_scale_cleanup,
                "greenTransparencyAudit": green_audit,
            }
        )

    write_json(out_dir / "preserve-canvas-metadata.json", metadata)


def _green_transparency_audit(image: Image.Image, *, dominance: int = 24) -> dict[str, int]:
    rgba = image.convert("RGBA")
    hidden_green = 0
    semi_transparent_green = 0
    pixels = rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata()
    for red, green, blue, alpha in pixels:
        if alpha == 0 and green:
            hidden_green += 1
        elif 0 < alpha < 255 and green - max(red, blue) >= dominance:
            semi_transparent_green += 1
    return {
        "hiddenGreenAlphaZeroPixels": hidden_green,
        "semiTransparentGreenFringePixels": semi_transparent_green,
    }


def _run_fal_image(paths: RunPaths, prompt: str, guide: Path, image_size: str, dry_fal: bool, model_alias: str, *, seed: int | None = None) -> None:
    args = [
        sys.executable,
        str(FAL_IMAGE_SCRIPT),
        "--model-alias",
        model_alias,
        "--prompt",
        prompt,
        "--image-file",
        str(paths.direction_anchor),
        "--image-file",
        str(guide),
        "--out-dir",
        str(paths.fal_dir),
        "--filename-prefix",
        "fal-image",
        "--task-slug",
        paths.run_id,
        "--extra-json",
        json.dumps(_custom_image_size_payload(image_size)),
        "--output-format",
        "png",
        "--quality",
        "high",
    ]
    if dry_fal:
        args.append("--dry-run")
    if seed is not None:
        args.extend(["--seed", str(seed)])
    run_command(args, stage="fal-image", run_dir=paths.root, events_path=paths.events_jsonl)


def _custom_image_size_payload(image_size: str) -> dict[str, dict[str, int]]:
    try:
        width_text, height_text = image_size.lower().split("x", maxsplit=1)
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise ValueError(f"custom image size must be WIDTHxHEIGHT, got {image_size!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"custom image size must be positive, got {image_size!r}")
    return {"image_size": {"width": width, "height": height}}


def _run_fal_video(
    paths: RunPaths,
    prompt: str,
    dry_fal: bool,
    video_model: str,
    video_duration: str | None = None,
    *,
    seed: int | None = None,
    end_image: Path | None = None,
) -> None:
    preset = resolve_video_model_preset(video_model)
    if end_image is not None:
        validate_video_end_reference_support(preset, model_alias=video_model)
    extra_json = _video_extra_json(preset, video_duration)
    args = [
        sys.executable,
        str(FAL_VIDEO_SCRIPT),
        "--prompt",
        prompt,
        "--image-file",
        str(paths.video_plate),
        "--out-dir",
        str(paths.fal_dir),
        "--filename-prefix",
        "fal-video",
        "--task-slug",
        paths.run_id,
    ]
    if end_image is not None:
        args.extend(["--end-image-file", str(end_image)])
        if preset.end_image_field:
            args.extend(["--end-image-field", preset.end_image_field])
    if preset.model_alias:
        args.extend(["--model-alias", preset.model_alias])
    if preset.endpoint_id:
        args.extend(["--endpoint-id", preset.endpoint_id])
    duration = _video_duration_arg(preset, video_duration)
    if duration:
        args.extend(["--duration", duration])
    if preset.resolution:
        args.extend(["--resolution", preset.resolution])
    if preset.aspect_ratio:
        args.extend(["--aspect-ratio", preset.aspect_ratio])
    if preset.generate_audio is not None:
        args.extend(["--generate-audio", "true" if preset.generate_audio else "false"])
    if extra_json:
        args.extend(["--extra-json", extra_json])
    if dry_fal:
        args.append("--dry-run")
    if seed is not None:
        args.extend(["--seed", str(seed)])
    run_command(args, stage="fal-video", run_dir=paths.root, events_path=paths.events_jsonl)


def _run_record_video_duration(preset: VideoModelPreset | None, override: str | None) -> str | None:
    if preset is None:
        return None
    if _is_wan_turbo_preset(preset):
        payload = _wan_turbo_frame_payload(override, preset)
        seconds = payload["num_frames"] / payload["frames_per_second"]
        return f"{seconds:.3f}s via {payload['num_frames']} frames at {payload['frames_per_second']}fps"
    return _video_duration_arg(preset, override)


def _effective_video_duration(action_id: str, preset: VideoModelPreset, override: str | None) -> str | None:
    if override is not None:
        return override
    if preset.id == "grok-imagine-video-i2v" and action_id == "walk":
        return "2"
    return None


def _video_duration_arg(preset: VideoModelPreset, override: str | None) -> str | None:
    if _is_wan_turbo_preset(preset):
        return None
    duration = override or preset.duration
    if duration is None:
        return None
    _validate_duration_choice(preset, duration)
    return duration


def _video_extra_json(preset: VideoModelPreset, override: str | None) -> str | None:
    payload = json.loads(preset.extra_json) if preset.extra_json else {}
    if _is_wan_turbo_preset(preset):
        payload.update(_wan_turbo_frame_payload(override, preset))
    return json.dumps(payload, separators=(",", ":")) if payload else None


def _is_wan_turbo_preset(preset: VideoModelPreset) -> bool:
    return preset.endpoint_id == "fal-ai/wan/v2.2-a14b/image-to-video/turbo"


def _wan_turbo_frame_payload(override: str | None, preset: VideoModelPreset) -> dict[str, int]:
    if override is None:
        return {
            "num_frames": WAN_TURBO_SHORT_NUM_FRAMES,
            "frames_per_second": WAN_TURBO_FRAMES_PER_SECOND,
        }
    try:
        seconds = float(override)
    except ValueError as exc:
        raise ValueError(f"{preset.id} duration override must be seconds, got {override!r}") from exc
    if seconds <= 0:
        raise ValueError(f"{preset.id} duration override must be positive, got {override!r}")
    frames = round(seconds * WAN_TURBO_FRAMES_PER_SECOND)
    if frames < 17 or frames > 161:
        raise ValueError(
            f"{preset.id} duration override {override!r} maps to {frames} frames; "
            "WAN turbo supports 17 to 161 frames"
        )
    return {"num_frames": frames, "frames_per_second": WAN_TURBO_FRAMES_PER_SECOND}


def _validate_duration_choice(preset: VideoModelPreset, duration: str) -> None:
    choices = {
        "seedance-2.0-i2v": ("auto",) + tuple(str(value) for value in range(4, 16)),
        "wan-2.7": tuple(str(value) for value in range(2, 16)),
        "grok-imagine-video-i2v": tuple(str(value) for value in range(1, 16)),
    }.get(preset.id)
    if choices and str(duration) not in choices:
        allowed = ", ".join(choices)
        raise ValueError(f"{preset.id} supports video durations: {allowed}")


def _with_action_context(prompt: str, action_context: str | None) -> str:
    if not action_context or not action_context.strip():
        return prompt
    cleaned = " ".join(action_context.strip().split())
    return f"""{prompt.rstrip()}

Additional user action note:
- {cleaned}

Apply the additional note only to the character action. Do not change the character identity, direction, camera, background, sheet layout, frame size, or output format.
"""


def _size_contract_run_record(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    if not contract:
        return None
    return {
        "name": contract.get("name"),
        "runtimeCell": contract.get("runtimeCell"),
        "targetVisibleHeight": contract.get("targetVisibleHeight"),
        "maxVisibleWidth": contract.get("maxVisibleWidth"),
        "targetBottomY": contract.get("targetBottomY"),
        "targetCenterX": contract.get("targetCenterX"),
        "pivot": contract.get("pivot"),
        "anchorPolicy": contract.get("anchorPolicy"),
    }


def _recover_normalize_review_export(paths: RunPaths, frame_count: int, *, pose_board: PoseBoardPreset) -> None:
    _crop_pose_board_cells(paths.generated_sheet, paths.grid_review_cells_dir, frame_count=frame_count, pose_board=pose_board)
    build_selected_contact_sheet(paths.grid_review_cells_dir, paths.review_dir / "grid-review-cell-contact.png")
    build_selected_preview_gif(paths.grid_review_cells_dir, paths.review_dir / "grid-review-cell-preview.gif")
    append_event(paths.events_jsonl, "grid_review_cells_cropped", sheet=str(paths.generated_sheet), outDir=str(paths.grid_review_cells_dir))
    recover_chroma_components_from_sheet(
        paths.generated_sheet,
        paths.recovered_dir,
        rows=pose_board.rows,
        cols=pose_board.columns,
        count=frame_count,
        min_component_area=500,
    )
    build_selected_contact_sheet(paths.recovered_dir, paths.review_dir / "recovered-component-contact.png")
    build_before_after_contact_sheet(
        paths.grid_review_cells_dir,
        paths.recovered_dir,
        paths.review_dir / "compare-01-grid-review-to-recovered-components.png",
        before_label="Before: rough grid review crops",
        after_label="After: recovered foreground components",
    )
    append_event(paths.events_jsonl, "pose_components_recovered", sheet=str(paths.generated_sheet), outDir=str(paths.recovered_dir))
    native_canvas = _build_recovered_native_review(paths, frame_count, pose_board=pose_board)
    append_event(
        paths.events_jsonl,
        "recovered_native_review_built",
        inputDir=str(paths.recovered_dir),
        outputDir=str(paths.recovered_native_frames_dir),
        canvas=f"{native_canvas[0]}x{native_canvas[1]}",
    )
    normalization_source = paths.recovered_dir
    pixel_snap_enabled = _run_options_pixel_snap(paths)
    if pixel_snap_enabled:
        pixel_snap_source = _run_options_pixel_snap_source(paths)
        snap_input_dir = paths.recovered_dir
        if pixel_snap_source in {"chroma-layout", "transparent-layout"}:
            _build_pixel_snap_layout_frames(
                paths.recovered_dir,
                paths.pixel_snap_source_dir,
                frame_count,
                canvas_size=native_canvas,
                chroma=_run_options_chroma(paths),
                transparent=pixel_snap_source == "transparent-layout",
            )
            build_selected_contact_sheet(paths.pixel_snap_source_dir, paths.review_dir / "pixel-snap-chroma-source-contact.png")
            append_event(paths.events_jsonl, "pixel_snap_layout_source_built", outputDir=str(paths.pixel_snap_source_dir), source=pixel_snap_source)
            snap_input_dir = paths.pixel_snap_source_dir
        _pixel_snap_recovered_frames(
            snap_input_dir,
            paths.pixel_snapped_native_dir,
            k_colors=_run_options_k_colors(paths),
            run_dir=paths.root,
            events_path=paths.events_jsonl,
        )
        normalization_source = paths.pixel_snapped_native_dir
        if pixel_snap_source == "chroma-layout":
            remove_chroma_or_corner_background_batch(
                paths.pixel_snapped_native_dir,
                paths.pixel_snapped_keyed_dir,
                chroma_rgb=_run_options_chroma_rgb(paths),
                min_component_area=8,
            )
            build_before_after_contact_sheet(
                paths.pixel_snapped_native_dir,
                paths.pixel_snapped_keyed_dir,
                paths.review_dir / "compare-04-pixel-snapped-chroma-to-keyed.png",
                before_label="Before: raw pixel-snap output",
                after_label="After: background-cleaned snapped output",
            )
            normalization_source = paths.pixel_snapped_keyed_dir
            append_event(paths.events_jsonl, "pixel_snapped_background_cleaned", outputDir=str(paths.pixel_snapped_keyed_dir))
            if _run_options_green_fringe_cleanup(paths) and _run_options_uses_keyable_chroma(paths):
                remove_fringe_batch(
                    paths.pixel_snapped_keyed_dir,
                    paths.pixel_snapped_fringe_cleaned_dir,
                    chroma_rgb=_run_options_chroma_rgb(paths),
                    min_level=_run_options_green_fringe_min_green(paths),
                    dominance=_run_options_green_fringe_dominance(paths),
                    edge_radius=_run_options_green_fringe_edge_radius(paths),
                    min_component_area=8,
                )
                build_before_after_contact_sheet(
                    paths.pixel_snapped_keyed_dir,
                    paths.pixel_snapped_fringe_cleaned_dir,
                    paths.review_dir / "compare-05-background-cleaned-to-green-fringe-cleaned.png",
                    before_label="Before: background-cleaned snapped output",
                    after_label="After: matte fringe sweep",
                )
                normalization_source = paths.pixel_snapped_fringe_cleaned_dir
                append_event(paths.events_jsonl, "pixel_snapped_green_fringe_cleaned", outputDir=str(paths.pixel_snapped_fringe_cleaned_dir))
        elif pixel_snap_source == "transparent-layout":
            append_event(paths.events_jsonl, "pixel_snapped_transparent_layout_used", outputDir=str(paths.pixel_snapped_native_dir))
        _build_pixel_snapped_raw_review(paths, frame_count, pixel_snap_source=pixel_snap_source)
        append_event(paths.events_jsonl, "pixel_snapped_raw_review_built", inputDir=str(paths.pixel_snapped_native_dir))
    else:
        append_event(paths.events_jsonl, "pixel_snap_skipped")
    _normalize_review_export(paths, normalization_source, frame_count, source_glob="frame-*.png", skip_bg_remove=True)
    if pixel_snap_enabled:
        _build_pixel_snap_runtime_comparison(paths, frame_count, pixel_snap_source=_run_options_pixel_snap_source(paths))
        append_event(paths.events_jsonl, "pixel_snap_runtime_comparison_built")


def _build_recovered_native_review(paths: RunPaths, frame_count: int, *, pose_board: PoseBoardPreset) -> tuple[int, int]:
    canvas = _pad_native_frames(
        paths.recovered_dir,
        paths.recovered_native_frames_dir,
        frame_count=frame_count,
        min_size=_native_review_min_size(pose_board),
    )
    build_selected_contact_sheet(paths.recovered_native_frames_dir, paths.review_dir / "recovered-native-contact.png")
    build_selected_preview_gif(
        paths.recovered_native_frames_dir,
        paths.review_dir / "recovered-native-preview.gif",
        max_size=canvas,
    )
    build_before_after_contact_sheet(
        paths.recovered_dir,
        paths.recovered_native_frames_dir,
        paths.review_dir / "compare-02-recovered-to-native-layout.png",
        before_label="Before: recovered variable-size components",
        after_label=f"After: padded native review frames {canvas[0]}x{canvas[1]}",
    )
    return canvas


def _build_pixel_snap_layout_frames(
    input_dir: Path,
    out_dir: Path,
    frame_count: int,
    *,
    canvas_size: tuple[int, int] = (384, 384),
    chroma: str = "#00FF00",
    transparent: bool = False,
    margin: int = 8,
) -> list[Path]:
    frames = sorted(input_dir.glob("frame-*.png"))[:frame_count]
    if len(frames) != frame_count:
        raise ValueError(f"expected {frame_count} recovered frames in {input_dir}, found {len(frames)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    images = [(frame, Image.open(frame).convert("RGBA")) for frame in frames]
    max_w = max(image.width for _frame, image in images)
    max_h = max(image.height for _frame, image in images)
    available_w = canvas_size[0] - margin * 2
    available_h = canvas_size[1] - margin * 2
    shared_scale = min(1.0, available_w / max_w, available_h / max_h)

    bg = (0, 0, 0, 0) if transparent else ImageColor.getrgb(chroma) + (255,)
    outputs = []
    center_x = canvas_size[0] // 2
    bottom_y = canvas_size[1] - margin
    records = []
    for frame, source_image in images:
        image = source_image
        if shared_scale < 1.0:
            image = image.resize(
                (
                    max(1, round(image.width * shared_scale)),
                    max(1, round(image.height * shared_scale)),
                ),
                Image.Resampling.NEAREST,
            )
        canvas = Image.new("RGBA", canvas_size, bg)
        x = center_x - image.width // 2
        y = bottom_y - image.height
        if x < 0 or y < 0 or x + image.width > canvas_size[0] or y + image.height > canvas_size[1]:
            raise ValueError(f"{frame} does not fit on chroma layout canvas {canvas_size} after shared scale {shared_scale:.4f}")
        canvas.alpha_composite(image, (x, y))
        out = out_dir / frame.name
        canvas.save(out)
        outputs.append(out)
        records.append(
            {
                "source": str(frame),
                "output": str(out),
                "sourceSize": list(source_image.size),
                "placedSize": list(image.size),
                "canvasSize": list(canvas_size),
                "offset": [x, y],
                "background": "transparent" if transparent else chroma,
            }
        )

    write_json(
        out_dir / "metadata.json",
        {
            "version": 1,
            "mode": "pixel-snap-transparent-layout-source" if transparent else "pixel-snap-chroma-layout-source",
            "description": (
                f"Recovered components placed on a shared transparent {canvas_size[0]}x{canvas_size[1]} native canvas before real pixel-snapper processing."
                if transparent
                else f"Recovered components placed on a shared opaque {canvas_size[0]}x{canvas_size[1]} chroma native canvas before real pixel-snapper processing."
            ),
            "canvasSize": list(canvas_size),
            "background": "transparent" if transparent else chroma,
            "placement": {"centerX": center_x, "bottomY": bottom_y, "margin": margin},
            "sourceMaxSize": [max_w, max_h],
            "availableSize": [available_w, available_h],
            "sharedScale": shared_scale,
            "frames": records,
        },
    )
    return outputs


def _build_pixel_snapped_raw_review(paths: RunPaths, frame_count: int, *, pixel_snap_source: str) -> None:
    build_native_size_contact_sheet(paths.pixel_snapped_native_dir, paths.review_dir / "pixel-snapped-raw-contact.png", scale=4)
    before_dir = paths.pixel_snap_source_dir if pixel_snap_source in {"chroma-layout", "transparent-layout"} else paths.recovered_dir
    source_canvas = _pixel_snap_source_canvas_label(paths)
    before_label = {
        "chroma-layout": f"Before: {source_canvas} chroma canvas",
        "transparent-layout": f"Before: {source_canvas} transparent canvas",
    }.get(pixel_snap_source, "Before: recovered variable-size components")
    build_before_after_contact_sheet(
        before_dir,
        paths.pixel_snapped_native_dir,
        paths.review_dir / "compare-03-recovered-to-pixel-snapped-raw.png",
        before_label=before_label,
        after_label="After: raw pixel-snap outputs",
    )


def _pixel_snap_recovered_frames(
    input_dir: Path,
    out_dir: Path,
    *,
    k_colors: int,
    run_dir: Path,
    events_path: Path,
) -> None:
    require_file(PIXEL_SNAPPER_SCRIPT, "pixel-snapper script")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()
    for frame in sorted(input_dir.glob("frame-*.png")):
        run_command(
            [
                sys.executable,
                str(PIXEL_SNAPPER_SCRIPT),
                str(frame),
                str(out_dir / frame.name),
                "--k-colors",
                str(k_colors),
            ],
            stage=f"pixel-snap-{frame.stem}",
            run_dir=run_dir,
            events_path=events_path,
        )


def _build_pixel_snap_runtime_comparison(paths: RunPaths, frame_count: int, *, pixel_snap_source: str) -> Path:
    recovered = sorted(paths.recovered_dir.glob("frame-*.png"))[:frame_count]
    layout_lookup = {path.name: path for path in sorted(paths.pixel_snap_source_dir.glob("frame-*.png"))}
    snapped_lookup = {path.name: path for path in sorted(paths.pixel_snapped_native_dir.glob("frame-*.png"))}
    keyed_lookup = {path.name: path for path in sorted(paths.pixel_snapped_keyed_dir.glob("frame-*.png"))}
    fringe_lookup = {path.name: path for path in sorted(paths.pixel_snapped_fringe_cleaned_dir.glob("frame-*.png"))}
    normalized_lookup = {path.name: path for path in sorted(paths.normalized_dir.glob("frame-*.png"))}
    rows: list[tuple[str, str]] = [("Recovered", "recovered"), ("Raw pixel snap output x4", "snapped")]
    if pixel_snap_source in {"chroma-layout", "transparent-layout"}:
        source_canvas = _pixel_snap_source_canvas_label(paths)
        rows = [
            ("Recovered", "recovered"),
            (f"{source_canvas} chroma canvas" if pixel_snap_source == "chroma-layout" else f"{source_canvas} transparent canvas", "layout"),
            ("Raw pixel snap output x4", "snapped"),
        ]
        if pixel_snap_source == "chroma-layout":
            rows.append(("Background-cleaned snapped output x4", "keyed"))
            if fringe_lookup:
                rows.append(("Green-fringe-cleaned output x4", "fringe"))
    rows.append(("Final 256x256", "runtime"))

    records = []
    for path in recovered:
        name = path.name
        if name not in snapped_lookup or name not in normalized_lookup:
            continue
        if pixel_snap_source in {"chroma-layout", "transparent-layout"} and name not in layout_lookup:
            continue
        if pixel_snap_source == "chroma-layout" and name not in keyed_lookup:
            continue
        if pixel_snap_source == "chroma-layout" and fringe_lookup and name not in fringe_lookup:
            continue
        records.append(
            {
                "name": path.stem,
                "recovered": path,
                "layout": layout_lookup.get(name),
                "snapped": snapped_lookup[name],
                "keyed": keyed_lookup.get(name),
                "fringe": fringe_lookup.get(name),
                "runtime": normalized_lookup[name],
            }
        )
    if len(records) != frame_count:
        raise ValueError(f"expected {frame_count} pixel snap comparison records, found {len(records)}")

    gutter = 12
    left_label_w = 150
    frame_label_h = 28
    stage_label_h = 24
    recovered_h = 170
    runtime_size = 256
    snap_scale = 4
    font = _review_font(size=15)
    small_font = _review_font(size=13)

    columns: list[dict[str, object]] = []
    for record in records:
        rendered: dict[str, Image.Image] = {}
        sizes: dict[str, tuple[int, int]] = {}
        for _label, key in rows:
            image = Image.open(record[key]).convert("RGBA")  # type: ignore[arg-type]
            sizes[key] = image.size
            if key == "runtime":
                rendered[key] = image.resize((runtime_size, runtime_size), Image.Resampling.NEAREST)
            elif key in {"snapped", "keyed", "fringe"}:
                rendered[key] = image.resize((image.width * snap_scale, image.height * snap_scale), Image.Resampling.NEAREST)
            else:
                rendered[key] = _resize_to_height(image, recovered_h)
        col_w = max([120, *[image.width for image in rendered.values()]])
        columns.append({"name": record["name"], "images": rendered, "sizes": sizes, "width": col_w})

    row_heights = {
        "recovered": recovered_h,
        "layout": recovered_h,
        "snapped": max(column["images"]["snapped"].height for column in columns),  # type: ignore[index]
        "keyed": max(column["images"]["keyed"].height for column in columns) if pixel_snap_source == "chroma-layout" else 0,  # type: ignore[index]
        "fringe": max(column["images"]["fringe"].height for column in columns) if any(key == "fringe" for _label, key in rows) else 0,  # type: ignore[index]
        "runtime": runtime_size,
    }
    width = left_label_w + sum(int(column["width"]) for column in columns) + gutter * (len(columns) + 1)
    height = frame_label_h + sum(stage_label_h + row_heights[key] for _label, key in rows) + gutter * (len(rows) + 2)
    sheet = Image.new("RGBA", (width, height), (18, 18, 18, 255))
    draw = ImageDraw.Draw(sheet)

    y_frame = gutter
    row_positions: dict[str, tuple[int, int]] = {}
    y = y_frame + frame_label_h
    for label, key in rows:
        label_y = y
        image_y = label_y + stage_label_h
        row_positions[key] = (label_y, image_y)
        draw.text((gutter, label_y), label, fill=(238, 238, 238, 255), font=font)
        y = image_y + row_heights[key] + gutter

    x = left_label_w + gutter
    for column in columns:
        col_w = int(column["width"])
        draw.text((x, y_frame), str(column["name"]), fill=(238, 238, 238, 255), font=font)
        for _label, key in rows:
            label_y, image_y = row_positions[key]
            image = column["images"][key]  # type: ignore[index]
            source_w, source_h = column["sizes"][key]  # type: ignore[index]
            draw.text((x, label_y), f"{source_w}x{source_h}", fill=(180, 180, 180, 255), font=small_font)
            sheet.alpha_composite(image, (x + (col_w - image.width) // 2, image_y))
        x += col_w + gutter

    out = paths.review_dir / "compare-04-pixel-snap-to-runtime.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def _pixel_snap_source_canvas_label(paths: RunPaths) -> str:
    metadata_path = paths.pixel_snap_source_dir / "metadata.json"
    if metadata_path.exists():
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            canvas = data.get("canvasSize")
            if isinstance(canvas, list) and len(canvas) == 2:
                return f"{canvas[0]}x{canvas[1]}"
        except json.JSONDecodeError:
            pass
    run_json = paths.run_json
    if run_json.exists():
        try:
            data = json.loads(run_json.read_text(encoding="utf-8"))
            cell = data.get("imageGenerationCellSize")
            if isinstance(cell, list) and len(cell) == 2:
                return f"{cell[0]}x{cell[1]}"
        except json.JSONDecodeError:
            pass
    return "384x384"


def _native_review_min_size(pose_board: PoseBoardPreset) -> tuple[int, int]:
    return (
        max(NATIVE_REVIEW_FRAME_WIDTH, pose_board.cell_width),
        max(NATIVE_REVIEW_FRAME_HEIGHT, pose_board.cell_height),
    )


def _pad_native_frames(
    input_dir: Path,
    out_dir: Path,
    *,
    frame_count: int,
    min_size: tuple[int, int],
    metadata_path: Path | None = None,
    margin: int = 8,
) -> tuple[int, int]:
    frames = sorted(input_dir.glob("frame-*.png"))[:frame_count]
    if len(frames) != frame_count:
        raise ValueError(f"expected {frame_count} recovered frames in {input_dir}, found {len(frames)}")

    images = [(path, Image.open(path).convert("RGBA")) for path in frames]
    max_w = max(image.width for _path, image in images)
    max_h = max(image.height for _path, image in images)
    canvas_w = _round_up(max(min_size[0], max_w + margin * 2), 16)
    canvas_h = _round_up(max(min_size[1], max_h + margin * 2), 16)
    center_x = canvas_w // 2
    bottom_y = canvas_h - margin

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    records: list[dict[str, object]] = []
    for path, image in images:
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        x = center_x - image.width // 2
        y = bottom_y - image.height
        canvas.alpha_composite(image, (x, y))
        dest = out_dir / path.name
        canvas.save(dest)
        records.append(
            {
                "source": str(path),
                "output": str(dest),
                "sourceSize": [image.width, image.height],
                "canvasSize": [canvas_w, canvas_h],
                "offset": [x, y],
            }
        )

    write_json(
        metadata_path or (out_dir.parent / "metadata.json"),
        {
            "version": 1,
            "mode": "padded-native-review",
            "description": "Recovered components placed on a shared padded canvas without scaling.",
            "canvasSize": [canvas_w, canvas_h],
            "minCanvasSize": [min_size[0], min_size[1]],
            "placement": {"centerX": center_x, "bottomY": bottom_y},
            "frames": records,
        },
    )
    return (canvas_w, canvas_h)


def _resize_to_height(image: Image.Image, height: int) -> Image.Image:
    scale = height / image.height
    return image.resize((max(1, round(image.width * scale)), height), Image.Resampling.NEAREST)


def _review_font(*, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return review_font(size=size)


def _round_up(value: int, multiple: int) -> int:
    return ((value + multiple - 1) // multiple) * multiple


def _crop_pose_board_cells(sheet: Path, out_dir: Path, *, frame_count: int, pose_board: PoseBoardPreset) -> list[Path]:
    image = Image.open(sheet).convert("RGBA")
    expected = (pose_board.width, pose_board.height)
    if image.size != expected:
        raise ValueError(
            f"generated pose board must be {expected[0]}x{expected[1]}, got {image.width}x{image.height}"
        )
    total_cells = pose_board.total_cells
    if frame_count > total_cells:
        raise ValueError(f"pose board has {total_cells} cells, need at least {frame_count}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs: list[Path] = []
    for index in range(frame_count):
        col = index % pose_board.columns
        row = index // pose_board.columns
        crop = image.crop(
            (
                col * pose_board.cell_width,
                row * pose_board.cell_height,
                (col + 1) * pose_board.cell_width,
                (row + 1) * pose_board.cell_height,
            )
        )
        out = out_dir / f"frame-{index + 1:02d}.png"
        crop.save(out)
        outputs.append(out)
    return outputs


def _normalize_review_export(
    paths: RunPaths,
    source_dir: Path,
    frame_count: int,
    source_glob: str,
    *,
    skip_bg_remove: bool = False,
) -> None:
    rows = sheet_rows(frame_count)
    order = ",".join(f"{index:02d}" for index in range(1, frame_count + 1))
    durations = ",".join(["120"] * frame_count)
    cleanup_source = source_dir
    bg_remove = _run_options_bg_remove(paths)
    if skip_bg_remove:
        append_event(paths.events_jsonl, "background_removal_skipped", reason="source frames are already recovered or background-cleaned components")
    elif bg_remove == "chroma":
        remove_chroma_batch(source_dir, paths.chroma_dir, glob=source_glob, chroma_rgb=_run_options_chroma_rgb(paths))
        cleanup_source = paths.chroma_dir
        source_glob = "frame-*.png"
    elif bg_remove == "bria":
        remove_background_batch(
            source_dir,
            paths.bg_removed_dir,
            run_dir=paths.root,
            events_path=paths.events_jsonl,
            glob=source_glob,
        )
        cleanup_source = paths.bg_removed_dir
        source_glob = "frame-*.png"

    if cleanup_source != source_dir:
        build_before_after_contact_sheet(
            source_dir,
            cleanup_source,
            paths.review_dir / "compare-01-cells-to-bg-removed.png",
            glob=source_glob,
            before_label="Before: raw recovered cells",
            after_label=f"After: {bg_remove} background removal",
        )
    scale_mode, allow_upscale = _normalization_scale_policy(paths)
    scale_frame_crops(
        cleanup_source,
        paths.scaled_dir,
        glob=source_glob,
        mode=scale_mode,
        allow_upscale=allow_upscale,
    )
    build_before_after_contact_sheet(
        cleanup_source,
        paths.scaled_dir,
        paths.review_dir / "compare-02-cleaned-to-scaled.png",
        before_label="Before: cleaned cells",
        after_label="After: scaled layout input",
    )

    run_command(
        [
            sys.executable,
            str(ANIMATED_SCRIPTS / "normalize_frames.py"),
            "--input-dir",
            str(paths.scaled_dir),
            "--out-dir",
            str(paths.normalized_dir),
            "--glob",
            "frame-*.png",
            "--canvas",
            f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
            "--center-x",
            str(TARGET_CENTER_X),
            "--bottom-y",
            str(TARGET_BOTTOM_Y),
            "--flat-bg",
            "#f0f0f0",
        ],
        stage="normalize-frames",
        run_dir=paths.root,
        events_path=paths.events_jsonl,
    )
    build_before_after_contact_sheet(
        paths.scaled_dir,
        paths.normalized_dir,
        paths.review_dir / "compare-03-scaled-to-normalized.png",
        before_label="Before: scaled layout input",
        after_label=f"After: normalized {FRAME_WIDTH}x{FRAME_HEIGHT} cells",
    )

    pack_spritesheet(paths.normalized_dir, paths.export_sheet_raw, frame_count)
    run_command(
        [
            sys.executable,
            str(GAMEDEV_SCRIPTS / "asset_sprite_baseline.py"),
            str(paths.export_sheet_raw),
            "--frame",
            f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
            "--target-bottom",
            str(TARGET_BOTTOM_Y),
            "--target-center-x",
            str(TARGET_CENTER_X),
            "--out",
            str(paths.export_sheet),
            "--json",
            str(paths.baseline_report),
        ],
        stage="baseline-audit-fix",
        run_dir=paths.root,
        events_path=paths.events_jsonl,
    )

    run_command(
        [
            sys.executable,
            str(ANIMATED_SCRIPTS / "build_contact_sheet.py"),
            "--input-dir",
            str(paths.normalized_dir),
            "--glob",
            "frame-*.png",
            "--rows",
            str(rows),
            "--cols",
            str(SHEET_COLUMNS),
            "--out",
            str(paths.review_contact),
            *_contact_sheet_font_args(),
        ],
        stage="build-contact-sheet",
        run_dir=paths.root,
        events_path=paths.events_jsonl,
    )
    run_command(
        [
            sys.executable,
            str(ANIMATED_SCRIPTS / "build_sequence_gif.py"),
            "--input-dir",
            str(paths.normalized_dir),
            "--pattern",
            "frame-{id}.png",
            "--order",
            order,
            "--durations-ms",
            durations,
            "--flat-bg",
            "#f0f0f0",
            "--out",
            str(paths.review_preview),
        ],
        stage="build-review-gif",
        run_dir=paths.root,
        events_path=paths.events_jsonl,
    )
    shutil.copy2(paths.review_preview, paths.export_preview)


def _run_options_bg_remove(paths: RunPaths) -> str:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
    except Exception:
        return "none"
    return str(data.get("bgRemove", "none"))


def _normalization_scale_policy(paths: RunPaths) -> tuple[str, bool]:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
    except Exception:
        return "shared", False
    action = str(data.get("action", ""))
    if action == "idle":
        return "per-frame", True
    return "shared", True


def _run_options_pixel_snap(paths: RunPaths) -> bool:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(data.get("pixelSnap", False))


def _run_options_pixel_snap_source(paths: RunPaths) -> str:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
    except Exception:
        return "recovered"
    return _resolve_pixel_snap_source(str(data.get("pixelSnapSource", "recovered")))


def _run_options_k_colors(paths: RunPaths) -> int:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
        value = int(data.get("kColors", 256))
    except Exception:
        return 256
    return max(1, value)


def _run_options_chroma(paths: RunPaths) -> str:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
    except Exception:
        return "#00FF00"
    return str(data.get("chroma", "#00FF00"))


def _run_options_chroma_rgb(paths: RunPaths) -> tuple[int, int, int]:
    return _chroma_rgb(_run_options_chroma(paths))


def _run_options_uses_keyable_chroma(paths: RunPaths) -> bool:
    """Whether the run's matte color supports chroma-aware fringe cleanup."""
    return is_keyable_fringe_chroma(_run_options_chroma_rgb(paths))


def _run_options_green_fringe_cleanup(paths: RunPaths) -> bool:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
    except Exception:
        return True
    return bool(data.get("greenFringeCleanup", True))


def _run_options_green_fringe_min_green(paths: RunPaths) -> int:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
        value = int(data.get("greenFringeMinGreen", 70))
    except Exception:
        return 70
    return max(0, min(255, value))


def _run_options_green_fringe_dominance(paths: RunPaths) -> int:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
        value = int(data.get("greenFringeDominance", 24))
    except Exception:
        return 24
    return max(0, min(255, value))


def _run_options_green_fringe_edge_radius(paths: RunPaths) -> int:
    try:
        data = json.loads(paths.run_json.read_text(encoding="utf-8"))
        value = int(data.get("greenFringeEdgeRadius", 1))
    except Exception:
        return 1
    return max(1, value)


def _resolve_pixel_snap_source(value: str) -> str:
    if value not in {"recovered", "chroma-layout", "transparent-layout"}:
        raise ValueError("pixel_snap_source must be recovered, chroma-layout, or transparent-layout")
    return value


def _resolve_bg_remove_option(value: str, mode: str) -> str:
    if value == "auto":
        return "chroma" if mode == "image" else "none"
    if value not in {"none", "chroma", "bria"}:
        raise ValueError("bg_remove must be auto, none, chroma, or bria")
    return value


def _chroma_rgb(value: str) -> tuple[int, int, int]:
    try:
        rgb = ImageColor.getrgb(value)
    except ValueError as exc:
        raise ValueError(f"invalid --chroma color {value!r}; use a CSS color such as #00FF00 or #FF00FF") from exc
    if len(rgb) == 4:
        return (rgb[0], rgb[1], rgb[2])
    return rgb


def _is_green_rgb(rgb: tuple[int, int, int]) -> bool:
    red, green, blue = rgb
    return green >= 180 and green - max(red, blue) >= 80


def _contact_sheet_font_args() -> list[str]:
    """``--font-path`` args for build_contact_sheet, or empty when none exist.

    Omitting the flag lets the subprocess fall back to ``load_default()`` rather
    than receiving a path that does not exist (e.g. on Windows).
    """
    path = contact_sheet_font_path()
    return ["--font-path", path] if path is not None else []
