from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from spriterrific.anchor_wizard import (
    AcceptAnchorOptions,
    AnchorWizardOptions,
    _enforce_lobit_snap_contract,
    _newest_path,
    _source_prompt,
    accept_direction_anchor,
    resolve_candidate_prompt,
    run_anchor_wizard,
)
from spriterrific.cli import main as cli_main
from spriterrific.pixel_snap import PIXEL_SNAPPER_SCRIPT, SnapResult


def _write_fake_source(path: Path) -> None:
    image = Image.new("RGBA", (512, 512), (235, 235, 235, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((205, 120, 310, 430), fill=(130, 78, 44, 255))
    draw.rectangle((220, 70, 292, 150), fill=(232, 190, 142, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_fake_pixel_character(path: Path, *, color: tuple[int, int, int, int]) -> None:
    base = Image.new("RGBA", (32, 32), (0, 255, 0, 255))
    draw = ImageDraw.Draw(base)
    draw.rectangle((12, 8, 20, 24), fill=color)
    draw.rectangle((14, 4, 18, 10), fill=(235, 190, 145, 255))
    draw.rectangle((11, 24, 14, 29), fill=(65, 45, 38, 255))
    draw.rectangle((18, 24, 21, 29), fill=(65, 45, 38, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    base.resize((512, 512), Image.Resampling.NEAREST).save(path)


def _write_fake_pixel_character_transparent(path: Path, *, color: tuple[int, int, int, int]) -> None:
    base = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    draw.rectangle((12, 8, 20, 24), fill=color)
    draw.rectangle((14, 4, 18, 10), fill=(235, 190, 145, 255))
    draw.rectangle((11, 24, 14, 29), fill=(65, 45, 38, 255))
    draw.rectangle((18, 24, 21, 29), fill=(65, 45, 38, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    base.resize((512, 512), Image.Resampling.NEAREST).save(path)


def _write_fake_checkerboard_candidate(path: Path) -> None:
    image = Image.new("RGBA", (1024, 1024), (232, 232, 232, 255))
    draw = ImageDraw.Draw(image)
    tile = 32
    for y in range(0, image.height, tile):
        for x in range(0, image.width, tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(248, 248, 248, 255))
    draw.rectangle((438, 260, 586, 790), fill=(46, 96, 180, 255))
    draw.rectangle((470, 185, 554, 290), fill=(235, 190, 145, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_fake_1024_chroma_anchor(path: Path, *, color: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (1024, 1024), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((390, 210, 660, 820), fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_fake_1024_transparent_anchor_with_dark_detail(path: Path) -> None:
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((390, 210, 660, 820), fill=(180, 70, 60, 255))
    draw.rectangle((430, 260, 470, 780), fill=(0, 0, 0, 255))
    draw.rectangle((550, 260, 590, 780), fill=(4, 4, 4, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_source_prompt_wraps_user_concept_in_sprite_constraints() -> None:
    prompt = _source_prompt("a goofy looking knight with a broken sword and messy hair")

    assert "a goofy looking knight with a broken sword and messy hair" in prompt
    assert "VibeGameDev" not in prompt
    assert "Spriterrific" not in prompt
    assert "limited 8 to 12 color feeling" in prompt
    assert "big pixel clusters" in prompt
    assert "not polished high-detail JRPG art" in prompt
    assert "no realistic photo" in prompt
    assert "one full-body character" in prompt
    assert "#D9D9D9" in prompt


def test_high_fidelity_source_prompt_avoids_low_bit_constraints() -> None:
    prompt = _source_prompt("a heroic explorer with a brass lantern", high_fidelity=True)

    assert "a heroic explorer with a brass lantern" in prompt
    assert "high-fidelity 2D pixel-art-inspired game sprite" in prompt
    assert "mixed pixels are acceptable" in prompt
    assert "limited 8 to 12 color feeling" not in prompt
    assert "big pixel clusters" not in prompt


def test_lobit_candidate_prompt_is_strict_low_bit_style() -> None:
    prompt = resolve_candidate_prompt(None, None, candidate_facing="front")

    assert "not polished high-detail JRPG art" in prompt
    assert "VibeGameDev" not in prompt
    assert "Spriterrific" not in prompt
    assert "identity reference only" in prompt
    assert "opinionated low-bit pixel-sprite distillation step" in prompt
    assert "limited 8 to 12 color feeling" in prompt
    assert "big pixel clusters" in prompt
    assert "no tiny accessories" in prompt
    assert "buttons" in prompt
    assert "buckles" in prompt
    assert "roughly 100 to 130 pixel tall native sprite" in prompt
    assert "polished 16-bit / early 32-bit JRPG" not in prompt


def test_candidate_prompt_can_use_magenta_chroma() -> None:
    prompt = resolve_candidate_prompt(None, None, candidate_facing="front", chroma="#FF00FF")

    assert "opaque exact flat chroma magenta #FF00FF background" in prompt
    assert "chroma green #00FF00" not in prompt


def test_high_fidelity_candidate_prompt_avoids_lobit_snap_contract_language() -> None:
    prompt = resolve_candidate_prompt(None, None, preset="high-fidelity-v1", candidate_facing="front")

    assert "mixels" in prompt
    assert "richer pixel-art texture" in prompt
    assert "non-pixel-snap-bound game assets" in prompt
    assert "limited 8 to 12 color feeling" not in prompt
    assert "roughly 100 to 130 pixel tall native sprite" not in prompt
    assert "lobit-v1" not in prompt


def test_preserve_reference_candidate_prompt_keeps_source_as_visual_authority() -> None:
    prompt = resolve_candidate_prompt(None, None, preset="preserve-reference-v1", candidate_facing="front")

    assert "strict visual authority" in prompt
    assert "chibi proportions" in prompt
    assert "head/body ratio" in prompt
    assert "Do not redesign" in prompt
    assert "de-chibi" in prompt
    assert "Pixel snapping and palette cleanup are allowed later" in prompt
    assert "limited 8 to 12 color feeling" not in prompt
    assert "opinionated low-bit pixel-sprite distillation" not in prompt


def test_rts_oblique_candidate_prompt_uses_elevated_camera() -> None:
    prompt = resolve_candidate_prompt(None, None, candidate_facing="south", game_view="rts-oblique")

    assert "small compact south-facing elevated oblique RTS unit anchor" in prompt
    assert "visible top planes of head, shoulders, armor, weapon, hands, and boots" in prompt
    assert "foreshortened unit proportions" in prompt
    assert "visible unit occupies roughly 35-45% of the canvas height" in prompt
    assert "tall full-height character turnaround" in prompt
    assert "not a straight-on front portrait" in prompt
    assert "not a pure side-view platformer" in prompt


def test_rts_oblique_source_prompt_avoids_full_height_turnaround() -> None:
    prompt = _source_prompt("orc warrior for a Warcraft-style top-down RTS, 1024x1024 full-body sprite anchor", game_view="rts-oblique", high_fidelity=True)

    assert "Create one small compact RTS unit sprite on a 1024x1024 square canvas" in prompt
    assert "If the user prompt says full-body, interpret that as whole unit visible" in prompt
    assert "not as a tall character-turnaround or portrait" in prompt
    assert "visible unit occupies roughly 35-45% of the canvas height" in prompt
    assert "Create one full-body character" not in prompt


def test_lobit_snap_contract_rejects_tall_dense_native_snap(tmp_path: Path) -> None:
    snap = SnapResult(
        run_dir=tmp_path,
        source=tmp_path / "source.png",
        snapped=tmp_path / "snapped.png",
        anchor=tmp_path / "anchor.png",
        chroma_anchor=None,
        snapped_size=(211, 208),
        target_size=(1024, 1024),
    )

    with pytest.raises(ValueError, match="too tall/detailed"):
        _enforce_lobit_snap_contract(snap)


def test_newest_path_prefers_latest_retry_output(tmp_path: Path) -> None:
    old = tmp_path / "output-old.png"
    new = tmp_path / "output-new.png"
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))

    assert _newest_path([new, old]) == new


def test_accept_direction_anchor_promotes_reviewed_anchor_to_canonical_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "bootstrap"
    source = tmp_path / "accepted-w.png"
    _write_fake_1024_chroma_anchor(source, color=(80, 96, 180, 255))
    (run_dir / "anchors" / "w").mkdir(parents=True)
    (run_dir / "bootstrap.json").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "bootstrap.json").write_text(
        json.dumps({"version": 1, "anchors": {"w": "old.png"}, "canonicalOutputs": {"directionAnchors": {"w": {"snapped1024Chroma": "old.png"}}}}),
        encoding="utf-8",
    )
    (run_dir / "character.json").write_text(json.dumps({"version": 1, "character": "scavenger-bot"}), encoding="utf-8")

    final = accept_direction_anchor(
        AcceptAnchorOptions(
            run_dir=run_dir,
            direction="w",
            source=source,
            reason="manual platformer side-profile correction",
            game_view="platformer",
            anchor_role="enemy",
            anchor_context="true W profile side-scrolling enemy",
        )
    )

    assert final == run_dir / "anchors" / "w" / "anchor-snapped-1024-chroma.png"
    assert final.is_file()
    assert (run_dir / "accepted" / "w" / "acceptance.json").is_file()
    character = json.loads((run_dir / "character.json").read_text(encoding="utf-8"))
    assert character["anchors"]["w"].endswith("anchors/w/anchor-snapped-1024-chroma.png")
    assert character["acceptedAnchors"]["w"]["reason"] == "manual platformer side-profile correction"
    bootstrap = json.loads((run_dir / "bootstrap.json").read_text(encoding="utf-8"))
    assert bootstrap["anchors"]["w"].endswith("anchors/w/anchor-snapped-1024-chroma.png")
    assert bootstrap["acceptedAnchors"]["w"]["acceptedCopy"].endswith("accepted/w/anchor-snapped-1024-chroma.png")


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_direction_stage_publishes_generated_anchor_during_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    accepted = tmp_path / "accepted.png"
    _write_fake_pixel_character(accepted, color=(46, 96, 180, 255))
    generated_root = tmp_path / "generated-root"
    generated_anchor = generated_root / "anchors" / "character-n-chroma.png"
    _write_fake_pixel_character(generated_anchor, color=(80, 96, 180, 255))
    run_dir = tmp_path / "runs" / "wizard-incremental"

    def fake_generate(options: object) -> Path:
        callback = getattr(options, "on_anchor_generated")
        callback("n", generated_anchor)
        assert (run_dir / "anchors" / "n" / "anchor-snapped-1024-chroma.png").is_file()
        return generated_root

    monkeypatch.setattr("spriterrific.anchor_wizard.generate_anchors", fake_generate)

    result = run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="courier",
            stage="directions",
            accepted_candidate=accepted,
            directions=("n",),
            k_colors=64,
        )
    )

    assert result.anchors is not None
    assert result.anchors["n"] == run_dir / "anchors" / "n" / "anchor-snapped-1024-chroma.png"
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "direction_anchor_published" in events


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_anchor_wizard_candidate_stage_writes_candidate_review(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    _write_fake_source(source)
    _write_fake_pixel_character(candidate, color=(46, 96, 180, 255))

    run_dir = tmp_path / "runs" / "wizard"
    result = run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="courier",
            stage="candidate",
            source_image=source,
            candidate_image=candidate,
            k_colors=64,
        )
    )

    assert result.candidate_anchor == run_dir / "candidate" / "front" / "snapped-1024-chroma.png"
    assert result.candidate_anchor.is_file()
    assert (run_dir / "candidate" / "front" / "snapped-native.png").is_file()
    assert (run_dir / "candidate" / "front" / "review" / "index.md").is_file()
    assert (run_dir / "review" / "candidate-overview.png").is_file()
    data = json.loads((run_dir / "character.json").read_text(encoding="utf-8"))
    assert data["character"] == "courier"
    assert data["candidateFacing"] == "front"
    assert data["candidateAnchor"].endswith("candidate/front/snapped-1024-chroma.png")
    assert data["pixelSnapAnchor"] is True


def test_anchor_wizard_candidate_stage_can_skip_anchor_pixel_snap(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    _write_fake_source(source)
    _write_fake_1024_chroma_anchor(candidate, color=(46, 96, 180, 255))

    run_dir = tmp_path / "runs" / "wizard-nosnap-candidate"
    result = run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="mixel-hero",
            stage="candidate",
            source_image=source,
            candidate_image=candidate,
            candidate_prompt_preset="high-fidelity-v1",
            pixel_snap_anchor=False,
        )
    )

    candidate_dir = run_dir / "candidate" / "front"
    assert result.candidate_anchor == candidate_dir / "snapped-1024-chroma.png"
    assert (candidate_dir / "anchor-1024-chroma.png").is_file()
    assert (candidate_dir / "snapped-1024-chroma.png").is_file()
    assert not (candidate_dir / "snapped-native.png").exists()
    assert not (candidate_dir / "snap").exists()
    metadata = json.loads((candidate_dir / "candidate.json").read_text(encoding="utf-8"))
    assert metadata["pixelSnapped"] is False
    assert metadata["anchorStyle"] == "high-fidelity-v1"
    assert metadata["snapRun"] is None
    assert metadata["snappedSize"] is None
    character = json.loads((run_dir / "character.json").read_text(encoding="utf-8"))
    assert character["pixelSnapAnchor"] is False
    assert character["candidatePromptPreset"] == "high-fidelity-v1"


def test_anchor_wizard_preserve_reference_source_image_skips_candidate_generation(tmp_path: Path) -> None:
    source = tmp_path / "transparent-source.png"
    _write_fake_pixel_character_transparent(source, color=(46, 96, 180, 255))

    run_dir = tmp_path / "runs" / "wizard-preserve-reference"
    result = run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="source-faithful-hero",
            stage="candidate",
            source_image=source,
            candidate_prompt_preset="preserve-reference-v1",
            pixel_snap_anchor=False,
        )
    )

    candidate_dir = run_dir / "candidate" / "front"
    assert result.candidate_anchor == candidate_dir / "snapped-1024-chroma.png"
    assert not (run_dir / "candidate-fal").exists()
    assert (run_dir / "input" / "source-original.png").is_file()
    assert (run_dir / "input" / "source-model-input.png").is_file()
    prompt = (candidate_dir / "candidate-prompt.txt").read_text(encoding="utf-8")
    assert "strict visual authority" in prompt
    assert "chroma background is a removal matte" in prompt
    metadata = json.loads((candidate_dir / "candidate.json").read_text(encoding="utf-8"))
    assert metadata["candidateGenerationMode"] == "source-image-preserve-reference-shortcut"
    assert metadata["anchorStyle"] == "preserve-reference-v1"
    assert metadata["pixelSnapped"] is False
    assert metadata["candidateBackgroundCheck"]["passed"] is True
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "candidate_source_preserved" in events


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_anchor_wizard_direction_stage_snaps_existing_generated_anchors(tmp_path: Path) -> None:
    accepted = tmp_path / "accepted.png"
    _write_fake_pixel_character(accepted, color=(46, 96, 180, 255))
    anchors_dir = tmp_path / "generated-anchors"
    for index, direction in enumerate(("n", "s", "e", "w")):
        _write_fake_pixel_character(anchors_dir / f"character-{direction}-chroma.png", color=(40 + index * 20, 90, 180, 255))
        _write_fake_pixel_character_transparent(anchors_dir / f"character-{direction}.png", color=(40 + index * 20, 90, 180, 255))

    run_dir = tmp_path / "runs" / "wizard-directions"
    result = run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="courier",
            stage="directions",
            accepted_candidate=accepted,
            anchors_dir=anchors_dir,
            k_colors=64,
        )
    )

    assert result.anchors is not None
    assert sorted(result.anchors) == ["e", "n", "s", "w"]
    for direction in ("n", "s", "e", "w"):
        assert (run_dir / "anchors" / direction / "anchor-snapped-native.png").is_file()
        final_anchor = run_dir / "anchors" / direction / "anchor-snapped-1024-chroma.png"
        assert final_anchor.is_file()
        with Image.open(final_anchor) as image:
            assert image.size == (1024, 1024)
            assert image.getpixel((0, 0)) == (0, 255, 0, 255)
        anchor_data = json.loads((run_dir / "anchors" / direction / "anchor.json").read_text(encoding="utf-8"))
        assert anchor_data["sourceForSnap"].endswith(f"character-{direction}.png")
    assert (run_dir / "review" / "direction-anchor-comparison.png").is_file()
    data = json.loads((run_dir / "character.json").read_text(encoding="utf-8"))
    assert data["anchors"]["n"].endswith("anchors/n/anchor-snapped-1024-chroma.png")


def test_anchor_wizard_direction_stage_can_skip_anchor_pixel_snap(tmp_path: Path) -> None:
    accepted = tmp_path / "accepted.png"
    _write_fake_1024_chroma_anchor(accepted, color=(46, 96, 180, 255))
    anchors_dir = tmp_path / "generated-anchors"
    _write_fake_1024_chroma_anchor(anchors_dir / "character-w-chroma.png", color=(80, 96, 180, 255))
    _write_fake_1024_chroma_anchor(anchors_dir / "character-w.png", color=(80, 96, 180, 255))

    run_dir = tmp_path / "runs" / "wizard-nosnap-directions"
    result = run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="mixel-hero",
            stage="directions",
            accepted_candidate=accepted,
            anchors_dir=anchors_dir,
            directions=("w",),
            candidate_prompt_preset="high-fidelity-v1",
            pixel_snap_anchor=False,
        )
    )

    assert result.anchors is not None
    direction_dir = run_dir / "anchors" / "w"
    assert result.anchors["w"] == direction_dir / "anchor-snapped-1024-chroma.png"
    assert (direction_dir / "anchor-1024-chroma.png").is_file()
    assert (direction_dir / "anchor-snapped-1024-chroma.png").is_file()
    assert not (direction_dir / "anchor-snapped-native.png").exists()
    assert not (direction_dir / "snap").exists()
    metadata = json.loads((direction_dir / "anchor.json").read_text(encoding="utf-8"))
    assert metadata["pixelSnapped"] is False
    assert metadata["snapRun"] is None
    assert metadata["snappedSize"] is None


def test_anchor_wizard_unsnapped_direction_preserves_existing_alpha(tmp_path: Path) -> None:
    accepted = tmp_path / "accepted.png"
    _write_fake_1024_chroma_anchor(accepted, color=(46, 96, 180, 255))
    anchors_dir = tmp_path / "generated-anchors"
    transparent_anchor = anchors_dir / "character-w.png"
    _write_fake_1024_transparent_anchor_with_dark_detail(transparent_anchor)
    _write_fake_1024_chroma_anchor(anchors_dir / "character-w-chroma.png", color=(80, 96, 180, 255))

    run_dir = tmp_path / "runs" / "wizard-nosnap-transparent-directions"
    run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="red-brawler",
            stage="directions",
            accepted_candidate=accepted,
            anchors_dir=anchors_dir,
            directions=("w",),
            candidate_prompt_preset="preserve-reference-v1",
            pixel_snap_anchor=False,
        )
    )

    direction_dir = run_dir / "anchors" / "w"
    source_visible = Image.open(transparent_anchor).convert("RGBA").getchannel("A").point(lambda value: 255 if value else 0)
    output = Image.open(direction_dir / "anchor-1024.png").convert("RGBA")
    output_visible = output.getchannel("A").point(lambda value: 255 if value else 0)
    assert output_visible.tobytes() == source_visible.tobytes()
    assert output.getpixel((440, 300)) == (0, 0, 0, 255)
    assert output.getpixel((560, 300)) == (4, 4, 4, 255)

    chroma = Image.open(direction_dir / "anchor-1024-chroma.png").convert("RGBA")
    assert chroma.getpixel((0, 0)) == (0, 255, 0, 255)
    assert chroma.getpixel((440, 300)) == (0, 0, 0, 255)
    assert chroma.getpixel((560, 300)) == (4, 4, 4, 255)

    metadata = json.loads((direction_dir / "anchor.json").read_text(encoding="utf-8"))
    assert metadata["pixelSnapped"] is False
    assert metadata["unsnappedTransform"]["backgroundCleanup"] == "preserved-alpha"


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_anchor_wizard_normalizes_transparent_source_image_for_model_input(tmp_path: Path) -> None:
    source = tmp_path / "transparent-source.png"
    candidate = tmp_path / "candidate.png"
    _write_fake_pixel_character_transparent(source, color=(46, 96, 180, 255))
    _write_fake_pixel_character(candidate, color=(46, 96, 180, 255))

    run_dir = tmp_path / "runs" / "wizard-transparent-source"
    run_anchor_wizard(
        AnchorWizardOptions(
            run_dir=run_dir,
            character_id="courier",
            stage="candidate",
            source_image=source,
            candidate_image=candidate,
            k_colors=64,
        )
    )

    assert (run_dir / "input" / "source-original.png").is_file()
    assert (run_dir / "input" / "source-model-input.png").is_file()
    metadata = json.loads((run_dir / "input" / "source.json").read_text(encoding="utf-8"))
    assert metadata["alphaNormalizedForModel"] is True
    assert metadata["alphaRange"] == [0, 255]
    assert metadata["sourceModelInput"].endswith("input/source-model-input.png")
    with Image.open(run_dir / "input" / "source-model-input.png") as model_input:
        assert model_input.convert("RGBA").getpixel((0, 0)) == (0, 255, 0, 255)
    prompt = (run_dir / "candidate" / "front" / "candidate-prompt.txt").read_text(encoding="utf-8")
    assert "chroma background is a removal matte" in prompt
    assert "Do not render checkerboard transparency" in prompt
    candidate_data = json.loads((run_dir / "candidate" / "front" / "candidate.json").read_text(encoding="utf-8"))
    assert candidate_data["candidateBackgroundCheck"]["passed"] is True


def test_anchor_wizard_rejects_faux_transparent_checkerboard_candidate(tmp_path: Path) -> None:
    source = tmp_path / "transparent-source.png"
    candidate = tmp_path / "checker-candidate.png"
    _write_fake_pixel_character_transparent(source, color=(46, 96, 180, 255))
    _write_fake_checkerboard_candidate(candidate)

    run_dir = tmp_path / "runs" / "wizard-checkerboard-candidate"
    with pytest.raises(ValueError, match="baked faux transparency"):
        run_anchor_wizard(
            AnchorWizardOptions(
                run_dir=run_dir,
                character_id="courier",
                stage="candidate",
                source_image=source,
                candidate_image=candidate,
                k_colors=64,
            )
        )

    check = json.loads((run_dir / "candidate" / "front" / "candidate-background-check.json").read_text(encoding="utf-8"))
    assert check["strict"] is True
    assert check["passed"] is False
    assert check["cornerLightNeutralCount"] == 4
    assert not (run_dir / "candidate" / "front" / "snapped-1024-chroma.png").exists()


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_anchor_wizard_cli_candidate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    _write_fake_source(source)
    _write_fake_pixel_character(candidate, color=(46, 96, 180, 255))
    run_dir = tmp_path / "runs" / "wizard-cli"

    cli_main(
        [
            "anchor-wizard",
            "--stage",
            "candidate",
            "--run-dir",
            str(run_dir),
            "--character-id",
            "courier",
            "--source-image",
            str(source),
            "--candidate-image",
            str(candidate),
            "--k-colors",
            "64",
        ]
    )

    lines = capsys.readouterr().out.strip().splitlines()
    assert Path(lines[0]) == run_dir / "character.json"
    assert (run_dir / "candidate" / "front" / "snapped-1024-chroma.png").is_file()
