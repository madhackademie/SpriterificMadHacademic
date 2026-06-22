from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageColor, ImageDraw

from .review_index import ReviewAsset, write_review_index

if TYPE_CHECKING:
    import tkinter as tk

    from PIL import ImageTk


CHECKER_LIGHT = (78, 84, 96, 255)
CHECKER_DARK = (38, 43, 54, 255)
GRID_COLOR = (18, 22, 30, 180)
PANEL_BG = "#1a1f2b"
TEXT_COLOR = "#e5e7eb"
ACCENT = "#3b82f6"


@dataclass(frozen=True)
class CleanupExport:
    out_dir: Path
    frames_dir: Path | None
    spritesheet: Path
    preview_gif: Path | None
    before_after: Path
    report: Path
    metadata: Path
    review_index: Path


def cleanup_frame_paths(input_dir: Path, *, glob: str = "frame-*.png") -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")
    return frames


def apply_pixel_edit(
    image: Image.Image,
    x: int,
    y: int,
    *,
    color: tuple[int, int, int, int],
    brush_size: int = 1,
    erase: bool = False,
) -> Image.Image:
    if brush_size <= 0:
        raise ValueError("brush_size must be positive")
    out = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(out)
    radius_left = (brush_size - 1) // 2
    radius_right = brush_size // 2
    box = (x - radius_left, y - radius_left, x + radius_right, y + radius_right)
    fill = (0, 0, 0, 0) if erase else color
    draw.rectangle(box, fill=fill)
    return out


def pack_cleanup_spritesheet(images: list[Image.Image], out: Path, *, columns: int) -> Path:
    if not images:
        raise ValueError("cannot pack an empty frame list")
    if columns <= 0:
        raise ValueError("columns must be positive")
    frames = [image.convert("RGBA") for image in images]
    cell_size = frames[0].size
    for index, frame in enumerate(frames, start=1):
        if frame.size != cell_size:
            raise ValueError(f"frame {index} must be {cell_size[0]}x{cell_size[1]}, got {frame.size[0]}x{frame.size[1]}")
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGBA", (columns * cell_size[0], rows * cell_size[1]), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        col = index % columns
        row = index // columns
        sheet.alpha_composite(frame, (col * cell_size[0], row * cell_size[1]))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def write_cleanup_export(
    *,
    source_paths: list[Path],
    originals: list[Image.Image],
    images: list[Image.Image],
    out_dir: Path,
    source_kind: str,
    columns: int = 5,
    fps: int = 10,
) -> CleanupExport:
    if source_kind not in {"frames", "sheet"}:
        raise ValueError("source_kind must be frames or sheet")
    if len(source_paths) != len(images) or len(originals) != len(images):
        raise ValueError("source_paths, originals, and images must have the same length")
    if not images:
        raise ValueError("cannot export an empty cleanup set")

    out_dir.mkdir(parents=True, exist_ok=True)
    review_dir = out_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    frames = [image.convert("RGBA") for image in images]
    before_frames = [image.convert("RGBA") for image in originals]

    if source_kind == "frames":
        first_size = frames[0].size
        frames_dir = out_dir / f"frames-{first_size[0]}x{first_size[1]}"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for old in frames_dir.glob("frame-*.png"):
            old.unlink()
        frame_records = []
        for index, (source, frame) in enumerate(zip(source_paths, frames), start=1):
            if frame.size != first_size:
                raise ValueError(f"{source} must be {first_size[0]}x{first_size[1]}, got {frame.size[0]}x{frame.size[1]}")
            output = frames_dir / f"frame-{index:02d}.png"
            frame.save(output)
            frame_records.append({"frame": output.name, "source": str(source)})
        spritesheet = out_dir / f"spritesheet-{first_size[0]}x{first_size[1]}-{columns}x{math.ceil(len(frames) / columns)}.png"
        pack_cleanup_spritesheet(frames, spritesheet, columns=columns)
        preview_gif = review_dir / f"preview-{len(frames)}f-{first_size[0]}x{first_size[1]}.gif"
        _save_gif(frames, preview_gif, fps=fps)
        before_after = review_dir / f"before-after-{len(frames)}f-{first_size[0]}x{first_size[1]}.png"
        _save_before_after_contact(before_frames, frames, before_after, columns=columns)
    else:
        if len(frames) != 1:
            raise ValueError("sheet cleanup export expects exactly one image")
        frames_dir = None
        spritesheet = out_dir / "spritesheet-cleaned.png"
        frames[0].save(spritesheet)
        preview_gif = None
        before_after = review_dir / "before-after-sheet.png"
        _save_before_after_contact(before_frames, frames, before_after, columns=1)
        frame_records = [{"frame": spritesheet.name, "source": str(source_paths[0])}]

    metadata = out_dir / "sprite-cleanup.json"
    metadata.write_text(
        json.dumps(
            {
                "version": 1,
                "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                "sourceKind": source_kind,
                "columns": columns,
                "fps": fps,
                "frames": frame_records,
                "spritesheet": str(spritesheet),
                "previewGif": str(preview_gif) if preview_gif else None,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    report = out_dir / "report.md"
    report.write_text(_cleanup_report(source_kind, frame_records, spritesheet, preview_gif, before_after, metadata), encoding="utf-8")
    assets = [
        ReviewAsset("Before/After Cleanup", before_after, "Original and manually cleaned pixels shown side by side.", True),
        ReviewAsset("Cleaned Spritesheet", spritesheet, "Cleaned transparent spritesheet export.", True),
        ReviewAsset("Cleanup Report", report, "Human-readable cleanup report.", False),
        ReviewAsset("Cleanup JSON", metadata, "Machine-readable cleanup metadata.", False),
    ]
    if preview_gif:
        assets.insert(1, ReviewAsset("Cleaned Preview GIF", preview_gif, "Cleaned runtime frames looped in order.", True))
    if frames_dir:
        assets.append(ReviewAsset("Cleaned Frames", frames_dir, "Directory containing cleaned runtime frame PNGs.", False))
    review_index = write_review_index(
        review_dir,
        title=f"{out_dir.name} Sprite Cleanup Review",
        summary="Review page for manually cleaned sprite pixels.",
        notes=[
            f"Source kind: `{source_kind}`.",
            f"Frames: `{len(frames)}`.",
            "The cleanup editor changes individual pixels only; it does not re-normalize, realign, or pixel-snap.",
        ],
        assets=assets,
    )

    return CleanupExport(
        out_dir=out_dir,
        frames_dir=frames_dir,
        spritesheet=spritesheet,
        preview_gif=preview_gif,
        before_after=before_after,
        report=report,
        metadata=metadata,
        review_index=review_index,
    )


def default_cleanup_output_dir(source: Path) -> Path:
    base = source if source.is_dir() else source.parent
    return base / "sprite-cleanup" / datetime.now().strftime("%Y%m%d-%H%M%S")


def launch_sprite_cleanup(
    *,
    sheet: Path | None = None,
    input_dir: Path | None = None,
    out_dir: Path | None = None,
    glob: str = "frame-*.png",
    columns: int = 5,
    fps: int = 10,
    zoom: int = 4,
) -> None:
    if (sheet is None) == (input_dir is None):
        raise ValueError("provide exactly one of sheet or input_dir")

    import tkinter as tk
    from tkinter import messagebox, ttk

    from PIL import ImageTk

    if sheet is not None:
        source_paths = [sheet]
        images = [Image.open(sheet).convert("RGBA")]
        source_kind = "sheet"
        default_out = default_cleanup_output_dir(sheet)
    else:
        assert input_dir is not None
        source_paths = cleanup_frame_paths(input_dir, glob=glob)
        images = [Image.open(path).convert("RGBA") for path in source_paths]
        source_kind = "frames"
        default_out = default_cleanup_output_dir(input_dir)
    originals = [image.copy() for image in images]

    root = tk.Tk()
    from .app_icon import apply_app_icon

    apply_app_icon(root)
    root.title("Spriterrific Sprite Cleanup")
    app = _SpriteCleanupApp(
        root,
        source_paths=source_paths,
        originals=originals,
        images=images,
        source_kind=source_kind,
        out_dir=out_dir or default_out,
        columns=columns,
        fps=fps,
        zoom=max(1, zoom),
        image_tk=ImageTk,
        messagebox=messagebox,
        ttk=ttk,
    )
    app.pack()
    root.mainloop()


class _SpriteCleanupApp:
    def __init__(
        self,
        root: "tk.Tk",
        *,
        source_paths: list[Path],
        originals: list[Image.Image],
        images: list[Image.Image],
        source_kind: str,
        out_dir: Path,
        columns: int,
        fps: int,
        zoom: int,
        image_tk: object,
        messagebox: object,
        ttk: object,
    ) -> None:
        import tkinter as tk

        self.root = root
        self.source_paths = source_paths
        self.originals = originals
        self.images = images
        self.source_kind = source_kind
        self.out_dir = out_dir
        self.columns = columns
        self.fps = fps
        self.zoom = zoom
        self.ImageTk = image_tk
        self.messagebox = messagebox
        self.ttk = ttk
        self.index = 0
        self.photo: "ImageTk.PhotoImage | None" = None
        self.tool = tk.StringVar(value="pencil")
        self.color_text = tk.StringVar(value="#ff66cc")
        self.brush_size = tk.IntVar(value=1)
        self.status = tk.StringVar(value="")
        self.swatch: "tk.Label | None" = None
        self.canvas: "tk.Canvas | None" = None

    def pack(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.root.configure(bg=PANEL_BG)
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        for text, value in [("Pencil", "pencil"), ("Eraser", "eraser"), ("Dropper", "dropper")]:
            ttk.Radiobutton(toolbar, text=text, variable=self.tool, value=value).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(toolbar, text="Color").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(toolbar, textvariable=self.color_text, width=10).pack(side=tk.LEFT)
        self.swatch = tk.Label(toolbar, width=3, relief=tk.SUNKEN, bg=self.color_text.get())
        self.swatch.pack(side=tk.LEFT, padx=(4, 12))
        self.color_text.trace_add("write", lambda *_: self._refresh_swatch())
        ttk.Label(toolbar, text="Brush").pack(side=tk.LEFT)
        ttk.Spinbox(toolbar, from_=1, to=16, textvariable=self.brush_size, width=4).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Button(toolbar, text="Prev", command=self._previous_frame).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Next", command=self._next_frame).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(toolbar, text="Reset Frame", command=self._reset_frame).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Save", command=self._save).pack(side=tk.LEFT, padx=(4, 0))

        frame = ttk.Frame(self.root)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(frame, bg="#0b0f16", highlightthickness=0)
        xbar = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        ybar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self._handle_paint)
        self.canvas.bind("<B1-Motion>", self._handle_paint)
        self.canvas.bind("<Motion>", self._handle_motion)

        status = ttk.Label(self.root, textvariable=self.status, padding=(8, 4))
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.root.bind("b", lambda _event: self.tool.set("pencil"))
        self.root.bind("e", lambda _event: self.tool.set("eraser"))
        self.root.bind("i", lambda _event: self.tool.set("dropper"))
        self.root.bind("<Left>", lambda _event: self._previous_frame())
        self.root.bind("<Right>", lambda _event: self._next_frame())
        self.root.bind("<bracketleft>", lambda _event: self._change_brush(-1))
        self.root.bind("<bracketright>", lambda _event: self._change_brush(1))
        self._render()

    def _render(self) -> None:
        assert self.canvas is not None
        image = render_cleanup_preview(self.images[self.index], scale=self.zoom)
        self.photo = self.ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, image.width, image.height))
        name = self.source_paths[self.index].name
        self.status.set(
            f"{self.source_kind} {self.index + 1}/{len(self.images)}: {name} | "
            f"{self.images[self.index].width}x{self.images[self.index].height} | "
            f"tool={self.tool.get()} brush={self.brush_size.get()} | out={self.out_dir}"
        )

    def _handle_motion(self, event: object) -> None:
        x, y = self._event_pixel(event)
        if x is None or y is None:
            return
        pixel = self.images[self.index].getpixel((x, y))
        self.status.set(f"x={x} y={y} rgba={pixel} | tool={self.tool.get()} brush={self.brush_size.get()} | out={self.out_dir}")

    def _handle_paint(self, event: object) -> None:
        x, y = self._event_pixel(event)
        if x is None or y is None:
            return
        tool = self.tool.get()
        if tool == "dropper":
            self._set_color(self.images[self.index].getpixel((x, y)))
            return
        self.images[self.index] = apply_pixel_edit(
            self.images[self.index],
            x,
            y,
            color=self._current_color(),
            brush_size=max(1, int(self.brush_size.get())),
            erase=tool == "eraser",
        )
        self._render()

    def _event_pixel(self, event: object) -> tuple[int | None, int | None]:
        assert self.canvas is not None
        canvas_x = int(self.canvas.canvasx(getattr(event, "x")) // self.zoom)
        canvas_y = int(self.canvas.canvasy(getattr(event, "y")) // self.zoom)
        image = self.images[self.index]
        if canvas_x < 0 or canvas_y < 0 or canvas_x >= image.width or canvas_y >= image.height:
            return (None, None)
        return (canvas_x, canvas_y)

    def _current_color(self) -> tuple[int, int, int, int]:
        try:
            r, g, b = ImageColor.getrgb(self.color_text.get())
        except ValueError:
            r, g, b = (255, 102, 204)
            self.color_text.set("#ff66cc")
        return (r, g, b, 255)

    def _set_color(self, rgba: tuple[int, int, int, int]) -> None:
        r, g, b, _ = rgba
        self.color_text.set(f"#{r:02x}{g:02x}{b:02x}")
        self.tool.set("pencil")

    def _refresh_swatch(self) -> None:
        if self.swatch is None:
            return
        try:
            ImageColor.getrgb(self.color_text.get())
            self.swatch.configure(bg=self.color_text.get())
        except ValueError:
            self.swatch.configure(bg="#ff66cc")

    def _previous_frame(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._render()

    def _next_frame(self) -> None:
        if self.index < len(self.images) - 1:
            self.index += 1
            self._render()

    def _reset_frame(self) -> None:
        self.images[self.index] = self.originals[self.index].copy()
        self._render()

    def _change_brush(self, delta: int) -> None:
        self.brush_size.set(max(1, min(16, int(self.brush_size.get()) + delta)))
        self._render()

    def _save(self) -> None:
        try:
            export = write_cleanup_export(
                source_paths=self.source_paths,
                originals=self.originals,
                images=self.images,
                out_dir=self.out_dir,
                source_kind=self.source_kind,
                columns=self.columns,
                fps=self.fps,
            )
        except Exception as exc:  # pragma: no cover - exercised manually in Tk
            self.messagebox.showerror("Save failed", str(exc))
            return
        self.messagebox.showinfo("Saved", f"Cleanup export written:\n{export.out_dir}")
        self.status.set(f"saved {export.out_dir}")


def render_cleanup_preview(image: Image.Image, *, scale: int = 4) -> Image.Image:
    rgba = image.convert("RGBA")
    preview = _checkerboard(rgba.size)
    preview.alpha_composite(rgba)
    if scale > 1:
        preview = preview.resize((rgba.width * scale, rgba.height * scale), Image.Resampling.NEAREST)
        if scale >= 8:
            _draw_scaled_grid(preview, scale)
    return preview


def _checkerboard(size: tuple[int, int], *, cell: int = 8) -> Image.Image:
    width, height = size
    out = Image.new("RGBA", size, CHECKER_LIGHT)
    draw = ImageDraw.Draw(out)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, min(width, x + cell) - 1, min(height, y + cell) - 1), fill=CHECKER_DARK)
    return out


def _draw_scaled_grid(image: Image.Image, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    for x in range(0, image.width + 1, scale):
        draw.line((x, 0, x, image.height), fill=GRID_COLOR)
    for y in range(0, image.height + 1, scale):
        draw.line((0, y, image.width, y), fill=GRID_COLOR)


def _save_gif(images: list[Image.Image], out: Path, *, fps: int) -> None:
    if not images:
        return
    duration_ms = round(1000 / fps) if fps > 0 else 100
    frames = [image.convert("RGBA") for image in images]
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=duration_ms, loop=0, disposal=2)


def _save_before_after_contact(before: list[Image.Image], after: list[Image.Image], out: Path, *, columns: int) -> None:
    if len(before) != len(after) or not before:
        raise ValueError("before and after image lists must be non-empty and equal length")
    pairs = []
    for source, cleaned in zip(before, after):
        left = source.convert("RGBA")
        right = cleaned.convert("RGBA")
        if left.size != right.size:
            raise ValueError("before and after frames must share a size")
        pair = Image.new("RGBA", (left.width * 2, left.height), (0, 0, 0, 0))
        pair.alpha_composite(left, (0, 0))
        pair.alpha_composite(right, (left.width, 0))
        pairs.append(pair)
    pack_cleanup_spritesheet(pairs, out, columns=columns)


def _cleanup_report(
    source_kind: str,
    records: list[dict[str, str]],
    spritesheet: Path,
    preview_gif: Path | None,
    before_after: Path,
    metadata: Path,
) -> str:
    lines = [
        "# Sprite Cleanup Export",
        "",
        f"- Source kind: `{source_kind}`",
        f"- Frames: `{len(records)}`",
        f"- Spritesheet: `{spritesheet}`",
        f"- Before/after review: `{before_after}`",
        f"- Metadata: `{metadata}`",
    ]
    if preview_gif:
        lines.append(f"- Preview GIF: `{preview_gif}`")
    lines.extend(["", "## Frame Sources", ""])
    for record in records:
        lines.append(f"- `{record['frame']}` <- `{record['source']}`")
    lines.append("")
    return "\n".join(lines)
