from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .pipeline import RunOptions, run_pipeline
from .presets import get_action
from .review_index import ReviewAsset, write_review_index


@dataclass(frozen=True)
class ActionBatchOptions:
    actions: tuple[str, ...]
    direction: str
    reference: Path
    run_dir: Path
    mode: str = "image"
    existing_sheet_root: Path | None = None
    dry_fal: bool = False
    pixel_snap: bool = False
    pixel_snap_source: str = "recovered"
    k_colors: int = 256
    chroma: str = "#00FF00"
    pose_board_preset: str = "standard"
    frame_prompt_style: str = "specific"
    green_fringe_cleanup: bool = True
    green_fringe_min_green: int = 70
    green_fringe_dominance: int = 24
    green_fringe_edge_radius: int = 1


def run_action_batch(options: ActionBatchOptions) -> list[Path]:
    if not options.actions:
        raise ValueError("at least one action is required")

    outputs = []
    for action in options.actions:
        get_action(action)
        run_dir = options.run_dir / f"{action}-{options.direction}"
        existing_sheet = None
        if options.existing_sheet_root is not None:
            existing_sheet = options.existing_sheet_root / f"{action}-{options.direction}" / "generated" / "sheet.png"
        paths = run_pipeline(
            RunOptions(
                action=action,
                direction=options.direction,
                reference=options.reference,
                run_dir=run_dir,
                mode=options.mode,
                dry_fal=options.dry_fal,
                existing_sheet=existing_sheet,
                pixel_snap=options.pixel_snap,
                pixel_snap_source=options.pixel_snap_source,
                k_colors=options.k_colors,
                chroma=options.chroma,
                pose_board_preset=options.pose_board_preset,
                frame_prompt_style=options.frame_prompt_style,
                green_fringe_cleanup=options.green_fringe_cleanup,
                green_fringe_min_green=options.green_fringe_min_green,
                green_fringe_dominance=options.green_fringe_dominance,
                green_fringe_edge_radius=options.green_fringe_edge_radius,
            )
        )
        outputs.append(paths.root)

    _write_action_batch_review(options.run_dir, outputs)
    return outputs


def _write_action_batch_review(run_dir: Path, action_dirs: list[Path]) -> Path:
    assets: list[ReviewAsset] = []
    for action_dir in action_dirs:
        label = action_dir.name
        assets.extend(
            [
                ReviewAsset(
                    f"{label} Pixel Snap To Runtime Comparison",
                    action_dir / "review" / "compare-04-pixel-snap-to-runtime.png",
                    "Frame-by-frame recovered/source/pixel-snap/runtime comparison for the action.",
                    True,
                ),
                ReviewAsset(
                    f"{label} Runtime Preview",
                    action_dir / "review" / "preview.gif",
                    "Final normalized 256x256 runtime preview.",
                    True,
                ),
                ReviewAsset(
                    f"{label} Detailed Review",
                    action_dir / "review" / "index.md",
                    "Detailed per-action review page.",
                    False,
                ),
            ]
        )

    existing = [asset for asset in assets if asset.path.exists()]
    return write_review_index(
        run_dir / "review",
        title=f"{run_dir.name} Review",
        summary="Top-level review for a multi-action Spriterrific run.",
        assets=existing,
    )
