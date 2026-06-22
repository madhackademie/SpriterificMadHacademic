from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from .review_index import ReviewAsset, write_review_index

if TYPE_CHECKING:
    import tkinter as tk

    from PIL import ImageTk


GUIDE_COLOR_X = (65, 145, 255, 255)
GUIDE_COLOR_Y = (255, 205, 60, 255)
BASELINE_COLOR = (70, 220, 120, 255)
GRID_BG = (22, 26, 34, 255)
PANEL_BG = "#1a1f2b"
TEXT_COLOR = "#e5e7eb"
ACCENT = "#3b82f6"
GHOST_COLORS = (
    (255, 80, 80, 255),
    (80, 180, 255, 255),
    (80, 235, 135, 255),
    (255, 210, 70, 255),
    (195, 120, 255, 255),
    (255, 130, 210, 255),
    (70, 230, 230, 255),
    (255, 145, 70, 255),
    (160, 220, 90, 255),
    (170, 185, 255, 255),
)


@dataclass(frozen=True)
class FrameOffset:
    dx: int = 0
    dy: int = 0


@dataclass(frozen=True)
class AlignmentExport:
    out_dir: Path
    frames_dir: Path
    spritesheet: Path
    before_preview_gif: Path
    preview_gif: Path
    before_after_preview_gif: Path
    report: Path
    metadata: Path
    review_index: Path


def runtime_frame_paths(input_dir: Path, *, glob: str = "frame-*.png") -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")
    return frames


def apply_frame_offset(image: Image.Image, offset: FrameOffset) -> Image.Image:
    src = image.convert("RGBA")
    width, height = src.size
    dx, dy = offset.dx, offset.dy

    src_left = max(0, -dx)
    src_top = max(0, -dy)
    src_right = min(width, width - dx)
    src_bottom = min(height, height - dy)
    out = Image.new("RGBA", src.size, (0, 0, 0, 0))
    if src_right <= src_left or src_bottom <= src_top:
        return out

    crop = src.crop((src_left, src_top, src_right, src_bottom))
    out.alpha_composite(crop, (max(0, dx), max(0, dy)))
    return out


def pack_aligned_spritesheet(frame_paths: list[Path], out: Path, *, columns: int) -> Path:
    if not frame_paths:
        raise ValueError("cannot pack an empty frame list")
    if columns <= 0:
        raise ValueError("columns must be positive")

    frames = [Image.open(path).convert("RGBA") for path in frame_paths]
    cell_size = frames[0].size
    for path, frame in zip(frame_paths, frames):
        if frame.size != cell_size:
            raise ValueError(f"{path} must be {cell_size[0]}x{cell_size[1]}, got {frame.size[0]}x{frame.size[1]}")

    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGBA", (columns * cell_size[0], rows * cell_size[1]), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        col = index % columns
        row = index // columns
        sheet.alpha_composite(frame, (col * cell_size[0], row * cell_size[1]))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def write_alignment_export(
    *,
    input_dir: Path,
    out_dir: Path,
    offsets: dict[str, FrameOffset],
    glob: str = "frame-*.png",
    columns: int = 5,
    fps: int = 10,
) -> AlignmentExport:
    source_frames = runtime_frame_paths(input_dir, glob=glob)
    first = Image.open(source_frames[0]).convert("RGBA")
    cell_w, cell_h = first.size

    frames_dir = out_dir / f"frames-{cell_w}x{cell_h}"
    review_dir = out_dir / "review"
    frames_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame-*.png"):
        old.unlink()

    records = []
    output_frames = []
    source_images = []
    output_images = []
    for index, source in enumerate(source_frames, start=1):
        offset = offsets.get(source.name, FrameOffset())
        image = Image.open(source).convert("RGBA")
        if image.size != (cell_w, cell_h):
            raise ValueError(f"{source} must be {cell_w}x{cell_h}, got {image.size[0]}x{image.size[1]}")
        source_images.append(image.copy())
        aligned = apply_frame_offset(image, offset)
        output_images.append(aligned.copy())
        output = frames_dir / f"frame-{index:02d}.png"
        aligned.save(output)
        output_frames.append(output)
        records.append(
            {
                "frame": output.name,
                "source": str(source),
                "dx": offset.dx,
                "dy": offset.dy,
            }
        )

    spritesheet = out_dir / f"spritesheet-{cell_w}x{cell_h}-{columns}x{math.ceil(len(output_frames) / columns)}.png"
    pack_aligned_spritesheet(output_frames, spritesheet, columns=columns)
    before_preview_gif = review_dir / f"before-preview-{len(output_frames)}f-{cell_w}x{cell_h}.gif"
    _save_gif(source_images, before_preview_gif, fps=fps)
    preview_gif = review_dir / f"preview-{len(output_frames)}f-{cell_w}x{cell_h}.gif"
    _save_gif(output_images, preview_gif, fps=fps)
    before_after_preview_gif = review_dir / f"before-after-preview-{len(output_frames)}f-{cell_w}x{cell_h}.gif"
    _save_gif(_before_after_frames(source_images, output_images), before_after_preview_gif, fps=fps)
    guide_contact = review_dir / f"guided-contact-{cell_w}x{cell_h}.png"
    _save_guided_contact(output_frames, guide_contact, columns=columns)

    metadata = out_dir / "alignment.json"
    metadata.write_text(
        json.dumps(
            {
                "version": 1,
                "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                "inputDir": str(input_dir),
                "cellSize": [cell_w, cell_h],
                "columns": columns,
                "fps": fps,
                "frames": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    report = out_dir / "report.md"
    report.write_text(
        _alignment_report(records, spritesheet, before_preview_gif, preview_gif, before_after_preview_gif, metadata),
        encoding="utf-8",
    )
    review_index = write_review_index(
        review_dir,
        title=f"{out_dir.name} Runtime Frame Alignment Review",
        summary="Review page for manually nudged runtime frames and the rebuilt spritesheet.",
        notes=[
            f"Input frame directory: `{input_dir}`.",
            f"Cell size: `{cell_w}x{cell_h}`.",
            f"Frames: `{len(output_frames)}`. Columns: `{columns}`. FPS: `{fps}`.",
            "Offsets are pixel shifts applied to already-normalized runtime frames without re-normalizing.",
        ],
        assets=[
            ReviewAsset("Guided Contact Sheet", guide_contact, "Aligned frames with center and horizontal guide lines.", True),
            ReviewAsset("Before Preview GIF", before_preview_gif, "Original runtime frames before manual alignment.", True),
            ReviewAsset("After Preview GIF", preview_gif, "Aligned runtime frames looped in order.", True),
            ReviewAsset("Before/After Preview GIF", before_after_preview_gif, "Original and aligned frames side by side.", True),
            ReviewAsset("Runtime Spritesheet", spritesheet, "Updated transparent spritesheet built from manually aligned frames.", True),
            ReviewAsset("Alignment Report", report, "Human-readable offset report.", False),
            ReviewAsset("Alignment JSON", metadata, "Machine-readable offsets and source frame mapping.", False),
        ],
    )

    return AlignmentExport(
        out_dir=out_dir,
        frames_dir=frames_dir,
        spritesheet=spritesheet,
        before_preview_gif=before_preview_gif,
        preview_gif=preview_gif,
        before_after_preview_gif=before_after_preview_gif,
        report=report,
        metadata=metadata,
        review_index=review_index,
    )


def default_aligner_output_dir(input_dir: Path) -> Path:
    return input_dir.parent / "frame-aligner" / datetime.now().strftime("%Y%m%d-%H%M%S")


def tint_alpha_mask(image: Image.Image, *, color: tuple[int, int, int, int], opacity: float) -> Image.Image:
    src = image.convert("RGBA")
    alpha = src.getchannel("A").point(lambda value: round(value * opacity))
    tinted = Image.new("RGBA", src.size, color)
    tinted.putalpha(alpha)
    return tinted


def render_guided_frame(
    image: Image.Image,
    *,
    offset: FrameOffset = FrameOffset(),
    scale: int = 3,
    ghost_layers: list[tuple[Image.Image, FrameOffset, tuple[int, int, int, int]]] | None = None,
    ghost_opacity: float = 0.35,
) -> Image.Image:
    aligned = apply_frame_offset(image, offset)
    width, height = aligned.size
    preview = Image.new("RGBA", (width, height), GRID_BG)
    for ghost_image, ghost_offset, ghost_color in ghost_layers or []:
        ghost = apply_frame_offset(ghost_image, ghost_offset)
        preview.alpha_composite(tint_alpha_mask(ghost, color=ghost_color, opacity=ghost_opacity))
    preview.alpha_composite(aligned)
    draw = ImageDraw.Draw(preview)
    cx = width // 2
    cy = height // 2
    draw.line((cx, 0, cx, height), fill=GUIDE_COLOR_X, width=1)
    draw.line((0, cy, width, cy), fill=GUIDE_COLOR_Y, width=1)
    draw.line((0, height - 1, width, height - 1), fill=BASELINE_COLOR, width=1)
    if scale > 1:
        preview = preview.resize((width * scale, height * scale), Image.Resampling.NEAREST)
    return preview


def launch_frame_aligner(
    *,
    input_dir: Path,
    out_dir: Path | None = None,
    glob: str = "frame-*.png",
    columns: int = 5,
    fps: int = 10,
    zoom: int = 3,
) -> None:
    import tkinter as tk
    from tkinter import messagebox

    from PIL import ImageTk

    frames = runtime_frame_paths(input_dir, glob=glob)
    images = [Image.open(path).convert("RGBA") for path in frames]
    cell_size = images[0].size
    for path, image in zip(frames, images):
        if image.size != cell_size:
            raise ValueError(f"{path} must be {cell_size[0]}x{cell_size[1]}, got {image.size[0]}x{image.size[1]}")

    resolved_out = out_dir or default_aligner_output_dir(input_dir)

    class RuntimeFrameAligner:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("VibeGameDev Sprite Tool Runtime Frame Aligner")
            self.current = 0
            self.offsets: dict[str, FrameOffset] = {path.name: FrameOffset() for path in frames}
            self.preview_image: ImageTk.PhotoImage | None = None
            self.status = tk.StringVar()
            self.zoom = max(1, zoom)
            self.ghost_enabled = tk.BooleanVar(value=True)
            self.ghost_opacity = tk.DoubleVar(value=0.35)
            self.ghost_vars: list[tk.BooleanVar] = []
            self.frame_buttons: list[tk.Button] = []
            self.frame_scale: tk.Scale | None = None
            self._setting_frame_scale = False
            self._build_ui()
            self._show_frame(0)
            self.root.bind("<Left>", lambda _event: self._nudge(-1, 0))
            self.root.bind("<Right>", lambda _event: self._nudge(1, 0))
            self.root.bind("<Up>", lambda _event: self._nudge(0, -1))
            self.root.bind("<Down>", lambda _event: self._nudge(0, 1))
            self.root.bind("<Shift-Left>", lambda _event: self._nudge(-5, 0))
            self.root.bind("<Shift-Right>", lambda _event: self._nudge(5, 0))
            self.root.bind("<Shift-Up>", lambda _event: self._nudge(0, -5))
            self.root.bind("<Shift-Down>", lambda _event: self._nudge(0, 5))

        def _build_ui(self) -> None:
            self.root.configure(bg=PANEL_BG)
            header = tk.Frame(self.root, bg=PANEL_BG)
            header.pack(fill=tk.X, padx=10, pady=8)
            tk.Label(header, text=f"{len(frames)} frames  {cell_size[0]}x{cell_size[1]}", bg=PANEL_BG, fg=TEXT_COLOR).pack(
                side=tk.LEFT
            )
            tk.Label(
                header,
                text="Blue vertical center, yellow horizontal center, green baseline",
                bg=PANEL_BG,
                fg=TEXT_COLOR,
            ).pack(side=tk.RIGHT)

            main = tk.Frame(self.root, bg=PANEL_BG)
            main.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

            preview_panel = tk.Frame(main, bg=PANEL_BG)
            preview_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.preview = tk.Label(preview_panel, bg="#0f1218")
            self.preview.pack(padx=6, pady=6)

            selector_panel = tk.Frame(main, bg=PANEL_BG)
            selector_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

            strip = tk.LabelFrame(selector_panel, text="View frame", bg=PANEL_BG, fg=TEXT_COLOR)
            strip.pack(fill=tk.X, pady=(0, 8))
            for index, path in enumerate(frames):
                color = self._hex_color(GHOST_COLORS[index % len(GHOST_COLORS)])
                button = tk.Button(
                    strip,
                    text=path.stem.replace("frame-", ""),
                    command=partial(self._show_frame, index),
                    width=5,
                    bg=color,
                    activebackground=color,
                )
                button.pack(fill=tk.X, padx=4, pady=2)
                self.frame_buttons.append(button)

            selector = tk.LabelFrame(selector_panel, text="Ghost frame layers", bg=PANEL_BG, fg=TEXT_COLOR)
            selector.pack(fill=tk.X, pady=(0, 8))
            for index, path in enumerate(frames):
                var = tk.BooleanVar(value=False)
                self.ghost_vars.append(var)
                color = self._hex_color(GHOST_COLORS[index % len(GHOST_COLORS)])
                tk.Checkbutton(
                    selector,
                    text=path.stem.replace("frame-", ""),
                    variable=var,
                    command=lambda: self._show_frame(self.current),
                    bg=PANEL_BG,
                    fg=color,
                    selectcolor="#111827",
                    activebackground=PANEL_BG,
                    activeforeground=color,
                    anchor="w",
                ).pack(fill=tk.X, padx=4, pady=2)

            controls = tk.Frame(self.root, bg=PANEL_BG)
            controls.pack(fill=tk.X, padx=10, pady=6)
            tk.Button(controls, text="Prev", command=lambda: self._show_frame(max(0, self.current - 1))).pack(side=tk.LEFT)
            tk.Button(controls, text="Next", command=lambda: self._show_frame(min(len(frames) - 1, self.current + 1))).pack(side=tk.LEFT)
            tk.Label(controls, text="Select", bg=PANEL_BG, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=(14, 4))
            self.frame_scale = tk.Scale(
                controls,
                from_=1,
                to=len(frames),
                orient=tk.HORIZONTAL,
                command=self._select_frame,
                length=240,
                showvalue=False,
                takefocus=False,
                bg=PANEL_BG,
                fg=TEXT_COLOR,
                troughcolor="#111827",
                highlightthickness=0,
            )
            self.frame_scale.pack(side=tk.LEFT, padx=(0, 12))
            self.frame_scale.bind("<ButtonRelease-1>", self._on_frame_scale_release, add="+")
            tk.Button(controls, text="Left", command=lambda: self._nudge(-1, 0)).pack(side=tk.LEFT, padx=(12, 2))
            tk.Button(controls, text="Right", command=lambda: self._nudge(1, 0)).pack(side=tk.LEFT, padx=2)
            tk.Button(controls, text="Up", command=lambda: self._nudge(0, -1)).pack(side=tk.LEFT, padx=2)
            tk.Button(controls, text="Down", command=lambda: self._nudge(0, 1)).pack(side=tk.LEFT, padx=2)
            tk.Button(controls, text="Reset Frame", command=self._reset_frame).pack(side=tk.LEFT, padx=(12, 2))
            tk.Button(controls, text="Reset All", command=self._reset_all).pack(side=tk.LEFT, padx=2)
            tk.Button(controls, text="Export", command=self._export).pack(side=tk.RIGHT)

            ghost_controls = tk.Frame(self.root, bg=PANEL_BG)
            ghost_controls.pack(fill=tk.X, padx=10, pady=4)
            tk.Checkbutton(
                ghost_controls,
                text="Ghost selected",
                variable=self.ghost_enabled,
                command=lambda: self._show_frame(self.current),
                bg=PANEL_BG,
                fg=TEXT_COLOR,
                selectcolor="#111827",
                activebackground=PANEL_BG,
                activeforeground=TEXT_COLOR,
            ).pack(side=tk.LEFT)
            tk.Label(ghost_controls, text="Opacity", bg=PANEL_BG, fg=TEXT_COLOR).pack(side=tk.LEFT, padx=(12, 4))
            tk.Scale(
                ghost_controls,
                from_=0.05,
                to=0.85,
                resolution=0.05,
                orient=tk.HORIZONTAL,
                variable=self.ghost_opacity,
                command=lambda _value: self._show_frame(self.current),
                length=180,
                bg=PANEL_BG,
                fg=TEXT_COLOR,
                troughcolor="#111827",
                highlightthickness=0,
            ).pack(side=tk.LEFT)
            tk.Button(ghost_controls, text="Ghost All", command=self._ghost_all).pack(side=tk.LEFT, padx=(12, 2))
            tk.Button(ghost_controls, text="Ghost Neighbors", command=self._ghost_neighbors).pack(side=tk.LEFT, padx=2)
            tk.Button(ghost_controls, text="Clear Ghosts", command=self._clear_ghosts).pack(side=tk.LEFT, padx=2)

            tk.Label(self.root, textvariable=self.status, bg=PANEL_BG, fg=TEXT_COLOR, anchor="w").pack(fill=tk.X, padx=10, pady=8)

        def _show_frame(self, index: int, *, update_scale: bool = True) -> None:
            self.current = index
            if update_scale and self.frame_scale is not None:
                self._setting_frame_scale = True
                try:
                    self.frame_scale.set(index + 1)
                finally:
                    self._setting_frame_scale = False
            offset = self.offsets[frames[index].name]
            guided = render_guided_frame(
                images[index],
                offset=offset,
                scale=self.zoom,
                ghost_layers=self._ghost_layers(),
                ghost_opacity=float(self.ghost_opacity.get()),
            )
            self.preview_image = ImageTk.PhotoImage(guided)
            self.preview.configure(image=self.preview_image)
            self._refresh_frame_buttons()
            self._refresh_status()

        def _select_frame(self, value: str) -> None:
            if self._setting_frame_scale:
                return
            index = int(float(value)) - 1
            if index != self.current:
                self._show_frame(index, update_scale=False)

        def _on_frame_scale_release(self, _event: object) -> None:
            self.root.focus_set()

        def _nudge(self, dx: int, dy: int) -> None:
            name = frames[self.current].name
            current = self.offsets[name]
            self.offsets[name] = FrameOffset(current.dx + dx, current.dy + dy)
            self._show_frame(self.current)

        def _reset_frame(self) -> None:
            self.offsets[frames[self.current].name] = FrameOffset()
            self._show_frame(self.current)

        def _reset_all(self) -> None:
            self.offsets = {path.name: FrameOffset() for path in frames}
            self._show_frame(self.current)

        def _ghost_all(self) -> None:
            for var in self.ghost_vars:
                var.set(True)
            self._show_frame(self.current)

        def _ghost_neighbors(self) -> None:
            for index, var in enumerate(self.ghost_vars):
                var.set(abs(index - self.current) == 1)
            self._show_frame(self.current)

        def _clear_ghosts(self) -> None:
            for var in self.ghost_vars:
                var.set(False)
            self._show_frame(self.current)

        def _export(self) -> None:
            export = write_alignment_export(
                input_dir=input_dir,
                out_dir=resolved_out,
                offsets=self.offsets,
                glob=glob,
                columns=columns,
                fps=fps,
            )
            messagebox.showinfo("Exported", f"Wrote {export.report}")

        def _refresh_status(self) -> None:
            name = frames[self.current].name
            offset = self.offsets[name]
            selected = [
                f"{index + 1:02d}" for index, var in enumerate(self.ghost_vars) if var.get() and index != self.current
            ]
            ghost_text = ",".join(selected) if selected and self.ghost_enabled.get() else "-"
            self.status.set(
                f"{self.current + 1}/{len(frames)} {name}    dx={offset.dx:+d} dy={offset.dy:+d}    ghost={ghost_text}    arrows nudge 1px, shift+arrows nudge 5px"
            )

        def _ghost_layers(self) -> list[tuple[Image.Image, FrameOffset, tuple[int, int, int, int]]]:
            if not self.ghost_enabled.get():
                return []
            layers = []
            for index, var in enumerate(self.ghost_vars):
                if index == self.current or not var.get():
                    continue
                layers.append(
                    (images[index], self.offsets[frames[index].name], GHOST_COLORS[index % len(GHOST_COLORS)])
                )
            return layers

        def _refresh_frame_buttons(self) -> None:
            for index, button in enumerate(self.frame_buttons):
                button.configure(relief=tk.SUNKEN if index == self.current else tk.RAISED)

        @staticmethod
        def _hex_color(color: tuple[int, int, int, int]) -> str:
            return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"

    root = tk.Tk()
    from .app_icon import apply_app_icon

    apply_app_icon(root)
    RuntimeFrameAligner(root)
    root.mainloop()


def _save_gif(frames: list[Image.Image], out: Path, *, fps: int) -> None:
    if not frames:
        raise ValueError("cannot build GIF without frames")
    out.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = round(1000 / fps)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=duration_ms, loop=0, disposal=2)


def _before_after_frames(before: list[Image.Image], after: list[Image.Image]) -> list[Image.Image]:
    if len(before) != len(after):
        raise ValueError("before and after frame lists must have the same length")
    if not before:
        raise ValueError("cannot build before/after preview without frames")
    frames = []
    font = ImageFont.load_default()
    gap = 12
    title_h = 26
    for before_frame, after_frame in zip(before, after):
        left = before_frame.convert("RGBA")
        right = after_frame.convert("RGBA")
        if left.size != right.size:
            raise ValueError("before and after frames must have matching sizes")
        width, height = left.size
        canvas = Image.new("RGBA", (width * 2 + gap, height + title_h), GRID_BG)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, canvas.width, title_h), fill=(15, 18, 24, 255))
        draw.text((8, 8), "Before alignment", fill=(255, 255, 255, 235), font=font)
        draw.text((width + gap + 8, 8), "After manual alignment", fill=(255, 255, 255, 235), font=font)
        canvas.alpha_composite(left, (0, title_h))
        canvas.alpha_composite(right, (width + gap, title_h))
        frames.append(canvas)
    return frames


def _save_guided_contact(frame_paths: list[Path], out: Path, *, columns: int) -> None:
    guided = [render_guided_frame(Image.open(path).convert("RGBA"), scale=2) for path in frame_paths]
    cell_w, cell_h = guided[0].size
    rows = math.ceil(len(guided) / columns)
    sheet = Image.new("RGBA", (columns * cell_w, rows * cell_h), GRID_BG)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, image in enumerate(guided):
        col = index % columns
        row = index // columns
        x = col * cell_w
        y = row * cell_h
        sheet.alpha_composite(image, (x, y))
        draw.text((x + 6, y + 6), f"{index + 1:02d}", fill=(255, 255, 255, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


def _alignment_report(
    records: list[dict[str, object]],
    spritesheet: Path,
    before_preview_gif: Path,
    preview_gif: Path,
    before_after_preview_gif: Path,
    metadata: Path,
) -> str:
    lines = [
        "# Runtime Frame Alignment Report",
        "",
        f"Spritesheet: `{spritesheet}`",
        f"Before Preview GIF: `{before_preview_gif}`",
        f"After Preview GIF: `{preview_gif}`",
        f"Before/After Preview GIF: `{before_after_preview_gif}`",
        f"Metadata: `{metadata}`",
        "",
        "## Offsets",
        "",
    ]
    for record in records:
        lines.append(f"- `{record['frame']}` <- `{record['source']}`: dx `{record['dx']}`, dy `{record['dy']}`")
    return "\n".join(lines).rstrip() + "\n"
