from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .anchor_wizard import (
    AnchorWizardOptions,
    CANDIDATE_PROMPT_PRESETS,
    candidate_dir_for,
    default_candidate_anchor,
    existing_candidate_anchor,
    resolve_candidate_prompt,
    run_anchor_wizard,
    write_anchor_wizard_review,
    _source_prompt,
)
from .events import append_event, now_iso, write_json
from .presets import DIRECTIONS, resolve_anchor_game_view, resolve_anchor_role
from .review_index import ReviewAsset, write_review_index
from .validate import require_file


@dataclass(frozen=True)
class BootstrapAnchorsOptions:
    run_dir: Path
    character_id: str = "character"
    source_image: Path | None = None
    source_prompt: str | None = None
    source_prompt_file: Path | None = None
    candidate_image: Path | None = None
    candidate_prompt: str | None = None
    candidate_prompt_file: Path | None = None
    candidate_prompt_preset: str = "lobit-v1"
    pixel_snap_anchor: bool = True
    candidate_facing: str = "front"
    anchors_dir: Path | None = None
    directions: tuple[str, ...] = ("w",)
    dry_fal: bool = False
    source_model_alias: str = "gpt-image-2-t2i"
    candidate_model_alias: str = "gpt-image-2-edit"
    anchor_model_alias: str = "gpt-image-2-edit"
    chroma: str = "#00FF00"
    k_colors: int = 256
    game_view: str = "platformer"
    anchor_role: str = "character"
    anchor_context: str | None = None
    resume: bool = False
    seed: int | None = None


@dataclass(frozen=True)
class BootstrapAnchorsResult:
    run_dir: Path
    bootstrap_json: Path
    character_json: Path
    candidate_anchor: Path | None
    anchors: dict[str, Path]
    review_index: Path | None


def run_bootstrap_anchors(options: BootstrapAnchorsOptions) -> BootstrapAnchorsResult:
    options = _normalize_bootstrap_options(options)
    _validate_options(options)
    options.run_dir.mkdir(parents=True, exist_ok=True)
    events_path = options.run_dir / "events.jsonl"
    append_event(
        events_path,
        "bootstrap_anchors_started",
        character=options.character_id,
        directions=list(options.directions),
        candidateFacing=options.candidate_facing,
        gameView=resolve_anchor_game_view(options.game_view),
        anchorRole=resolve_anchor_role(options.anchor_role),
        pixelSnapAnchor=options.pixel_snap_anchor,
        resume=options.resume,
    )
    _write_bootstrap_request(options)
    _write_prompt_config(options)

    candidate_anchor = existing_candidate_anchor(options.run_dir, options.candidate_facing) or default_candidate_anchor(options.run_dir, options.candidate_facing)
    missing_directions = [direction for direction in options.directions if not _final_anchor(options.run_dir, direction).exists()]
    if options.resume and candidate_anchor.exists() and not missing_directions:
        append_event(events_path, "bootstrap_anchors_resume_hit", candidate=str(candidate_anchor), directions=list(options.directions))
        wizard_result = None
        review_index = write_anchor_wizard_review(options.run_dir)
    else:
        stage = "all" if options.directions else "candidate"
        accepted_candidate = options.candidate_image
        if options.resume and candidate_anchor.exists():
            stage = "directions"
            accepted_candidate = candidate_anchor
            append_event(events_path, "bootstrap_anchors_resuming_directions", missingDirections=missing_directions)

        wizard_result = run_anchor_wizard(
            AnchorWizardOptions(
                run_dir=options.run_dir,
                character_id=options.character_id,
                stage=stage,
                source_image=options.source_image,
                source_prompt=options.source_prompt,
                source_prompt_file=options.source_prompt_file,
                candidate_image=options.candidate_image,
                candidate_prompt=options.candidate_prompt,
                candidate_prompt_file=options.candidate_prompt_file,
                candidate_prompt_preset=options.candidate_prompt_preset,
                pixel_snap_anchor=options.pixel_snap_anchor,
                candidate_facing=options.candidate_facing,
                accepted_candidate=accepted_candidate,
                anchors_dir=options.anchors_dir,
                directions=options.directions,
                dry_fal=options.dry_fal,
                source_model_alias=options.source_model_alias,
                candidate_model_alias=options.candidate_model_alias,
                anchor_model_alias=options.anchor_model_alias,
                chroma=options.chroma,
                k_colors=options.k_colors,
                game_view=options.game_view,
                anchor_role=options.anchor_role,
                anchor_context=options.anchor_context,
                seed=options.seed,
            )
        )
        review_index = wizard_result.review_index

    _sync_prompt_config(options)
    anchors = _existing_anchors(options.run_dir, options.directions)
    character_json = options.run_dir / "character.json"
    bootstrap_json = write_bootstrap_summary(
        options,
        candidate_anchor=candidate_anchor if candidate_anchor.exists() else None,
        anchors=anchors,
        character_json=character_json,
        review_index=review_index,
        status="completed",
    )
    review_index = write_bootstrap_review(options, bootstrap_json=bootstrap_json, review_index=review_index)
    append_event(events_path, "bootstrap_anchors_completed", bootstrapJson=str(bootstrap_json))
    return BootstrapAnchorsResult(
        run_dir=options.run_dir,
        bootstrap_json=bootstrap_json,
        character_json=character_json,
        candidate_anchor=candidate_anchor if candidate_anchor.exists() else None,
        anchors=anchors,
        review_index=review_index,
    )


def load_bootstrap_options(path: Path, *, run_dir: Path | None = None) -> BootstrapAnchorsOptions:
    require_file(path, "bootstrap config")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bootstrap config must be a JSON object")
    data = dict(data)
    if run_dir is not None:
        data["runDir"] = str(run_dir)
    return bootstrap_options_from_mapping(data)


def bootstrap_options_from_mapping(data: dict[str, Any]) -> BootstrapAnchorsOptions:
    def get(*names: str, default: Any = None) -> Any:
        for name in names:
            if name in data:
                return data[name]
        return default

    run_dir = get("run_dir", "runDir")
    if not run_dir:
        raise ValueError("bootstrap config requires run_dir")
    directions = get("directions", default=("w",))
    if isinstance(directions, str):
        parsed_directions = _parse_directions(directions)
    else:
        parsed_directions = tuple(str(part) for part in directions)
    return BootstrapAnchorsOptions(
        run_dir=Path(run_dir),
        character_id=str(get("character_id", "characterId", default="character")),
        source_image=_path_or_none(get("source_image", "sourceImage")),
        source_prompt=get("source_prompt", "sourcePrompt"),
        source_prompt_file=_path_or_none(get("source_prompt_file", "sourcePromptFile")),
        candidate_image=_path_or_none(get("candidate_image", "candidateImage")),
        candidate_prompt=get("candidate_prompt", "candidatePrompt"),
        candidate_prompt_file=_path_or_none(get("candidate_prompt_file", "candidatePromptFile")),
        candidate_prompt_preset=str(get("candidate_prompt_preset", "candidatePromptPreset", default="lobit-v1")),
        pixel_snap_anchor=_bool_option(get("pixel_snap_anchor", "pixelSnapAnchor", default=True), default=True),
        candidate_facing=str(get("candidate_facing", "candidateFacing", default="front")),
        anchors_dir=_path_or_none(get("anchors_dir", "anchorsDir")),
        directions=parsed_directions,
        dry_fal=bool(get("dry_fal", "dryFal", default=False)),
        source_model_alias=str(get("source_model_alias", "sourceModelAlias", default="gpt-image-2-t2i")),
        candidate_model_alias=str(get("candidate_model_alias", "candidateModelAlias", default="gpt-image-2-edit")),
        anchor_model_alias=str(get("anchor_model_alias", "anchorModelAlias", default="gpt-image-2-edit")),
        chroma=str(get("chroma", default="#00FF00")),
        k_colors=int(get("k_colors", "kColors", default=256)),
        game_view=str(get("game_view", "gameView", default="platformer")),
        anchor_role=str(get("anchor_role", "anchorRole", default="character")),
        anchor_context=get("anchor_context", "anchorContext"),
        resume=bool(get("resume", default=False)),
        seed=_int_or_none(get("seed", default=None)),
    )


def write_bootstrap_summary(
    options: BootstrapAnchorsOptions,
    *,
    candidate_anchor: Path | None,
    anchors: dict[str, Path],
    character_json: Path,
    review_index: Path | None,
    status: str,
) -> Path:
    out = options.run_dir / "bootstrap.json"
    source_mode = "image" if options.source_image else "text"
    write_json(
        out,
        {
            "version": 1,
            "type": "bootstrap-anchors",
            "status": status,
            "updatedAt": now_iso(),
            "character": options.character_id,
            "directions": list(options.directions),
            "candidateFacing": options.candidate_facing,
            "sourceMode": source_mode,
            "sourceImage": _string_if_exists(options.run_dir / "input" / "source.png"),
            "sourceOriginal": _string_if_exists(options.run_dir / "input" / "source-original.png"),
            "sourceModelInput": _string_if_exists(options.run_dir / "input" / "source-model-input.png"),
            "sourceInputMetadata": _string_if_exists(options.run_dir / "input" / "source.json"),
            "sourceUserImage": str(options.source_image) if options.source_image else None,
            "sourcePromptFile": str(options.source_prompt_file) if options.source_prompt_file else None,
            "candidatePromptPreset": options.candidate_prompt_preset,
            "pixelSnapAnchor": options.pixel_snap_anchor,
            "candidatePromptSource": _candidate_prompt_source(options),
            "gameView": resolve_anchor_game_view(options.game_view),
            "anchorRole": resolve_anchor_role(options.anchor_role),
            "anchorContext": options.anchor_context,
            "candidateAnchor": str(candidate_anchor) if candidate_anchor else None,
            "anchors": {direction: str(path) for direction, path in anchors.items()},
            "canonicalOutputs": {
                "source": _string_if_exists(options.run_dir / "input" / "source.png"),
                "sourceOriginal": _string_if_exists(options.run_dir / "input" / "source-original.png"),
                "sourceModelInput": _string_if_exists(options.run_dir / "input" / "source-model-input.png"),
                "sourceInputMetadata": _string_if_exists(options.run_dir / "input" / "source.json"),
                "candidateRaw": _string_if_exists(candidate_dir_for(options.run_dir, options.candidate_facing) / "candidate-raw.png"),
                "candidateAnchor1024Chroma": _string_if_exists(candidate_dir_for(options.run_dir, options.candidate_facing) / "anchor-1024-chroma.png"),
                "candidateSnapped1024Chroma": _string_if_exists(candidate_anchor),
                "directionAnchors": {
                    direction: {
                        "raw": _string_if_exists(options.run_dir / "anchors" / direction / "anchor-raw.png"),
                        "anchor1024Chroma": _string_if_exists(options.run_dir / "anchors" / direction / "anchor-1024-chroma.png"),
                        "snapped1024Chroma": _string_if_exists(_final_anchor(options.run_dir, direction)),
                        "manifest": _string_if_exists(options.run_dir / "anchors" / direction / "anchor.json"),
                    }
                    for direction in options.directions
                },
                "character": _string_if_exists(character_json),
                "review": str(review_index) if review_index else None,
            },
            "config": {
                "request": str(options.run_dir / "config" / "bootstrap-request.json"),
                "candidatePromptRendered": str(options.run_dir / "config" / "candidate-prompt-rendered.txt"),
                "sourcePromptRendered": _string_if_exists(options.run_dir / "config" / "source-prompt-rendered.txt"),
            },
            "chroma": options.chroma,
            "kColors": options.k_colors,
            "models": {
                "source": options.source_model_alias,
                "candidate": options.candidate_model_alias,
                "anchor": options.anchor_model_alias,
            },
            "resume": options.resume,
            "dryFal": options.dry_fal,
        },
    )
    return out


def write_bootstrap_review(options: BootstrapAnchorsOptions, *, bootstrap_json: Path, review_index: Path | None) -> Path:
    candidate_anchor = existing_candidate_anchor(options.run_dir, options.candidate_facing) or default_candidate_anchor(options.run_dir, options.candidate_facing)
    candidate_label = "Front Candidate" if options.candidate_facing == "front" else "South Candidate"
    candidate_description = (
        "Front-facing identity production candidate."
        if options.candidate_facing == "front"
        else "South-facing top-down production candidate."
    )
    assets = [
        ReviewAsset("Source Image", options.run_dir / "input" / "source.png", "Generated or user-provided 1024x1024 source image.", True),
        ReviewAsset(candidate_label, candidate_anchor, candidate_description, True),
    ]
    for direction in options.directions:
        assets.append(
            ReviewAsset(
                f"{direction.upper()} Anchor",
                _final_anchor(options.run_dir, direction),
                f"{direction.upper()}-facing 1024x1024 chroma anchor.",
                True,
            )
        )
    assets.extend(
        [
            ReviewAsset("Bootstrap Metadata", bootstrap_json, "Machine-readable run summary and canonical output paths.", False),
            ReviewAsset("Anchor Wizard Review", review_index or options.run_dir / "review" / "index.md", "Underlying anchor wizard review page.", False),
        ]
    )
    return write_review_index(
        options.run_dir / "review" / "bootstrap",
        title=f"{options.character_id} Bootstrap Anchors",
        summary="Concrete text-or-image to front-facing platformer candidate and optional directional anchor bootstrap run.",
        notes=[
            f"Candidate facing: `{options.candidate_facing}`.",
            f"Directions: `{', '.join(options.directions) if options.directions else 'none'}`.",
            f"Candidate prompt preset: `{options.candidate_prompt_preset}`.",
            f"Anchor pixel snap: `{'enabled' if options.pixel_snap_anchor else 'disabled'}`.",
            f"Game view: `{resolve_anchor_game_view(options.game_view)}`.",
            f"Anchor role: `{resolve_anchor_role(options.anchor_role)}`.",
            "Use the 1024 chroma anchors as the stable references for animation generation.",
        ],
        assets=[asset for asset in assets if asset.path.exists()],
    )


def _write_bootstrap_request(options: BootstrapAnchorsOptions) -> Path:
    config_dir = options.run_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    data = _options_json(options)
    out = config_dir / "bootstrap-request.json"
    write_json(out, data)
    return out


def _write_prompt_config(options: BootstrapAnchorsOptions) -> None:
    config_dir = options.run_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    rendered_candidate = resolve_candidate_prompt(
        options.candidate_prompt,
        options.candidate_prompt_file,
        preset=options.candidate_prompt_preset,
        candidate_facing=options.candidate_facing,
        game_view=options.game_view,
        chroma=options.chroma,
    )
    (config_dir / "candidate-prompt-rendered.txt").write_text(rendered_candidate, encoding="utf-8")
    if options.candidate_prompt:
        (config_dir / "candidate-prompt-user.txt").write_text(options.candidate_prompt, encoding="utf-8")
    if options.candidate_prompt_file is not None:
        shutil.copy2(options.candidate_prompt_file, config_dir / "candidate-prompt-user.txt")

    user_prompt = _read_source_prompt(options)
    if user_prompt:
        (config_dir / "source-user-prompt.txt").write_text(user_prompt, encoding="utf-8")
        (config_dir / "source-prompt-rendered.txt").write_text(
            _source_prompt(
                user_prompt,
                high_fidelity=options.candidate_prompt_preset in {"high-fidelity-v1", "preserve-reference-v1"} or not options.pixel_snap_anchor,
                game_view=options.game_view,
            ),
            encoding="utf-8",
        )


def _sync_prompt_config(options: BootstrapAnchorsOptions) -> None:
    config_dir = options.run_dir / "config"
    copies = [
        (options.run_dir / "input" / "source-user-prompt.txt", config_dir / "source-user-prompt.txt"),
        (options.run_dir / "input" / "source-prompt.txt", config_dir / "source-prompt-rendered.txt"),
        (candidate_dir_for(options.run_dir, options.candidate_facing) / "candidate-prompt.txt", config_dir / "candidate-prompt-rendered.txt"),
    ]
    for source, target in copies:
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _validate_options(options: BootstrapAnchorsOptions) -> None:
    unknown = [direction for direction in options.directions if direction not in DIRECTIONS]
    if unknown:
        raise ValueError(f"unknown directions: {', '.join(unknown)}")
    if options.candidate_facing not in {"front", "south"}:
        raise ValueError("candidate_facing must be front or south")
    if options.candidate_prompt_preset not in CANDIDATE_PROMPT_PRESETS:
        raise ValueError(
            "candidate_prompt_preset must be one of: "
            + ", ".join(sorted(CANDIDATE_PROMPT_PRESETS))
        )
    resolve_anchor_game_view(options.game_view)
    resolve_anchor_role(options.anchor_role)
    if options.source_image is not None:
        require_file(options.source_image, "source image")
    if options.source_prompt_file is not None:
        require_file(options.source_prompt_file, "source prompt file")
    if options.candidate_image is not None:
        require_file(options.candidate_image, "candidate image")
    if options.candidate_prompt_file is not None:
        require_file(options.candidate_prompt_file, "candidate prompt file")
    if options.anchors_dir is not None and not options.anchors_dir.exists():
        raise FileNotFoundError(f"anchors dir does not exist: {options.anchors_dir}")
    if options.resume and existing_candidate_anchor(options.run_dir, options.candidate_facing):
        return
    source_count = int(options.source_image is not None) + int(bool(options.source_prompt)) + int(options.source_prompt_file is not None)
    if source_count != 1:
        raise ValueError("bootstrap requires exactly one of source_image, source_prompt, or source_prompt_file")


def _normalize_bootstrap_options(options: BootstrapAnchorsOptions) -> BootstrapAnchorsOptions:
    game_view = resolve_anchor_game_view(options.game_view)
    if game_view == "rts-oblique" and options.candidate_facing == "front":
        return replace(options, game_view=game_view, candidate_facing="south")
    if game_view != options.game_view:
        return replace(options, game_view=game_view)
    return options


def _read_source_prompt(options: BootstrapAnchorsOptions) -> str | None:
    if options.source_prompt_file is not None:
        return options.source_prompt_file.read_text(encoding="utf-8")
    return options.source_prompt


def _existing_anchors(run_dir: Path, directions: tuple[str, ...]) -> dict[str, Path]:
    anchors: dict[str, Path] = {}
    for direction in directions:
        final = _final_anchor(run_dir, direction)
        if final.exists():
            anchors[direction] = final
    return anchors


def _final_anchor(run_dir: Path, direction: str) -> Path:
    return run_dir / "anchors" / direction / "anchor-snapped-1024-chroma.png"


def _candidate_prompt_source(options: BootstrapAnchorsOptions) -> str:
    if options.candidate_prompt_file is not None:
        return str(options.candidate_prompt_file)
    if options.candidate_prompt:
        return "inline"
    return f"preset:{options.candidate_prompt_preset}"


def _string_if_exists(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return str(path)


def _path_or_none(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value))


def _bool_option(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _parse_directions(value: str) -> tuple[str, ...]:
    if value.strip().lower() in {"", "none", "no", "false"}:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _options_json(options: BootstrapAnchorsOptions) -> dict[str, Any]:
    data = asdict(options)
    for key, value in list(data.items()):
        if isinstance(value, Path):
            data[key] = str(value)
        elif isinstance(value, tuple):
            data[key] = list(value)
        elif isinstance(value, dict):
            data[key] = dict(value)
    return data
