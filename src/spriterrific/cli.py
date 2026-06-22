from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageColor

from .action_batch import ActionBatchOptions, run_action_batch
from .chroma import despill_chroma, despill_chroma_batch, is_keyable_fringe_chroma
from .anchor_wizard import (
    AcceptAnchorOptions,
    AnchorWizardOptions,
    CANDIDATE_PROMPT_PRESETS,
    accept_direction_anchor,
    run_anchor_wizard,
)
from .anchor_wizard_gui import launch_anchor_wizard_gui
from .anchors import AnchorOptions, generate_anchors
from .bootstrap_anchors import BootstrapAnchorsOptions, load_bootstrap_options, run_bootstrap_anchors
from .frame_clean import CleanFrameOptions, clean_frame_batch
from .frame_aligner import launch_frame_aligner
from .finalize_runtime import FinalizeRuntimeOptions, finalize_runtime_animation_dirs
from .frame_picker import launch_frame_picker
from .frame_sheet import SheetFrameOptions, build_frame_sheet
from .pipeline import RunOptions, run_pipeline
from .pixel_snap import SnapOptions, snap_user_anchor
from .post_selection import PostSelectionOptions, default_post_selection_output_dir, process_frame_picker_selection
from .preprocess import preprocess_user_anchor
from .presets import ACTION_PRESETS, ANCHOR_GAME_VIEWS, ANCHOR_ROLES, ANIMATION_TEMPLATES, DIRECTIONS, FRAME_COUNT_PROFILES, POSE_BOARD_PRESETS, REFERENCE_SIZE, resolve_animation_template
from .runids import default_run_dir
from .size_contract import audit_size_contract, derive_size_contract, load_size_contract
from .skill_install import SKILL_TARGET_DIRS, install_skill
from .sprite_cleanup import launch_sprite_cleanup
from .validate import validate_export_sheet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spriterrific", description="VibeGameDev Sprite Tool — constrained AI sprite animation pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run an image or video spritesheet pipeline.")
    run.add_argument("--action", required=True, choices=sorted(ACTION_PRESETS))
    run.add_argument("--direction", required=True, choices=sorted(DIRECTIONS))
    run.add_argument("--reference", type=Path, required=True)
    run.add_argument(
        "--end-reference",
        type=Path,
        default=None,
        help="Optional final-frame reference for transition video actions. Requires a video model that supports first+last-frame generation, such as wan-2.7.",
    )
    run.add_argument("--run-dir", type=Path, default=None)
    run.add_argument("--mode", choices=["image", "video"], default=None)
    run.add_argument("--frames", type=int, default=None, help="Final frame count. Defaults depend on action and --preset-profile.")
    run.add_argument(
        "--preset-profile",
        choices=sorted(FRAME_COUNT_PROFILES),
        default="platformer",
        help="Frame-count profile. platformer keeps Spriterrific defaults; fighting-game uses longer animation-friendly defaults.",
    )
    run.add_argument(
        "--animation-template",
        choices=sorted(ANIMATION_TEMPLATES),
        default=None,
        help="User-facing animation template. Maps to a frame-count profile while keeping engine actions generic.",
    )
    run.add_argument(
        "--allow-frame-count-override",
        action="store_true",
        help="Expert mode: allow --frames outside the action preset list for manual video recovery with --existing-video, --selected-order, or --selected-range.",
    )
    run.add_argument(
        "--strict-frame-counts",
        action="store_true",
        help="Fail instead of coercing unsupported --frames values to the nearest recommended frame count.",
    )
    run.add_argument("--dry-fal", action="store_true")
    run.add_argument("--seed", type=int, default=None, help="Optional provider seed passed through to supported FAL image/video models.")
    run.add_argument("--existing-sheet", type=Path, default=None)
    run.add_argument("--existing-video", type=Path, default=None)
    run.add_argument("--selected-order", default=None, help="Comma-separated dense video frame filenames.")
    run.add_argument(
        "--selected-range",
        default=None,
        help="Dense frame range as START:END_EXCLUSIVE, e.g. 7:31 selects from frame-0007 through frame-0030.",
    )
    run.add_argument("--fps", type=int, default=None, help="Override exported preview/runtime FPS. Useful for slower walk cycles.")
    run.add_argument(
        "--cycle-start-fraction",
        type=float,
        default=None,
        help="Override automatic loop-cycle start as a 0..1 fraction through dense video frames.",
    )
    run.add_argument(
        "--cycle-span-factor",
        type=float,
        default=None,
        help="Override automatic loop-cycle span multiplier. Higher values sample a wider loop window.",
    )
    run.add_argument("--bg-remove", choices=["auto", "none", "chroma", "bria"], default="auto", help="Background removal after recovery.")
    run.add_argument("--chroma", default="#00FF00", help="Opaque matte/chroma color expected from generation and used for cleanup, e.g. #00FF00 or #FF00FF.")
    run.add_argument("--pixel-snap", action="store_true", help="Pixel snap recovered image-action frames before runtime normalization.")
    run.add_argument(
        "--pixel-snap-source",
        choices=["recovered", "chroma-layout", "transparent-layout"],
        default="recovered",
        help="Pixel-snap strategy when --pixel-snap is enabled.",
    )
    run.add_argument("--k-colors", type=int, default=256, help="Pixel-snapper k-means palette size when --pixel-snap is enabled.")
    run.add_argument("--no-green-fringe-cleanup", action="store_true", help="Disable targeted matte fringe cleanup after chroma-layout background cleaning (applies to any saturated matte color, e.g. #00FF00 or #FF00FF).")
    run.add_argument("--green-fringe-min-green", type=int, default=70)
    run.add_argument("--green-fringe-dominance", type=int, default=24)
    run.add_argument("--green-fringe-edge-radius", type=int, default=1)
    run.add_argument(
        "--pose-board-preset",
        choices=sorted(POSE_BOARD_PRESETS),
        default="standard",
        help="Image-generation pose board size preset. standard=1536x1152/384px cells; hires=2048x1536/512px cells.",
    )
    run.add_argument(
        "--frame-prompt-style",
        choices=["specific", "loose"],
        default="specific",
        help="Image prompt frame guidance. specific labels each frame; loose keeps layout strict but lets the model choose action in-betweens.",
    )
    run.add_argument(
        "--video-model",
        default=None,
        help="Override the action preset video model. Video actions default to grok-imagine-video-i2v (Grok Imagine); use wan-2.2-a14b-i2v-turbo, seedance-2.0-i2v, or wan-2.7 only when requested.",
    )
    run.add_argument(
        "--video-duration",
        default=None,
        help=(
            "Override generated video duration in seconds where the provider supports it. "
            "WAN turbo maps this to num_frames; Grok minimum is 1, Seedance minimum is 4, WAN 2.7 minimum is 2."
        ),
    )
    run.add_argument(
        "--action-context",
        default=None,
        help="Optional bounded action note appended to the controlled prompt, e.g. 'attack with a compact fireball'.",
    )
    run.add_argument(
        "--size-contract",
        type=Path,
        default=None,
        help="Optional Spriterrific size-contract JSON used to add scale/anchor guidance to generation prompts.",
    )
    run.add_argument(
        "--layout-mode",
        choices=["preserve-canvas", "fit-foreground"],
        default=None,
        help="Video export layout. preserve-canvas keeps the full video frame scale/position; fit-foreground crops and recenters the sprite. Defaults to preserve-canvas for video actions.",
    )
    run.add_argument(
        "--video-recovery",
        choices=["preserve-canvas", "fit-foreground"],
        dest="layout_mode",
        default=None,
        help="Alias for --layout-mode for video runs. Use preserve-canvas for stable image-to-video outputs.",
    )
    run.add_argument(
        "--preserve-video-canvas",
        dest="layout_mode",
        action="store_const",
        const="preserve-canvas",
        help="Alias for --layout-mode preserve-canvas.",
    )
    run.add_argument(
        "--preserve-motion",
        dest="layout_mode",
        action="store_const",
        const="preserve-canvas",
        help="Alias for --layout-mode preserve-canvas. Recommended for video actions with a consistent camera canvas.",
    )
    run.add_argument(
        "--normalize-foreground",
        dest="layout_mode",
        action="store_const",
        const="fit-foreground",
        help="Alias for --layout-mode fit-foreground. Crops and normalizes visible sprite height/baseline per frame.",
    )

    run_actions = subparsers.add_parser("run-actions", help="Run multiple actions through the same Spriterrific pipeline and write a top-level review.")
    run_actions.add_argument("--actions", default="idle,attack,hurt,jump,death", help="Comma-separated actions.")
    run_actions.add_argument("--direction", required=True, choices=sorted(DIRECTIONS))
    run_actions.add_argument("--reference", type=Path, required=True)
    run_actions.add_argument("--run-dir", type=Path, required=True)
    run_actions.add_argument("--mode", choices=["image"], default="image")
    run_actions.add_argument("--existing-sheet-root", type=Path, default=None, help="Root containing <action>-<direction>/generated/sheet.png.")
    run_actions.add_argument("--dry-fal", action="store_true")
    run_actions.add_argument("--pixel-snap", action="store_true")
    run_actions.add_argument("--pixel-snap-source", choices=["recovered", "chroma-layout", "transparent-layout"], default="recovered")
    run_actions.add_argument("--k-colors", type=int, default=256)
    run_actions.add_argument("--chroma", default="#00FF00", help="Opaque matte/chroma color expected from generation and used for cleanup.")
    run_actions.add_argument("--no-green-fringe-cleanup", action="store_true", help="Disable targeted matte fringe cleanup after chroma-layout background cleaning (applies to any saturated matte color, e.g. #00FF00 or #FF00FF).")
    run_actions.add_argument("--green-fringe-min-green", type=int, default=70)
    run_actions.add_argument("--green-fringe-dominance", type=int, default=24)
    run_actions.add_argument("--green-fringe-edge-radius", type=int, default=1)
    run_actions.add_argument(
        "--pose-board-preset",
        choices=sorted(POSE_BOARD_PRESETS),
        default="standard",
        help="Image-generation pose board size preset. standard=1536x1152/384px cells; hires=2048x1536/512px cells.",
    )
    run_actions.add_argument(
        "--frame-prompt-style",
        choices=["specific", "loose"],
        default="specific",
        help="Image prompt frame guidance. specific labels each frame; loose keeps layout strict but lets the model choose action in-betweens.",
    )

    anchors = subparsers.add_parser("anchors", help="Generate n/s/e/w directional anchors from one reference image.")
    anchors.add_argument("--reference", type=Path, required=True)
    anchors.add_argument("--run-dir", type=Path, default=None)
    anchors.add_argument("--directions", default="n,s,e,w", help="Comma-separated directions. Defaults to n,s,e,w.")
    anchors.add_argument("--dry-fal", action="store_true")
    anchors.add_argument("--model-alias", default="gpt-image-2-edit")
    anchors.add_argument("--no-preprocess", action="store_true", help="Require the reference to already be a 1024x1024 anchor.")
    anchors.add_argument("--preprocess-padding", type=int, default=48, help="Chroma padding around the snapped foreground.")
    anchors.add_argument("--pixel-snap-long-edge", type=int, default=256, help="Foreground long edge used before nearest-neighbor upscale.")
    anchors.add_argument("--chroma", default="#00FF00", help="Opaque background color for preprocessed anchors.")
    anchors.add_argument("--k-colors", type=int, default=256, help="Pixel-snapper k-means palette size.")
    anchors.add_argument("--game-view", choices=sorted(ANCHOR_GAME_VIEWS), default="platformer", help="Game view used to render direction prompts. Use rts-oblique for Warcraft-like RTS units; top-down and isometric are experimental.")
    anchors.add_argument("--anchor-role", choices=sorted(ANCHOR_ROLES), default="character", help="Asset role used to render direction prompts.")
    anchors.add_argument("--anchor-context", default=None, help="Optional short context appended to direction prompts.")

    bootstrap = subparsers.add_parser("bootstrap-anchors", help="Run the text-or-image to front candidate plus optional directional anchor bootstrap workflow.")
    bootstrap.add_argument("--config", type=Path, default=None, help="Load a previously saved bootstrap request JSON.")
    bootstrap.add_argument("--run-dir", type=Path, default=None)
    bootstrap.add_argument("--character-id", default="character")
    bootstrap.add_argument("--source-image", type=Path, default=None, help="User-supplied source image.")
    bootstrap.add_argument("--source-prompt", default=None, help="Text prompt for generating the source image.")
    bootstrap.add_argument("--source-prompt-file", type=Path, default=None)
    bootstrap.add_argument("--candidate-image", type=Path, default=None, help="Existing production candidate image.")
    bootstrap.add_argument("--candidate-prompt", default=None, help="Inline override for the rendered candidate prompt.")
    bootstrap.add_argument("--candidate-prompt-file", type=Path, default=None)
    bootstrap.add_argument(
        "--candidate-prompt-preset",
        choices=sorted(CANDIDATE_PROMPT_PRESETS),
        default="lobit-v1",
        help="Candidate style preset. lobit-v1 is snap-ready low-bit; high-fidelity-v1 keeps richer mixel art; preserve-reference-v1 treats --source-image as strict visual authority.",
    )
    bootstrap.add_argument(
        "--pixel-snap-anchor",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Pixel snap candidate and directional anchors. Use --no-pixel-snap-anchor for high-fidelity/mixel anchors.",
    )
    bootstrap.add_argument(
        "--candidate-facing",
        choices=["front", "south"],
        default="front",
        help="Base candidate facing. Defaults to front for platformers; --game-view rts-oblique auto-normalizes front to south.",
    )
    bootstrap.add_argument("--anchors-dir", type=Path, default=None, help="Existing generated anchors directory to pixel-snap instead of calling fal.")
    bootstrap.add_argument("--directions", default="w", help="Comma-separated directions. Defaults to w for the bootstrap use case.")
    bootstrap.add_argument("--no-directions", action="store_true", help="Generate only the front/south candidate anchor and skip directional anchors.")
    bootstrap.add_argument("--resume", action="store_true", help="Reuse existing candidate/anchors in the run folder when present.")
    bootstrap.add_argument("--dry-fal", action="store_true")
    bootstrap.add_argument("--seed", type=int, default=None, help="Optional provider seed passed through to supported FAL image models.")
    bootstrap.add_argument("--source-model-alias", default="gpt-image-2-t2i")
    bootstrap.add_argument("--candidate-model-alias", default="gpt-image-2-edit")
    bootstrap.add_argument("--anchor-model-alias", default="gpt-image-2-edit")
    bootstrap.add_argument("--chroma", default="#00FF00")
    bootstrap.add_argument("--k-colors", type=int, default=256)
    bootstrap.add_argument("--game-view", choices=sorted(ANCHOR_GAME_VIEWS), default="platformer", help="Game view used to render direction prompts. Use rts-oblique for Warcraft-like RTS units; top-down and isometric are experimental.")
    bootstrap.add_argument("--anchor-role", choices=sorted(ANCHOR_ROLES), default="character", help="Asset role used to render direction prompts.")
    bootstrap.add_argument("--anchor-context", default=None, help="Optional short context appended to direction prompts.")

    wizard = subparsers.add_parser("anchor-wizard", help="Create a production candidate and optional N/S/E/W anchors from text or an image.")
    wizard.add_argument("--stage", choices=["candidate", "directions", "all"], default="candidate")
    wizard.add_argument("--run-dir", type=Path, default=None)
    wizard.add_argument("--character-id", default="character")
    wizard.add_argument("--source-image", type=Path, default=None, help="User-supplied source image.")
    wizard.add_argument("--source-prompt", default=None, help="Text prompt for generating the source image.")
    wizard.add_argument("--source-prompt-file", type=Path, default=None)
    wizard.add_argument("--candidate-image", type=Path, default=None, help="Existing production candidate image.")
    wizard.add_argument("--candidate-prompt", default=None, help="Inline override for the rendered candidate prompt.")
    wizard.add_argument("--candidate-prompt-file", type=Path, default=None)
    wizard.add_argument(
        "--candidate-prompt-preset",
        choices=sorted(CANDIDATE_PROMPT_PRESETS),
        default="lobit-v1",
        help="Candidate style preset. lobit-v1 is snap-ready low-bit; high-fidelity-v1 keeps richer mixel art; preserve-reference-v1 treats --source-image as strict visual authority.",
    )
    wizard.add_argument(
        "--pixel-snap-anchor",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Pixel snap candidate and directional anchors. Use --no-pixel-snap-anchor for high-fidelity/mixel anchors.",
    )
    wizard.add_argument(
        "--candidate-facing",
        choices=["front", "south"],
        default="front",
        help="Base candidate facing. Defaults to front for platformers; --game-view rts-oblique auto-normalizes front to south.",
    )
    wizard.add_argument("--accepted-candidate", type=Path, default=None, help="Accepted 1024x1024 chroma candidate for direction generation.")
    wizard.add_argument("--anchors-dir", type=Path, default=None, help="Existing generated anchors directory to pixel-snap instead of calling fal.")
    wizard.add_argument("--directions", default="n,s,e,w", help="Comma-separated directions. Defaults to n,s,e,w.")
    wizard.add_argument("--dry-fal", action="store_true")
    wizard.add_argument("--seed", type=int, default=None, help="Optional provider seed passed through to supported FAL image models.")
    wizard.add_argument("--source-model-alias", default="gpt-image-2-t2i")
    wizard.add_argument("--candidate-model-alias", default="gpt-image-2-edit")
    wizard.add_argument("--anchor-model-alias", default="gpt-image-2-edit")
    wizard.add_argument("--chroma", default="#00FF00")
    wizard.add_argument("--k-colors", type=int, default=256)
    wizard.add_argument("--game-view", choices=sorted(ANCHOR_GAME_VIEWS), default="platformer", help="Game view used to render direction prompts. Use rts-oblique for Warcraft-like RTS units; top-down and isometric are experimental.")
    wizard.add_argument("--anchor-role", choices=sorted(ANCHOR_ROLES), default="character", help="Asset role used to render direction prompts.")
    wizard.add_argument("--anchor-context", default=None, help="Optional short context appended to direction prompts.")

    wizard_gui = subparsers.add_parser("anchor-wizard-gui", help="Open a GUI for staged source/candidate/N/S/E/W anchor setup.")
    wizard_gui.add_argument("--run-dir", type=Path, default=None)

    accept_anchor = subparsers.add_parser("accept-anchor", help="Promote a reviewed 1024x1024 snapped chroma anchor into a run's canonical anchors/<direction> folder.")
    accept_anchor.add_argument("--run-dir", type=Path, required=True)
    accept_anchor.add_argument("--direction", required=True, choices=sorted(DIRECTIONS))
    accept_anchor.add_argument("--source", type=Path, required=True, help="Accepted 1024x1024 snapped chroma anchor image.")
    accept_anchor.add_argument("--reason", default=None)
    accept_anchor.add_argument("--character-id", default=None)
    accept_anchor.add_argument("--candidate-facing", choices=["front", "south"], default="front")
    accept_anchor.add_argument("--chroma", default="#00FF00")
    accept_anchor.add_argument("--k-colors", type=int, default=256)
    accept_anchor.add_argument("--game-view", choices=sorted(ANCHOR_GAME_VIEWS), default="platformer")
    accept_anchor.add_argument("--anchor-role", choices=sorted(ANCHOR_ROLES), default="character")
    accept_anchor.add_argument("--anchor-context", default=None)

    preprocess = subparsers.add_parser("preprocess", help="Pixel-snap user input onto a 1024x1024 chroma anchor.")
    preprocess.add_argument("--reference", type=Path, required=True)
    preprocess.add_argument("--out", type=Path, required=True)
    preprocess.add_argument("--metadata", type=Path, default=None)
    preprocess.add_argument("--padding", type=int, default=48)
    preprocess.add_argument("--pixel-snap-long-edge", type=int, default=256)
    preprocess.add_argument("--chroma", default="#00FF00")

    snap = subparsers.add_parser("snap", help="Run the pixel-snapper skill on an input image and upscale to a 1024x1024 anchor.")
    snap.add_argument("--reference", type=Path, required=True, help="Input image to snap.")
    snap.add_argument("--run-dir", type=Path, default=None, help="Override the timestamped run folder.")
    snap.add_argument("--k-colors", type=int, default=256, help="Pixel-snapper k-means palette size.")
    snap.add_argument(
        "--target-size",
        type=int,
        nargs=2,
        metavar=("W", "H"),
        default=list(REFERENCE_SIZE),
        help="Target anchor size (default 1024 1024).",
    )
    snap.add_argument("--chroma", default="#00FF00", help="Chroma fill color for the chroma anchor variant.")
    snap.add_argument("--no-chroma", action="store_true", help="Skip producing the chroma anchor variant.")

    clean = subparsers.add_parser("clean-frames", help="Despeckle transparent frame crops after background removal.")
    clean.add_argument("--input-dir", type=Path, required=True)
    clean.add_argument("--out-dir", type=Path, required=True)
    clean.add_argument("--glob", default="frame-*.png")
    clean.add_argument("--alpha-threshold", type=int, default=24)
    clean.add_argument("--neutral-delta", type=int, default=18)
    clean.add_argument("--neutral-min-mean", type=float, default=112.0)
    clean.add_argument("--min-component-area", type=int, default=6)
    clean.add_argument("--edge-radius", type=int, default=1)
    clean.add_argument("--no-trim", action="store_true")

    sheet = subparsers.add_parser("sheet-frames", help="Normalize cleaned frame crops into a spritesheet and preview GIF.")
    sheet.add_argument("--input-dir", type=Path, required=True)
    sheet.add_argument("--out-dir", type=Path, required=True)
    sheet.add_argument("--glob", default="frame-*.png")
    sheet.add_argument("--order", default=None, help="Comma-separated frame ids, e.g. 01,02,03 or frame-01.png,...")
    sheet.add_argument("--drop", default=None, help="Comma-separated frame ids to omit after ordering.")
    sheet.add_argument("--cell-size", type=int, nargs=2, metavar=("W", "H"), default=[256, 256])
    sheet.add_argument("--target-height", type=int, default=None, help="Visible sprite height before padding. Defaults to cell height.")
    sheet.add_argument("--columns", type=int, default=5)
    sheet.add_argument("--fps", type=int, default=10)
    sheet.add_argument("--review-upscale", type=int, default=4)

    picker = subparsers.add_parser("frame-picker", help="Open a GUI to pick frames from an extracted video run.")
    picker.add_argument("--run-dir", type=Path, default=None, help="Existing video run containing extracted/dense-frames.")
    picker.add_argument("--frames-dir", type=Path, default=None, help="Override dense frame directory.")
    picker.add_argument("--video", type=Path, default=None, help="Raw video path for report metadata.")
    picker.add_argument("--out-dir", type=Path, default=None, help="Where to write report.md, selection.json, and selected frames.")
    picker.add_argument("--frames", type=int, default=6, help="Default number of frames to select between start/end.")
    picker.add_argument("--action", default=None, help="Action for follow-on command, such as walk, run, idle, or crouch.")
    picker.add_argument("--direction", default=None, help="Direction for follow-on command, n/s/e/w.")
    picker.add_argument("--reference", type=Path, default=None, help="Reference image for follow-on command.")

    aligner = subparsers.add_parser("frame-aligner", help="Open a GUI to manually nudge runtime frames and rebuild a spritesheet.")
    aligner.add_argument("--input-dir", type=Path, required=True, help="Directory of already-normalized runtime frames.")
    aligner.add_argument("--out-dir", type=Path, default=None, help="Where to write aligned frames, spritesheet, GIF, and report.")
    aligner.add_argument("--glob", default="frame-*.png")
    aligner.add_argument("--columns", type=int, default=5)
    aligner.add_argument("--fps", type=int, default=10)
    aligner.add_argument("--zoom", type=int, default=3)

    cleanup = subparsers.add_parser("sprite-cleanup", help="Open a GUI to pencil/erase/dropper-clean a final spritesheet or runtime frames.")
    cleanup_source = cleanup.add_mutually_exclusive_group(required=True)
    cleanup_source.add_argument("--sheet", type=Path, help="Final exported spritesheet PNG to clean as one image.")
    cleanup_source.add_argument("--input-dir", type=Path, help="Directory of final ready-to-export runtime frames.")
    cleanup.add_argument("--out-dir", type=Path, default=None, help="Where to write cleaned frames/spritesheet, review assets, and metadata.")
    cleanup.add_argument("--glob", default="frame-*.png", help="Frame glob when using --input-dir.")
    cleanup.add_argument("--columns", type=int, default=5, help="Spritesheet columns when exporting cleaned frame directories.")
    cleanup.add_argument("--fps", type=int, default=10, help="Preview GIF frame rate when exporting cleaned frame directories.")
    cleanup.add_argument("--zoom", type=int, default=4, help="Nearest-neighbor editor zoom.")

    despill = subparsers.add_parser(
        "despill",
        help="Neutralize residual matte color bleeding on a finished spritesheet or runtime frames without re-running the pipeline.",
    )
    despill_source = despill.add_mutually_exclusive_group(required=True)
    despill_source.add_argument("--sheet", type=Path, help="Final exported spritesheet PNG to despill as one image.")
    despill_source.add_argument("--input-dir", type=Path, help="Directory of runtime frames to despill.")
    despill.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output spritesheet file (with --sheet) or directory (with --input-dir). Defaults to overwriting the input in place.",
    )
    despill.add_argument("--chroma", default="#00FF00", help="Matte color whose bleed should be neutralized, e.g. #00FF00 or #FF00FF.")
    despill.add_argument("--glob", default="frame-*.png", help="Frame glob when using --input-dir.")
    despill.add_argument("--edge-radius", type=int, default=2, help="How many pixels in from a transparent edge to despill.")
    despill.add_argument(
        "--whole-image",
        action="store_true",
        help="Despill every foreground pixel, not just the matte edge band. Use only when sprites carry no genuine matte-colored detail.",
    )

    viewer = subparsers.add_parser("viewer", help="Open a GUI to browse runs, preview spritesheets/GIFs, and launch frame tools.")
    viewer.add_argument("--project-dir", type=Path, default=None, help="Project folder to scan. Defaults to the project resolved from the current directory.")
    viewer.add_argument("--run-dir", type=Path, default=None, help="Run folder to preselect in the viewer.")

    finalize = subparsers.add_parser("finalize-runtime", help="Apply final runtime anchor policy to animation exports.")
    finalize.add_argument(
        "--animation-dir",
        type=Path,
        action="append",
        required=True,
        help="Animation folder containing manifest.json, spritesheet.png, and preview.gif. May be repeated.",
    )
    finalize.add_argument("--anchor-policy", choices=["auto", "grounded", "preserve-motion", "centered"], default="auto")
    finalize.add_argument("--target-bottom-y", type=int, default=None, help="Grounded policy target bottom pixel. Default: cell height - 1.")
    finalize.add_argument("--target-center-x", type=int, default=None, help="Centered policy target x. Default: cell width / 2.")

    size_contract = subparsers.add_parser("size-contract", help="Derive a size-contract JSON from approved runtime frames or a spritesheet.")
    size_contract.add_argument("--source", type=Path, required=True, help="Frame directory, single PNG, or packed spritesheet.")
    size_contract.add_argument("--out", type=Path, default=None, help="Output contract JSON. Defaults beside the source.")
    size_contract.add_argument("--frame-glob", default="frame-*.png", help="Frame glob when --source is a directory.")
    size_contract.add_argument("--cell-size", type=int, nargs=2, metavar=("W", "H"), default=[256, 256])
    size_contract.add_argument("--name", default=None)
    size_contract.add_argument("--action", default=None)
    size_contract.add_argument("--direction", default=None)
    size_contract.add_argument("--anchor-policy", choices=["grounded", "preserve-motion", "centered"], default="grounded")
    size_contract.add_argument("--pivot", default="base-center", help="Human-facing pivot name, e.g. base-center or foot-center.")
    size_contract.add_argument("--source-canvas", type=int, nargs=2, metavar=("W", "H"), default=None)
    size_contract.add_argument("--max-target-height-drift-pct", type=float, default=None)
    size_contract.add_argument("--max-intra-height-drift-pct", type=float, default=None)
    size_contract.add_argument("--max-bottom-drift-px", type=int, default=None)
    size_contract.add_argument("--max-width-overflow-pct", type=float, default=None)
    size_contract.add_argument("--max-center-drift-px", type=int, default=None)

    audit_contract = subparsers.add_parser("audit-size-contract", help="Audit frames or a spritesheet against a size-contract JSON.")
    audit_contract.add_argument("--source", type=Path, required=True, help="Frame directory, single PNG, or packed spritesheet.")
    audit_contract.add_argument("--contract", type=Path, required=True)
    audit_contract.add_argument("--out", type=Path, default=None)
    audit_contract.add_argument("--frame-glob", default="frame-*.png")
    audit_contract.add_argument("--cell-size", type=int, nargs=2, metavar=("W", "H"), default=None)
    audit_contract.add_argument("--stage", default="manual")
    audit_contract.add_argument("--strict", action="store_true", help="Exit non-zero when the contract audit warns.")

    post = subparsers.add_parser("process-selection", help="Process a frame-picker selection into runtime frames and a spritesheet.")
    post.add_argument("--picker-dir", type=Path, required=True, help="Frame picker output folder containing selected/ and report files.")
    post.add_argument("--out-dir", type=Path, default=None, help="Where to write processed frames, spritesheet, previews, and handoff report.")
    post.add_argument("--action", default="walk")
    post.add_argument("--direction", default="w")
    post.add_argument("--columns", type=int, default=5)
    post.add_argument("--fps", type=int, default=10)
    post.add_argument("--k-colors", type=int, default=256)
    post.add_argument("--chroma", default="#00FF00", help="Opaque matte/chroma color to key from selected frames.")
    post.add_argument("--chroma-threshold", type=float, default=90.0)
    post.add_argument("--chroma-min-component-area", type=int, default=4)
    post.add_argument("--no-green-fringe-cleanup", action="store_true", help="Disable targeted matte fringe removal after chroma keying (applies to any saturated matte color, e.g. #00FF00 or #FF00FF).")
    post.add_argument("--green-fringe-min-green", type=int, default=70)
    post.add_argument("--green-fringe-dominance", type=int, default=24)
    post.add_argument("--cell-size", type=int, nargs=2, metavar=("W", "H"), default=[256, 256])
    post.add_argument("--target-height", type=int, default=None, help="Visible sprite target height. Defaults to about 82%% of cell height.")
    post.add_argument("--max-width", type=int, default=None, help="Visible sprite max width. Defaults to about 86%% of cell width.")
    post.add_argument("--center-x", type=int, default=None, help="Runtime anchor center x. Defaults to half the cell width.")
    post.add_argument("--ground-y", type=int, default=None, help="Runtime visible bottom baseline. Defaults to a padded baseline above the bottom edge.")
    post.add_argument(
        "--layout-mode",
        choices=["preserve-canvas", "fit-foreground"],
        default=None,
        help="preserve-canvas scales the full selected video frame into the runtime cell; fit-foreground crops and normalizes the visible sprite. Defaults to preserve-canvas for video actions.",
    )
    post.add_argument(
        "--video-recovery",
        choices=["preserve-canvas", "fit-foreground"],
        dest="layout_mode",
        default=None,
        help="Alias for --layout-mode. Use preserve-canvas for stable image-to-video frame selections.",
    )
    post.add_argument(
        "--preserve-video-canvas",
        dest="layout_mode",
        action="store_const",
        const="preserve-canvas",
        help="Alias for --layout-mode preserve-canvas.",
    )
    post.add_argument(
        "--preserve-motion",
        dest="layout_mode",
        action="store_const",
        const="preserve-canvas",
        help="Alias for --layout-mode preserve-canvas. Recommended for image-to-video actions with a stable source canvas.",
    )
    post.add_argument(
        "--normalize-foreground",
        dest="layout_mode",
        action="store_const",
        const="fit-foreground",
        help="Alias for --layout-mode fit-foreground. Useful when selected frames need consistent visible sprite height and baseline.",
    )
    post.add_argument("--scale-mode", choices=["per-frame", "shared"], default="per-frame")
    post.add_argument("--no-upscale", action="store_true", help="Do not upscale cleaned native crops while fitting to the runtime cell.")
    post.add_argument("--review-upscale", type=int, default=4)
    post.add_argument("--pixel-snap", dest="pixel_snap", action="store_true", default=False, help="Run pixel snapper on full selected frames before cleanup.")
    post.add_argument("--no-pixel-snap", dest="pixel_snap", action="store_false", help="Skip pixel snap and process selected frames directly.")
    post.add_argument(
        "--pixel-snap-mode",
        choices=["discover-per-frame", "locked-grid"],
        default="discover-per-frame",
        help="Pixel-snap strategy. locked-grid discovers one grid from a selected frame and reuses it across the sequence.",
    )
    post.add_argument(
        "--pixel-snap-grid-source",
        default=None,
        help="Frame filename or path used to discover the locked grid, e.g. frame-01.png. Defaults to the first selected frame.",
    )
    post.add_argument("--pixel-snap-workers", type=int, default=1, help="Number of selected frames to pixel-snap concurrently.")
    post.add_argument(
        "--size-contract",
        type=Path,
        default=None,
        help="Optional Spriterrific size-contract JSON. Its target height, width, center, and bottom fill unset normalization defaults and write an audit.",
    )
    post.add_argument("--size-contract-strict", action="store_true", help="Fail the run when the runtime size-contract audit warns.")

    inspect = subparsers.add_parser("inspect", help="Print run metadata.")
    inspect.add_argument("--run-dir", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="Validate an exported run.")
    validate.add_argument("--run-dir", type=Path, required=True)

    skill = subparsers.add_parser("skill", help="Manage the bundled Spriterrific agent skill.")
    skill.add_argument("skill_action", choices=["install"], help="Skill action to perform.")
    skill.add_argument("--dest", type=Path, default=Path("."), help="Project root to install the skill into (default: current directory).")
    skill.add_argument(
        "--target",
        action="append",
        choices=[*SKILL_TARGET_DIRS, "all"],
        help="Agent skill folder(s) to install into: claude (.claude/skills), codex (.codex/skills), agents (.agents/skills), or all. Default: claude.",
    )
    skill.add_argument("--force", action="store_true", help="Overwrite an existing installed skill.")

    return parser


def _parse_selected_range(value: str) -> tuple[int, int]:
    try:
        start_text, end_text = value.split(":", maxsplit=1)
        start = int(start_text)
        end = int(end_text)
    except ValueError as exc:
        raise SystemExit("--selected-range must be START:END_EXCLUSIVE, e.g. 7:31") from exc
    if start < 1 or end <= start:
        raise SystemExit("--selected-range must have START >= 1 and END_EXCLUSIVE > START")
    return (start, end)


def _parse_csv(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_directions_arg(value: str) -> tuple[str, ...]:
    if value.strip().lower() in {"", "none", "no", "false"}:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        selected_order = [part.strip() for part in args.selected_order.split(",") if part.strip()] if args.selected_order else None
        selected_range = _parse_selected_range(args.selected_range) if args.selected_range else None
        run_dir = args.run_dir or default_run_dir("run", [args.action, args.direction, args.mode or "default"])
        action_preset = ACTION_PRESETS[args.action]
        animation_template = resolve_animation_template(args.animation_template or args.preset_profile)
        frame_count_profile = animation_template.frame_count_profile
        resolved_mode = args.mode or action_preset.default_mode
        if resolved_mode == "video":
            if args.video_model:
                print(f"Using requested video model: {args.video_model}.", file=sys.stderr)
            elif args.end_reference:
                print(
                    "Using video model: wan-2.7 because --end-reference requires first+last-frame support.",
                    file=sys.stderr,
                )
            else:
                print(
                    "Using default video model: grok-imagine-video-i2v (Grok Imagine image-to-video). "
                    "It uses a short clip (duration=1, or duration=2 for walk) to limit identity/costume drift. "
                    "Use --video-model wan-2.2-a14b-i2v-turbo, seedance-2.0-i2v, or wan-2.7 only if you explicitly want that experiment.",
                    file=sys.stderr,
                )
        paths = run_pipeline(
            RunOptions(
                action=args.action,
                direction=args.direction,
                reference=args.reference,
                end_reference=args.end_reference,
                run_dir=run_dir,
                mode=args.mode,
                frame_count=args.frames,
                frame_count_profile=frame_count_profile,
                animation_template=animation_template.id,
                allow_frame_count_override=args.allow_frame_count_override,
                strict_frame_counts=args.strict_frame_counts,
                dry_fal=args.dry_fal,
                existing_sheet=args.existing_sheet,
                existing_video=args.existing_video,
                selected_order=selected_order,
                selected_range=selected_range,
                fps=args.fps,
                cycle_start_fraction=args.cycle_start_fraction,
                cycle_span_factor=args.cycle_span_factor,
                bg_remove=args.bg_remove,
                chroma=args.chroma,
                pixel_snap=args.pixel_snap,
                pixel_snap_source=args.pixel_snap_source,
                k_colors=args.k_colors,
                video_model_alias=args.video_model,
                video_duration=args.video_duration,
                action_context=args.action_context,
                size_contract=args.size_contract,
                pose_board_preset=args.pose_board_preset,
                frame_prompt_style=args.frame_prompt_style,
                green_fringe_cleanup=not args.no_green_fringe_cleanup,
                green_fringe_min_green=args.green_fringe_min_green,
                green_fringe_dominance=args.green_fringe_dominance,
                green_fringe_edge_radius=args.green_fringe_edge_radius,
                video_layout_mode=args.layout_mode,
                seed=args.seed,
            )
        )
        print(paths.export_manifest)
    elif args.command == "run-actions":
        actions = tuple(part.strip() for part in args.actions.split(",") if part.strip())
        outputs = run_action_batch(
            ActionBatchOptions(
                actions=actions,
                direction=args.direction,
                reference=args.reference,
                run_dir=args.run_dir,
                mode=args.mode,
                existing_sheet_root=args.existing_sheet_root,
                dry_fal=args.dry_fal,
                pixel_snap=args.pixel_snap,
                pixel_snap_source=args.pixel_snap_source,
                k_colors=args.k_colors,
                chroma=args.chroma,
                pose_board_preset=args.pose_board_preset,
                frame_prompt_style=args.frame_prompt_style,
                green_fringe_cleanup=not args.no_green_fringe_cleanup,
                green_fringe_min_green=args.green_fringe_min_green,
                green_fringe_dominance=args.green_fringe_dominance,
                green_fringe_edge_radius=args.green_fringe_edge_radius,
            )
        )
        print(args.run_dir / "review" / "index.md")
        for output in outputs:
            print(output)
    elif args.command == "anchors":
        directions = _parse_directions_arg(args.directions)
        run_dir = args.run_dir or default_run_dir("anchors", list(directions))
        root = generate_anchors(
            AnchorOptions(
                reference=args.reference,
                run_dir=run_dir,
                directions=directions,
                dry_fal=args.dry_fal,
                model_alias=args.model_alias,
                preprocess=not args.no_preprocess,
                preprocess_padding=args.preprocess_padding,
                pixel_snap_long_edge=args.pixel_snap_long_edge,
                chroma=args.chroma,
                k_colors=args.k_colors,
                game_view=args.game_view,
                anchor_role=args.anchor_role,
                anchor_context=args.anchor_context,
            )
        )
        print(root)
    elif args.command == "bootstrap-anchors":
        directions = () if args.no_directions else _parse_directions_arg(args.directions)
        if args.config is not None:
            result = run_bootstrap_anchors(load_bootstrap_options(args.config, run_dir=args.run_dir))
        else:
            run_dir = args.run_dir or default_run_dir("bootstrap-anchors", [args.character_id, "-".join(directions) or "candidate"])
            result = run_bootstrap_anchors(
                BootstrapAnchorsOptions(
                    run_dir=run_dir,
                    character_id=args.character_id,
                    source_image=args.source_image,
                    source_prompt=args.source_prompt,
                    source_prompt_file=args.source_prompt_file,
                    candidate_image=args.candidate_image,
                    candidate_prompt=args.candidate_prompt,
                    candidate_prompt_file=args.candidate_prompt_file,
                    candidate_prompt_preset=args.candidate_prompt_preset,
                    pixel_snap_anchor=args.pixel_snap_anchor,
                    candidate_facing=args.candidate_facing,
                    anchors_dir=args.anchors_dir,
                    directions=directions,
                    resume=args.resume,
                    dry_fal=args.dry_fal,
                    source_model_alias=args.source_model_alias,
                    candidate_model_alias=args.candidate_model_alias,
                    anchor_model_alias=args.anchor_model_alias,
                    chroma=args.chroma,
                    k_colors=args.k_colors,
                    game_view=args.game_view,
                    anchor_role=args.anchor_role,
                    anchor_context=args.anchor_context,
                    seed=args.seed,
                )
            )
        print(result.bootstrap_json)
        if result.review_index is not None:
            print(result.review_index)
    elif args.command == "anchor-wizard":
        directions = _parse_directions_arg(args.directions)
        run_dir = args.run_dir or default_run_dir("anchor-wizard", [args.character_id, args.stage])
        result = run_anchor_wizard(
            AnchorWizardOptions(
                run_dir=run_dir,
                character_id=args.character_id,
                stage=args.stage,
                source_image=args.source_image,
                source_prompt=args.source_prompt,
                source_prompt_file=args.source_prompt_file,
                candidate_image=args.candidate_image,
                candidate_prompt=args.candidate_prompt,
                candidate_prompt_file=args.candidate_prompt_file,
                candidate_prompt_preset=args.candidate_prompt_preset,
                pixel_snap_anchor=args.pixel_snap_anchor,
                candidate_facing=args.candidate_facing,
                accepted_candidate=args.accepted_candidate,
                anchors_dir=args.anchors_dir,
                directions=directions,
                dry_fal=args.dry_fal,
                source_model_alias=args.source_model_alias,
                candidate_model_alias=args.candidate_model_alias,
                anchor_model_alias=args.anchor_model_alias,
                chroma=args.chroma,
                k_colors=args.k_colors,
                game_view=args.game_view,
                anchor_role=args.anchor_role,
                anchor_context=args.anchor_context,
                seed=args.seed,
            )
        )
        print(result.character_json)
        if result.review_index is not None:
            print(result.review_index)
    elif args.command == "anchor-wizard-gui":
        launch_anchor_wizard_gui(run_dir=args.run_dir)
    elif args.command == "accept-anchor":
        final_anchor = accept_direction_anchor(
            AcceptAnchorOptions(
                run_dir=args.run_dir,
                direction=args.direction,
                source=args.source,
                reason=args.reason,
                character_id=args.character_id,
                candidate_facing=args.candidate_facing,
                chroma=args.chroma,
                k_colors=args.k_colors,
                game_view=args.game_view,
                anchor_role=args.anchor_role,
                anchor_context=args.anchor_context,
            )
        )
        print(final_anchor)
    elif args.command == "preprocess":
        preprocess_user_anchor(
            args.reference,
            args.out,
            metadata_out=args.metadata,
            padding=args.padding,
            snap_long_edge=args.pixel_snap_long_edge,
            chroma=args.chroma,
        )
        print(args.out)
    elif args.command == "snap":
        run_dir = args.run_dir or default_run_dir("snap", [args.reference.stem])
        result = snap_user_anchor(
            SnapOptions(
                source=args.reference,
                run_dir=run_dir,
                target_size=tuple(args.target_size),
                k_colors=args.k_colors,
                chroma=None if args.no_chroma else args.chroma,
            )
        )
        print(result.anchor)
        if result.chroma_anchor is not None:
            print(result.chroma_anchor)
    elif args.command == "clean-frames":
        outputs = clean_frame_batch(
            args.input_dir,
            args.out_dir,
            glob=args.glob,
            options=CleanFrameOptions(
                alpha_threshold=args.alpha_threshold,
                neutral_delta=args.neutral_delta,
                neutral_min_mean=args.neutral_min_mean,
                min_component_area=args.min_component_area,
                edge_radius=args.edge_radius,
                trim=not args.no_trim,
            ),
        )
        print(args.out_dir / "clean-frame-metadata.json")
        print(f"{len(outputs)} frames")
    elif args.command == "sheet-frames":
        paths = build_frame_sheet(
            args.input_dir,
            args.out_dir,
            glob=args.glob,
            options=SheetFrameOptions(
                cell_size=tuple(args.cell_size),
                target_height=args.target_height,
                columns=args.columns,
                fps=args.fps,
                review_upscale=args.review_upscale,
                order=_parse_csv(args.order),
                drop=_parse_csv(args.drop) or (),
            ),
        )
        print(paths["spritesheet"])
        print(paths["preview"])
    elif args.command == "frame-picker":
        inferred = _read_run_metadata(args.run_dir)
        launch_frame_picker(
            run_dir=args.run_dir,
            frames_dir=args.frames_dir,
            video=args.video,
            out_dir=args.out_dir,
            action=args.action or inferred.get("action"),
            direction=args.direction or inferred.get("direction"),
            reference=args.reference or _default_reference(args.run_dir),
            frame_count=args.frames,
        )
    elif args.command == "viewer":
        from .viewer import launch_viewer

        launch_viewer(project_dir=args.project_dir, run_dir=args.run_dir)
    elif args.command == "frame-aligner":
        launch_frame_aligner(
            input_dir=args.input_dir,
            out_dir=args.out_dir,
            glob=args.glob,
            columns=args.columns,
            fps=args.fps,
            zoom=args.zoom,
        )
    elif args.command == "sprite-cleanup":
        launch_sprite_cleanup(
            sheet=args.sheet,
            input_dir=args.input_dir,
            out_dir=args.out_dir,
            glob=args.glob,
            columns=args.columns,
            fps=args.fps,
            zoom=args.zoom,
        )
    elif args.command == "despill":
        chroma_rgb = ImageColor.getrgb(args.chroma)[:3]
        if not is_keyable_fringe_chroma(chroma_rgb):
            raise SystemExit(
                f"--chroma {args.chroma!r} is not a saturated matte color; despill needs a keyable matte such as #00FF00 or #FF00FF"
            )
        band_only = not args.whole_image
        if args.sheet is not None:
            out = args.out or args.sheet
            cleaned, record = despill_chroma(
                Image.open(args.sheet),
                chroma_rgb=chroma_rgb,
                edge_radius=args.edge_radius,
                band_only=band_only,
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            cleaned.save(out)
            print(out)
            print(f"despilled {record['despilledPixels']} edge pixels")
        else:
            out_dir = args.out or args.input_dir
            outputs = despill_chroma_batch(
                args.input_dir,
                out_dir,
                chroma_rgb=chroma_rgb,
                glob=args.glob,
                edge_radius=args.edge_radius,
                band_only=band_only,
            )
            print(out_dir / "despill-metadata.json")
            print(f"{len(outputs)} frames")
    elif args.command == "finalize-runtime":
        reports = finalize_runtime_animation_dirs(
            FinalizeRuntimeOptions(
                animation_dirs=tuple(args.animation_dir),
                anchor_policy=args.anchor_policy,
                target_bottom_y=args.target_bottom_y,
                target_center_x=args.target_center_x,
            )
        )
        for report in reports:
            print(report)
    elif args.command == "size-contract":
        tolerances = {
            key: value
            for key, value in {
                "maxTargetHeightDriftPct": args.max_target_height_drift_pct,
                "maxIntraHeightDriftPct": args.max_intra_height_drift_pct,
                "maxBottomDriftPx": args.max_bottom_drift_px,
                "maxWidthOverflowPct": args.max_width_overflow_pct,
                "maxCenterDriftPx": args.max_center_drift_px,
            }.items()
            if value is not None
        }
        out = args.out or _default_size_contract_out(args.source)
        result = derive_size_contract(
            args.source,
            out=out,
            cell_size=tuple(args.cell_size),
            frame_glob=args.frame_glob,
            name=args.name,
            action=args.action,
            direction=args.direction,
            anchor_policy=args.anchor_policy,
            pivot=args.pivot,
            source_canvas=tuple(args.source_canvas) if args.source_canvas else None,
            tolerances=tolerances,
        )
        print(result)
    elif args.command == "audit-size-contract":
        report = audit_size_contract(
            args.source,
            load_size_contract(args.contract),
            out=args.out,
            cell_size=tuple(args.cell_size) if args.cell_size else None,
            frame_glob=args.frame_glob,
            stage=args.stage,
        )
        if args.out:
            print(args.out)
        print(report["status"])
        if args.strict and not report["passed"]:
            raise SystemExit(1)
    elif args.command == "process-selection":
        report = process_frame_picker_selection(
            PostSelectionOptions(
                picker_dir=args.picker_dir,
                out_dir=args.out_dir or default_post_selection_output_dir(args.picker_dir),
                action=args.action,
                direction=args.direction,
                columns=args.columns,
                fps=args.fps,
                k_colors=args.k_colors,
                chroma=args.chroma,
                chroma_threshold=args.chroma_threshold,
                chroma_min_component_area=args.chroma_min_component_area,
                green_fringe_cleanup=not args.no_green_fringe_cleanup,
                green_fringe_min_green=args.green_fringe_min_green,
                green_fringe_dominance=args.green_fringe_dominance,
                cell_size=tuple(args.cell_size),
                target_height=args.target_height,
                max_width=args.max_width,
                center_x=args.center_x,
                ground_y=args.ground_y,
                layout_mode=args.layout_mode or _default_post_selection_layout_mode(args.action),
                scale_mode=args.scale_mode,
                allow_upscale=not args.no_upscale,
                review_upscale=args.review_upscale,
                pixel_snap=args.pixel_snap,
                pixel_snap_mode=args.pixel_snap_mode,
                pixel_snap_grid_source=args.pixel_snap_grid_source,
                pixel_snap_workers=args.pixel_snap_workers,
                size_contract=args.size_contract,
                size_contract_strict=args.size_contract_strict,
            )
        )
        print(report)
    elif args.command == "inspect":
        print((args.run_dir / "run.json").read_text(encoding="utf-8"))
    elif args.command == "validate":
        manifest = json.loads((args.run_dir / "export" / "manifest.json").read_text(encoding="utf-8"))
        validate_export_sheet(args.run_dir / "export" / manifest["spritesheet"], int(manifest["frames"]))
        print("ok")
    elif args.command == "skill":
        if args.skill_action == "install":
            for installed in install_skill(args.dest, targets=args.target, force=args.force):
                print(installed)

def _read_run_metadata(run_dir: Path | None) -> dict[str, str]:
    if run_dir is None:
        return {}
    path = run_dir / "run.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {key: str(value) for key, value in data.items() if isinstance(value, str)}


def _default_post_selection_layout_mode(action: str | None) -> str:
    return "preserve-canvas"


def _default_size_contract_out(source: Path) -> Path:
    return (source if source.is_dir() else source.parent) / "size-contract.json"


def _default_reference(run_dir: Path | None) -> Path | None:
    if run_dir is None:
        return None
    reference = run_dir / "input" / "source.png"
    return reference if reference.exists() else None


if __name__ == "__main__":
    main()
