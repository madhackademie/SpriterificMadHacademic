from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from spriterrific.api import create_app
from spriterrific.bootstrap_anchors import BootstrapAnchorsOptions, load_bootstrap_options, run_bootstrap_anchors
from spriterrific.cli import main as cli_main
from spriterrific.pixel_snap import PIXEL_SNAPPER_SCRIPT


def _write_source(path: Path) -> None:
    image = Image.new("RGBA", (512, 512), (217, 217, 217, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((205, 130, 310, 430), fill=(78, 82, 92, 255))
    draw.rectangle((223, 75, 292, 150), fill=(232, 190, 142, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_pixel_character(path: Path, *, color: tuple[int, int, int, int]) -> None:
    base = Image.new("RGBA", (32, 32), (0, 255, 0, 255))
    draw = ImageDraw.Draw(base)
    draw.rectangle((12, 8, 20, 24), fill=color)
    draw.rectangle((14, 4, 18, 10), fill=(235, 190, 145, 255))
    draw.rectangle((11, 24, 14, 29), fill=(65, 45, 38, 255))
    draw.rectangle((18, 24, 21, 29), fill=(65, 45, 38, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    base.resize((512, 512), Image.Resampling.NEAREST).save(path)


def _fixtures(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    anchors_dir = tmp_path / "generated-anchors"
    _write_source(source)
    _write_pixel_character(candidate, color=(70, 82, 120, 255))
    _write_pixel_character(anchors_dir / "character-w-chroma.png", color=(78, 94, 130, 255))
    _write_pixel_character(anchors_dir / "character-w.png", color=(78, 94, 130, 255))
    return source, candidate, anchors_dir


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_bootstrap_anchors_writes_debuggable_layout_and_metadata(tmp_path: Path) -> None:
    source, candidate, anchors_dir = _fixtures(tmp_path)
    run_dir = tmp_path / "runs" / "bootstrap"

    result = run_bootstrap_anchors(
        BootstrapAnchorsOptions(
            run_dir=run_dir,
            character_id="clockwork-courier",
            source_image=source,
            candidate_image=candidate,
            anchors_dir=anchors_dir,
            directions=("w",),
            k_colors=64,
            game_view="platformer",
            anchor_role="enemy",
            anchor_context="side-scrolling platformer enemy",
        )
    )

    assert result.bootstrap_json == run_dir / "bootstrap.json"
    assert (run_dir / "input" / "source.png").is_file()
    assert (run_dir / "input" / "source-model-input.png").is_file()
    assert (run_dir / "input" / "source.json").is_file()
    assert (run_dir / "candidate" / "front" / "snapped-1024-chroma.png").is_file()
    assert (run_dir / "anchors" / "w" / "anchor-snapped-1024-chroma.png").is_file()
    assert (run_dir / "config" / "bootstrap-request.json").is_file()
    assert (run_dir / "config" / "candidate-prompt-rendered.txt").is_file()
    assert (run_dir / "review" / "bootstrap" / "index.md").is_file()

    data = json.loads(result.bootstrap_json.read_text(encoding="utf-8"))
    assert data["type"] == "bootstrap-anchors"
    assert data["directions"] == ["w"]
    assert data["candidateFacing"] == "front"
    assert data["candidatePromptPreset"] == "lobit-v1"
    assert data["pixelSnapAnchor"] is True
    assert data["gameView"] == "platformer"
    assert data["anchorRole"] == "enemy"
    assert data["anchorContext"] == "side-scrolling platformer enemy"
    assert data["canonicalOutputs"]["candidateSnapped1024Chroma"].endswith("candidate/front/snapped-1024-chroma.png")
    assert data["canonicalOutputs"]["candidateAnchor1024Chroma"].endswith("candidate/front/anchor-1024-chroma.png")
    assert data["canonicalOutputs"]["sourceModelInput"].endswith("input/source-model-input.png")
    assert data["canonicalOutputs"]["sourceInputMetadata"].endswith("input/source.json")
    assert data["canonicalOutputs"]["directionAnchors"]["w"]["anchor1024Chroma"].endswith("anchors/w/anchor-1024-chroma.png")
    assert data["canonicalOutputs"]["directionAnchors"]["w"]["snapped1024Chroma"].endswith("anchors/w/anchor-snapped-1024-chroma.png")

    loaded = load_bootstrap_options(run_dir / "config" / "bootstrap-request.json")
    assert loaded.character_id == "clockwork-courier"
    assert loaded.directions == ("w",)
    assert loaded.candidate_facing == "front"
    assert loaded.game_view == "platformer"
    assert loaded.anchor_role == "enemy"
    assert loaded.anchor_context == "side-scrolling platformer enemy"
    assert loaded.pixel_snap_anchor is True


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_bootstrap_anchors_can_generate_front_candidate_only(tmp_path: Path) -> None:
    source, candidate, _anchors_dir = _fixtures(tmp_path)
    run_dir = tmp_path / "runs" / "front-only"

    result = run_bootstrap_anchors(
        BootstrapAnchorsOptions(
            run_dir=run_dir,
            character_id="platformer-hero",
            source_image=source,
            candidate_image=candidate,
            directions=(),
            k_colors=64,
        )
    )

    assert result.candidate_anchor == run_dir / "candidate" / "front" / "snapped-1024-chroma.png"
    assert result.anchors == {}
    data = json.loads(result.bootstrap_json.read_text(encoding="utf-8"))
    assert data["directions"] == []
    assert data["candidateFacing"] == "front"
    assert data["canonicalOutputs"]["candidateSnapped1024Chroma"].endswith("candidate/front/snapped-1024-chroma.png")


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_rts_oblique_bootstrap_defaults_to_south_candidate(tmp_path: Path) -> None:
    source, candidate, _anchors_dir = _fixtures(tmp_path)
    run_dir = tmp_path / "runs" / "rts-oblique"

    result = run_bootstrap_anchors(
        BootstrapAnchorsOptions(
            run_dir=run_dir,
            character_id="orc-warrior",
            source_image=source,
            candidate_image=candidate,
            directions=(),
            k_colors=64,
            game_view="rts-oblique",
            anchor_role="enemy",
        )
    )

    assert result.candidate_anchor == run_dir / "candidate" / "s" / "snapped-1024-chroma.png"
    data = json.loads(result.bootstrap_json.read_text(encoding="utf-8"))
    assert data["candidateFacing"] == "south"
    assert data["gameView"] == "rts-oblique"
    prompt = (run_dir / "config" / "candidate-prompt-rendered.txt").read_text(encoding="utf-8")
    assert "elevated oblique RTS" in prompt
    assert "not a straight-on front portrait" in prompt


def test_bootstrap_anchors_can_skip_anchor_pixel_snap(tmp_path: Path) -> None:
    source, candidate, anchors_dir = _fixtures(tmp_path)
    run_dir = tmp_path / "runs" / "bootstrap-nosnap"

    result = run_bootstrap_anchors(
        BootstrapAnchorsOptions(
            run_dir=run_dir,
            character_id="mixel-hero",
            source_image=source,
            candidate_image=candidate,
            anchors_dir=anchors_dir,
            directions=("w",),
            candidate_prompt_preset="high-fidelity-v1",
            pixel_snap_anchor=False,
        )
    )

    assert result.candidate_anchor == run_dir / "candidate" / "front" / "snapped-1024-chroma.png"
    assert (run_dir / "candidate" / "front" / "anchor-1024-chroma.png").is_file()
    assert not (run_dir / "candidate" / "front" / "snapped-native.png").exists()
    assert (run_dir / "anchors" / "w" / "anchor-1024-chroma.png").is_file()
    assert not (run_dir / "anchors" / "w" / "anchor-snapped-native.png").exists()
    data = json.loads(result.bootstrap_json.read_text(encoding="utf-8"))
    assert data["candidatePromptPreset"] == "high-fidelity-v1"
    assert data["pixelSnapAnchor"] is False
    loaded = load_bootstrap_options(run_dir / "config" / "bootstrap-request.json")
    assert loaded.pixel_snap_anchor is False
    assert loaded.candidate_prompt_preset == "high-fidelity-v1"


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_bootstrap_anchors_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source, candidate, anchors_dir = _fixtures(tmp_path)
    run_dir = tmp_path / "runs" / "bootstrap-cli"

    cli_main(
        [
            "bootstrap-anchors",
            "--run-dir",
            str(run_dir),
            "--character-id",
            "clockwork-courier",
            "--source-image",
            str(source),
            "--candidate-image",
            str(candidate),
            "--anchors-dir",
            str(anchors_dir),
            "--candidate-prompt-preset",
            "high-fidelity-v1",
            "--no-pixel-snap-anchor",
            "--directions",
            "w",
            "--k-colors",
            "64",
        ]
    )

    lines = capsys.readouterr().out.strip().splitlines()
    assert Path(lines[0]) == run_dir / "bootstrap.json"
    assert (run_dir / "anchors" / "w" / "anchor-snapped-1024-chroma.png").is_file()
    assert not (run_dir / "anchors" / "w" / "anchor-snapped-native.png").exists()


@pytest.mark.skipif(not PIXEL_SNAPPER_SCRIPT.exists(), reason="pixel-snapper skill script not available")
def test_bootstrap_anchors_api_endpoint(tmp_path: Path) -> None:
    source, candidate, anchors_dir = _fixtures(tmp_path)
    requested_run_dir = tmp_path / "client-requested-run-dir"
    run_root = tmp_path / "api-runs"
    client = TestClient(create_app(run_root=run_root))

    response = client.post(
        "/bootstrap-anchors",
        json={
            "runDir": str(requested_run_dir),
            "characterId": "clockwork-courier",
            "runLabel": "Clockwork Courier Web",
            "sourceImage": str(source),
            "candidateImage": str(candidate),
            "anchorsDir": str(anchors_dir),
            "candidatePromptPreset": "high-fidelity-v1",
            "pixelSnapAnchor": False,
            "directions": ["w"],
            "kColors": 64,
        },
    )

    assert response.status_code == 202, response.text
    data = response.json()
    assert "runDir" not in data
    assert data["runId"].startswith("20")
    assert "-api-bootstrap-clockwork-courier-web-" in data["runId"]
    run_dir = run_root / data["runId"]
    status_response = client.get(data["pollUrl"])
    assert status_response.status_code == 200
    data = status_response.json()
    assert data["status"] == "completed"
    assert run_dir.is_dir()
    assert not requested_run_dir.exists()
    assert (run_dir / "bootstrap.json").is_file()
    assert (run_dir / "api-status.json").is_file()
    assert (run_dir / "input" / "source.png").is_file()
    assert (run_dir / "anchors" / "w" / "anchor-snapped-1024-chroma.png").is_file()
    assert not (run_dir / "anchors" / "w" / "anchor-snapped-native.png").exists()
    assert data["artifactUrls"]["source"] == f"/runs/{data['runId']}/artifacts/source"
    assert data["artifactUrls"]["candidate"] == f"/runs/{data['runId']}/artifacts/candidate-front"
    assert data["artifactUrls"]["candidate-front"] == f"/runs/{data['runId']}/artifacts/candidate-front"
    assert data["artifactUrls"]["anchor-w"] == f"/runs/{data['runId']}/artifacts/anchor-w"
    assert data["anchors"]["w"] == data["artifactUrls"]["anchor-w"]


def test_web_app_and_static_assets_are_served() -> None:
    client = TestClient(create_app())

    app_info = client.get("/app-info")
    assert app_info.status_code == 200
    info = app_info.json()
    assert info["version"]
    assert info["appVersion"] == info["version"]
    assert info["sdkVersion"]
    assert info["cliVersion"]

    response = client.get("/")
    assert response.status_code == 200
    assert "Spriterrific" in response.text
    assert 'id="bootstrap-form"' in response.text
    assert 'id="about-versions"' in response.text
    assert 'id="sdk-version"' in response.text
    assert 'id="cli-version"' in response.text
    assert "Run Label" in response.text
    assert "Run Folder" not in response.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "fetch(\"/bootstrap-anchors\"" in script.text
    assert "sdkVersion" in script.text
    assert "cliVersion" in script.text
    assert "candidatePromptPreset" in script.text
    assert "pixelSnapAnchor" in script.text
    assert "fetch(path, { cache: \"no-store\" })" in script.text
    assert "runDir" not in script.text

    styles = client.get("/static/styles.css")
    assert styles.status_code == 200
    assert ".workspace" in styles.text
    assert ".about-versions" in styles.text


def test_artifact_endpoint_serves_supported_files(tmp_path: Path) -> None:
    run_root = tmp_path / "api-runs"
    source = run_root / "run-123" / "input" / "source.png"
    _write_source(source)
    client = TestClient(create_app(run_root=run_root))

    response = client.get("/runs/run-123/artifacts/source")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG")
