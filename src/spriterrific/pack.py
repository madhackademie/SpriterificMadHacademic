from __future__ import annotations

from pathlib import Path

from PIL import Image

from .presets import FRAME_HEIGHT, FRAME_WIDTH, SHEET_COLUMNS, sheet_rows


def pack_spritesheet(
    input_dir: Path,
    output: Path,
    frame_count: int,
    glob: str = "frame-*.png",
    *,
    cell_size: tuple[int, int] = (FRAME_WIDTH, FRAME_HEIGHT),
    columns: int = SHEET_COLUMNS,
) -> Path:
    frames = sorted(input_dir.glob(glob))[:frame_count]
    if len(frames) != frame_count:
        raise ValueError(f"expected {frame_count} frames in {input_dir}, found {len(frames)}")

    if columns == SHEET_COLUMNS:
        rows = sheet_rows(frame_count)
    else:
        if columns <= 0:
            raise ValueError("columns must be positive")
        rows = (frame_count + columns - 1) // columns
    cell_w, cell_h = cell_size
    sheet = Image.new("RGBA", (columns * cell_w, rows * cell_h), (0, 0, 0, 0))
    for index, frame_path in enumerate(frames):
        frame = Image.open(frame_path).convert("RGBA")
        if frame.size != (cell_w, cell_h):
            raise ValueError(f"{frame_path} must be {cell_w}x{cell_h}, got {frame.size[0]}x{frame.size[1]}")
        col = index % columns
        row = index // columns
        sheet.alpha_composite(frame, (col * cell_w, row * cell_h))

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output
