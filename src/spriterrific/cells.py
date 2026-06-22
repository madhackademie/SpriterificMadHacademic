from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from .presets import FRAME_HEIGHT, FRAME_WIDTH


def crop_exact_cells(
    sheet: Path,
    out_dir: Path,
    *,
    rows: int,
    cols: int,
    prefix: str = "frame",
) -> list[Path]:
    image = Image.open(sheet).convert("RGBA")
    expected = (cols * FRAME_WIDTH, rows * FRAME_HEIGHT)
    if image.size != expected:
        raise ValueError(f"exact cell crop requires sheet size {expected[0]}x{expected[1]}, got {image.size[0]}x{image.size[1]}")

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    metadata = {"sheet": str(sheet), "rows": rows, "cols": cols, "frameSize": [FRAME_WIDTH, FRAME_HEIGHT], "frames": []}
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col + 1
            left = col * FRAME_WIDTH
            top = row * FRAME_HEIGHT
            crop = image.crop((left, top, left + FRAME_WIDTH, top + FRAME_HEIGHT))
            out = out_dir / f"{prefix}-{index:02d}.png"
            crop.save(out)
            outputs.append(out)
            metadata["frames"].append({"frame": f"{index:02d}", "col": col, "row": row, "path": str(out)})

    (out_dir / f"{prefix}-cell-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return outputs
