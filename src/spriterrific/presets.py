from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DirectionId = str
ActionId = str
Mode = str
RuntimeAnchorPolicy = Literal["auto", "grounded", "preserve-motion", "centered"]
AnchorGameView = Literal["platformer", "adventure", "top-down", "rts-oblique", "isometric", "generic"]
AnchorRole = Literal["character", "enemy", "prop", "turret", "object"]
AnimationTiming = Literal["loop", "one_shot", "transition", "hold"]
SelectionPolicy = Literal["cycle", "action_window", "full_duration_include_end", "hold_pose"]


@dataclass(frozen=True)
class Direction:
    id: DirectionId
    label: str
    prompt_name: str
    screen_facing: str


@dataclass(frozen=True)
class ActionPreset:
    id: ActionId
    default_mode: Mode
    default_frames: int
    allowed_frames: tuple[int, ...]
    fps: int
    image_model_alias: str
    video_model_alias: str
    prompt_template: str
    timing: AnimationTiming = "one_shot"
    loopable: bool = False
    selection_policy: SelectionPolicy = "action_window"


@dataclass(frozen=True)
class FrameCountResolution:
    requested: int
    resolved: int
    allowed_frames: tuple[int, ...]
    source: str
    coerced: bool = False
    warning: str | None = None
    override_allowed: bool = False


@dataclass(frozen=True)
class AnimationTemplate:
    id: str
    label: str
    frame_count_profile: str
    default_actions: tuple[ActionId, ...]
    description: str


@dataclass(frozen=True)
class PoseBoardPreset:
    id: str
    width: int
    height: int
    columns: int
    rows: int

    @property
    def cell_width(self) -> int:
        return self.width // self.columns

    @property
    def cell_height(self) -> int:
        return self.height // self.rows

    @property
    def total_cells(self) -> int:
        return self.columns * self.rows


@dataclass(frozen=True)
class VideoModelPreset:
    id: str
    model_alias: str | None = None
    endpoint_id: str | None = None
    duration: str | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    generate_audio: bool | None = None
    extra_json: str | None = None
    supports_end_image: bool = False
    input_image_field: str = "image_url"
    end_image_field: str | None = None


FRAME_WIDTH = 256
FRAME_HEIGHT = 256
SHEET_COLUMNS = 5
TARGET_CENTER_X = 128
TARGET_BOTTOM_Y = 255
REFERENCE_SIZE = (1024, 1024)
IMAGE_POSE_BOARD_WIDTH = 1536
IMAGE_POSE_BOARD_HEIGHT = 1152
IMAGE_POSE_BOARD_COLUMNS = 4
IMAGE_POSE_BOARD_ROWS = 3
IMAGE_POSE_BOARD_CELL_WIDTH = 384
IMAGE_POSE_BOARD_CELL_HEIGHT = 384
NATIVE_REVIEW_FRAME_WIDTH = 384
NATIVE_REVIEW_FRAME_HEIGHT = 448
VIDEO_PLATE_SIZE = (1024, 1024)
# Spritesheet video clips should use the shortest provider-supported setting
# to limit identity, costume, palette, and scale drift. FAL models do not share
# one duration contract: WAN turbo uses frame count, Seedance starts at 4s, and
# WAN 2.7 starts at 2s.
VIDEO_DURATION = "4"
SEEDANCE_MIN_DURATION = "4"
WAN_27_MIN_DURATION = "2"
WAN_25_DEFAULT_DURATION = "5"
GROK_IMAGINE_MIN_DURATION = "1"
WAN_TURBO_SHORT_NUM_FRAMES = 17
WAN_TURBO_FRAMES_PER_SECOND = 16
VIDEO_RESOLUTION = "720p"
VIDEO_ASPECT_RATIO = "1:1"
VIDEO_GENERATE_AUDIO = False
WAN_TURBO_SHORT_CLIP_JSON = (
    f'"num_frames":{WAN_TURBO_SHORT_NUM_FRAMES},'
    f'"frames_per_second":{WAN_TURBO_FRAMES_PER_SECOND}'
)


VIDEO_MODEL_PRESETS: dict[str, VideoModelPreset] = {
    "seedance-2.0-i2v": VideoModelPreset(
        "seedance-2.0-i2v",
        model_alias="seedance-2.0-i2v",
        duration=SEEDANCE_MIN_DURATION,
        resolution=VIDEO_RESOLUTION,
        aspect_ratio=VIDEO_ASPECT_RATIO,
        generate_audio=VIDEO_GENERATE_AUDIO,
        supports_end_image=True,
        end_image_field="end_image_url",
    ),
    "wan-2.2-a14b-i2v-turbo": VideoModelPreset(
        "wan-2.2-a14b-i2v-turbo",
        endpoint_id="fal-ai/wan/v2.2-a14b/image-to-video/turbo",
        resolution="720p",
        aspect_ratio=VIDEO_ASPECT_RATIO,
        extra_json=(
            "{"
            + WAN_TURBO_SHORT_CLIP_JSON
            + ',"enable_prompt_expansion":false,"enable_safety_checker":true,'
            + '"enable_output_safety_checker":false,"video_quality":"maximum",'
            + '"video_write_mode":"balanced"}'
        ),
    ),
    "wan-2.0": VideoModelPreset(
        "wan-2.0",
        endpoint_id="fal-ai/wan/v2.2-a14b/image-to-video/turbo",
        resolution="720p",
        aspect_ratio=VIDEO_ASPECT_RATIO,
        extra_json=(
            "{"
            + WAN_TURBO_SHORT_CLIP_JSON
            + ',"enable_prompt_expansion":false,"enable_safety_checker":true,'
            + '"enable_output_safety_checker":false,"video_quality":"maximum",'
            + '"video_write_mode":"balanced"}'
        ),
    ),
    "wan-2.5": VideoModelPreset(
        "wan-2.5",
        endpoint_id="fal-ai/wan-25-preview/image-to-video",
        duration=WAN_25_DEFAULT_DURATION,
        resolution="1080p",
        extra_json='{"enable_prompt_expansion":false,"enable_safety_checker":true,"negative_prompt":"low resolution, errors, worst quality, low quality, incomplete, blurry, distorted, camera drift, duplicate body parts, extra limbs, palette drift, recolored costume, changed outfit colors, simplified boots, missing buckles, missing goggles, missing belt pouches, lost costume details, smoothed pixel art, painterly rendering, airbrushed shading, motion blur, defocus blur, smear frames, cinematic lighting, color grading, shadows on background, cast shadow, contact shadow, ground shadow, ambient occlusion blob, base ellipse, reflection, footprint, dust puff, floor line, ground line, platform edge, floor plane, horizon, scenery"}',
    ),
    "wan-2.7": VideoModelPreset(
        "wan-2.7",
        endpoint_id="fal-ai/wan/v2.7/image-to-video",
        duration=WAN_27_MIN_DURATION,
        resolution="1080p",
        aspect_ratio=VIDEO_ASPECT_RATIO,
        extra_json='{"enable_prompt_expansion":false,"enable_safety_checker":true,"enable_output_safety_checker":false,"video_quality":"maximum","video_write_mode":"balanced","negative_prompt":"low resolution, errors, worst quality, low quality, incomplete, blurry, distorted, camera drift, duplicate body parts, extra limbs, palette drift, recolored costume, changed outfit colors, simplified boots, missing buckles, missing goggles, missing belt pouches, lost costume details, smoothed pixel art, painterly rendering, airbrushed shading, motion blur, defocus blur, smear frames, cinematic lighting, color grading, shadows on background, cast shadow, contact shadow, ground shadow, ambient occlusion blob, base ellipse, reflection, footprint, dust puff, floor line, ground line, platform edge, floor plane, horizon, scenery"}',
        supports_end_image=True,
        end_image_field="end_image_url",
    ),
    "grok-imagine-video-i2v": VideoModelPreset(
        "grok-imagine-video-i2v",
        endpoint_id="xai/grok-imagine-video/image-to-video",
        duration=GROK_IMAGINE_MIN_DURATION,
        resolution="720p",
        aspect_ratio=VIDEO_ASPECT_RATIO,
        generate_audio=VIDEO_GENERATE_AUDIO,
    ),
}

ANCHOR_GAME_VIEWS: dict[str, str] = {
    "platformer": "side-scrolling / side-view platformer or action game",
    "adventure": "point-and-click adventure character view",
    "point-and-click": "point-and-click adventure character view",
    "top-down": "experimental loose top-down or three-quarter top-down game",
    "rts-oblique": "Warcraft-like elevated oblique RTS unit camera",
    "isometric": "experimental true isometric tactics / diamond-tile game",
    "generic": "generic 2D game asset pipeline",
}

ANCHOR_ROLES: dict[str, str] = {
    "character": "playable or NPC character",
    "enemy": "enemy or creature",
    "prop": "small interactive or decorative prop",
    "turret": "planted turret or mechanical hazard",
    "object": "non-character game object",
}


DIRECTIONS: dict[DirectionId, Direction] = {
    "n": Direction("n", "North", "north / back-facing", "back-facing, away from the viewer"),
    "ne": Direction("ne", "North-East", "north-east / back-right-facing", "diagonal back-right-facing, away from the viewer"),
    "s": Direction("s", "South", "south / front-facing", "front-facing, toward the viewer"),
    "se": Direction("se", "South-East", "south-east / front-right-facing", "diagonal front-right-facing, toward screen-right"),
    "e": Direction("e", "East", "east / right-facing", "profile facing screen-right"),
    "sw": Direction("sw", "South-West", "south-west / front-left-facing", "diagonal front-left-facing, toward screen-left"),
    "w": Direction("w", "West", "west / left-facing", "profile facing screen-left"),
    "nw": Direction("nw", "North-West", "north-west / back-left-facing", "diagonal back-left-facing, away toward screen-left"),
}


ACTION_PRESETS: dict[ActionId, ActionPreset] = {
    "idle": ActionPreset("idle", "image", 10, (8, 10, 12), 6, "gpt-image-2-edit", "grok-imagine-video-i2v", "idle-sheet", "loop", True, "cycle"),
    "hurt": ActionPreset("hurt", "image", 6, (4, 5, 6, 8), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "hurt-sheet", "one_shot", False, "action_window"),
    "jump": ActionPreset("jump", "image", 6, (6, 8, 10), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "jump-sheet", "transition", False, "full_duration_include_end"),
    "crouch": ActionPreset("crouch", "video", 6, (5, 6, 8), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "crouch-cycle", "hold", True, "hold_pose"),
    "attack": ActionPreset("attack", "image", 8, (6, 8, 10, 12), 10, "gpt-image-2-edit", "grok-imagine-video-i2v", "attack-sheet", "one_shot", False, "action_window"),
    "death": ActionPreset("death", "image", 10, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "death-sheet", "transition", False, "full_duration_include_end"),
    "walk": ActionPreset("walk", "video", 8, (8, 10, 12), 10, "gpt-image-2-edit", "grok-imagine-video-i2v", "walk-cycle", "loop", True, "cycle"),
    "run": ActionPreset("run", "video", 8, (8, 10, 12), 12, "gpt-image-2-edit", "grok-imagine-video-i2v", "run-cycle", "loop", True, "cycle"),
    "talk": ActionPreset("talk", "video", 12, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "talk-cycle", "loop", True, "cycle"),
    "interact": ActionPreset("interact", "video", 10, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "interact", "one_shot", False, "action_window"),
    "pick_up": ActionPreset("pick_up", "video", 12, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "pick-up", "one_shot", False, "action_window"),
    "use": ActionPreset("use", "video", 10, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "use", "one_shot", False, "action_window"),
    "examine": ActionPreset("examine", "video", 10, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "examine", "one_shot", False, "action_window"),
    "give": ActionPreset("give", "video", 10, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "give", "one_shot", False, "action_window"),
    "shrug": ActionPreset("shrug", "video", 10, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "shrug", "one_shot", False, "action_window"),
    "walk_forward": ActionPreset("walk_forward", "video", 12, (8, 10, 12), 10, "gpt-image-2-edit", "grok-imagine-video-i2v", "walk-forward-cycle", "loop", True, "cycle"),
    "walk_backward": ActionPreset("walk_backward", "video", 12, (8, 10, 12), 10, "gpt-image-2-edit", "grok-imagine-video-i2v", "walk-backward-cycle", "loop", True, "cycle"),
    "block_high": ActionPreset("block_high", "video", 8, (4, 6, 8, 10), 10, "gpt-image-2-edit", "grok-imagine-video-i2v", "block-high", "hold", True, "hold_pose"),
    "block_low": ActionPreset("block_low", "video", 8, (4, 6, 8, 10), 10, "gpt-image-2-edit", "grok-imagine-video-i2v", "block-low", "hold", True, "hold_pose"),
    "knockdown": ActionPreset("knockdown", "video", 12, (8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "knockdown", "transition", False, "full_duration_include_end"),
    "get_up": ActionPreset("get_up", "video", 12, (6, 8, 10, 12), 8, "gpt-image-2-edit", "grok-imagine-video-i2v", "get-up", "transition", False, "full_duration_include_end"),
    "light_attack": ActionPreset("light_attack", "video", 8, (6, 8, 10, 12), 12, "gpt-image-2-edit", "grok-imagine-video-i2v", "light-attack", "one_shot", False, "action_window"),
    "heavy_attack": ActionPreset("heavy_attack", "video", 12, (6, 8, 10, 12), 10, "gpt-image-2-edit", "grok-imagine-video-i2v", "heavy-attack", "one_shot", False, "action_window"),
}


ACTION_RUNTIME_ANCHOR_POLICIES: dict[ActionId, RuntimeAnchorPolicy] = {
    "idle": "grounded",
    "hurt": "grounded",
    "jump": "preserve-motion",
    "crouch": "grounded",
    "attack": "grounded",
    "death": "grounded",
    "walk": "grounded",
    "run": "grounded",
    "talk": "grounded",
    "interact": "grounded",
    "pick_up": "grounded",
    "use": "grounded",
    "examine": "grounded",
    "give": "grounded",
    "shrug": "grounded",
    "walk_forward": "grounded",
    "walk_backward": "grounded",
    "block_high": "grounded",
    "block_low": "grounded",
    "knockdown": "grounded",
    "get_up": "grounded",
    "light_attack": "grounded",
    "heavy_attack": "grounded",
}


FRAME_COUNT_PROFILES: dict[str, dict[ActionId, int]] = {
    "platformer": {},
    "simple": {},
    "fighting-game": {
        "idle": 12,
        "walk": 12,
        "run": 12,
        "attack": 12,
        "hurt": 8,
        "jump": 8,
        "death": 12,
        "crouch": 8,
        "walk_forward": 12,
        "walk_backward": 12,
        "block_high": 8,
        "block_low": 8,
        "knockdown": 12,
        "get_up": 12,
        "light_attack": 8,
        "heavy_attack": 12,
    },
    "point-and-click": {
        "idle": 12,
        "walk": 12,
        "talk": 12,
        "interact": 10,
        "pick_up": 12,
        "use": 10,
        "examine": 10,
        "give": 10,
        "shrug": 10,
    },
}


ANIMATION_TEMPLATES: dict[str, AnimationTemplate] = {
    "platformer": AnimationTemplate(
        id="platformer",
        label="Platformer",
        frame_count_profile="platformer",
        default_actions=("idle", "attack", "hurt", "death", "walk", "jump", "crouch"),
        description="Side-view platformer defaults for loops, jumps, attacks, reactions, and death.",
    ),
    "simple": AnimationTemplate(
        id="simple",
        label="Simple",
        frame_count_profile="simple",
        default_actions=("idle", "attack", "hurt", "death", "walk", "jump"),
        description="Small general-purpose action set using Spriterrific's baseline frame defaults.",
    ),
    "fighting-game": AnimationTemplate(
        id="fighting-game",
        label="Fighting game",
        frame_count_profile="fighting-game",
        default_actions=(
            "idle",
            "walk_forward",
            "walk_backward",
            "crouch",
            "jump",
            "light_attack",
            "heavy_attack",
            "block_high",
            "block_low",
            "hurt",
            "knockdown",
            "get_up",
        ),
        description="Side-view fighting-game defaults for attacks, blocks, hit reactions, knockdown, and get-up transitions.",
    ),
    "point-and-click": AnimationTemplate(
        id="point-and-click",
        label="Point and click",
        frame_count_profile="point-and-click",
        default_actions=("idle", "walk", "talk", "interact", "pick_up", "use", "examine", "give", "shrug"),
        description="Point-and-click adventure defaults for walking, dialogue gestures, object interaction, examination, handoff, and reactions.",
    ),
    "adventure": AnimationTemplate(
        id="adventure",
        label="Adventure",
        frame_count_profile="point-and-click",
        default_actions=("idle", "walk", "talk", "interact", "pick_up", "use", "examine", "give", "shrug"),
        description="Alias-friendly point-and-click adventure defaults for characterful room-scale interactions.",
    ),
}


POSE_BOARD_PRESETS: dict[str, PoseBoardPreset] = {
    "standard": PoseBoardPreset("standard", 1536, 1152, 4, 3),
    "hires": PoseBoardPreset("hires", 2048, 1536, 4, 3),
}


def get_direction(direction_id: str) -> Direction:
    try:
        return DIRECTIONS[direction_id]
    except KeyError as exc:
        known = ", ".join(sorted(DIRECTIONS))
        raise ValueError(f"Unknown direction {direction_id!r}; expected one of: {known}") from exc


def get_action(action_id: str) -> ActionPreset:
    try:
        return ACTION_PRESETS[action_id]
    except KeyError as exc:
        known = ", ".join(sorted(ACTION_PRESETS))
        raise ValueError(f"Unknown action {action_id!r}; expected one of: {known}") from exc


def resolve_mode(action: ActionPreset, mode: str | None) -> Mode:
    resolved = mode or action.default_mode
    if resolved not in {"image", "video"}:
        raise ValueError("mode must be image or video")
    return resolved


def resolve_frame_count(
    action: ActionPreset,
    frame_count: int | None,
    *,
    profile: str | None = None,
    allow_override: bool = False,
    strict: bool = False,
    override_context: str = "",
) -> int:
    return resolve_frame_count_resolution(
        action,
        frame_count,
        profile=profile,
        allow_override=allow_override,
        strict=strict,
        override_context=override_context,
    ).resolved


def resolve_frame_count_resolution(
    action: ActionPreset,
    frame_count: int | None,
    *,
    profile: str | None = None,
    allow_override: bool = False,
    strict: bool = False,
    override_context: str = "",
) -> FrameCountResolution:
    profile_id = profile or "platformer"
    try:
        profile_defaults = FRAME_COUNT_PROFILES[profile_id]
    except KeyError as exc:
        known = ", ".join(sorted(FRAME_COUNT_PROFILES))
        raise ValueError(f"Unknown frame count profile {profile_id!r}; expected one of: {known}") from exc

    source = "requested" if frame_count is not None else "profile" if action.id in profile_defaults else "default"
    requested = frame_count or profile_defaults.get(action.id) or action.default_frames
    if requested <= 0:
        raise ValueError("frame count must be positive")
    if allow_override:
        if requested > 60:
            raise ValueError("frame count override must be 60 or fewer frames")
        return FrameCountResolution(
            requested=requested,
            resolved=requested,
            allowed_frames=action.allowed_frames,
            source=source,
            override_allowed=True,
        )
    if requested not in action.allowed_frames:
        allowed = ", ".join(str(value) for value in action.allowed_frames)
        if strict:
            suffix = (
                f" Use --allow-frame-count-override for manual existing-video recovery{override_context}."
                if override_context
                else " Use --allow-frame-count-override with --existing-video and --selected-order or --selected-range for manual recovery."
            )
            raise ValueError(f"{action.id} supports frame counts: {allowed}.{suffix}")
        resolved = min(action.allowed_frames, key=lambda value: (abs(value - requested), -value))
        warning = (
            f"{action.id} requested {requested} frames, but recommended frame counts are: "
            f"{allowed}. Using {resolved}."
        )
        return FrameCountResolution(
            requested=requested,
            resolved=resolved,
            allowed_frames=action.allowed_frames,
            source=source,
            coerced=True,
            warning=warning,
        )
    return FrameCountResolution(
        requested=requested,
        resolved=requested,
        allowed_frames=action.allowed_frames,
        source=source,
    )


def resolve_animation_template(template_id: str | None) -> AnimationTemplate:
    resolved = template_id or "platformer"
    try:
        return ANIMATION_TEMPLATES[resolved]
    except KeyError as exc:
        known = ", ".join(sorted(ANIMATION_TEMPLATES))
        raise ValueError(f"Unknown animation template {resolved!r}; expected one of: {known}") from exc


def resolve_runtime_anchor_policy(action_id: str, policy: RuntimeAnchorPolicy = "auto") -> RuntimeAnchorPolicy:
    if policy != "auto":
        return policy
    return ACTION_RUNTIME_ANCHOR_POLICIES.get(action_id, "grounded")


def resolve_pose_board_preset(preset_id: str | None) -> PoseBoardPreset:
    resolved = preset_id or "standard"
    try:
        preset = POSE_BOARD_PRESETS[resolved]
    except KeyError as exc:
        known = ", ".join(sorted(POSE_BOARD_PRESETS))
        raise ValueError(f"Unknown pose board preset {resolved!r}; expected one of: {known}") from exc
    if preset.width % preset.columns or preset.height % preset.rows:
        raise ValueError(f"pose board preset {preset.id!r} does not divide evenly into its grid")
    return preset


def resolve_video_model_preset(model_id: str) -> VideoModelPreset:
    try:
        return VIDEO_MODEL_PRESETS[model_id]
    except KeyError:
        return VideoModelPreset(model_id, model_alias=model_id, duration=VIDEO_DURATION, resolution=VIDEO_RESOLUTION, aspect_ratio=VIDEO_ASPECT_RATIO, generate_audio=VIDEO_GENERATE_AUDIO)


def resolve_video_model_for_run(action: ActionPreset, requested_model: str | None, *, end_reference: bool = False) -> str:
    if end_reference and requested_model is None and action.timing == "transition":
        return "wan-2.7"
    return requested_model or action.video_model_alias


def validate_video_end_reference_support(preset: VideoModelPreset, *, model_alias: str) -> None:
    if not preset.supports_end_image or not preset.end_image_field:
        raise ValueError(
            f"{model_alias} does not support --end-reference. "
            "Use --video-model seedance-2.0-i2v, --video-model wan-2.7, or remove --end-reference."
        )


def resolve_anchor_game_view(game_view: str | None) -> str:
    resolved = (game_view or "platformer").strip().lower()
    if resolved == "side-scroller":
        resolved = "platformer"
    if resolved in {"point-and-click", "point_and_click", "pnc", "adventure-game"}:
        resolved = "adventure"
    if resolved in {"rts", "rts-oblique", "rts_oblique", "warcraft", "warcraft-rts", "oblique-rts", "isometric-rts", "iso-rts", "isometric_rts"}:
        resolved = "rts-oblique"
    if resolved not in ANCHOR_GAME_VIEWS:
        known = ", ".join(sorted(ANCHOR_GAME_VIEWS))
        raise ValueError(f"unknown anchor game view {game_view!r}; expected one of: {known}")
    return resolved


def resolve_anchor_role(anchor_role: str | None) -> str:
    resolved = (anchor_role or "character").strip().lower()
    if resolved not in ANCHOR_ROLES:
        known = ", ".join(sorted(ANCHOR_ROLES))
        raise ValueError(f"unknown anchor role {anchor_role!r}; expected one of: {known}")
    return resolved


def sheet_rows(frame_count: int) -> int:
    if frame_count <= 0:
        raise ValueError("frame count must be positive")
    return (frame_count + SHEET_COLUMNS - 1) // SHEET_COLUMNS
