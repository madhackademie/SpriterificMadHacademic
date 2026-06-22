from __future__ import annotations

from importlib import resources
from pathlib import Path


def copy_anchor_guide(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    guide = resources.files("spriterrific").joinpath("assets/guides/alternating-1024x1024.png")
    with resources.as_file(guide) as source:
        out.write_bytes(source.read_bytes())
    return out
