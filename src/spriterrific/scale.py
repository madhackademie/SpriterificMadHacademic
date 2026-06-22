from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


def scale_frame_crops(
    input_dir: Path,
    out_dir: Path,
    *,
    glob: str = "frame-*.png",
    target_height: int = 210,
    max_width: int = 220,
    mode: str = "shared",
    allow_upscale: bool = False,
) -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    measurements = []
    for path in frames:
        image = Image.open(path).convert("RGBA")
        bbox = image.getchannel("A").getbbox() or (0, 0, image.width, image.height)
        visible_w = bbox[2] - bbox[0]
        visible_h = bbox[3] - bbox[1]
        measurements.append((path, image, bbox, visible_w, visible_h))

    max_visible_h = max(item[4] for item in measurements)
    max_visible_w = max(item[3] for item in measurements)
    shared_scale = min(target_height / max_visible_h, max_width / max_visible_w)
    if not allow_upscale:
        shared_scale = min(1.0, shared_scale)
    if mode not in {"shared", "per-frame"}:
        raise ValueError("mode must be shared or per-frame")

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.png"):
        old.unlink()

    outputs = []
    metadata = {
        "targetHeight": target_height,
        "maxWidth": max_width,
        "sourceMaxVisibleSize": [max_visible_w, max_visible_h],
        "mode": mode,
        "allowUpscale": allow_upscale,
        "scale": shared_scale,
        "sharedScale": shared_scale,
        "frames": [],
    }

    for path, image, bbox, visible_w, visible_h in measurements:
        crop = image.crop(bbox)
        scale = shared_scale
        if mode == "per-frame":
            scale = min(target_height / visible_h, max_width / visible_w)
            if not allow_upscale:
                scale = min(1.0, scale)
        if scale != 1.0:
            new_size = (
                max(1, round(crop.width * scale)),
                max(1, round(crop.height * scale)),
            )
            crop = crop.resize(new_size, Image.Resampling.NEAREST)
        dest = out_dir / path.name
        crop.save(dest)
        outputs.append(dest)
        metadata["frames"].append(
            {
                "input": str(path),
                "output": str(dest),
                "sourceBBox": list(bbox),
                "sourceVisibleSize": [visible_w, visible_h],
                "scale": scale,
                "outputSize": [crop.width, crop.height],
            }
        )

    (out_dir / "scale-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs
