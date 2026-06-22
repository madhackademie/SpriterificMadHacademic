from __future__ import annotations

import json
import math
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor

from .chroma import (
    despill_chroma,
    despill_chroma_batch,
    is_keyable_fringe_chroma,
    remove_chroma_batch,
    remove_fringe_batch,
)
from .commands import run_command
from .events import append_event, now_iso, write_json
from .frame_clean import CleanFrameOptions, clean_frame_batch
from .media import build_before_after_contact_sheet, build_selected_contact_sheet, build_selected_preview_gif
from .pack import pack_spritesheet
from .pipeline import ANIMATED_SCRIPTS, GAMEDEV_SCRIPTS
from .pixel_snap import PIXEL_SNAPPER_SCRIPT
from .presets import FRAME_HEIGHT, FRAME_WIDTH, SHEET_COLUMNS, TARGET_BOTTOM_Y, TARGET_CENTER_X
from .review_index import ReviewAsset, write_review_index
from .runtime_tools.pixel_snapper.scripts.pixel_snapper import (
    Config as PixelSnapperConfig,
    discover_grid,
    grid_to_dict,
    resample_with_grid,
)
from .scale import scale_frame_crops
from .size_contract import audit_size_contract, load_size_contract
from .validate import require_file


@dataclass(frozen=True)
class PostSelectionOptions:
    picker_dir: Path
    out_dir: Path
    action: str = "walk"
    direction: str = "w"
    columns: int = SHEET_COLUMNS
    fps: int = 10
    k_colors: int = 256
    chroma: str = "#00FF00"
    chroma_threshold: float = 90.0
    chroma_min_component_area: int = 4
    green_fringe_cleanup: bool = True
    green_fringe_min_green: int = 70
    green_fringe_dominance: int = 24
    cell_size: tuple[int, int] = (FRAME_WIDTH, FRAME_HEIGHT)
    target_height: int | None = None
    max_width: int | None = None
    center_x: int | None = None
    ground_y: int | None = None
    layout_mode: str = "preserve-canvas"
    scale_mode: str = "per-frame"
    allow_upscale: bool = True
    review_upscale: int = 4
    pixel_snap: bool = False
    pixel_snap_workers: int = 1
    pixel_snap_mode: str = "discover-per-frame"
    pixel_snap_grid_source: str | None = None
    size_contract: Path | None = None
    size_contract_strict: bool = False


def default_post_selection_output_dir(picker_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return picker_dir / "post-selection" / stamp


def process_frame_picker_selection(options: PostSelectionOptions) -> Path:
    picker_dir = options.picker_dir
    selected_dir = picker_dir / "selected"
    if not selected_dir.exists():
        raise ValueError(f"missing selected frame directory: {selected_dir}")
    selected_frames = sorted(selected_dir.glob("frame-*.png"))
    if not selected_frames:
        raise ValueError(f"no selected frames found in {selected_dir}")
    if options.columns <= 0:
        raise ValueError("columns must be positive")
    cell_w, cell_h = options.cell_size
    if cell_w <= 0 or cell_h <= 0:
        raise ValueError("cell size must be positive")
    if options.layout_mode not in {"preserve-canvas", "fit-foreground"}:
        raise ValueError("layout mode must be preserve-canvas or fit-foreground")
    if options.pixel_snap_mode not in {"discover-per-frame", "locked-grid"}:
        raise ValueError("pixel snap mode must be discover-per-frame or locked-grid")
    if not options.pixel_snap and options.pixel_snap_mode != "discover-per-frame":
        raise ValueError("--pixel-snap-mode requires --pixel-snap")
    if options.pixel_snap_grid_source and options.pixel_snap_mode != "locked-grid":
        raise ValueError("--pixel-snap-grid-source requires --pixel-snap-mode locked-grid")
    size_contract = load_size_contract(options.size_contract) if options.size_contract else None
    if size_contract and options.cell_size == (FRAME_WIDTH, FRAME_HEIGHT):
        contract_cell = size_contract.get("runtimeCell")
        if isinstance(contract_cell, (list, tuple)) and len(contract_cell) == 2:
            cell_w, cell_h = int(contract_cell[0]), int(contract_cell[1])
    target_height = options.target_height or _contract_int(size_contract, "targetVisibleHeight") or max(1, round(cell_h * 0.82))
    max_width = options.max_width or _contract_int(size_contract, "maxVisibleWidth") or max(1, round(cell_w * 0.86))
    center_x = options.center_x if options.center_x is not None else _contract_int(size_contract, "targetCenterX") or cell_w // 2
    ground_y = options.ground_y if options.ground_y is not None else _contract_int(size_contract, "targetBottomY") or max(0, cell_h - max(8, round(cell_h * 0.0625)))
    preserve_canvas_resample = None
    if options.layout_mode == "preserve-canvas":
        preserve_canvas_resample = "NEAREST" if options.pixel_snap else "LANCZOS"
    chroma_rgb = _chroma_rgb(options.chroma)
    green_fringe_cleanup = options.green_fringe_cleanup and is_keyable_fringe_chroma(chroma_rgb)

    out_dir = options.out_dir
    events_path = out_dir / "events.jsonl"
    raw_dir = out_dir / "raw-selected"
    snapped_dir = out_dir / "pixel-snapped" / "native"
    chroma_dir = out_dir / "chroma-keyed"
    defringed_dir = out_dir / "green-fringe-cleaned"
    cleaned_dir = out_dir / "cleaned"
    scaled_dir = out_dir / "scaled"
    normalized_dir = out_dir / f"frames-{cell_w}x{cell_h}"
    export_dir = out_dir / "export"
    review_dir = out_dir / "review"
    logs_dir = out_dir / "logs"
    for directory in (raw_dir, snapped_dir, chroma_dir, defringed_dir, cleaned_dir, scaled_dir, normalized_dir, export_dir, review_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    run_record: dict[str, Any] = {
        "version": 1,
        "kind": "post-selection",
        "createdAt": now_iso(),
        "status": "running",
        "pickerDir": str(picker_dir),
        "outDir": str(out_dir),
        "action": options.action,
        "direction": options.direction,
        "selectedFrameCount": len(selected_frames),
        "columns": options.columns,
        "rows": math.ceil(len(selected_frames) / options.columns),
        "fps": options.fps,
        "pixelSnap": options.pixel_snap,
        "pixelSnapWorkers": options.pixel_snap_workers,
        "pixelSnapMode": options.pixel_snap_mode,
        "pixelSnapGridSource": options.pixel_snap_grid_source,
        "sizeContract": str(options.size_contract) if options.size_contract else None,
        "sizeContractStrict": options.size_contract_strict,
        "kColors": options.k_colors,
        "chroma": options.chroma,
        "chromaRgb": list(chroma_rgb),
        "cellSize": [cell_w, cell_h],
        "targetHeight": target_height,
        "maxWidth": max_width,
        "centerX": center_x,
        "groundY": ground_y,
        "layoutMode": options.layout_mode,
        "heightNormalization": options.layout_mode == "fit-foreground",
        "motionPreserved": options.layout_mode == "preserve-canvas",
        "scaleMode": options.scale_mode,
        "allowUpscale": options.allow_upscale,
        "preserveCanvasResample": preserve_canvas_resample,
        "preScaleGreenFringeCleanup": green_fringe_cleanup,
        "postScaleGreenFringeCleanup": False,
        "runtimeGreenCleanup": False,
        "chromaThreshold": options.chroma_threshold,
        "chromaMinComponentArea": options.chroma_min_component_area,
        "greenFringeCleanup": options.green_fringe_cleanup,
        "greenFringeCleanupEffective": green_fringe_cleanup,
        "greenFringeMinGreen": options.green_fringe_min_green,
        "greenFringeDominance": options.green_fringe_dominance,
        "despillCleanup": green_fringe_cleanup and not options.pixel_snap,
    }
    if size_contract:
        run_record["sizeContractResolved"] = {
            "name": size_contract.get("name"),
            "targetVisibleHeight": size_contract.get("targetVisibleHeight"),
            "maxVisibleWidth": size_contract.get("maxVisibleWidth"),
            "targetBottomY": size_contract.get("targetBottomY"),
            "targetCenterX": size_contract.get("targetCenterX"),
            "pivot": size_contract.get("pivot"),
            "anchorPolicy": size_contract.get("anchorPolicy"),
        }
    write_json(out_dir / "post-selection.json", run_record)
    append_event(events_path, "post_selection_started", pickerDir=str(picker_dir))

    try:
        frame_map = _copy_raw_selected(selected_frames, raw_dir)
        source_canvas = _first_frame_size(raw_dir) or (256, 256)
        raw_contact = build_selected_contact_sheet(raw_dir, review_dir / "raw-selected-contact.png")
        raw_preview = build_selected_preview_gif(
            raw_dir,
            review_dir / "raw-selected-preview.gif",
            duration_ms=round(1000 / options.fps),
            max_size=source_canvas,
        )

        pixel_snap_grid_path: Path | None = None
        if options.pixel_snap:
            pixel_snap_grid_path = _pixel_snap_frames(raw_dir, snapped_dir, options=options, run_dir=out_dir, events_path=events_path)
        else:
            _copy_frame_dir(raw_dir, snapped_dir)
            append_event(events_path, "pixel_snap_skipped")

        compare_raw_to_cleanup_input = build_before_after_contact_sheet(
            raw_dir,
            snapped_dir,
            review_dir / "compare-01-raw-to-cleanup-input.png",
            before_label="Before: raw selected frames",
            after_label="After: cleanup input" if not options.pixel_snap else "After: pixel-snapped cleanup input",
        )
        snapped_contact = build_selected_contact_sheet(snapped_dir, review_dir / "snapped-native-contact.png")
        snapped_preview = build_selected_preview_gif(
            snapped_dir,
            review_dir / "snapped-native-preview.gif",
            duration_ms=round(1000 / options.fps),
            max_size=source_canvas,
        )

        remove_chroma_batch(
            snapped_dir,
            chroma_dir,
            chroma_rgb=chroma_rgb,
            threshold=options.chroma_threshold,
            min_component_area=options.chroma_min_component_area,
        )
        compare_cleanup_input_to_chroma = build_before_after_contact_sheet(
            snapped_dir,
            chroma_dir,
            review_dir / "compare-02-cleanup-input-to-chroma-keyed.png",
            before_label="Before: cleanup input",
            after_label="After: chroma keyed",
        )
        cleanup_source = chroma_dir
        if green_fringe_cleanup:
            remove_fringe_batch(
                chroma_dir,
                defringed_dir,
                chroma_rgb=chroma_rgb,
                min_level=options.green_fringe_min_green,
                dominance=options.green_fringe_dominance,
                min_component_area=options.chroma_min_component_area,
            )
            cleanup_source = defringed_dir
        else:
            _copy_frame_dir(chroma_dir, defringed_dir)
        compare_chroma_to_fringe = build_before_after_contact_sheet(
            chroma_dir,
            defringed_dir,
            review_dir / "compare-03-chroma-keyed-to-fringe-cleaned.png",
            before_label="Before: chroma keyed",
            after_label="After: fringe cleaned",
        )
        clean_frame_batch(
            cleanup_source,
            cleaned_dir,
            options=CleanFrameOptions(
                min_component_area=options.chroma_min_component_area,
                trim=options.layout_mode == "fit-foreground",
            ),
        )
        compare_fringe_to_cleaned = build_before_after_contact_sheet(
            cleanup_source,
            cleaned_dir,
            review_dir / "compare-04-fringe-cleaned-to-component-cleaned.png",
            before_label="Before: fringe cleaned",
            after_label="After: component cleaned",
        )
        despill_cleanup = green_fringe_cleanup and not options.pixel_snap
        if despill_cleanup:
            despill_chroma_batch(cleaned_dir, cleaned_dir, chroma_rgb=chroma_rgb)
            append_event(events_path, "despill_applied", inputDir=str(cleaned_dir), chroma=options.chroma)
        if options.layout_mode == "preserve-canvas":
            preserve_resample = Image.Resampling.NEAREST if options.pixel_snap else Image.Resampling.LANCZOS
            _layout_preserve_canvas_frames(
                cleaned_dir,
                normalized_dir,
                cell_size=(cell_w, cell_h),
                resample=preserve_resample,
                chroma_rgb=chroma_rgb if despill_cleanup else None,
            )
            _copy_frame_dir(cleaned_dir, scaled_dir)
            append_event(events_path, "preserve_canvas_layout", inputDir=str(cleaned_dir), outputDir=str(normalized_dir))
        else:
            scale_frame_crops(
                cleaned_dir,
                scaled_dir,
                target_height=target_height,
                max_width=max_width,
                mode=options.scale_mode,
                allow_upscale=options.allow_upscale,
            )
            _normalize_scaled_frames(
                scaled_dir,
                normalized_dir,
                cell_size=(cell_w, cell_h),
                center_x=center_x,
                ground_y=ground_y,
                run_dir=out_dir,
                events_path=events_path,
            )
        compare_cleaned_to_scaled = build_before_after_contact_sheet(
            cleaned_dir,
            scaled_dir,
            review_dir / "compare-05-cleaned-to-layout-input.png",
            before_label="Before: component cleaned",
            after_label="After: layout input",
        )
        compare_scaled_to_runtime = build_before_after_contact_sheet(
            scaled_dir,
            normalized_dir,
            review_dir / "compare-06-layout-input-to-runtime-cells.png",
            before_label="Before: layout input",
            after_label=f"After: runtime cells {cell_w}x{cell_h}",
        )
        size_contract_audit_path: Path | None = None
        size_contract_audit: dict[str, Any] | None = None
        if size_contract:
            size_contract_audit_path = out_dir / "size-contract-audit.json"
            size_contract_audit = audit_size_contract(
                normalized_dir,
                size_contract,
                out=size_contract_audit_path,
                cell_size=(cell_w, cell_h),
                stage="runtime-frames",
            )
            append_event(
                events_path,
                "size_contract_audited",
                status=size_contract_audit["status"],
                passed=size_contract_audit["passed"],
                audit=str(size_contract_audit_path),
            )
            if options.size_contract_strict and not size_contract_audit["passed"]:
                raise ValueError(f"size contract audit failed; see {size_contract_audit_path}")

        sheet_raw = pack_spritesheet(
            normalized_dir,
            export_dir / "spritesheet.raw.png",
            len(selected_frames),
            cell_size=(cell_w, cell_h),
            columns=options.columns,
        )
        if options.layout_mode == "preserve-canvas":
            sheet = export_dir / "spritesheet.png"
            shutil.copy2(sheet_raw, sheet)
            write_json(
                export_dir / "baseline-report.json",
                {
                    "status": "skipped",
                    "reason": "preserve-canvas layout keeps the source video camera framing and does not recenter foreground bboxes",
                    "cellSize": [cell_w, cell_h],
                },
            )
            append_event(events_path, "baseline_fix_skipped", layoutMode=options.layout_mode)
        else:
            sheet = _baseline_fix(
                sheet_raw,
                export_dir / "spritesheet.png",
                export_dir / "baseline-report.json",
                cell_size=(cell_w, cell_h),
                center_x=center_x,
                ground_y=ground_y,
                run_dir=out_dir,
                events_path=events_path,
            )
        preview = build_selected_preview_gif(
            normalized_dir,
            export_dir / "preview.gif",
            duration_ms=round(1000 / options.fps),
            max_size=(cell_w, cell_h),
        )
        review_sheet = _upscale_image(sheet, review_dir / f"spritesheet-{cell_w}x{cell_h}-{options.columns}x{math.ceil(len(selected_frames) / options.columns)}-x{options.review_upscale}.png", options.review_upscale)
        review_preview = build_selected_preview_gif(
            normalized_dir,
            review_dir / f"preview-{len(selected_frames)}f-{cell_w}x{cell_h}.gif",
            duration_ms=round(1000 / options.fps),
            max_size=(cell_w, cell_h),
        )
        normalized_contact = build_selected_contact_sheet(normalized_dir, review_dir / "normalized-contact.png")

        aligner_command = (
            "uv run spriterrific frame-aligner "
            f"--input-dir {normalized_dir} "
            f"--columns {options.columns} "
            f"--fps {options.fps} "
            "--zoom 3"
        )
        report = {
            **run_record,
            "status": "completed",
            "completedAt": now_iso(),
            "sourceSelection": _read_selection_json(picker_dir),
            "frames": frame_map,
            "artifacts": {
                "rawSelectedDir": str(raw_dir),
                "pixelSnappedNativeDir": str(snapped_dir),
                "pixelSnapGrid": str(pixel_snap_grid_path) if pixel_snap_grid_path else None,
                "chromaKeyedDir": str(chroma_dir),
                "greenFringeCleanedDir": str(defringed_dir),
                "cleanedDir": str(cleaned_dir),
                "scaledDir": str(scaled_dir),
                "runtimeFramesDir": str(normalized_dir),
                "spritesheetRaw": str(sheet_raw),
                "spritesheet": str(sheet),
                "previewGif": str(preview),
                "baselineReport": str(export_dir / "baseline-report.json"),
                "reviewIndex": str(review_dir / "index.md"),
                "rawSelectedContact": str(raw_contact),
                "rawSelectedPreview": str(raw_preview),
                "snappedNativeContact": str(snapped_contact),
                "snappedNativePreview": str(snapped_preview),
                "normalizedContact": str(normalized_contact),
                "reviewSpritesheet": str(review_sheet),
                "reviewPreviewGif": str(review_preview),
                "compareRawToCleanupInput": str(compare_raw_to_cleanup_input),
                "compareCleanupInputToChroma": str(compare_cleanup_input_to_chroma),
                "compareChromaToFringe": str(compare_chroma_to_fringe),
                "compareFringeToCleaned": str(compare_fringe_to_cleaned),
                "compareCleanedToScaled": str(compare_cleaned_to_scaled),
                "compareScaledToRuntime": str(compare_scaled_to_runtime),
                "sizeContractAudit": str(size_contract_audit_path) if size_contract_audit_path else None,
            },
            "sizeContractAudit": size_contract_audit,
            "handoff": {
                "frameAlignerCommand": aligner_command,
                "frameAlignerInputDir": str(normalized_dir),
            },
        }
        write_json(out_dir / "post-selection.json", report)
        _write_report_md(out_dir / "report.md", report)
        review_index = _write_review_index(
            review_dir=review_dir,
            out_dir=out_dir,
            report=report,
            report_path=out_dir / "report.md",
            json_path=out_dir / "post-selection.json",
            raw_contact=raw_contact,
            raw_preview=raw_preview,
            snapped_contact=snapped_contact,
            snapped_preview=snapped_preview,
            normalized_contact=normalized_contact,
            review_preview=review_preview,
            review_sheet=review_sheet,
            sheet=sheet,
            aligner_command=aligner_command,
        )
        report["artifacts"]["reviewIndex"] = str(review_index)
        write_json(out_dir / "post-selection.json", report)
        append_event(events_path, "post_selection_completed", report=str(out_dir / "post-selection.json"))
        return out_dir / "post-selection.json"
    except Exception as exc:
        run_record.update({"status": "failed", "failedAt": now_iso(), "error": str(exc)})
        write_json(out_dir / "post-selection.json", run_record)
        append_event(events_path, "post_selection_failed", error=str(exc))
        raise


def _copy_raw_selected(selected_frames: list[Path], raw_dir: Path) -> list[dict[str, object]]:
    for old in raw_dir.glob("frame-*.png"):
        old.unlink()
    records = []
    for index, source in enumerate(selected_frames, start=1):
        dest = raw_dir / f"frame-{index:02d}.png"
        shutil.copy2(source, dest)
        records.append({"output": dest.name, "source": str(source), "sourceName": source.name})
    return records


def _copy_frame_dir(input_dir: Path, out_dir: Path) -> None:
    for old in out_dir.glob("frame-*.png"):
        old.unlink()
    for source in sorted(input_dir.glob("frame-*.png")):
        shutil.copy2(source, out_dir / source.name)


def _layout_preserve_canvas_frames(
    input_dir: Path,
    out_dir: Path,
    *,
    cell_size: tuple[int, int],
    resample: Image.Resampling = Image.Resampling.LANCZOS,
    chroma_rgb: tuple[int, int, int] | None = None,
) -> list[Path]:
    """Fit frames onto runtime cells, despilling matte tint reintroduced by LANCZOS resampling.

    When ``chroma_rgb`` is a keyable matte and ``resample`` is LANCZOS, each
    scaled frame is despilled so resampled edge pixels do not keep matte tint.
    Passing ``chroma_rgb=None`` (or a NEAREST resample) preserves the original
    behavior.
    """
    frames = sorted(input_dir.glob("frame-*.png"))
    if not frames:
        raise ValueError(f"no frames found in {input_dir}")

    images = [(path, Image.open(path).convert("RGBA")) for path in frames]
    max_w = max(image.width for _path, image in images)
    max_h = max(image.height for _path, image in images)
    cell_w, cell_h = cell_size
    scale = min(cell_w / max(1, max_w), cell_h / max(1, max_h))
    scaled_w = max(1, round(max_w * scale))
    scaled_h = max(1, round(max_h * scale))
    paste_x = (cell_w - scaled_w) // 2
    paste_y = (cell_h - scaled_h) // 2

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    lanczos = resample == Image.Resampling.LANCZOS
    despill = lanczos and chroma_rgb is not None and is_keyable_fringe_chroma(chroma_rgb)

    outputs: list[Path] = []
    metadata = {
        "layoutMode": "preserve-canvas",
        "sourceMaxCanvas": [max_w, max_h],
        "cellSize": [cell_w, cell_h],
        "scale": scale,
        "scaledCanvas": [scaled_w, scaled_h],
        "paste": [paste_x, paste_y],
        "resample": getattr(resample, "name", str(resample)),
        "postScaleDespill": despill,
        "frames": [],
    }
    for path, image in images:
        scaled = image.resize((scaled_w, scaled_h), resample)
        if despill:
            scaled, _despill_record = despill_chroma(scaled, chroma_rgb=chroma_rgb)
        canvas = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
        canvas.alpha_composite(scaled, (paste_x, paste_y))
        dest = out_dir / path.name
        canvas.save(dest)
        outputs.append(dest)
        metadata["frames"].append(
            {
                "input": str(path),
                "output": str(dest),
                "sourceSize": [image.width, image.height],
            }
        )

    (out_dir / "preserve-canvas-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs


def _pixel_snap_frames(raw_dir: Path, snapped_dir: Path, *, options: PostSelectionOptions, run_dir: Path, events_path: Path) -> Path | None:
    require_file(PIXEL_SNAPPER_SCRIPT, "pixel-snapper script")
    for old in snapped_dir.glob("frame-*.png"):
        old.unlink()
    grid_metadata = snapped_dir / "pixel-snap-grid.json"
    if grid_metadata.exists():
        grid_metadata.unlink()
    frames = sorted(raw_dir.glob("frame-*.png"))
    workers = max(1, min(options.pixel_snap_workers, len(frames) or 1))
    append_event(events_path, "pixel_snap_batch_started", frames=len(frames), workers=workers, mode=options.pixel_snap_mode)
    if options.pixel_snap_mode == "locked-grid":
        grid_path = _pixel_snap_frames_locked_grid(
            frames,
            snapped_dir,
            options=options,
            workers=workers,
            events_path=events_path,
        )
        append_event(events_path, "pixel_snap_batch_completed", frames=len(frames), workers=workers, mode=options.pixel_snap_mode)
        return grid_path

    def snap(frame: Path) -> None:
        run_command(
            [
                sys.executable,
                str(PIXEL_SNAPPER_SCRIPT),
                str(frame),
                str(snapped_dir / frame.name),
                "--k-colors",
                str(options.k_colors),
            ],
            stage=f"pixel-snap-{frame.stem}",
            run_dir=run_dir,
            events_path=events_path,
        )

    if workers == 1:
        for frame in frames:
            snap(frame)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(snap, frame): frame for frame in frames}
            for future in as_completed(futures):
                future.result()
    append_event(events_path, "pixel_snap_batch_completed", frames=len(frames), workers=workers, mode=options.pixel_snap_mode)
    return None


def _pixel_snap_frames_locked_grid(
    frames: list[Path],
    snapped_dir: Path,
    *,
    options: PostSelectionOptions,
    workers: int,
    events_path: Path,
) -> Path:
    if not frames:
        raise ValueError("no frames to pixel snap")
    reference = _resolve_pixel_snap_grid_source(frames, options.pixel_snap_grid_source)
    cfg = PixelSnapperConfig(k_colors=options.k_colors)
    grid = discover_grid(reference, cfg)
    grid_path = snapped_dir / "pixel-snap-grid.json"
    append_event(
        events_path,
        "pixel_snap_locked_grid_discovered",
        source=str(reference),
        outputSize=list(grid.output_size),
        sourceSize=[grid.source_width, grid.source_height],
    )

    def snap(frame: Path) -> dict[str, object]:
        out = snapped_dir / frame.name
        out_size = resample_with_grid(frame, out, cfg, grid)
        return {"frame": frame.name, "source": str(frame), "output": str(out), "outputSize": list(out_size)}

    if workers == 1:
        records = [snap(frame) for frame in frames]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(snap, frame): frame for frame in frames}
            records = [future.result() for future in as_completed(futures)]
        records.sort(key=lambda record: str(record["frame"]))

    metadata = {
        "version": 1,
        "mode": "locked-grid",
        "kColors": options.k_colors,
        "gridSource": str(reference),
        "grid": grid_to_dict(grid),
        "frames": records,
    }
    write_json(grid_path, metadata)
    return grid_path


def _resolve_pixel_snap_grid_source(frames: list[Path], requested: str | None) -> Path:
    if not requested:
        return frames[0]
    requested_path = Path(requested)
    if requested_path.exists():
        return requested_path
    requested_name = requested_path.name
    for frame in frames:
        if frame.name == requested_name:
            return frame
    raise ValueError(f"pixel snap grid source not found in selected frames: {requested}")


def _normalize_scaled_frames(
    scaled_dir: Path,
    normalized_dir: Path,
    *,
    cell_size: tuple[int, int],
    center_x: int,
    ground_y: int,
    run_dir: Path,
    events_path: Path,
) -> None:
    cell_w, cell_h = cell_size
    run_command(
        [
            sys.executable,
            str(ANIMATED_SCRIPTS / "normalize_frames.py"),
            "--input-dir",
            str(scaled_dir),
            "--out-dir",
            str(normalized_dir),
            "--glob",
            "frame-*.png",
            "--canvas",
            f"{cell_w}x{cell_h}",
            "--center-x",
            str(center_x),
            "--bottom-y",
            str(ground_y),
            "--flat-bg",
            "#f0f0f0",
        ],
        stage="normalize-frames",
        run_dir=run_dir,
        events_path=events_path,
    )


def _remove_green_dominant_in_place(input_dir: Path, *, min_green: int, dominance: int) -> None:
    records: list[dict[str, object]] = []
    for frame in sorted(input_dir.glob("frame-*.png")):
        image = Image.open(frame).convert("RGBA")
        px = image.load()
        removed = 0
        for y in range(image.height):
            for x in range(image.width):
                r, g, b, a = px[x, y]
                if a and g >= min_green and g - max(r, b) >= dominance:
                    px[x, y] = (0, 0, 0, 0)
                    removed += 1
        image.save(frame)
        records.append({"frame": frame.name, "removedGreenDominantPixels": removed})
    (input_dir / "runtime-green-cleanup.json").write_text(
        json.dumps(
            {
                "minGreen": min_green,
                "dominance": dominance,
                "frames": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _baseline_fix(
    sheet_raw: Path,
    sheet: Path,
    report: Path,
    *,
    cell_size: tuple[int, int],
    center_x: int,
    ground_y: int,
    run_dir: Path,
    events_path: Path,
) -> Path:
    cell_w, cell_h = cell_size
    run_command(
        [
            sys.executable,
            str(GAMEDEV_SCRIPTS / "asset_sprite_baseline.py"),
            str(sheet_raw),
            "--frame",
            f"{cell_w}x{cell_h}",
            "--target-bottom",
            str(ground_y),
            "--target-center-x",
            str(center_x),
            "--out",
            str(sheet),
            "--json",
            str(report),
        ],
        stage="baseline-audit-fix",
        run_dir=run_dir,
        events_path=events_path,
    )
    return sheet


def _upscale_image(source: Path, out: Path, scale: int) -> Path:
    if scale < 1:
        raise ValueError("review upscale must be >= 1")
    image = Image.open(source).convert("RGBA")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST).save(out)
    return out


def _read_selection_json(picker_dir: Path) -> dict[str, Any]:
    for path in (picker_dir / "report.json", picker_dir / "selection.json"):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _write_report_md(path: Path, report: dict[str, Any]) -> None:
    artifacts = report["artifacts"]
    source_size = _first_frame_size(Path(artifacts["rawSelectedDir"]))
    sheet_size = _image_size(Path(artifacts["spritesheet"]))
    cell_w, cell_h = report["cellSize"]
    lines = [
        "# Post-Selection Processing Report",
        "",
        f"Picker folder: `{report['pickerDir']}`",
        f"Action: `{report['action']}`",
        f"Direction: `{report['direction']}`",
        f"Frames: `{report['selectedFrameCount']}`",
        f"Pixel snap: `{report['pixelSnap']}`",
        f"Pixel snap mode: `{report.get('pixelSnapMode', 'discover-per-frame')}`",
        f"Source selected frame size: `{_format_size(source_size)}`",
        f"Runtime cell size: `{cell_w}x{cell_h}`",
        f"Runtime layout: `{report['columns']}x{report['rows']}`",
        f"Runtime spritesheet size: `{_format_size(sheet_size)}`",
        f"Target visible height: `{report['targetHeight']}`",
        f"Max visible width: `{report['maxWidth']}`",
        f"Anchor center x: `{report['centerX']}`",
        f"Ground/bottom y: `{report['groundY']}`",
        f"Layout mode: `{report['layoutMode']}`",
        f"Scale mode: `{report['scaleMode']}`",
        "",
        "## Outputs",
        "",
        f"- Runtime frames: `{artifacts['runtimeFramesDir']}`",
        f"- Spritesheet: `{artifacts['spritesheet']}`",
        f"- Preview GIF: `{artifacts['previewGif']}`",
        f"- Review index: `{artifacts['reviewIndex']}`",
    ]
    if artifacts.get("pixelSnapGrid"):
        lines.append(f"- Pixel snap locked grid: `{artifacts['pixelSnapGrid']}`")
    if artifacts.get("sizeContractAudit"):
        lines.append(f"- Size contract audit: `{artifacts['sizeContractAudit']}`")
    lines.extend(
        [
            "",
            "## Frame Aligner Handoff",
            "",
            "```bash",
            report["handoff"]["frameAlignerCommand"],
            "```",
            "",
            "## Frame Map",
            "",
        ]
    )
    for frame in report["frames"]:
        lines.append(f"- `{frame['output']}` <- `{frame['sourceName']}`")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_review_index(
    *,
    review_dir: Path,
    out_dir: Path,
    report: dict[str, Any],
    report_path: Path,
    json_path: Path,
    raw_contact: Path,
    raw_preview: Path,
    snapped_contact: Path,
    snapped_preview: Path,
    normalized_contact: Path,
    review_preview: Path,
    review_sheet: Path,
    sheet: Path,
    aligner_command: str,
) -> Path:
    artifacts = report["artifacts"]
    cell_w, cell_h = report["cellSize"]
    source_size = _first_frame_size(Path(artifacts["rawSelectedDir"]))
    sheet_size = _image_size(sheet)
    review_sheet_size = _image_size(review_sheet)
    raw_contact_size = _image_size(raw_contact)
    raw_preview_size = _image_size(raw_preview)
    snapped_contact_size = _image_size(snapped_contact)
    snapped_preview_size = _image_size(snapped_preview)
    normalized_contact_size = _image_size(normalized_contact)
    review_preview_size = _image_size(review_preview)
    comparison_assets = _normalization_comparison_assets(artifacts, report)
    layout_description = (
        "full source-canvas preservation"
        if report["layoutMode"] == "preserve-canvas"
        else "foreground-fit normalization"
    )
    snap_description = "pixel snap, " if report["pixelSnap"] else ""
    summary = (
        f"Review page for selected video frames after {snap_description}chroma cleanup, "
        f"{layout_description}, and runtime sheet export. Source frames: `{_format_size(source_size)}`. "
        f"Selected frames: `{report['selectedFrameCount']}`. Runtime cell: `{cell_w}x{cell_h}`. "
        f"Layout: `{report['columns']}x{report['rows']}`. Spritesheet: `{_format_size(sheet_size)}`."
    )
    if report["layoutMode"] == "preserve-canvas":
        layout_note = (
            "Layout mode is `preserve-canvas`: the full selected video frame is scaled into each runtime cell, "
            "so camera framing and apparent scale stay close to the video source."
        )
        normalization_notes = [
            f"Runtime placement: full source canvas scaled and centered into each `{cell_w}x{cell_h}` cell.",
            "Foreground-fit settings such as target height, max width, center x, and ground y are recorded but not applied in preserve-canvas mode.",
            f"Baseline audit is skipped in preserve-canvas mode. Review spritesheet is nearest-neighbor upscaled to `{_format_size(review_sheet_size)}` for inspection.",
        ]
        runtime_sheet_description = (
            f"Final transparent spritesheet. Sheet size is `{_format_size(sheet_size)}` with `{cell_w}x{cell_h}` "
            f"cells in a `{report['columns']}x{report['rows']}` layout. Baseline audit is skipped for preserve-canvas mode."
        )
    else:
        layout_note = (
            "Layout mode is `fit-foreground`: each frame is cropped to the visible sprite and normalized to the "
            "configured center/bottom anchor."
        )
        normalization_notes = [
            f"Target visible height: `{report['targetHeight']}` px; max visible width: `{report['maxWidth']}` px.",
            f"Anchor point: center x `{report['centerX']}`, ground/bottom y `{report['groundY']}` inside each `{cell_w}x{cell_h}` cell.",
            f"Scale mode: `{report['scaleMode']}`. Upscale during normalization: `{report['allowUpscale']}`.",
            f"Review spritesheet is nearest-neighbor upscaled to `{_format_size(review_sheet_size)}` for inspection.",
        ]
        runtime_sheet_description = (
            f"Final transparent spritesheet after baseline audit. Sheet size is `{_format_size(sheet_size)}` with `{cell_w}x{cell_h}` "
            f"cells in a `{report['columns']}x{report['rows']}` layout."
        )
    if report["pixelSnap"] and report.get("pixelSnapMode") == "locked-grid":
        snap_note = (
            "Pixel snapping uses `locked-grid`: one grid is discovered from a selected frame and reused for every frame, "
            "so native snapped frames share one output size before layout."
        )
    elif report["pixelSnap"]:
        snap_note = "Pixel snapping uses `discover-per-frame`: each selected frame discovers its own native grid before layout."
    else:
        snap_note = "Pixel snapping was skipped; selected frames go through chroma cleanup before layout."
    contract_note = None
    if report.get("sizeContract"):
        audit = report.get("sizeContractAudit") or {}
        contract_note = (
            f"Size contract `{report['sizeContract']}` was applied. "
            f"Runtime audit status: `{audit.get('status', 'unknown')}`."
        )
    return write_review_index(
        review_dir,
        title=f"{out_dir.name} Post-Selection Review",
        summary=summary,
        notes=[
            snap_note,
            *([contract_note] if contract_note else []),
            layout_note,
            *normalization_notes,
            f"Frame aligner handoff: `{aligner_command}`",
        ],
        assets=[
            *comparison_assets,
            ReviewAsset(
                "Raw Selected Contact",
                raw_contact,
                f"Human-selected frames copied from the frame picker. Source frames are `{_format_size(source_size)}` each; contact image is `{_format_size(raw_contact_size)}`.",
                True,
            ),
            ReviewAsset(
                "Raw Selected Preview",
                raw_preview,
                f"Human-selected frames looped before processing. GIF canvas is `{_format_size(raw_preview_size)}`.",
                True,
            ),
            ReviewAsset(
                "Pixel-Snapped Native Contact" if report["pixelSnap"] else "Cleanup Input Contact",
                snapped_contact,
                (
                    (
                        f"Native grid recovered by pixel snapper before chroma cleanup. Mode: `{report.get('pixelSnapMode', 'discover-per-frame')}`. "
                        f"Contact image is `{_format_size(snapped_contact_size)}`."
                    )
                    if report["pixelSnap"]
                    else f"Selected frames copied directly because pixel snap was skipped. Contact image is `{_format_size(snapped_contact_size)}`."
                ),
                True,
            ),
            ReviewAsset(
                "Pixel-Snapped Native Preview" if report["pixelSnap"] else "Cleanup Input Preview",
                snapped_preview,
                (
                    f"Pixel-snapped native frames looped before runtime normalization. GIF canvas is `{_format_size(snapped_preview_size)}`."
                    if report["pixelSnap"]
                    else f"Selected frames looped before chroma cleanup and layout. GIF canvas is `{_format_size(snapped_preview_size)}`."
                ),
                True,
            ),
            *(
                [
                    ReviewAsset(
                        "Pixel Snap Locked Grid JSON",
                        Path(artifacts["pixelSnapGrid"]),
                        "Machine-readable locked grid reused across the selected video frames.",
                        False,
                    )
                ]
                if artifacts.get("pixelSnapGrid")
                else []
            ),
            *(
                [
                    ReviewAsset(
                        "Size Contract Audit JSON",
                        Path(artifacts["sizeContractAudit"]),
                        "Machine-readable geometry audit against the chosen size contract.",
                        False,
                    )
                ]
                if artifacts.get("sizeContractAudit")
                else []
            ),
            ReviewAsset(
                "Normalized Contact",
                normalized_contact,
                (
                    f"Cleaned full-canvas frames scaled to `{cell_w}x{cell_h}` runtime cells. Contact image is `{_format_size(normalized_contact_size)}`."
                    if report["layoutMode"] == "preserve-canvas"
                    else f"Cleaned frames normalized to `{cell_w}x{cell_h}` runtime cells. Contact image is `{_format_size(normalized_contact_size)}`."
                ),
                True,
            ),
            ReviewAsset(
                "Normalized Preview GIF",
                review_preview,
                f"Runtime-cell animation preview. GIF canvas is `{_format_size(review_preview_size)}`.",
                True,
            ),
            ReviewAsset(
                "Runtime Spritesheet",
                sheet,
                runtime_sheet_description,
                True,
            ),
            ReviewAsset(
                "Upscaled Runtime Spritesheet",
                review_sheet,
                f"Nearest-neighbor enlarged runtime spritesheet for inspection. Review image size is `{_format_size(review_sheet_size)}`; runtime sheet remains `{_format_size(sheet_size)}`.",
                True,
            ),
            ReviewAsset("Markdown Report", report_path, "Human-readable processing report and frame-aligner handoff command.", False),
            ReviewAsset("JSON Report", json_path, "Machine-readable processing report.", False),
        ],
    )


def _normalization_comparison_assets(artifacts: dict[str, str], report: dict[str, Any]) -> list[ReviewAsset]:
    cell_w, cell_h = report["cellSize"]
    specs = [
        (
            "Comparison 01: Raw Selected To Cleanup Input",
            artifacts.get("compareRawToCleanupInput"),
            "Before/after comparison for the handoff from frame-picker selected frames into the cleanup input.",
        ),
        (
            "Comparison 02: Cleanup Input To Chroma Keyed",
            artifacts.get("compareCleanupInputToChroma"),
            "Before/after comparison for background removal.",
        ),
        (
            "Comparison 03: Chroma Keyed To Fringe Cleaned",
            artifacts.get("compareChromaToFringe"),
            "Before/after comparison for targeted green-fringe cleanup.",
        ),
        (
            "Comparison 04: Fringe Cleaned To Component Cleaned",
            artifacts.get("compareFringeToCleaned"),
            "Before/after comparison for alpha cleanup, small-component removal, and optional foreground trimming.",
        ),
        (
            "Comparison 05: Component Cleaned To Layout Input",
            artifacts.get("compareCleanedToScaled"),
            "Before/after comparison for the scale/layout preparation step.",
        ),
        (
            "Comparison 06: Layout Input To Runtime Cells",
            artifacts.get("compareScaledToRuntime"),
            f"Before/after comparison for final placement into `{cell_w}x{cell_h}` runtime cells.",
        ),
    ]
    assets = []
    for title, value, description in specs:
        if not value:
            continue
        path = Path(value)
        size = _image_size(path)
        assets.append(ReviewAsset(title, path, f"{description} Review image size is `{_format_size(size)}`.", True))
    return assets


def _contract_int(contract: dict[str, Any] | None, key: str) -> int | None:
    if not contract:
        return None
    value = contract.get(key)
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _first_frame_size(frame_dir: Path) -> tuple[int, int] | None:
    first = next(iter(sorted(frame_dir.glob("frame-*.png"))), None)
    if first is None:
        return None
    return _image_size(first)


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


def _chroma_rgb(value: str) -> tuple[int, int, int]:
    try:
        rgb = ImageColor.getrgb(value)
    except ValueError as exc:
        raise ValueError(f"invalid --chroma color {value!r}; use a CSS color such as #00FF00 or #FF00FF") from exc
    if len(rgb) == 4:
        return (rgb[0], rgb[1], rgb[2])
    return rgb


