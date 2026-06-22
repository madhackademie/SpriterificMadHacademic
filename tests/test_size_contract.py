from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from spriterrific.size_contract import audit_size_contract, derive_size_contract, load_size_contract


def _make_runtime_frame(path: Path, *, bbox: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((bbox[0], bbox[1], bbox[2] - 1, bbox[3] - 1), fill=(120, 80, 40, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_derive_size_contract_from_runtime_frames_and_audit(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    _make_runtime_frame(frames / "frame-01.png", bbox=(25, 52, 206, 196))
    _make_runtime_frame(frames / "frame-02.png", bbox=(27, 53, 205, 196))
    _make_runtime_frame(frames / "frame-03.png", bbox=(28, 54, 204, 196))

    contract_path = derive_size_contract(
        frames,
        out=tmp_path / "size-contract.json",
        name="turret-v1",
        action="idle",
        direction="w",
        pivot="base-center",
    )
    contract = load_size_contract(contract_path)

    assert contract["kind"] == "spriterrific-size-contract"
    assert contract["name"] == "turret-v1"
    assert contract["targetVisibleHeight"] == 143
    assert contract["targetBottomY"] == 195
    assert contract["maxVisibleWidth"] == 181
    assert contract["promptGuidance"]

    report = audit_size_contract(frames, contract, out=tmp_path / "audit.json")
    assert report["status"] == "pass"
    assert json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))["passed"] is True


def test_audit_size_contract_warns_on_scale_drift(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    _make_runtime_frame(frames / "frame-01.png", bbox=(25, 52, 206, 196))
    _make_runtime_frame(frames / "frame-02.png", bbox=(25, 80, 206, 196))

    contract_path = tmp_path / "size-contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "spriterrific-size-contract",
                "runtimeCell": [256, 256],
                "targetVisibleHeight": 144,
                "maxVisibleWidth": 181,
                "targetBottomY": 195,
                "targetCenterX": 115,
                "tolerances": {
                    "maxTargetHeightDriftPct": 0.05,
                    "maxIntraHeightDriftPct": 0.05,
                    "maxBottomDriftPx": 2,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = audit_size_contract(frames, load_size_contract(contract_path))
    assert report["status"] == "warn"
    assert report["passed"] is False
    assert any(check["name"] == "target-visible-height" and check["status"] == "warn" for check in report["checks"])
