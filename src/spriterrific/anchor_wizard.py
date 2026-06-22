from __future__ import annotations

import shutil
import sys
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .anchors import AnchorOptions, build_anchor_comparison_sheet, build_anchor_detail_sheet, generate_anchors
from .commands import run_command
from .events import append_event, now_iso, write_json
from .fonts import review_font
from .media import remove_corner_background
from .pipeline import FAL_IMAGE_SCRIPT
from .pixel_snap import SnapOptions, SnapResult, snap_user_anchor
from .presets import DIRECTIONS, REFERENCE_SIZE, resolve_anchor_game_view, resolve_anchor_role
from .review_index import ReviewAsset, write_review_index
from .validate import require_file


CANDIDATE_FACINGS = {"front", "south"}
CANDIDATE_PROMPT_PRESETS = {"lobit-v1", "high-fidelity-v1", "preserve-reference-v1"}
LOBIT_NATIVE_HEIGHT_TARGET = (100, 130)
LOBIT_NATIVE_HEIGHT_MAX = 160


@dataclass(frozen=True)
class AnchorWizardOptions:
    run_dir: Path
    character_id: str = "character"
    stage: str = "candidate"
    source_image: Path | None = None
    source_prompt: str | None = None
    source_prompt_file: Path | None = None
    candidate_image: Path | None = None
    candidate_prompt: str | None = None
    candidate_prompt_file: Path | None = None
    candidate_prompt_preset: str = "lobit-v1"
    pixel_snap_anchor: bool = True
    candidate_facing: str = "front"
    accepted_candidate: Path | None = None
    anchors_dir: Path | None = None
    directions: tuple[str, ...] = ("n", "s", "e", "w")
    dry_fal: bool = False
    source_model_alias: str = "gpt-image-2-t2i"
    candidate_model_alias: str = "gpt-image-2-edit"
    anchor_model_alias: str = "gpt-image-2-edit"
    chroma: str = "#00FF00"
    k_colors: int = 256
    game_view: str = "platformer"
    anchor_role: str = "character"
    anchor_context: str | None = None
    seed: int | None = None


@dataclass(frozen=True)
class AnchorWizardResult:
    run_dir: Path
    character_json: Path
    candidate_anchor: Path | None = None
    anchors: dict[str, Path] | None = None
    review_index: Path | None = None


@dataclass(frozen=True)
class AcceptAnchorOptions:
    run_dir: Path
    direction: str
    source: Path
    reason: str | None = None
    character_id: str | None = None
    candidate_facing: str = "front"
    chroma: str = "#00FF00"
    k_colors: int = 256
    game_view: str = "platformer"
    anchor_role: str = "character"
    anchor_context: str | None = None


def run_anchor_wizard(options: AnchorWizardOptions) -> AnchorWizardResult:
    if options.stage not in {"candidate", "directions", "all"}:
        raise ValueError("stage must be candidate, directions, or all")
    options = _normalize_anchor_wizard_options(options)
    _validate_directions(options.directions)
    _validate_candidate_facing(options.candidate_facing)
    game_view = resolve_anchor_game_view(options.game_view)
    anchor_role = resolve_anchor_role(options.anchor_role)

    options.run_dir.mkdir(parents=True, exist_ok=True)
    events_path = options.run_dir / "events.jsonl"
    append_event(
        events_path,
        "anchor_wizard_started",
        stage=options.stage,
        character=options.character_id,
        candidateFacing=options.candidate_facing,
        pixelSnapAnchor=options.pixel_snap_anchor,
        gameView=game_view,
        anchorRole=anchor_role,
        seed=options.seed,
    )

    candidate_anchor: Path | None = None
    anchors: dict[str, Path] | None = None
    review_index: Path | None = None

    if options.stage in {"candidate", "all"}:
        candidate_anchor = create_candidate_stage(options)
        review_index = write_anchor_wizard_review(options.run_dir)

    if options.stage in {"directions", "all"} and options.directions:
        accepted = options.accepted_candidate or candidate_anchor or existing_candidate_anchor(options.run_dir, options.candidate_facing)
        anchors = create_direction_stage(options, accepted_candidate=accepted)
        review_index = write_anchor_wizard_review(options.run_dir)

    character_json = write_character_manifest(
        options.run_dir,
        character_id=options.character_id,
        stage=options.stage,
        candidate_anchor=candidate_anchor or existing_candidate_anchor(options.run_dir, options.candidate_facing),
        anchors=anchors or _existing_final_anchors(options.run_dir, options.directions),
        options=options,
    )
    append_event(events_path, "anchor_wizard_completed", stage=options.stage, character=options.character_id)
    return AnchorWizardResult(
        run_dir=options.run_dir,
        character_json=character_json,
        candidate_anchor=candidate_anchor,
        anchors=anchors,
        review_index=review_index,
    )


def create_candidate_stage(options: AnchorWizardOptions) -> Path | None:
    source = _resolve_source(options)
    if source is None:
        return None

    candidate_raw = _resolve_candidate(options, source)
    if candidate_raw is None:
        return None

    candidate_dir = candidate_dir_for(options.run_dir, options.candidate_facing)
    raw_path = candidate_dir / "candidate-raw.png"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_raw, raw_path)
    candidate_background = _validate_candidate_background(
        raw_path,
        out=candidate_dir / "candidate-background-check.json",
        chroma=options.chroma,
        strict=_source_model_input_used_alpha_matte(options.run_dir),
    )

    if options.pixel_snap_anchor:
        snap = snap_user_anchor(
            SnapOptions(
                source=raw_path,
                run_dir=candidate_dir / "snap",
                k_colors=options.k_colors,
                chroma=options.chroma,
            )
        )
        if _uses_guarded_lobit_candidate(options):
            _enforce_lobit_snap_contract(snap)
        _copy_snap_aliases(snap, candidate_dir)
        shutil.copy2(snap.anchor, candidate_dir / "anchor-1024.png")
        if snap.chroma_anchor is not None:
            shutil.copy2(snap.chroma_anchor, candidate_dir / "anchor-1024-chroma.png")
        candidate_metadata = {
            "pixelSnapped": True,
            "anchorStyle": options.candidate_prompt_preset,
            "anchor1024": str(candidate_dir / "anchor-1024.png"),
            "anchor1024Chroma": str(candidate_dir / "anchor-1024-chroma.png"),
            "snappedNative": str(candidate_dir / "snapped-native.png"),
            "snapped1024": str(candidate_dir / "snapped-1024.png"),
            "snapped1024Chroma": str(candidate_dir / "snapped-1024-chroma.png"),
            "snapRun": str(snap.run_dir),
            "snappedSize": list(snap.snapped_size),
            "unsnappedTransform": None,
        }
    else:
        variants = _write_unsnapped_anchor_variants(
            raw_path,
            candidate_dir,
            chroma=options.chroma,
            legacy_1024_name="snapped-1024.png",
            legacy_chroma_name="snapped-1024-chroma.png",
        )
        candidate_metadata = {
            "pixelSnapped": False,
            "anchorStyle": options.candidate_prompt_preset,
            "anchor1024": str(variants["anchor"]),
            "anchor1024Chroma": str(variants["chromaAnchor"]),
            "snappedNative": None,
            "snapped1024": str(candidate_dir / "snapped-1024.png"),
            "snapped1024Chroma": str(candidate_dir / "snapped-1024-chroma.png"),
            "snapRun": None,
            "snappedSize": None,
            "unsnappedTransform": variants["metadata"],
        }
    write_json(
        candidate_dir / "candidate.json",
        {
            "version": 1,
            "createdAt": now_iso(),
            "candidateFacing": options.candidate_facing,
            "legacyDirection": "s" if options.candidate_facing == "south" else None,
            "candidateGenerationMode": _candidate_generation_mode(options),
            "raw": str(raw_path),
            **candidate_metadata,
            "kColors": options.k_colors,
            "chroma": options.chroma,
            "seed": options.seed,
            "candidateBackgroundCheck": candidate_background,
        },
    )
    _write_candidate_review(options.run_dir, candidate_dir)
    return candidate_dir / "snapped-1024-chroma.png"


def create_direction_stage(options: AnchorWizardOptions, *, accepted_candidate: Path | None) -> dict[str, Path]:
    if accepted_candidate is None:
        raise ValueError("directions stage requires --accepted-candidate or an existing candidate anchor")
    require_file(accepted_candidate, "accepted candidate")

    anchors: dict[str, Path] = {}
    comparison_pairs: list[tuple[str, Path, Path]] = []

    def publish(direction: str, source_anchor: Path) -> None:
        if direction in anchors:
            return
        raw, final_anchor = _publish_direction_anchor(options, direction, source_anchor)
        anchors[direction] = final_anchor
        comparison_pairs.append((direction, raw, final_anchor))
        _write_direction_review(options, accepted_candidate=accepted_candidate, comparison_pairs=comparison_pairs)
        all_anchors = _existing_final_anchors(options.run_dir, tuple(DIRECTIONS))
        all_anchors.update(anchors)
        write_character_manifest(
            options.run_dir,
            character_id=options.character_id,
            stage="directions",
            candidate_anchor=existing_candidate_anchor(options.run_dir, options.candidate_facing),
            anchors=all_anchors,
            options=options,
        )

    generated_anchors_dir = options.anchors_dir
    if generated_anchors_dir is None:
        generated_root = generate_anchors(
            AnchorOptions(
                reference=accepted_candidate,
                run_dir=options.run_dir / "anchors-nsew",
                directions=options.directions,
                dry_fal=options.dry_fal,
                model_alias=options.anchor_model_alias,
                preprocess=False,
                chroma=options.chroma,
                k_colors=options.k_colors,
                game_view=options.game_view,
                anchor_role=options.anchor_role,
                anchor_context=options.anchor_context,
                on_anchor_generated=publish,
            )
        )
        generated_anchors_dir = generated_root / "anchors"

    for direction in options.directions:
        if direction in anchors:
            continue
        source_anchor = _direction_anchor_source(generated_anchors_dir, direction)
        if source_anchor is None:
            if options.dry_fal:
                continue
            raise FileNotFoundError(f"could not find generated anchor for direction {direction} in {generated_anchors_dir}")
        publish(direction, source_anchor)

    all_anchors = _existing_final_anchors(options.run_dir, tuple(DIRECTIONS))
    all_anchors.update(anchors)
    return all_anchors


def accept_direction_anchor(options: AcceptAnchorOptions) -> Path:
    _validate_directions((options.direction,))
    _validate_candidate_facing(options.candidate_facing)
    game_view = resolve_anchor_game_view(options.game_view)
    anchor_role = resolve_anchor_role(options.anchor_role)
    require_file(options.source, "accepted anchor source")
    _validate_accepted_anchor_image(options.source, chroma=options.chroma)

    character_id = options.character_id or _existing_character_id(options.run_dir)
    direction_dir = options.run_dir / "anchors" / options.direction
    accepted_dir = options.run_dir / "accepted" / options.direction
    direction_dir.mkdir(parents=True, exist_ok=True)
    accepted_dir.mkdir(parents=True, exist_ok=True)

    final_anchor = direction_dir / "anchor-snapped-1024-chroma.png"
    snapped_1024 = direction_dir / "anchor-snapped-1024.png"
    source_copy = direction_dir / "anchor-source.png"
    accepted_copy = accepted_dir / "anchor-snapped-1024-chroma.png"

    shutil.copy2(options.source, final_anchor)
    shutil.copy2(options.source, snapped_1024)
    shutil.copy2(options.source, source_copy)
    shutil.copy2(options.source, accepted_copy)
    if not (direction_dir / "anchor-raw.png").exists():
        shutil.copy2(options.source, direction_dir / "anchor-raw.png")

    acceptance = {
        "version": 1,
        "createdAt": now_iso(),
        "direction": options.direction,
        "source": str(options.source),
        "canonical": str(final_anchor),
        "acceptedCopy": str(accepted_copy),
        "reason": options.reason,
        "gameView": game_view,
        "anchorRole": anchor_role,
        "anchorContext": options.anchor_context,
        "chroma": options.chroma,
        "kColors": options.k_colors,
    }
    write_json(accepted_dir / "acceptance.json", acceptance)
    write_json(
        direction_dir / "anchor.json",
        {
            "version": 1,
            "createdAt": now_iso(),
            "direction": options.direction,
            "acceptedOverride": True,
            "acceptedSource": str(options.source),
            "acceptedCopy": str(accepted_copy),
            "reason": options.reason,
            "snapped1024": str(snapped_1024),
            "snapped1024Chroma": str(final_anchor),
            "snapRun": None,
            "kColors": options.k_colors,
            "chroma": options.chroma,
            "gameView": game_view,
            "anchorRole": anchor_role,
            "anchorContext": options.anchor_context,
        },
    )

    anchors = _existing_final_anchors(options.run_dir, tuple(DIRECTIONS))
    anchors[options.direction] = final_anchor
    character_path = _update_character_manifest_for_acceptance(
        options,
        character_id=character_id,
        anchors=anchors,
        final_anchor=final_anchor,
        accepted_copy=accepted_copy,
        game_view=game_view,
        anchor_role=anchor_role,
    )
    _update_bootstrap_summary_for_acceptance(
        options,
        character_path=character_path,
        final_anchor=final_anchor,
        accepted_copy=accepted_copy,
        game_view=game_view,
        anchor_role=anchor_role,
    )
    write_anchor_wizard_review(options.run_dir)
    append_event(
        options.run_dir / "events.jsonl",
        "direction_anchor_accepted",
        direction=options.direction,
        source=str(options.source),
        canonical=str(final_anchor),
        reason=options.reason,
        gameView=game_view,
        anchorRole=anchor_role,
    )
    return final_anchor


def _publish_direction_anchor(options: AnchorWizardOptions, direction: str, source_anchor: Path) -> tuple[Path, Path]:
    direction_dir = options.run_dir / "anchors" / direction
    direction_dir.mkdir(parents=True, exist_ok=True)
    raw = direction_dir / "anchor-raw.png"
    snap_source = direction_dir / "anchor-source.png"
    display_raw = _direction_raw_sibling(source_anchor, direction) or source_anchor
    source_for_snap = _direction_clean_sibling(source_anchor, direction) or source_anchor
    shutil.copy2(display_raw, raw)
    shutil.copy2(source_for_snap, snap_source)

    final_anchor = direction_dir / "anchor-snapped-1024-chroma.png"
    if options.pixel_snap_anchor:
        snap = snap_user_anchor(
            SnapOptions(
                source=snap_source,
                run_dir=direction_dir / "snap",
                k_colors=options.k_colors,
                chroma=options.chroma,
            )
        )
        _copy_snap_aliases(snap, direction_dir, prefix="anchor")
        shutil.copy2(snap.anchor, direction_dir / "anchor-1024.png")
        if snap.chroma_anchor is not None:
            shutil.copy2(snap.chroma_anchor, direction_dir / "anchor-1024-chroma.png")
        anchor_metadata = {
            "pixelSnapped": True,
            "anchor1024": str(direction_dir / "anchor-1024.png"),
            "anchor1024Chroma": str(direction_dir / "anchor-1024-chroma.png"),
            "snappedNative": str(direction_dir / "anchor-snapped-native.png"),
            "snapped1024": str(direction_dir / "anchor-snapped-1024.png"),
            "snapped1024Chroma": str(final_anchor),
            "snapRun": str(snap.run_dir),
            "snappedSize": list(snap.snapped_size),
            "unsnappedTransform": None,
        }
    else:
        variants = _write_unsnapped_anchor_variants(
            snap_source,
            direction_dir,
            chroma=options.chroma,
            legacy_1024_name="anchor-snapped-1024.png",
            legacy_chroma_name="anchor-snapped-1024-chroma.png",
        )
        anchor_metadata = {
            "pixelSnapped": False,
            "anchor1024": str(variants["anchor"]),
            "anchor1024Chroma": str(variants["chromaAnchor"]),
            "snappedNative": None,
            "snapped1024": str(direction_dir / "anchor-snapped-1024.png"),
            "snapped1024Chroma": str(final_anchor),
            "snapRun": None,
            "snappedSize": None,
            "unsnappedTransform": variants["metadata"],
        }
    write_json(
        direction_dir / "anchor.json",
        {
            "version": 1,
            "createdAt": now_iso(),
            "direction": direction,
            "raw": str(raw),
            "snapSource": str(snap_source),
            "sourceForSnap": str(source_for_snap),
            **anchor_metadata,
            "kColors": options.k_colors,
            "chroma": options.chroma,
            "seed": options.seed,
            "gameView": resolve_anchor_game_view(options.game_view),
            "anchorRole": resolve_anchor_role(options.anchor_role),
            "anchorContext": options.anchor_context,
        },
    )
    append_event(options.run_dir / "events.jsonl", "direction_anchor_published", direction=direction, path=str(final_anchor))
    return raw, final_anchor


def _validate_accepted_anchor_image(path: Path, *, chroma: str) -> None:
    with Image.open(path).convert("RGBA") as image:
        if image.size != REFERENCE_SIZE:
            raise ValueError(f"accepted anchor must be {REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]}, got {image.size[0]}x{image.size[1]}")
        expected = ImageColor.getrgb(chroma) + (255,)
        corners = [
            image.getpixel((0, 0)),
            image.getpixel((image.width - 1, 0)),
            image.getpixel((0, image.height - 1)),
            image.getpixel((image.width - 1, image.height - 1)),
        ]
        if any(pixel != expected for pixel in corners):
            raise ValueError(f"accepted anchor corners must be exact {chroma} chroma")


def _existing_character_id(run_dir: Path) -> str:
    data = _read_json_object(run_dir / "character.json")
    value = data.get("character")
    return str(value) if value else "character"


def _update_character_manifest_for_acceptance(
    options: AcceptAnchorOptions,
    *,
    character_id: str,
    anchors: dict[str, Path],
    final_anchor: Path,
    accepted_copy: Path,
    game_view: str,
    anchor_role: str,
) -> Path:
    path = options.run_dir / "character.json"
    data = _read_json_object(path)
    data.update(
        {
            "version": 1,
            "character": character_id,
            "updatedAt": now_iso(),
            "stage": "accepted-anchor",
            "candidateFacing": data.get("candidateFacing") or options.candidate_facing,
            "anchors": {direction: str(anchor) for direction, anchor in anchors.items()},
            "chroma": options.chroma,
            "kColors": options.k_colors,
            "gameView": game_view,
            "anchorRole": anchor_role,
            "anchorContext": options.anchor_context,
        }
    )
    accepted = dict(data.get("acceptedAnchors") or {})
    accepted[options.direction] = {
        "source": str(options.source),
        "canonical": str(final_anchor),
        "acceptedCopy": str(accepted_copy),
        "reason": options.reason,
        "updatedAt": now_iso(),
    }
    data["acceptedAnchors"] = accepted
    write_json(path, data)
    return path


def _update_bootstrap_summary_for_acceptance(
    options: AcceptAnchorOptions,
    *,
    character_path: Path,
    final_anchor: Path,
    accepted_copy: Path,
    game_view: str,
    anchor_role: str,
) -> None:
    path = options.run_dir / "bootstrap.json"
    data = _read_json_object(path)
    if not data:
        return
    data["updatedAt"] = now_iso()
    data["gameView"] = game_view
    data["anchorRole"] = anchor_role
    data["anchorContext"] = options.anchor_context
    anchors = dict(data.get("anchors") or {})
    anchors[options.direction] = str(final_anchor)
    data["anchors"] = anchors
    canonical = dict(data.get("canonicalOutputs") or {})
    direction_anchors = dict(canonical.get("directionAnchors") or {})
    existing = dict(direction_anchors.get(options.direction) or {})
    existing.update(
        {
            "snapped1024Chroma": str(final_anchor),
            "manifest": str(options.run_dir / "anchors" / options.direction / "anchor.json"),
            "acceptedCopy": str(accepted_copy),
        }
    )
    direction_anchors[options.direction] = existing
    canonical["directionAnchors"] = direction_anchors
    canonical["character"] = str(character_path)
    data["canonicalOutputs"] = canonical
    accepted = dict(data.get("acceptedAnchors") or {})
    accepted[options.direction] = {
        "source": str(options.source),
        "canonical": str(final_anchor),
        "acceptedCopy": str(accepted_copy),
        "reason": options.reason,
        "updatedAt": now_iso(),
    }
    data["acceptedAnchors"] = accepted
    write_json(path, data)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _direction_raw_sibling(source_anchor: Path, direction: str) -> Path | None:
    candidates = [
        source_anchor.with_name(f"character-{direction}-raw.png"),
        source_anchor.parent / f"character-{direction}-raw.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _direction_clean_sibling(source_anchor: Path, direction: str) -> Path | None:
    candidates = [
        source_anchor.with_name(f"character-{direction}.png"),
        source_anchor.parent / f"character-{direction}.png",
    ]
    if source_anchor.name.endswith("-chroma.png"):
        candidates.append(source_anchor.with_name(source_anchor.name.replace("-chroma.png", ".png")))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _write_direction_review(
    options: AnchorWizardOptions,
    *,
    accepted_candidate: Path,
    comparison_pairs: list[tuple[str, Path, Path]],
) -> None:
    all_pairs = _existing_comparison_pairs(options.run_dir)
    seen = {direction for direction, _raw, _snapped in all_pairs}
    all_pairs.extend(pair for pair in comparison_pairs if pair[0] not in seen)
    if not all_pairs:
        return
    review_dir = options.run_dir / "review"
    comparison = build_anchor_comparison_sheet(all_pairs, review_dir / "direction-anchor-comparison.png", chroma=options.chroma)
    detail = build_anchor_detail_sheet(all_pairs, review_dir / "direction-anchor-detail.png", chroma=options.chroma)
    write_review_index(
        review_dir,
        title=f"{options.character_id} Anchor Wizard Review",
        summary="Review page for accepted production candidate and generated directional anchors.",
        notes=[
            f"Directions: `{', '.join(options.directions)}`.",
            f"Accepted candidate: `{accepted_candidate}`.",
            "Use the 1024 chroma anchors as animation references after approval.",
        ],
        assets=_wizard_assets(options.run_dir) + [
            ReviewAsset("Direction Anchor Comparison", comparison, "Raw generated anchors compared with final 1024 chroma anchors.", True),
            ReviewAsset("Direction Anchor Detail", detail, "Zoomed crops to inspect mixed pixels and palette shifts.", True),
        ],
    )


def _existing_comparison_pairs(run_dir: Path) -> list[tuple[str, Path, Path]]:
    pairs: list[tuple[str, Path, Path]] = []
    for direction in DIRECTIONS:
        raw = run_dir / "anchors" / direction / "anchor-raw.png"
        final = run_dir / "anchors" / direction / "anchor-snapped-1024-chroma.png"
        if raw.exists() and final.exists():
            pairs.append((direction, raw, final))
    return pairs


def candidate_dir_for(run_dir: Path, candidate_facing: str = "front") -> Path:
    _validate_candidate_facing(candidate_facing)
    return run_dir / "candidate" / ("s" if candidate_facing == "south" else candidate_facing)


def default_candidate_anchor(run_dir: Path, candidate_facing: str = "front") -> Path:
    return candidate_dir_for(run_dir, candidate_facing) / "snapped-1024-chroma.png"


def existing_candidate_anchor(run_dir: Path, candidate_facing: str = "front") -> Path | None:
    canonical = default_candidate_anchor(run_dir, candidate_facing)
    if canonical.exists():
        return canonical
    if candidate_facing == "front":
        old = run_dir / "candidate" / "s" / "snapped-1024-chroma.png"
        if old.exists():
            return old
    return None


def write_character_manifest(
    run_dir: Path,
    *,
    character_id: str,
    stage: str,
    candidate_anchor: Path | None,
    anchors: dict[str, Path],
    options: AnchorWizardOptions,
) -> Path:
    out = run_dir / "character.json"
    write_json(
        out,
        {
            "version": 1,
            "character": character_id,
            "updatedAt": now_iso(),
            "stage": stage,
            "candidateFacing": options.candidate_facing,
            "candidateAnchor": str(candidate_anchor) if candidate_anchor else None,
            "candidatePromptPreset": options.candidate_prompt_preset,
            "pixelSnapAnchor": options.pixel_snap_anchor,
            "anchors": {direction: str(path) for direction, path in anchors.items()},
            "chroma": options.chroma,
            "kColors": options.k_colors,
            "seed": options.seed,
            "gameView": resolve_anchor_game_view(options.game_view),
            "anchorRole": resolve_anchor_role(options.anchor_role),
            "anchorContext": options.anchor_context,
            "sourceMode": "image" if options.source_image else "text",
            "sourcePrompt": str(options.source_prompt_file) if options.source_prompt_file else options.source_prompt,
        },
    )
    return out


def write_anchor_wizard_review(run_dir: Path) -> Path:
    review_dir = run_dir / "review"
    assets = _wizard_assets(run_dir)
    return write_review_index(
        review_dir,
        title=f"{run_dir.name} Anchor Wizard Review",
        summary="Current review page for source, production candidate, and directional anchor setup.",
        notes=[
            "Accept the production candidate before generating N/S/E/W anchors.",
            "Final animation references are the snapped 1024 chroma anchors under anchors/<direction>/.",
        ],
        assets=assets,
    )


def _resolve_source(options: AnchorWizardOptions) -> Path | None:
    input_dir = options.run_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    user_prompt = _read_prompt(options.source_prompt, options.source_prompt_file)
    source_prompt: str | None = None
    if user_prompt:
        source_prompt = _source_prompt(
            user_prompt,
            high_fidelity=_uses_high_fidelity_source_prompt(options),
            game_view=options.game_view,
        )
        (input_dir / "source-user-prompt.txt").write_text(user_prompt, encoding="utf-8")
        (input_dir / "source-prompt.txt").write_text(source_prompt, encoding="utf-8")

    source_out = input_dir / "source.png"
    if options.source_image is not None:
        require_file(options.source_image, "source image")
        return _prepare_source_image_input(options.source_image, source_out, chroma=options.chroma)

    if not source_prompt:
        raise ValueError("candidate stage requires --source-image, --source-prompt, or --source-prompt-file")

    fal_dir = options.run_dir / "source-fal"
    _run_fal_image(
        options,
        stage="fal-source",
        model_alias=options.source_model_alias,
        prompt_file=input_dir / "source-prompt.txt",
        image_files=[],
        out_dir=fal_dir,
        filename_prefix="user-input-source",
        task_slug=f"{options.run_dir.name}-source",
    )
    outputs = sorted(fal_dir.glob("user-input-source-output-*.png"))
    if not outputs:
        if options.dry_fal:
            return None
        raise FileNotFoundError(f"no source image output found in {fal_dir}")
    shutil.copy2(_newest_path(outputs), source_out)
    return source_out


def _resolve_candidate(options: AnchorWizardOptions, source: Path) -> Path | None:
    candidate_dir = candidate_dir_for(options.run_dir, options.candidate_facing)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = candidate_dir / "candidate-prompt.txt"
    prompt = resolve_candidate_prompt(
        options.candidate_prompt,
        options.candidate_prompt_file,
        preset=options.candidate_prompt_preset,
        candidate_facing=options.candidate_facing,
        game_view=options.game_view,
        chroma=options.chroma,
    )
    if _source_model_input_used_alpha_matte(options.run_dir):
        prompt = _append_alpha_matte_candidate_guidance(prompt, chroma=options.chroma)
    prompt_path.write_text(prompt, encoding="utf-8")

    if options.candidate_image is not None:
        require_file(options.candidate_image, "candidate image")
        return options.candidate_image

    if _uses_source_preserving_candidate(options):
        append_event(
            options.run_dir / "events.jsonl",
            "candidate_source_preserved",
            preset=options.candidate_prompt_preset,
            source=str(source),
            prompt=str(prompt_path),
        )
        return source

    fal_dir = options.run_dir / "candidate-fal"
    _run_fal_image(
        options,
        stage=f"fal-candidate-{options.candidate_facing}",
        model_alias=options.candidate_model_alias,
        prompt_file=prompt_path,
        image_files=[source],
        out_dir=fal_dir,
        filename_prefix=f"candidate-{options.candidate_facing}",
        task_slug=f"{options.run_dir.name}-candidate-{options.candidate_facing}",
    )
    outputs = sorted(fal_dir.glob(f"candidate-{options.candidate_facing}-output-*.png"))
    if not outputs:
        if options.dry_fal:
            return None
        raise FileNotFoundError(f"no candidate image output found in {fal_dir}")
    return _newest_path(outputs)


def _run_fal_image(
    options: AnchorWizardOptions,
    *,
    stage: str,
    model_alias: str,
    prompt_file: Path,
    image_files: list[Path],
    out_dir: Path,
    filename_prefix: str,
    task_slug: str,
) -> None:
    args = [
        sys.executable,
        str(FAL_IMAGE_SCRIPT),
        "--model-alias",
        model_alias,
        "--prompt-file",
        str(prompt_file),
        "--out-dir",
        str(out_dir),
        "--filename-prefix",
        filename_prefix,
        "--task-slug",
        task_slug,
        "--image-size",
        "square_hd",
        "--output-format",
        "png",
        "--quality",
        "high",
    ]
    for image_file in image_files:
        args.extend(["--image-file", str(image_file)])
    if options.dry_fal:
        args.append("--dry-run")
    if options.seed is not None:
        args.extend(["--seed", str(options.seed)])
    run_command(args, stage=stage, run_dir=options.run_dir, events_path=options.run_dir / "events.jsonl")


def _copy_snap_aliases(snap: SnapResult, out_dir: Path, *, prefix: str = "") -> None:
    stem = f"{prefix}-" if prefix else ""
    shutil.copy2(snap.snapped, out_dir / f"{stem}snapped-native.png")
    shutil.copy2(snap.anchor, out_dir / f"{stem}snapped-1024.png")
    if snap.chroma_anchor is not None:
        shutil.copy2(snap.chroma_anchor, out_dir / f"{stem}snapped-1024-chroma.png")


def _write_unsnapped_anchor_variants(
    source: Path,
    out_dir: Path,
    *,
    chroma: str,
    legacy_1024_name: str,
    legacy_chroma_name: str,
) -> dict[str, Any]:
    anchor = out_dir / "anchor-1024.png"
    chroma_anchor = out_dir / "anchor-1024-chroma.png"
    image, metadata = _prepare_unsnapped_anchor_canvas(source, chroma=chroma)
    chroma_image = Image.new("RGBA", REFERENCE_SIZE, ImageColor.getrgb(chroma) + (255,))
    chroma_image.alpha_composite(image, (0, 0))

    out_dir.mkdir(parents=True, exist_ok=True)
    image.save(anchor)
    chroma_image.save(chroma_anchor)
    shutil.copy2(anchor, out_dir / legacy_1024_name)
    shutil.copy2(chroma_anchor, out_dir / legacy_chroma_name)
    return {"anchor": anchor, "chromaAnchor": chroma_anchor, "metadata": metadata}


def _prepare_unsnapped_anchor_canvas(source: Path, *, chroma: str) -> tuple[Image.Image, dict[str, Any]]:
    with Image.open(source) as opened:
        rgba = opened.convert("RGBA")
    alpha = rgba.getchannel("A")
    has_transparency = alpha.getextrema()[0] < 255
    cleaned = rgba if has_transparency else remove_corner_background(rgba)
    background_cleanup = "preserved-alpha" if has_transparency else "corner-connected"
    if rgba.size == REFERENCE_SIZE:
        return cleaned, {
            "source": str(source),
            "sourceSize": list(rgba.size),
            "targetSize": list(REFERENCE_SIZE),
            "preservedCanvas": True,
            "scale": 1.0,
            "offset": [0, 0],
            "resampling": "none",
            "backgroundCleanup": background_cleanup,
            "chroma": chroma,
        }

    bbox = cleaned.getchannel("A").getbbox() or (0, 0, cleaned.width, cleaned.height)
    crop = cleaned.crop(bbox)
    max_w = round(REFERENCE_SIZE[0] * 0.82)
    max_h = round(REFERENCE_SIZE[1] * 0.86)
    scale = min(max_w / crop.width, max_h / crop.height)
    new_size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    sprite = crop.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", REFERENCE_SIZE, (0, 0, 0, 0))
    offset = ((REFERENCE_SIZE[0] - sprite.width) // 2, (REFERENCE_SIZE[1] - sprite.height) // 2)
    canvas.alpha_composite(sprite, offset)
    return canvas, {
        "source": str(source),
        "sourceSize": list(rgba.size),
        "targetSize": list(REFERENCE_SIZE),
        "preservedCanvas": False,
        "foregroundBbox": list(bbox),
        "scale": scale,
        "offset": list(offset),
        "resampling": "lanczos",
        "backgroundCleanup": background_cleanup,
        "chroma": chroma,
    }


def _prepare_source_image_input(source_image: Path, source_out: Path, *, chroma: str) -> Path:
    input_dir = source_out.parent
    original_out = input_dir / "source-original.png"
    model_input = input_dir / "source-model-input.png"
    shutil.copy2(source_image, source_out)
    shutil.copy2(source_image, original_out)

    with Image.open(source_image) as opened:
        rgba = opened.convert("RGBA")
        alpha = rgba.getchannel("A")
        alpha_min, alpha_max = alpha.getextrema()
        transparent_pixels = _count_pixels_matching_alpha(alpha, alpha_value=0)
        total_pixels = rgba.width * rgba.height
        has_alpha = alpha_min < 255
        if has_alpha:
            chroma_rgba = ImageColor.getrgb(chroma) + (255,)
            canvas = Image.new("RGBA", rgba.size, chroma_rgba)
            canvas.alpha_composite(rgba, (0, 0))
            canvas.save(model_input)
            model_input_path = model_input
        else:
            shutil.copy2(source_image, model_input)
            model_input_path = model_input

    write_json(
        input_dir / "source.json",
        {
            "version": 1,
            "createdAt": now_iso(),
            "source": str(source_out),
            "sourceOriginal": str(original_out),
            "sourceModelInput": str(model_input_path),
            "alphaNormalizedForModel": has_alpha,
            "alphaRange": [alpha_min, alpha_max],
            "transparentPixelRatio": transparent_pixels / total_pixels if total_pixels else 0,
            "chroma": chroma,
        },
    )
    return model_input_path


def _count_pixels_matching_alpha(alpha: Image.Image, *, alpha_value: int) -> int:
    return sum(count for value, count in enumerate(alpha.histogram()) if value == alpha_value)


def _source_model_input_used_alpha_matte(run_dir: Path) -> bool:
    data = _read_json_object(run_dir / "input" / "source.json")
    return bool(data.get("alphaNormalizedForModel"))


def _append_alpha_matte_candidate_guidance(prompt: str, *, chroma: str) -> str:
    return (
        prompt.rstrip()
        + "\n\nTransparent source-image handling:\n"
        + f"- The supplied reference was normalized onto exact {_chroma_phrase(chroma)} because the original PNG had real alpha transparency.\n"
        + "- The chroma background is a removal matte, not part of the character.\n"
        + "- Keep or replace it only with the requested exact flat chroma background.\n"
        + "- Do not render checkerboard transparency, gray/white tiles, UI transparency grids, or faux transparent backgrounds.\n"
    )


def _validate_candidate_background(raw_path: Path, *, out: Path, chroma: str, strict: bool) -> dict[str, Any]:
    with Image.open(raw_path) as opened:
        metrics = _candidate_background_metrics(opened, chroma=chroma)
    metrics["strict"] = strict
    metrics["passed"] = not _candidate_has_faux_transparency(metrics, strict=strict)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, metrics)
    if not metrics["passed"]:
        raise ValueError(
            "candidate image appears to contain baked faux transparency/checkerboard or an opaque neutral background. "
            f"Raw candidate: {raw_path}. "
            "Regenerate from the normalized source-model-input.png and make the prompt keep an exact flat chroma background."
        )
    return metrics


def _candidate_background_metrics(image: Image.Image, *, chroma: str) -> dict[str, Any]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    px = rgba.load()
    chroma_rgb = ImageColor.getrgb(chroma)
    total = width * height
    opaque = 0
    transparent = 0
    chroma_like = 0
    neutral_light = 0
    neutral_buckets: dict[tuple[int, int, int], int] = {}
    corner_pixels = [
        px[0, 0],
        px[width - 1, 0],
        px[0, height - 1],
        px[width - 1, height - 1],
    ]
    corner_light_neutral = 0
    corner_chroma_like = 0
    transitions = 0
    sampled_edges = 0

    for y in range(height):
        previous_neutral: bool | None = None
        for x in range(width):
            r, g, b, a = px[x, y]
            if a == 0:
                transparent += 1
                continue
            opaque += 1
            is_chroma = _rgb_distance((r, g, b), chroma_rgb) <= 36
            if is_chroma:
                chroma_like += 1
            is_neutral = _is_light_neutral((r, g, b))
            if is_neutral:
                neutral_light += 1
                bucket = (round(r / 16) * 16, round(g / 16) * 16, round(b / 16) * 16)
                neutral_buckets[bucket] = neutral_buckets.get(bucket, 0) + 1
            if x % 8 == 0 and y % 8 == 0:
                if previous_neutral is not None and previous_neutral != is_neutral:
                    transitions += 1
                sampled_edges += 1
                previous_neutral = is_neutral

    for pixel in corner_pixels:
        rgb = pixel[:3]
        if _is_light_neutral(rgb):
            corner_light_neutral += 1
        if _rgb_distance(rgb, chroma_rgb) <= 36:
            corner_chroma_like += 1

    top_neutral_buckets = sorted(neutral_buckets.values(), reverse=True)[:4]
    second_bucket_ratio = (top_neutral_buckets[1] / total) if len(top_neutral_buckets) > 1 and total else 0
    return {
        "version": 1,
        "image": str(getattr(image, "filename", "")),
        "size": [width, height],
        "alphaRange": list(rgba.getchannel("A").getextrema()),
        "opaqueRatio": opaque / total if total else 0,
        "transparentRatio": transparent / total if total else 0,
        "chromaLikeRatio": chroma_like / total if total else 0,
        "neutralLightRatio": neutral_light / total if total else 0,
        "secondNeutralBucketRatio": second_bucket_ratio,
        "cornerLightNeutralCount": corner_light_neutral,
        "cornerChromaLikeCount": corner_chroma_like,
        "sampledNeutralTransitionRatio": transitions / sampled_edges if sampled_edges else 0,
        "chroma": chroma,
    }


def _candidate_has_faux_transparency(metrics: dict[str, Any], *, strict: bool) -> bool:
    if metrics["transparentRatio"] > 0.01:
        return False
    if metrics["chromaLikeRatio"] >= 0.45 or metrics["cornerChromaLikeCount"] >= 3:
        return False
    neutral_background = (
        metrics["cornerLightNeutralCount"] >= 3
        and metrics["neutralLightRatio"] >= (0.10 if strict else 0.18)
        and metrics["secondNeutralBucketRatio"] >= (0.01 if strict else 0.025)
    )
    checker_signal = metrics["sampledNeutralTransitionRatio"] >= (0.08 if strict else 0.12)
    return bool(neutral_background and (strict or checker_signal))


def _is_light_neutral(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    avg = (r + g + b) / 3
    return 150 <= avg <= 252 and max(rgb) - min(rgb) <= 24


def _rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((a[index] - b[index]) ** 2 for index in range(3)) ** 0.5


def _uses_guarded_lobit_candidate(options: AnchorWizardOptions) -> bool:
    return (
        options.candidate_prompt_preset == "lobit-v1"
        and options.pixel_snap_anchor
        and options.candidate_prompt is None
        and options.candidate_prompt_file is None
    )


def _uses_source_preserving_candidate(options: AnchorWizardOptions) -> bool:
    return (
        options.candidate_prompt_preset == "preserve-reference-v1"
        and options.source_image is not None
        and options.candidate_image is None
        and options.candidate_prompt is None
        and options.candidate_prompt_file is None
    )


def _candidate_generation_mode(options: AnchorWizardOptions) -> str:
    if options.candidate_image is not None:
        return "provided-candidate-image"
    if _uses_source_preserving_candidate(options):
        return "source-image-preserve-reference-shortcut"
    return "generated-candidate"


def _enforce_lobit_snap_contract(snap: SnapResult) -> None:
    native_w, native_h = snap.snapped_size
    if native_h > LOBIT_NATIVE_HEIGHT_MAX:
        target_min, target_max = LOBIT_NATIVE_HEIGHT_TARGET
        raise ValueError(
            "lobit-v1 candidate snap is too tall/detailed for the pixel-snap-bound anchor contract: "
            f"native snapped size is {native_w}x{native_h}, expected roughly {target_min}-{target_max}px tall "
            f"and no more than {LOBIT_NATIVE_HEIGHT_MAX}px. Regenerate with stronger low-bit distillation "
            "or use a custom candidate prompt only for intentionally non-pixel-snap-bound game art."
        )


def _write_candidate_review(run_dir: Path, candidate_dir: Path) -> Path:
    overview = _build_candidate_overview(run_dir, candidate_dir, run_dir / "review" / "candidate-overview.png")
    facing = candidate_dir.name
    label = "front-facing identity" if facing == "front" else "south-facing top-down"
    return write_review_index(
        candidate_dir / "review",
        title="Production Candidate Review",
        summary=f"Review page for the {label} production candidate before facing generation.",
        notes=[
            "Accept `anchor-1024-chroma.png` before generating optional N/S/E/W anchors. `snapped-1024-chroma.png` remains as a compatibility alias.",
            "If identity or silhouette is wrong, regenerate the candidate rather than continuing.",
        ],
        assets=[
            ReviewAsset("Candidate Overview", overview, "Source, raw candidate, optional native snap, and 1024 chroma candidate.", True),
            ReviewAsset("Source Image", run_dir / "input" / "source.png", "Input source used for candidate generation.", True),
            ReviewAsset("Candidate Raw", candidate_dir / "candidate-raw.png", f"Generated {label} candidate.", True),
            ReviewAsset("Snapped Native", candidate_dir / "snapped-native.png", "Native pixel grid recovered by pixel snapper, when anchor snapping is enabled.", True),
            ReviewAsset("Anchor 1024 Chroma", candidate_dir / "anchor-1024-chroma.png", "Accepted candidate reference for direction generation.", True),
            ReviewAsset("Legacy Snapped 1024 Chroma", candidate_dir / "snapped-1024-chroma.png", "Compatibility alias for tools that still expect snapped candidate paths.", True),
            ReviewAsset("Candidate Manifest", candidate_dir / "candidate.json", "Machine-readable candidate metadata.", False),
        ],
    )


def _build_candidate_overview(run_dir: Path, candidate_dir: Path, out: Path) -> Path:
    items = [
        ("source", run_dir / "input" / "source.png"),
        ("candidate raw", candidate_dir / "candidate-raw.png"),
        ("snapped native", candidate_dir / "snapped-native.png"),
        ("anchor 1024 chroma", candidate_dir / "anchor-1024-chroma.png"),
        ("legacy snapped chroma", candidate_dir / "snapped-1024-chroma.png"),
    ]
    existing = [(label, path) for label, path in items if path.exists()]
    if not existing:
        raise ValueError("no candidate overview images exist")
    thumb = 256
    label_h = 34
    sheet = Image.new("RGBA", (thumb * len(existing), thumb + label_h), (24, 24, 24, 255))
    draw = ImageDraw.Draw(sheet)
    font = _font(18)
    for index, (label, path) in enumerate(existing):
        image = _thumb(path, thumb)
        x = index * thumb
        draw.text((x + 8, 8), label, fill=(238, 238, 238, 255), font=font)
        sheet.alpha_composite(image, (x, label_h))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def _wizard_assets(run_dir: Path) -> list[ReviewAsset]:
    accepted = existing_candidate_anchor(run_dir) or default_candidate_anchor(run_dir)
    candidate_dir = accepted.parent
    candidates = [
        ReviewAsset("Candidate Overview", run_dir / "review" / "candidate-overview.png", "Source and production candidate comparison.", True),
        ReviewAsset("Candidate Review", candidate_dir / "review" / "index.md", "Detailed candidate checkpoint.", False),
        ReviewAsset("Accepted Candidate", accepted, "1024 chroma candidate used for facing generation.", True),
        ReviewAsset("Direction Anchor Comparison", run_dir / "review" / "direction-anchor-comparison.png", "Raw N/S/E/W anchors compared to final anchors.", True),
        ReviewAsset("Direction Anchor Detail", run_dir / "review" / "direction-anchor-detail.png", "Zoomed raw and final anchor crops for mixed-pixel review.", True),
        ReviewAsset("Character Manifest", run_dir / "character.json", "Machine-readable character setup metadata.", False),
    ]
    for direction in ("n", "s", "e", "w"):
        candidates.append(
            ReviewAsset(
                f"{direction.upper()} Final Anchor",
                run_dir / "anchors" / direction / "anchor-snapped-1024-chroma.png",
                f"Final 1024 chroma {direction.upper()} anchor for animation generation.",
                True,
            )
        )
    return [asset for asset in candidates if asset.path.exists()]


def _direction_anchor_source(anchors_dir: Path, direction: str) -> Path | None:
    candidates = [
        anchors_dir / f"character-{direction}-chroma.png",
        anchors_dir / f"character-{direction}.png",
        anchors_dir / f"character-{direction}-raw.png",
        anchors_dir / direction / "anchor-raw.png",
        anchors_dir / direction / "anchor.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _existing_final_anchors(run_dir: Path, directions: tuple[str, ...]) -> dict[str, Path]:
    anchors: dict[str, Path] = {}
    for direction in directions:
        path = run_dir / "anchors" / direction / "anchor-snapped-1024-chroma.png"
        if path.exists():
            anchors[direction] = path
    return anchors


def _existing_or_none(path: Path) -> Path | None:
    return path if path.exists() else None


def _validate_directions(directions: tuple[str, ...]) -> None:
    unknown = [direction for direction in directions if direction not in DIRECTIONS]
    if unknown:
        raise ValueError(f"unknown directions: {', '.join(unknown)}")


def _validate_candidate_facing(candidate_facing: str) -> None:
    if candidate_facing not in CANDIDATE_FACINGS:
        raise ValueError(f"candidate_facing must be one of: {', '.join(sorted(CANDIDATE_FACINGS))}")


def _normalize_anchor_wizard_options(options: AnchorWizardOptions) -> AnchorWizardOptions:
    game_view = resolve_anchor_game_view(options.game_view)
    if game_view == "rts-oblique" and options.candidate_facing == "front":
        return replace(options, game_view=game_view, candidate_facing="south")
    if game_view != options.game_view:
        return replace(options, game_view=game_view)
    return options


def _read_prompt(prompt: str | None, prompt_file: Path | None) -> str | None:
    if prompt_file is not None:
        require_file(prompt_file, "prompt file")
        return prompt_file.read_text(encoding="utf-8")
    return prompt


def resolve_candidate_prompt(
    prompt: str | None,
    prompt_file: Path | None,
    *,
    preset: str = "lobit-v1",
    candidate_facing: str = "front",
    game_view: str = "platformer",
    chroma: str = "#00FF00",
) -> str:
    custom = _read_prompt(prompt, prompt_file)
    if custom:
        return custom
    if preset not in CANDIDATE_PROMPT_PRESETS:
        raise ValueError(f"unknown candidate prompt preset: {preset}. Expected one of: {', '.join(sorted(CANDIDATE_PROMPT_PRESETS))}")
    _validate_candidate_facing(candidate_facing)
    resolved_view = resolve_anchor_game_view(game_view)
    if preset == "high-fidelity-v1":
        return _high_fidelity_candidate_prompt(candidate_facing, game_view=resolved_view, chroma=chroma)
    if preset == "preserve-reference-v1":
        return _preserve_reference_candidate_prompt(candidate_facing, game_view=resolved_view, chroma=chroma)
    return _candidate_prompt(candidate_facing, game_view=resolved_view, chroma=chroma)


def _newest_path(paths: list[Path]) -> Path:
    return max(paths, key=lambda path: path.stat().st_mtime_ns)


def _candidate_prompt(candidate_facing: str, *, game_view: str = "platformer", chroma: str = "#00FF00") -> str:
    if game_view == "rts-oblique":
        facing_line = "Create one small compact south-facing elevated oblique RTS unit anchor on a 1024x1024 square canvas."
        composition_facing = "- south-facing/front-facing as a compact RTS unit seen from an elevated oblique camera, not a straight-on portrait"
        composition_subject = "small RTS unit sprite"
        composition_visibility = "whole unit visible, including head, weapon, hands, body, and feet, but not drawn as a tall full-height character turnaround"
        composition_scale = "- compact squat footprint; visible unit occupies roughly 35-45% of the canvas height"
        composition_ground = "- feet planted on an implied RTS ground plane without drawing a floor, shadow, or base mark"
    else:
        facing_line = (
            "Create one full-body front-facing character identity anchor on a 1024x1024 square canvas."
            if candidate_facing == "front"
            else "Create one full-body south-facing top-down character anchor on a 1024x1024 square canvas."
        )
        composition_facing = (
            "- facing the viewer / screen-front"
            if candidate_facing == "front"
            else "- facing screen/front/south for a top-down game"
        )
        composition_subject = "full-body character"
        composition_visibility = "full body visible"
        composition_scale = ""
        composition_ground = ""
    camera_guidance = _candidate_camera_guidance(game_view)
    chroma_phrase = _chroma_phrase(chroma)
    return f"""Intended use: create a deliberately simple low-bit production sprite anchor for a pixel-snap animation pipeline.

Input image role: identity reference only. Treat any supplied prompt or image as raw identity material, not as a style or detail reference. Preserve only the broad character identity, silhouette, outfit color blocks, proportions, and readable personality.

Do not preserve the high-detail rendering style, native resolution, accessory density, or tiny costume details. Force the reference through an opinionated low-bit pixel-sprite distillation step before it can become a pixel-snap anchor.
This constrained style is required because this candidate will be pixel-snapped and used as an animation anchor. If the goal is a non-pixel-snap-bound game asset where mixels are acceptable at the target resolution, use a custom candidate prompt instead of this preset.

{facing_line}
{camera_guidance}

Style target:
- deliberately simple 16-bit-era pixel art, not polished high-detail JRPG art
- low fidelity, chunky, readable from far away
- limited 8 to 12 color feeling, with flat color clusters rather than rich gradients
- big pixel clusters and clean stepped edges
- compact body proportions and a readable full-body silhouette
- simplify costume into large readable color blocks; collapse small identity details into one or two big cues
- no tiny accessories, ornate trim, jewelry, stitching, buttons, buckles, texture noise, fabric weave, cloth-fold detail, or layered micro-props
- dark outline clusters and clear internal separations
- designed to fit cleanly inside future 256x256 animation cells
- after pixel snapping, the character should feel like a roughly 100 to 130 pixel tall native sprite, not a 200+ pixel high-detail illustration

Composition:
- exactly one {composition_subject}
{composition_facing}
- centered
- {composition_visibility}
- generous margin on all sides
{composition_scale}
{composition_ground}
- neutral upright pose

Background:
- opaque exact flat {chroma_phrase} background
- no gradients
- no texture
- no shadows
- no checkerboard
- no faux transparency
- no matte-color spill

Avoid:
- text, labels, frame numbers
- props beyond the character concept
- scenery
- extra characters
- cropped limbs
- transparent background
"""


def _high_fidelity_candidate_prompt(candidate_facing: str, *, game_view: str = "platformer", chroma: str = "#00FF00") -> str:
    if game_view == "rts-oblique":
        facing_line = "Create one small compact south-facing elevated oblique RTS unit anchor on a 1024x1024 square canvas."
        composition_facing = "- south-facing/front-facing as a compact RTS unit seen from an elevated oblique camera, not a straight-on portrait"
        composition_subject = "small RTS unit sprite"
        composition_visibility = "whole unit visible, including head, weapon, hands, body, and feet, but not drawn as a tall full-height character turnaround"
        composition_scale = "- compact squat footprint; visible unit occupies roughly 35-45% of the canvas height"
        composition_ground = "- feet planted on an implied RTS ground plane without drawing a floor, shadow, or base mark"
    else:
        facing_line = (
            "Create one full-body front-facing character identity anchor on a 1024x1024 square canvas."
            if candidate_facing == "front"
            else "Create one full-body south-facing top-down character anchor on a 1024x1024 square canvas."
        )
        composition_facing = (
            "- facing the viewer / screen-front"
            if candidate_facing == "front"
            else "- facing screen/front/south for a top-down game"
        )
        composition_subject = "full-body character or object"
        composition_visibility = "full body visible"
        composition_scale = ""
        composition_ground = ""
    camera_guidance = _candidate_camera_guidance(game_view)
    chroma_phrase = _chroma_phrase(chroma)
    return f"""Intended use: create a high-fidelity game sprite anchor where AI-generated mixels and richer pixel-art texture are acceptable.

Input image role: identity and style reference. Preserve the broad character identity, silhouette, outfit color blocks, proportions, readable personality, and the user's intended game-art fidelity.

This preset is for non-pixel-snap-bound game assets. Do not force the strict low-bit native sprite constraints. The result should still be clean game production art, but it may keep richer shading, larger forms, and higher-detail pixel texture when that benefits the game.

{facing_line}
{camera_guidance}

Style target:
- high-fidelity 2D pixel-art-inspired game sprite
- clear silhouette and readable outfit at gameplay scale
- richer color ramps and texture are acceptable
- mixed pixels are acceptable if they improve the final high-resolution asset
- keep character identity stronger than strict retro simplification
- avoid photographic realism, 3D model rendering, painterly concept-art brushwork, and cinematic lighting
- designed to be usable as an animation reference, not as a marketing illustration

Composition:
- exactly one {composition_subject}
{composition_facing}
- centered
- {composition_visibility}
- generous margin on all sides
{composition_scale}
{composition_ground}
- neutral upright pose unless the asset role implies a planted object

Background:
- opaque exact flat {chroma_phrase} background
- no gradients
- no texture
- no shadows
- no checkerboard
- no faux transparency
- no matte-color spill

Avoid:
- text, labels, frame numbers
- props beyond the character concept
- scenery
- extra characters
- cropped limbs
- transparent background
"""


def _preserve_reference_candidate_prompt(candidate_facing: str, *, game_view: str = "platformer", chroma: str = "#00FF00") -> str:
    if game_view == "rts-oblique":
        facing_line = "Create one small compact south-facing elevated oblique RTS unit anchor on a 1024x1024 square canvas."
        composition_facing = "- south-facing/front-facing as a compact RTS unit seen from an elevated oblique camera, not a straight-on portrait"
        composition_subject = "small RTS unit sprite"
        composition_visibility = "whole unit visible, including head, weapon, hands, body, and feet, but not drawn as a tall full-height character turnaround"
        composition_scale = "- compact squat footprint; visible unit occupies roughly 35-45% of the canvas height"
        composition_ground = "- feet planted on an implied RTS ground plane without drawing a floor, shadow, or base mark"
    else:
        facing_line = (
            "Create one full-body front-facing character identity anchor on a 1024x1024 square canvas."
            if candidate_facing == "front"
            else "Create one full-body south-facing top-down character anchor on a 1024x1024 square canvas."
        )
        composition_facing = (
            "- facing the viewer / screen-front"
            if candidate_facing == "front"
            else "- facing screen/front/south for a top-down game"
        )
        composition_subject = "full-body character or object"
        composition_visibility = "full body visible"
        composition_scale = ""
        composition_ground = ""
    camera_guidance = _candidate_camera_guidance(game_view)
    chroma_phrase = _chroma_phrase(chroma)
    return f"""Intended use: create a source-faithful game sprite anchor from a supplied visual reference.

Input image role: strict visual authority. Preserve the source image's character identity and visual style. Keep the same chibi proportions when present, head/body ratio, silhouette, outfit, palette, line weight, rendering style, facial design, shape language, and key costume cues.

Do not redesign, mature, de-chibi, normalize, westernize, reinterpret, restyle, simplify into a different aesthetic, or replace the character with a generic game sprite. Pixel snapping and palette cleanup are allowed later, but they must not imply a style redesign.

Only adapt canvas, background, and facing as required by the requested anchor.

{facing_line}
{camera_guidance}

Style target:
- source-faithful 2D game sprite
- preserve the reference image's art direction and visual proportions
- preserve character-specific color relationships and line weight
- keep outfit cues and silhouette readable at gameplay scale
- clean enough for animation reference without inventing a new style
- if pixel snapping is enabled later, keep the design compatible with snapping while preserving the source style

Composition:
- exactly one {composition_subject}
{composition_facing}
- centered
- {composition_visibility}
- generous margin on all sides
{composition_scale}
{composition_ground}
- neutral upright pose unless the asset role implies a planted object

Background:
- opaque exact flat {chroma_phrase} background
- no gradients
- no texture
- no shadows
- no checkerboard
- no faux transparency
- no matte-color spill

Avoid:
- text, labels, frame numbers
- props beyond the reference design
- scenery
- extra characters
- cropped limbs
- transparent background
"""


def _candidate_camera_guidance(game_view: str) -> str:
    if game_view == "rts-oblique":
        return """Camera contract:
- elevated oblique RTS camera similar to Warcraft-like unit sprites, not a portrait camera and not strict tactics isometric
- visible top planes of head, shoulders, armor, weapon, hands, and boots
- foreshortened unit proportions suitable for an RTS selection circle or tile
- compact and squat, roughly 35-45% of the 1024 canvas height
- feet planted on an implied RTS ground plane
- not a straight-on front portrait
- not a pure side-view platformer or fighting-game sprite
- not a tall full-height character turnaround
- not a large character illustration or paper-doll pose"""
    if game_view == "isometric":
        return """Experimental camera contract:
- true isometric / tactics-style camera is experimental and less tested than platformer and rts-oblique
- aim for a diamond-tile tactics view with visible top planes and foreshortened proportions
- avoid front portrait, platformer profile, and tall full-height character turnaround"""
    if game_view == "top-down":
        return """Experimental camera contract:
- top-down / three-quarter top-down character anchors are experimental and less tested than platformer
- keep the facing readable from an overhead gameplay camera
- avoid side-scroller platformer profile unless the requested direction explicitly needs profile readability"""
    return ""


def _chroma_phrase(chroma: str) -> str:
    normalized = chroma.upper()
    names = {
        "#00FF00": "chroma green #00FF00",
        "#FF00FF": "chroma magenta #FF00FF",
        "#0000FF": "chroma blue #0000FF",
    }
    return names.get(normalized, f"chroma color {chroma}")


def _uses_high_fidelity_source_prompt(options: AnchorWizardOptions) -> bool:
    return options.candidate_prompt_preset in {"high-fidelity-v1", "preserve-reference-v1"} or not options.pixel_snap_anchor


def _source_prompt(user_prompt: str, *, high_fidelity: bool = False, game_view: str = "platformer") -> str:
    concept = user_prompt.strip()
    resolved_view = resolve_anchor_game_view(game_view)
    camera_guidance = _source_camera_guidance(resolved_view)
    pose_guidance = (
        "- south-facing or slight diagonal RTS unit stance from an elevated oblique camera"
        if resolved_view == "rts-oblique"
        else "- front-facing or slight three-quarter game sprite stance"
    )
    if resolved_view == "rts-oblique":
        source_subject = "one small compact RTS unit sprite"
        source_visibility = "whole unit visible, including head, weapon, hands, body, and feet, but not drawn as a tall full-height character turnaround"
        source_scale = "- compact squat footprint; visible unit occupies roughly 35-45% of the canvas height"
        source_ground = "- feet planted on an implied RTS ground plane without drawing a floor, shadow, or base mark"
        source_intent = "If the user prompt says full-body, interpret that as whole unit visible, not as a tall character-turnaround or portrait."
    else:
        source_subject = "one full-body character"
        source_visibility = "full body visible from hair to feet"
        source_scale = ""
        source_ground = ""
        source_intent = ""
    if high_fidelity:
        return f"""Intended use: create a clean user-input source character for a high-fidelity pixel-art-inspired game asset pipeline.

Character concept from the user:
{concept}

Interpret the user concept as the character identity and intended game-art direction. Do not follow any implied photographic, cinematic, realistic, 3D, painterly, or environment style from the user text.

Create {source_subject} on a 1024x1024 square canvas.
{source_intent}
{camera_guidance}

Style target:
- high-fidelity 2D pixel-art-inspired game sprite
- clear silhouette and readable outfit at gameplay scale
- richer color ramps and texture are acceptable
- mixed pixels are acceptable if they improve the final high-resolution asset
- preserve the user's intended identity and style more strongly than a strict low-bit distillation would
- no realistic photo, no photorealism, no cinematic render, no 3D model look

Composition:
- exactly {source_subject}
- neutral upright pose
{pose_guidance}
- centered
- {source_visibility}
- generous margin on all sides
{source_scale}
{source_ground}

Background:
- opaque exact flat light gray background #D9D9D9
- no scenery
- no castle, room, landscape, props, or ground plane
- no gradients
- no texture
- no shadows
- no checkerboard
- no faux transparency

Avoid:
- text, labels, logos, frame numbers
- extra characters
- cropped limbs
- transparent background
- photographic lighting
"""

    return f"""Intended use: create a clean user-input source character for a pixel-sprite animation pipeline.

Character concept from the user:
{concept}

Interpret the user concept as the character identity only. Do not follow any implied photographic, cinematic, realistic, 3D, painterly, or environment style from the user text.
Use these constraints when the source is intended to continue into pixel snapping and animation anchors. Higher-fidelity game art can be valid when mixels are acceptable at the target resolution, but it should not be treated as a pixel-snap-ready source without a low-bit distillation step.
If the user supplies a detailed image, use it as identity input only. The eventual production candidate must remove complexity and conform to the opinionated low-bit pixel-sprite style before snapping.

Create {source_subject} on a 1024x1024 square canvas.
{source_intent}
{camera_guidance}

Style target:
- deliberately simple 16-bit-era pixel art, not polished high-detail JRPG art
- low-fidelity game character art with a limited 8 to 12 color feeling
- big pixel clusters, crisp chunky edges, and flat readable color masses
- simplified shapes and fewer fine details
- strong readable silhouette at small size
- compact body proportions where appropriate for a game sprite
- simplify the outfit into large readable color blocks and only a few major identity cues
- dark outline clusters
- no tiny accessories, ornate trim, jewelry, stitching, buttons, buckles, texture noise, fabric weave, cloth-fold detail, or layered micro-props
- no realistic photo, no photorealism, no cinematic render, no 3D model look

Composition:
- exactly {source_subject}
- neutral upright pose
{pose_guidance}
- centered
- {source_visibility}
- generous margin on all sides
- readable at future 256x256 animation-cell scale
{source_scale}
{source_ground}

Background:
- opaque exact flat light gray background #D9D9D9
- no scenery
- no castle, room, landscape, props, or ground plane
- no gradients
- no texture
- no shadows
- no checkerboard
- no faux transparency

Avoid:
- text, labels, logos, frame numbers
- extra characters
- cropped limbs
- transparent background
- photographic lighting
- high-fidelity concept art rendering
"""


def _source_camera_guidance(game_view: str) -> str:
    if game_view == "rts-oblique":
        return """Camera target:
- elevated oblique RTS unit view, similar to Warcraft-like unit sprites rather than strict tactics isometric
- visible top planes of head, shoulders, armor, hands, weapon, and boots
- compact foreshortened proportions suitable for a small RTS unit
- feet on an implied RTS ground plane
- not a front portrait, not a side-scroller platformer sprite, not a fighting-game sprite"""
    if game_view == "isometric":
        return """Experimental camera target:
- true isometric / tactics-style source generation is experimental
- aim for a diamond-tile tactics camera with visible top planes and compact foreshortening
- not a front portrait, not a side-scroller platformer sprite, not a fighting-game sprite"""
    if game_view == "top-down":
        return """Experimental camera target:
- top-down / three-quarter top-down source generation is experimental
- keep the facing readable from an overhead gameplay camera
- not a side-scroller platformer sprite unless explicitly requested"""
    return ""


def _thumb(path: Path, size: int) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    image.thumbnail((size, size), Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (size, size), ImageColor.getrgb("#1f2937") + (255,))
    x = (size - image.width) // 2
    y = (size - image.height) // 2
    canvas.alpha_composite(image, (x, y))
    return canvas


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return review_font(size=size)
