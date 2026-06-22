from __future__ import annotations

import pytest

from spriterrific.presets import (
    ACTION_PRESETS,
    ANIMATION_TEMPLATES,
    DIRECTIONS,
    FRAME_COUNT_PROFILES,
    GROK_IMAGINE_MIN_DURATION,
    POSE_BOARD_PRESETS,
    SEEDANCE_MIN_DURATION,
    VIDEO_DURATION,
    WAN_25_DEFAULT_DURATION,
    WAN_27_MIN_DURATION,
    WAN_TURBO_FRAMES_PER_SECOND,
    WAN_TURBO_SHORT_NUM_FRAMES,
    resolve_frame_count,
    resolve_video_model_for_run,
    resolve_pose_board_preset,
    resolve_video_model_preset,
    sheet_rows,
    validate_video_end_reference_support,
    resolve_anchor_game_view,
    resolve_animation_template,
)


def test_all_actions_and_directions_are_registered() -> None:
    assert set(ACTION_PRESETS) == {
        "idle",
        "hurt",
        "jump",
        "crouch",
        "death",
        "attack",
        "walk",
        "run",
        "talk",
        "interact",
        "pick_up",
        "use",
        "examine",
        "give",
        "shrug",
        "walk_forward",
        "walk_backward",
        "block_high",
        "block_low",
        "knockdown",
        "get_up",
        "light_attack",
        "heavy_attack",
    }
    assert set(DIRECTIONS) == {"n", "ne", "e", "se", "s", "sw", "w", "nw"}


def test_rts_oblique_game_view_aliases() -> None:
    assert resolve_anchor_game_view("rts-oblique") == "rts-oblique"
    assert resolve_anchor_game_view("rts") == "rts-oblique"
    assert resolve_anchor_game_view("isometric-rts") == "rts-oblique"
    assert resolve_anchor_game_view("isometric") == "isometric"
    assert resolve_anchor_game_view("top-down") == "top-down"
    assert resolve_anchor_game_view("adventure") == "adventure"
    assert resolve_anchor_game_view("point-and-click") == "adventure"


def test_video_actions_default_to_grok_imagine() -> None:
    assert ACTION_PRESETS["walk"].video_model_alias == "grok-imagine-video-i2v"
    assert ACTION_PRESETS["run"].video_model_alias == "grok-imagine-video-i2v"
    assert ACTION_PRESETS["crouch"].default_mode == "video"
    assert ACTION_PRESETS["crouch"].video_model_alias == "grok-imagine-video-i2v"
    assert ACTION_PRESETS["talk"].video_model_alias == "grok-imagine-video-i2v"


def test_video_presets_use_shortest_supported_provider_settings() -> None:
    assert VIDEO_DURATION == "4"
    assert GROK_IMAGINE_MIN_DURATION == "1"
    assert SEEDANCE_MIN_DURATION == "4"
    assert WAN_27_MIN_DURATION == "2"
    assert WAN_TURBO_SHORT_NUM_FRAMES == 17
    assert WAN_TURBO_FRAMES_PER_SECOND == 16

    wan_turbo = resolve_video_model_preset("wan-2.2-a14b-i2v-turbo")
    assert wan_turbo.duration is None
    assert '"num_frames":17' in str(wan_turbo.extra_json)
    assert '"frames_per_second":16' in str(wan_turbo.extra_json)
    assert resolve_video_model_preset("seedance-2.0-i2v").duration == "4"
    assert resolve_video_model_preset("seedance-2.0-i2v").supports_end_image is True
    assert resolve_video_model_preset("seedance-2.0-i2v").end_image_field == "end_image_url"
    assert resolve_video_model_preset("wan-2.7").duration == "2"
    assert resolve_video_model_preset("grok-imagine-video-i2v").duration == "1"
    assert resolve_video_model_preset("wan-2.7").supports_end_image is True
    assert resolve_video_model_preset("wan-2.7").end_image_field == "end_image_url"
    assert resolve_video_model_preset("grok-imagine-video-i2v").supports_end_image is False


def test_grok_imagine_video_preset_uses_xai_endpoint() -> None:
    preset = resolve_video_model_preset("grok-imagine-video-i2v")

    assert preset.endpoint_id == "xai/grok-imagine-video/image-to-video"
    assert preset.duration == "1"
    assert preset.resolution == "720p"
    assert preset.aspect_ratio == "1:1"


def test_wan_25_video_preset_uses_preview_endpoint() -> None:
    preset = resolve_video_model_preset("wan-2.5")

    assert preset.endpoint_id == "fal-ai/wan-25-preview/image-to-video"
    assert preset.duration == WAN_25_DEFAULT_DURATION
    assert preset.resolution == "1080p"
    assert preset.aspect_ratio is None


def test_sheet_rows_are_five_column_based() -> None:
    assert sheet_rows(5) == 1
    assert sheet_rows(6) == 2
    assert sheet_rows(8) == 2
    assert sheet_rows(10) == 2


def test_frame_count_profiles_and_overrides() -> None:
    assert set(FRAME_COUNT_PROFILES) == {"platformer", "simple", "fighting-game", "point-and-click"}
    assert set(ANIMATION_TEMPLATES) == {"platformer", "simple", "fighting-game", "point-and-click", "adventure"}
    assert resolve_animation_template("platformer").default_actions == ("idle", "attack", "hurt", "death", "walk", "jump", "crouch")
    assert resolve_animation_template("fighting-game").frame_count_profile == "fighting-game"
    assert resolve_animation_template("point-and-click").default_actions == (
        "idle",
        "walk",
        "talk",
        "interact",
        "pick_up",
        "use",
        "examine",
        "give",
        "shrug",
    )
    assert resolve_animation_template("adventure").frame_count_profile == "point-and-click"
    assert resolve_frame_count(ACTION_PRESETS["idle"], None) == 10
    assert resolve_frame_count(ACTION_PRESETS["idle"], None, profile="fighting-game") == 12
    assert resolve_frame_count(ACTION_PRESETS["idle"], None, profile="point-and-click") == 12
    assert resolve_frame_count(ACTION_PRESETS["walk"], None, profile="point-and-click") == 12
    assert resolve_frame_count(ACTION_PRESETS["talk"], None, profile="point-and-click") == 12
    assert resolve_frame_count(ACTION_PRESETS["interact"], None, profile="point-and-click") == 10
    assert resolve_frame_count(ACTION_PRESETS["pick_up"], None, profile="point-and-click") == 12
    assert resolve_frame_count(ACTION_PRESETS["use"], None, profile="point-and-click") == 10
    assert resolve_frame_count(ACTION_PRESETS["examine"], None, profile="point-and-click") == 10
    assert resolve_frame_count(ACTION_PRESETS["give"], None, profile="point-and-click") == 10
    assert resolve_frame_count(ACTION_PRESETS["shrug"], None, profile="point-and-click") == 10
    assert resolve_frame_count(ACTION_PRESETS["attack"], 12) == 12
    assert resolve_frame_count(ACTION_PRESETS["hurt"], 4) == 4
    assert resolve_frame_count(ACTION_PRESETS["walk"], 12) == 12
    assert resolve_frame_count(ACTION_PRESETS["get_up"], 6) == 6
    assert resolve_frame_count(ACTION_PRESETS["block_high"], 4) == 4


def test_action_presets_record_timing_semantics() -> None:
    assert ACTION_PRESETS["idle"].timing == "loop"
    assert ACTION_PRESETS["idle"].loopable is True
    assert ACTION_PRESETS["idle"].selection_policy == "cycle"
    assert ACTION_PRESETS["walk"].timing == "loop"
    assert ACTION_PRESETS["talk"].timing == "loop"
    assert ACTION_PRESETS["talk"].default_mode == "video"
    assert ACTION_PRESETS["talk"].loopable is True
    assert ACTION_PRESETS["talk"].selection_policy == "cycle"
    assert ACTION_PRESETS["interact"].timing == "one_shot"
    assert ACTION_PRESETS["interact"].default_mode == "video"
    assert ACTION_PRESETS["pick_up"].timing == "one_shot"
    assert ACTION_PRESETS["pick_up"].default_mode == "video"
    assert ACTION_PRESETS["use"].timing == "one_shot"
    assert ACTION_PRESETS["use"].default_mode == "video"
    assert ACTION_PRESETS["examine"].timing == "one_shot"
    assert ACTION_PRESETS["examine"].default_mode == "video"
    assert ACTION_PRESETS["give"].timing == "one_shot"
    assert ACTION_PRESETS["give"].default_mode == "video"
    assert ACTION_PRESETS["shrug"].timing == "one_shot"
    assert ACTION_PRESETS["shrug"].default_mode == "video"
    assert ACTION_PRESETS["attack"].timing == "one_shot"
    assert ACTION_PRESETS["attack"].loopable is False
    assert ACTION_PRESETS["jump"].timing == "transition"
    assert ACTION_PRESETS["jump"].selection_policy == "full_duration_include_end"
    assert ACTION_PRESETS["death"].timing == "transition"
    assert ACTION_PRESETS["knockdown"].timing == "transition"
    assert ACTION_PRESETS["get_up"].timing == "transition"
    assert ACTION_PRESETS["block_high"].timing == "hold"
    assert ACTION_PRESETS["block_low"].selection_policy == "hold_pose"


def test_invalid_frame_count_explains_manual_video_override() -> None:
    assert resolve_frame_count(ACTION_PRESETS["idle"], 7) == 8

    with pytest.raises(ValueError, match="Use --allow-frame-count-override"):
        resolve_frame_count(ACTION_PRESETS["idle"], 7, strict=True)

    assert resolve_frame_count(ACTION_PRESETS["idle"], 7, allow_override=True) == 7


def test_end_reference_video_model_capability_helpers() -> None:
    assert resolve_video_model_for_run(ACTION_PRESETS["get_up"], None, end_reference=True) == "wan-2.7"
    assert resolve_video_model_for_run(ACTION_PRESETS["walk"], None, end_reference=True) == "grok-imagine-video-i2v"
    assert resolve_video_model_for_run(ACTION_PRESETS["get_up"], "grok-imagine-video-i2v", end_reference=True) == "grok-imagine-video-i2v"

    validate_video_end_reference_support(resolve_video_model_preset("wan-2.7"), model_alias="wan-2.7")
    validate_video_end_reference_support(resolve_video_model_preset("seedance-2.0-i2v"), model_alias="seedance-2.0-i2v")
    with pytest.raises(ValueError, match="does not support --end-reference"):
        validate_video_end_reference_support(resolve_video_model_preset("grok-imagine-video-i2v"), model_alias="grok-imagine-video-i2v")


def test_pose_board_presets_are_registered() -> None:
    assert set(POSE_BOARD_PRESETS) == {"standard", "hires"}
    standard = resolve_pose_board_preset("standard")
    hires = resolve_pose_board_preset("hires")

    assert (standard.width, standard.height, standard.cell_width, standard.cell_height) == (1536, 1152, 384, 384)
    assert (hires.width, hires.height, hires.cell_width, hires.cell_height) == (2048, 1536, 512, 512)
