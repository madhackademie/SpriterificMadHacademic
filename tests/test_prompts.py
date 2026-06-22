from __future__ import annotations

from spriterrific.presets import get_action, get_direction
from spriterrific.prompts import render_anchor_prompt, render_prompt


def test_anchor_prompt_uses_explicit_platformer_enemy_context() -> None:
    prompt = render_anchor_prompt(
        get_direction("w"),
        game_view="platformer",
        anchor_role="enemy",
        anchor_context="side-scrolling platformer enemy with one clear claw arm",
    )

    assert "side-scrolling / side-view platformer" in prompt
    assert "enemy or creature" in prompt
    assert "side-scrolling platformer enemy with one clear claw arm" in prompt
    assert "true side-view profile" in prompt
    assert "facing screen-left" in prompt
    assert "Do not leave it front-facing or three-quarter-facing" in prompt
    assert "top-down 2D action game" not in prompt
    assert "handheld weapon" not in prompt


def test_rts_oblique_anchor_prompt_locks_elevated_camera() -> None:
    prompt = render_anchor_prompt(
        get_direction("se"),
        game_view="rts-oblique",
        anchor_role="enemy",
        anchor_context="Warcraft-style top-down RTS orc warrior unit",
    )

    assert "elevated oblique RTS camera" in prompt
    assert "top planes of the head, shoulders, armor, weapon, and boots" in prompt
    assert "foreshortened, compact, squat body proportions" in prompt
    assert "visible unit should occupy roughly 35-45% of the 1024 canvas height" in prompt
    assert "not a tall full-height character turnaround" in prompt
    assert "paper-doll front view" in prompt
    assert "south-east / front-right-facing as a compact unit rotated on an oblique RTS ground plane" in prompt
    assert "Warcraft-style top-down RTS orc warrior unit" in prompt
    assert "pure side-view platformer profile" in prompt


def test_rts_oblique_east_prompt_avoids_side_profile_language() -> None:
    prompt = render_anchor_prompt(
        get_direction("e"),
        game_view="rts-oblique",
        anchor_role="enemy",
        anchor_context="Warcraft-like orc unit",
    )

    assert "east / screen-right-facing from the fixed elevated RTS camera, not a pure side profile" in prompt
    assert "One isolated small RTS unit sprite" in prompt
    assert "One isolated full-body sprite" not in prompt


def test_adventure_sw_anchor_prompt_uses_three_quarter_left_view() -> None:
    prompt = render_anchor_prompt(
        get_direction("sw"),
        game_view="adventure",
        anchor_role="character",
        anchor_context="classic point-and-click room-scale protagonist",
    )

    assert "point-and-click adventure character view" in prompt
    assert "front-left three-quarter adventure view" in prompt
    assert "classic point-and-click adventure character camera" in prompt
    assert "angled toward screen-left" in prompt
    assert "visible character should occupy roughly 65-80% of the 1024 canvas height" in prompt
    assert "not a side-view platformer profile" in prompt
    assert "classic point-and-click room-scale protagonist" in prompt
    assert "true side-view profile" not in prompt


def test_walk_video_prompt_requires_alternating_stride_and_chroma() -> None:
    prompt = render_prompt(get_action("walk"), get_direction("s"), 10, "video")

    assert "flat exact chroma green #00FF00" in prompt
    assert "The sprite source must not include baked shadows" in prompt
    assert "floor line" in prompt
    assert "ground line" in prompt
    assert "Treat foot-down timing as character pose only" in prompt
    assert "left foot forward while right foot back" in prompt
    assert "right foot forward while left foot back" in prompt
    assert "Arms counter-swing opposite the legs" in prompt
    assert "Do not move both arms forward together" in prompt
    assert "Do not move both feet together" in prompt
    assert "synchronized arm-and-foot sway" in prompt


def test_video_prompt_can_use_magenta_chroma_for_green_characters() -> None:
    prompt = render_prompt(get_action("walk"), get_direction("w"), 10, "video", chroma="#FF00FF")

    assert "flat exact chroma magenta #FF00FF" in prompt
    assert "flat exact chroma green #00FF00" not in prompt
    assert "matte-color spill" in prompt


def test_run_video_prompt_requires_counter_swing() -> None:
    prompt = render_prompt(get_action("run"), get_direction("e"), 10, "video")

    assert "flat exact chroma green #00FF00" in prompt
    assert "pure side-profile silhouette facing screen-right" in prompt
    assert "do not reveal both eyes" in prompt
    assert "not toward the viewer" in prompt
    assert "running stride poses" in prompt
    assert "Arms counter-swing opposite the legs" in prompt
    assert "Use the input image as a strict first-frame identity, palette, scale, and sprite-style reference" in prompt
    assert "Preserve the exact costume colors" in prompt
    assert "head-to-boot detail still readable" in prompt
    assert "No palette drift" in prompt
    assert "No boot simplification" in prompt
    assert "Preserve any existing held or worn equipment" in prompt
    assert "must not float, detach, duplicate" in prompt
    assert "No new props" in prompt
    assert "synchronized arm-and-foot sway" in prompt


def test_idle_video_prompt_stays_idle() -> None:
    prompt = render_prompt(get_action("idle"), get_direction("w"), 10, "video")

    assert "in-place idle cycle" in prompt
    assert "rooted in one spot" in prompt
    assert "feet fused to the ground" in prompt
    assert "does not travel across the frame" in prompt
    assert "subtle breathing" in prompt
    assert "no stepping" in prompt
    assert "in-place walk cycle" not in prompt
    assert "alternating left/right stride" not in prompt


def test_non_locomotion_video_prompt_does_not_force_walk_or_run() -> None:
    prompt = render_prompt(get_action("jump"), get_direction("n"), 6, "video")

    assert "in-place jump animation" in prompt
    assert "requested action" in prompt
    assert "visible floor, ground line, contact mark" in prompt
    assert "in-place walk cycle" not in prompt
    assert "running stride poses" not in prompt
    assert "strong contact" not in prompt


def test_crouch_video_prompt_stays_planted() -> None:
    prompt = render_prompt(get_action("crouch"), get_direction("w"), 6, "video")

    assert "in-place crouch animation" in prompt
    assert "bend knees and lower the body" in prompt
    assert "Keep both feet planted in place" in prompt
    assert "Do not step, walk, run, jump, attack" in prompt
    assert "in-place walk cycle" not in prompt
    assert "running stride poses" not in prompt


def test_fighting_game_prompts_have_action_specific_cadence() -> None:
    prompt = render_prompt(get_action("heavy_attack"), get_direction("w"), 12, "video")

    assert "in-place heavy_attack animation" in prompt
    assert "heavier attack animation" in prompt
    assert "No attack animation" not in prompt


def test_image_frame_labels_support_extended_counts() -> None:
    prompt = render_prompt(get_action("idle"), get_direction("w"), 12, "image")

    assert "create a 12-frame idle sequence" in prompt
    assert "Frame 12:" in prompt


def test_point_and_click_action_prompts_have_specific_contract_labels() -> None:
    talk_prompt = render_prompt(get_action("talk"), get_direction("sw"), 12, "image")
    interact_prompt = render_prompt(get_action("interact"), get_direction("sw"), 10, "image")

    assert "create a 12-frame talk sequence" in talk_prompt
    assert "settled speaking idle" in talk_prompt
    assert "gesture peak" in talk_prompt
    assert "create a 10-frame interact sequence" in interact_prompt
    assert "operate or take peak" in interact_prompt
    assert "return to idle" in interact_prompt


def test_loose_attack_prompt_keeps_layout_strict_but_omits_frame_by_frame_labels() -> None:
    prompt = render_prompt(
        get_action("attack"),
        get_direction("w"),
        8,
        "image",
        frame_prompt_style="loose",
    )

    assert "Motion guidance:" in prompt
    assert "Let the model choose the exact in-between poses" in prompt
    assert "Keep the same attacking side" in prompt
    assert "Exact implied grid: 4 columns x 3 rows" in prompt
    assert "Use an opaque exact flat chroma green #00FF00 background" in prompt
    assert "- Frame 1:" not in prompt
    assert "- Frame 8:" not in prompt


def test_image_prompt_rejects_visible_guides_and_non_chroma_backgrounds() -> None:
    prompt = render_prompt(
        get_action("hurt"),
        get_direction("w"),
        6,
        "image",
        frame_prompt_style="loose",
    )

    assert "black-and-white alternating-pixel pose-board geometry guide" in prompt
    assert "not a background, style, contact-sheet, border, or grid-line reference" in prompt
    assert "only separate character sprites on one uninterrupted solid chroma background" in prompt
    assert "Do not render a contact sheet" in prompt
    assert "Every non-character pixel must be exact solid #00FF00" in prompt
    assert "No white, gray, black, neutral, paper, studio, transparent, or checkerboard background" in prompt


def test_image_prompt_can_use_magenta_chroma() -> None:
    prompt = render_prompt(
        get_action("hurt"),
        get_direction("w"),
        6,
        "image",
        frame_prompt_style="loose",
        chroma="#FF00FF",
    )

    assert "Use an opaque exact flat chroma magenta #FF00FF background" in prompt
    assert "Every non-character pixel must be exact solid #FF00FF" in prompt
    assert "exact solid #00FF00" not in prompt
