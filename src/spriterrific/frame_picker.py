from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from .media import build_selected_contact_sheet, build_selected_preview_gif
from .review_index import ReviewAsset, write_review_index

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk

    from PIL import ImageTk


THUMBNAIL_CARD_SIZE = (132, 154)
THUMBNAIL_IMAGE_BOX = (112, 88)
THUMBNAIL_CELL_SIZE = (150, 172)

COLOR_OFF = (112, 112, 112, 255)
COLOR_SELECTED = (20, 94, 210, 255)
COLOR_START = (22, 145, 75, 255)
COLOR_END = (210, 54, 54, 255)
COLOR_CURRENT = (232, 178, 0, 255)
COLOR_TEXT = (245, 245, 245, 255)
COLOR_MUTED_TEXT = (34, 34, 34, 255)

_BG_LIGHT = (238, 238, 238, 255)
_BG_DARK = (22, 30, 42, 255)
_IMAGE_BG_LIGHT = (255, 255, 255, 255)
_IMAGE_BG_DARK = (12, 18, 26, 255)

_BORDER_WIDTH = 4
_INNER_BORDER_INSET = 5
_LABEL_ORIGIN = (8, 7)
_IMAGE_ORIGIN = (10, 22)
_BADGE_ROW_TOP = 116
_BADGE_ROW_BOTTOM = 136
_BADGE_LEFT = 8
_BADGE_RIGHT = 61

_PALETTE = {
    "bg": "#1a1f2b",
    "panel": "#222936",
    "panel_alt": "#2a3242",
    "border": "#374151",
    "text": "#e5e7eb",
    "text_muted": "#9ca3af",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "preview_bg": "#0f1218",
    "danger": "#dc2626",
}


@dataclass(frozen=True)
class PickerSelection:
    output: str
    source: str
    source_index: int


@dataclass(frozen=True)
class ThumbnailState:
    current: bool = False
    selected_order: int | None = None
    start: bool = False
    end: bool = False


def dense_frame_paths(run_dir: Path | None = None, frames_dir: Path | None = None) -> list[Path]:
    source = frames_dir or (run_dir / "extracted" / "dense-frames" if run_dir is not None else None)
    if source is None:
        raise ValueError("run_dir or frames_dir is required")
    frames = sorted(source.glob("frame-*.png"))
    if not frames:
        raise ValueError(f"no dense frames found in {source}")
    return frames


def evenly_spaced_indices(start: int, end: int, count: int) -> list[int]:
    if count < 2:
        raise ValueError("count must be at least 2")
    if start == end:
        raise ValueError("start and end frames must be different")
    span = abs(end - start) + 1
    if count > span:
        raise ValueError(f"cannot select {count} distinct frames from {span} frames")
    step = (end - start) / (count - 1)
    indices = [round(start + step * slot) for slot in range(count)]
    if len(set(indices)) != len(indices):
        raise ValueError("selection produced duplicate frames; choose a wider start/end range or fewer frames")
    return indices


def write_frame_picker_report(
    *,
    run_dir: Path | None,
    frames: list[Path],
    selected_indices: list[int],
    out_dir: Path,
    action: str | None = None,
    direction: str | None = None,
    reference: Path | None = None,
    video: Path | None = None,
    start_index: int | None = None,
    end_index: int | None = None,
) -> Path:
    if not selected_indices:
        raise ValueError("no selected frames")
    if len(set(selected_indices)) != len(selected_indices):
        raise ValueError("selected frames must be unique")
    for index in selected_indices:
        if index < 0 or index >= len(frames):
            raise ValueError(f"selected frame index out of range: {index}")

    out_dir.mkdir(parents=True, exist_ok=True)
    selected_dir = out_dir / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    for old in selected_dir.glob("frame-*.png"):
        old.unlink()

    records: list[PickerSelection] = []
    for output_index, source_index in enumerate(selected_indices, start=1):
        source = frames[source_index]
        output = selected_dir / f"frame-{output_index:02d}.png"
        shutil.copy2(source, output)
        records.append(PickerSelection(output=output.name, source=source.name, source_index=source_index))

    selected_order = ",".join(record.source for record in records)
    command = None
    if action and direction and reference and video:
        command_run_dir = out_dir.parent / f"{out_dir.name}-rerun"
        command = (
            "uv run spriterrific run "
            f"--action {shlex.quote(action)} --direction {shlex.quote(direction)} --mode video "
            f"--reference {shlex.quote(str(reference))} --existing-video {shlex.quote(str(video))} "
            f"--run-dir {shlex.quote(str(command_run_dir))} --selected-order {shlex.quote(selected_order)}"
        )

    payload = {
        "version": 1,
        "kind": "frame-picker-selection",
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runDir": str(run_dir) if run_dir else None,
        "framesDir": str(frames[0].parent),
        "denseFrameCount": len(frames),
        "startFrame": frames[start_index].name if start_index is not None else None,
        "endFrame": frames[end_index].name if end_index is not None else None,
        "selectedFrameCount": len(records),
        "selectedOrder": selected_order,
        "frames": [record.__dict__ for record in records],
        "artifacts": {
            "markdownReport": "report.md",
            "jsonReport": "report.json",
            "selectionJson": "selection.json",
            "selectedOrder": "selected-order.txt",
            "selectedDir": "selected",
            "selectedPreviewGif": "selected-preview.gif",
            "selectedContactSheet": "selected-contact.png",
            "reviewIndex": "review/index.md",
            "reviewPreviewGif": "review/selected-preview.gif",
            "reviewContactSheet": "review/selected-contact.png",
        },
        "command": command,
    }
    (out_dir / "selection.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (out_dir / "selected-order.txt").write_text(selected_order + "\n", encoding="utf-8")
    build_selected_contact_sheet(selected_dir, out_dir / "selected-contact.png")
    build_selected_preview_gif(selected_dir, out_dir / "selected-preview.gif")

    lines = [
        "# Frame Picker Selection",
        "",
        f"Dense frames: `{len(frames)}` from `{frames[0].parent}`.",
        f"Selected frames: `{len(records)}`.",
    ]
    if start_index is not None:
        lines.append(f"Start frame: `{frames[start_index].name}`.")
    if end_index is not None:
        lines.append(f"End frame: `{frames[end_index].name}`.")
    lines.extend(["", "## Selected Order", "", f"`{selected_order}`", ""])
    if command:
        lines.extend(["## Follow-On Command", "", "```bash", command, "```", ""])
    lines.extend(["## Frames", ""])
    for record in records:
        lines.extend(
            [
                f"### {record.output}",
                "",
                f"Source: `{record.source}`.",
                "",
                f"![{record.output}](selected/{record.output})",
                "",
            ]
        )
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    _write_picker_review_index(
        out_dir=out_dir,
        selected_dir=selected_dir,
        report_path=report_path,
        selected_count=len(records),
        selected_order=selected_order,
        start_frame=payload["startFrame"],
        end_frame=payload["endFrame"],
    )
    return report_path


def _write_picker_review_index(
    *,
    out_dir: Path,
    selected_dir: Path,
    report_path: Path,
    selected_count: int,
    selected_order: str,
    start_frame: object,
    end_frame: object,
) -> Path:
    review_dir = out_dir / "review"
    contact = review_dir / "selected-contact.png"
    preview = review_dir / "selected-preview.gif"
    build_selected_contact_sheet(selected_dir, contact)
    build_selected_preview_gif(selected_dir, preview)
    notes = [
        f"Selected `{selected_count}` dense video frames.",
        f"Start frame: `{start_frame or '-'}`.",
        f"Last frame: `{end_frame or '-'}`.",
        f"Selected order: `{selected_order}`.",
    ]
    return write_review_index(
        review_dir,
        title=f"{out_dir.name} Frame Picker Review",
        summary="Review page for a human-selected video frame sequence before VibeGameDev Sprite Tool post-processing.",
        notes=notes,
        assets=[
            ReviewAsset("Selected Contact Sheet", contact, "Selected dense video frames laid out for quick comparison.", embed=True),
            ReviewAsset("Selected Preview GIF", preview, "Selected dense video frames looped in order.", embed=True),
            ReviewAsset("Frame Picker Report", report_path, "Markdown report with selected frames and follow-on command.", embed=False),
            ReviewAsset("Selection JSON", out_dir / "selection.json", "Machine-readable selected frame metadata.", embed=False),
            ReviewAsset("Selected Order", out_dir / "selected-order.txt", "Comma-separated dense frame order for --selected-order.", embed=False),
        ],
    )


def default_picker_output_dir(run_dir: Path | None, frames_dir: Path | None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if run_dir is not None:
        return run_dir / "frame-picker" / stamp
    if frames_dir is not None:
        return frames_dir.parent / "frame-picker" / stamp
    return Path("frame-picker") / stamp


def render_frame_thumbnail(frame: Image.Image, label: str, state: ThumbnailState) -> Image.Image:
    card_w, card_h = THUMBNAIL_CARD_SIZE
    image_w, image_h = THUMBNAIL_IMAGE_BOX
    selected = state.selected_order is not None
    background = _BG_DARK if selected else _BG_LIGHT
    card = Image.new("RGBA", THUMBNAIL_CARD_SIZE, background)
    draw = ImageDraw.Draw(card)
    font = ImageFont.load_default()

    border = COLOR_SELECTED if selected else COLOR_OFF
    if state.start:
        border = COLOR_START
    if state.end:
        border = COLOR_END
    draw.rectangle((0, 0, card_w - 1, card_h - 1), outline=border, width=_BORDER_WIDTH)
    if state.current:
        draw.rectangle(
            (
                _INNER_BORDER_INSET,
                _INNER_BORDER_INSET,
                card_w - _INNER_BORDER_INSET - 1,
                card_h - _INNER_BORDER_INSET - 1,
            ),
            outline=COLOR_CURRENT,
            width=_BORDER_WIDTH,
        )

    image_bg = _IMAGE_BG_DARK if selected else _IMAGE_BG_LIGHT
    image_x, image_y = _IMAGE_ORIGIN
    draw.rectangle((image_x, image_y, image_x + image_w, image_y + image_h), fill=image_bg)

    thumb = frame.convert("RGBA").copy()
    thumb.thumbnail(THUMBNAIL_IMAGE_BOX, Image.Resampling.NEAREST)
    thumb_x = (card_w - thumb.width) // 2
    thumb_y = image_y + 2 + (image_h - thumb.height) // 2
    card.alpha_composite(thumb, (thumb_x, thumb_y))

    text_fill = COLOR_TEXT if selected else COLOR_MUTED_TEXT
    draw.text(_LABEL_ORIGIN, label, fill=text_fill, font=font)

    if selected:
        _badge(draw, (_BADGE_LEFT, _BADGE_ROW_TOP), f"SEL {state.selected_order}", COLOR_SELECTED, font)
    else:
        _badge(draw, (_BADGE_LEFT, _BADGE_ROW_TOP), "OFF", COLOR_OFF, font)
    if state.start:
        _badge(draw, (_BADGE_RIGHT, _BADGE_ROW_TOP), "START", COLOR_START, font)
    if state.end:
        _badge(draw, (_BADGE_RIGHT, _BADGE_ROW_BOTTOM), "END", COLOR_END, font)
    if state.current:
        _badge(draw, (_BADGE_LEFT, _BADGE_ROW_BOTTOM), "VIEW", COLOR_CURRENT, font, text_color=(20, 20, 20, 255))
    return card


def _badge(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    label: str,
    fill: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    *,
    text_color: tuple[int, int, int, int] = COLOR_TEXT,
) -> None:
    x, y = xy
    bbox = draw.textbbox((x, y), label, font=font)
    width = bbox[2] - bbox[0] + 8
    height = bbox[3] - bbox[1] + 6
    draw.rectangle((x, y, x + width, y + height), fill=fill)
    draw.text((x + 4, y + 3), label, fill=text_color, font=font)


def _short_frame_label(path: Path) -> str:
    stem = path.stem
    if stem.startswith("frame-"):
        return stem.replace("frame-", "f", 1)
    return stem


def thumbnail_columns_for_width(width: int) -> int:
    return max(1, max(1, width - 16) // THUMBNAIL_CELL_SIZE[0])


def _scroll_units(delta: int) -> int:
    if delta == 0:
        return 0
    return max(1, min(8, abs(delta) // 40)) * (1 if delta > 0 else -1)


def next_play_index(*, current: int, total: int, selected: list[int], play_selected: bool) -> int:
    if play_selected and selected:
        try:
            pos = selected.index(current)
        except ValueError:
            return selected[0]
        return selected[(pos + 1) % len(selected)]
    return (current + 1) % total


def _rgb_hex(rgba: tuple[int, int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgba[:3])


def _apply_dark_theme(root: "tk.Tk") -> "ttk.Style":
    from tkinter import ttk

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    p = _PALETTE
    root.configure(bg=p["bg"])
    style.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["panel"])
    style.configure("TFrame", background=p["bg"])
    style.configure("Panel.TFrame", background=p["panel"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"])
    style.configure("Heading.TLabel", background=p["bg"], foreground=p["text_muted"], font=("TkDefaultFont", 9, "bold"))
    style.configure("Status.TLabel", background=p["panel"], foreground=p["text"], padding=(10, 6))
    style.configure(
        "TButton",
        background=p["panel_alt"],
        foreground=p["text"],
        borderwidth=0,
        focusthickness=0,
        padding=(10, 5),
    )
    style.map(
        "TButton",
        background=[("active", p["border"]), ("pressed", p["border"])],
        foreground=[("disabled", p["text_muted"])],
    )
    style.configure(
        "Accent.TButton",
        background=p["accent"],
        foreground="#ffffff",
        padding=(12, 6),
    )
    style.map("Accent.TButton", background=[("active", p["accent_hover"]), ("pressed", p["accent_hover"])])
    style.configure("TSpinbox", fieldbackground=p["panel_alt"], foreground=p["text"], arrowsize=12)
    style.configure(
        "Horizontal.TScale",
        background=p["bg"],
        troughcolor=p["panel_alt"],
        bordercolor=p["panel_alt"],
    )
    style.configure(
        "TSeparator",
        background=p["border"],
    )
    style.configure(
        "TCheckbutton",
        background=p["bg"],
        foreground=p["text"],
        focuscolor=p["bg"],
        indicatorbackground=p["panel_alt"],
        indicatorforeground=p["accent"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", p["bg"])],
        foreground=[("disabled", p["text_muted"])],
    )
    return style


class _MouseWheelMixin:
    def _bind_mousewheel(self, widget: "tk.Widget | None") -> None:
        if widget is None:
            return
        bindings = {
            "<MouseWheel>": self._on_mousewheel,
            "<Shift-MouseWheel>": self._on_shift_mousewheel,
            "<Button-4>": lambda _e: self._scroll_vertical(120),
            "<Button-5>": lambda _e: self._scroll_vertical(-120),
            "<Shift-Button-4>": lambda _e: self._scroll_horizontal(120),
            "<Shift-Button-5>": lambda _e: self._scroll_horizontal(-120),
        }
        for sequence, handler in bindings.items():
            widget.bind(sequence, handler, add="+")

    def _on_mousewheel(self, event: "tk.Event") -> str:
        if event.state & 0x0001:
            return self._scroll_horizontal(event.delta)
        return self._scroll_vertical(event.delta)

    def _on_shift_mousewheel(self, event: "tk.Event") -> str:
        return self._scroll_horizontal(event.delta)

    def _scroll_vertical(self, delta: int) -> str:
        canvas = getattr(self, "thumbnail_canvas", None)
        if canvas is not None:
            canvas.yview_scroll(-_scroll_units(delta), "units")
        return "break"

    def _scroll_horizontal(self, delta: int) -> str:
        canvas = getattr(self, "thumbnail_canvas", None)
        if canvas is not None:
            canvas.xview_scroll(-_scroll_units(delta), "units")
        return "break"


class FramePickerApp(_MouseWheelMixin):
    def __init__(
        self,
        root: "tk.Tk",
        *,
        frames: list[Path],
        run_dir: Path | None,
        video: Path | None,
        out_dir: Path,
        action: str | None,
        direction: str | None,
        reference: Path | None,
        frame_count: int,
    ) -> None:
        import tkinter as tk

        self.root = root
        self.frames = frames
        self.run_dir = run_dir
        self.video = video
        self.out_dir = out_dir
        self.action = action
        self.direction = direction
        self.reference = reference

        self.current = 0
        self.start_index: int | None = None
        self.end_index: int | None = None
        self.selected: list[int] = []
        self.playing = False
        self.delay_ms = 100

        self.preview_image: "ImageTk.PhotoImage | None" = None
        self.thumbnail_sources: list[Image.Image] = []
        self.thumb_photos: list["ImageTk.PhotoImage"] = []
        self.frame_buttons: list["tk.Button"] = []
        self.thumbnail_canvas: "tk.Canvas | None" = None
        self.thumbnail_window: int | None = None
        self.thumbnail_columns = 0
        self._setting_scrub = False

        self.count_var = tk.IntVar(value=frame_count)
        self.status_var = tk.StringVar()
        self.counter_var = tk.StringVar()
        self.play_selected_var = tk.BooleanVar(value=False)

        self._style = _apply_dark_theme(root)
        root.title("VibeGameDev Sprite Tool — Frame Picker")
        root.geometry("1180x880")
        root.bind("<space>", self._on_space)
        root.bind("<Left>", lambda _event: self._show_frame(max(0, self.current - 1)))
        root.bind("<Right>", lambda _event: self._show_frame(min(len(self.frames) - 1, self.current + 1)))

        self._build_ui()
        self._load_thumbnails()
        self._show_frame(0)
        self._refresh_status()

    def _build_ui(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        root = self.root
        p = _PALETTE

        header = ttk.Frame(root, padding=(14, 12, 14, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, text="FRAME PICKER", style="Heading.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.counter_var, style="TLabel").pack(side=tk.LEFT, padx=(12, 0))
        if self.video:
            ttk.Label(header, text=str(self.video), style="Muted.TLabel").pack(side=tk.LEFT, padx=(16, 0))
        legend = ttk.Frame(header)
        legend.pack(side=tk.RIGHT)
        for label, color in (
            ("selected", COLOR_SELECTED),
            ("start", COLOR_START),
            ("end", COLOR_END),
            ("viewing", COLOR_CURRENT),
        ):
            chip = tk.Frame(legend, bg=_rgb_hex(color), width=12, height=12, highlightthickness=0)
            chip.pack(side=tk.LEFT, padx=(8, 4))
            ttk.Label(legend, text=label, style="Muted.TLabel").pack(side=tk.LEFT)

        preview_wrap = tk.Frame(root, bg=p["preview_bg"], height=440)
        preview_wrap.pack(fill=tk.X, padx=14)
        preview_wrap.pack_propagate(False)
        self.preview = tk.Label(preview_wrap, bg=p["preview_bg"], borderwidth=0)
        self.preview.pack(expand=True)

        controls = ttk.Frame(root, padding=(14, 10, 14, 6))
        controls.pack(fill=tk.X)

        playback = ttk.Frame(controls)
        playback.pack(side=tk.LEFT)
        self.play_button = ttk.Button(playback, text="Play", command=self._toggle_play)
        self.play_button.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(playback, text="Prev", command=lambda: self._show_frame(max(0, self.current - 1))).pack(side=tk.LEFT, padx=2)
        ttk.Button(playback, text="Next", command=lambda: self._show_frame(min(len(self.frames) - 1, self.current + 1))).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(
            playback,
            text="Selected only",
            variable=self.play_selected_var,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Separator(controls, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        select_group = ttk.Frame(controls)
        select_group.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(select_group, text="Select", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        self.scrub = ttk.Scale(
            select_group,
            from_=1,
            to=len(self.frames),
            orient=tk.HORIZONTAL,
            command=self._scrub,
            length=380,
            takefocus=False,
        )
        self.scrub.pack(side=tk.LEFT, pady=4)
        self.scrub.bind("<ButtonRelease-1>", self._on_scrub_release, add="+")

        ttk.Separator(controls, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        edit_group = ttk.Frame(controls)
        edit_group.pack(side=tk.LEFT)
        ttk.Button(edit_group, text="Select/Deselect", command=self._toggle_current).pack(side=tk.LEFT, padx=2)
        ttk.Button(edit_group, text="Clear", command=self._clear).pack(side=tk.LEFT, padx=2)

        ttk.Separator(controls, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        range_group = ttk.Frame(controls)
        range_group.pack(side=tk.LEFT)
        ttk.Label(range_group, text="Range", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(range_group, text="N", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(range_group, from_=2, to=24, textvariable=self.count_var, width=4).pack(side=tk.LEFT)
        ttk.Button(range_group, text="Start", command=self._set_start).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Button(range_group, text="End", command=self._set_end).pack(side=tk.LEFT, padx=2)
        ttk.Button(range_group, text="Distribute", command=self._select_evenly).pack(side=tk.LEFT, padx=(8, 2))

        ttk.Button(controls, text="Save Report", style="Accent.TButton", command=self._save_report).pack(side=tk.RIGHT)

        ttk.Label(root, textvariable=self.status_var, style="Status.TLabel", anchor="w").pack(fill=tk.X, padx=14, pady=(4, 8))

        thumbs = ttk.Frame(root, padding=(14, 0, 14, 14))
        thumbs.pack(fill=tk.BOTH, expand=True)
        self.thumbnail_canvas = tk.Canvas(thumbs, bg=p["bg"], highlightthickness=0)
        xscroll = ttk.Scrollbar(thumbs, orient=tk.HORIZONTAL, command=self.thumbnail_canvas.xview)
        yscroll = ttk.Scrollbar(thumbs, orient=tk.VERTICAL, command=self.thumbnail_canvas.yview)
        self.grid = tk.Frame(self.thumbnail_canvas, bg=p["bg"])
        self.grid.bind("<Configure>", lambda _e: self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox("all")))
        self.thumbnail_window = self.thumbnail_canvas.create_window((0, 0), window=self.grid, anchor="nw")
        self.thumbnail_canvas.bind("<Configure>", self._on_thumbnail_canvas_configure)
        self.thumbnail_canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.thumbnail_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self._bind_mousewheel(self.thumbnail_canvas)
        self._bind_mousewheel(self.grid)

    def _load_thumbnails(self) -> None:
        import tkinter as tk

        from PIL import ImageTk

        for index, path in enumerate(self.frames):
            image = Image.open(path).convert("RGBA")
            photo = ImageTk.PhotoImage(render_frame_thumbnail(image, _short_frame_label(path), ThumbnailState()))
            self.thumbnail_sources.append(image)
            self.thumb_photos.append(photo)
            button = tk.Button(
                self.grid,
                image=photo,
                width=THUMBNAIL_CELL_SIZE[0] - 10,
                height=THUMBNAIL_CELL_SIZE[1] - 10,
                bg=_PALETTE["bg"],
                activebackground=_PALETTE["panel_alt"],
                borderwidth=0,
                highlightthickness=0,
                command=partial(self._on_thumbnail_click, index),
            )
            button.bind("<Shift-Button-1>", partial(self._on_shift_click, index))
            button.bind("<Button-3>", partial(self._on_right_click, index))
            self._bind_mousewheel(button)
            self.frame_buttons.append(button)
        self._layout_thumbnail_grid()

    def _on_space(self, _event: object) -> str:
        self._toggle_current()
        return "break"

    def _on_thumbnail_click(self, index: int) -> None:
        self._show_frame(index)
        self._toggle_index(index)

    def _on_shift_click(self, index: int, _event: object) -> str:
        start = self.current
        self._show_frame(index)
        low, high = sorted((start, index))
        for frame_index in range(low, high + 1):
            if frame_index not in self.selected:
                self.selected.append(frame_index)
        self.selected.sort()
        self._refresh_status()
        self._refresh_buttons()
        return "break"

    def _on_right_click(self, index: int, _event: object) -> None:
        self._toggle_index(index)

    def _on_thumbnail_canvas_configure(self, event: "tk.Event") -> None:
        if self.thumbnail_canvas is not None and self.thumbnail_window is not None:
            self.thumbnail_canvas.itemconfigure(self.thumbnail_window, width=event.width)
        self._layout_thumbnail_grid(event.width)

    def _layout_thumbnail_grid(self, width: int | None = None) -> None:
        if not self.frame_buttons:
            return
        canvas_width = width
        if canvas_width is None and self.thumbnail_canvas is not None:
            canvas_width = self.thumbnail_canvas.winfo_width()
        columns = thumbnail_columns_for_width(canvas_width or 1)
        if columns == self.thumbnail_columns:
            return
        self.thumbnail_columns = columns
        for index, button in enumerate(self.frame_buttons):
            button.grid(row=index // columns, column=index % columns, padx=3, pady=3, sticky="nsew")
        for column in range(columns):
            self.grid.columnconfigure(column, weight=1)
        canvas = self.thumbnail_canvas
        if canvas is not None:
            canvas.after_idle(lambda: canvas.configure(scrollregion=canvas.bbox("all")))

    def _show_frame(self, index: int, *, update_scrub: bool = True) -> None:
        from PIL import ImageTk

        self.current = index
        image = Image.open(self.frames[index]).convert("RGBA")
        image.thumbnail((720, 420), Image.Resampling.NEAREST)
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview.configure(image=self.preview_image)
        if update_scrub:
            self._setting_scrub = True
            try:
                self.scrub.set(index + 1)
            finally:
                self._setting_scrub = False
        self._refresh_status()
        self._refresh_buttons()

    def _scrub(self, value: str) -> None:
        if self._setting_scrub:
            return
        index = int(float(value)) - 1
        if index != self.current:
            self._show_frame(index, update_scrub=False)

    def _on_scrub_release(self, _event: object) -> None:
        self.root.focus_set()

    def _toggle_play(self) -> None:
        self.playing = not self.playing
        self.play_button.configure(text="Pause" if self.playing else "Play")
        if self.playing:
            self._play_next()

    def _play_next(self) -> None:
        if not self.playing:
            return
        self._show_frame(self._next_play_index())
        self.root.after(self.delay_ms, self._play_next)

    def _next_play_index(self) -> int:
        return next_play_index(
            current=self.current,
            total=len(self.frames),
            selected=self.selected,
            play_selected=self.play_selected_var.get(),
        )

    def _set_start(self) -> None:
        self.start_index = self.current
        self._refresh_status()
        self._refresh_buttons()

    def _set_end(self) -> None:
        self.end_index = self.current
        self._refresh_status()
        self._refresh_buttons()

    def _select_evenly(self) -> None:
        from tkinter import messagebox

        if self.start_index is None or self.end_index is None:
            messagebox.showerror("Missing range", "Set both a start and end frame first.")
            return
        try:
            self.selected = evenly_spaced_indices(self.start_index, self.end_index, int(self.count_var.get()))
        except ValueError as exc:
            messagebox.showerror("Selection failed", str(exc))
            return
        self._refresh_status()
        self._refresh_buttons()

    def _toggle_current(self) -> None:
        self._toggle_index(self.current)

    def _toggle_index(self, index: int) -> None:
        if index in self.selected:
            self.selected.remove(index)
        else:
            self.selected.append(index)
            self.selected.sort()
        self._refresh_status()
        self._refresh_buttons()

    def _clear(self) -> None:
        self.start_index = None
        self.end_index = None
        self.selected = []
        self._refresh_status()
        self._refresh_buttons()

    def _save_report(self) -> None:
        from tkinter import messagebox

        if not self.selected:
            messagebox.showerror("No frames selected", "Select frames before saving.")
            return
        report = write_frame_picker_report(
            run_dir=self.run_dir,
            frames=self.frames,
            selected_indices=self.selected,
            out_dir=self.out_dir,
            action=self.action,
            direction=self.direction,
            reference=self.reference,
            video=self.video,
            start_index=self.start_index,
            end_index=self.end_index,
        )
        messagebox.showinfo("Saved", f"Wrote {report}")

    def _refresh_status(self) -> None:
        total = len(self.frames)
        self.counter_var.set(f"{self.current + 1} / {total}")
        start = self.frames[self.start_index].name if self.start_index is not None else "-"
        end = self.frames[self.end_index].name if self.end_index is not None else "-"
        if self.selected:
            picked = ", ".join(self.frames[i].name for i in self.selected)
            selected_summary = f"{len(self.selected)} selected: {picked}"
        else:
            selected_summary = "0 selected"
        self.status_var.set(
            f"current {self.frames[self.current].name}    │    start {start}    │    end {end}    │    {selected_summary}"
        )

    def _refresh_buttons(self) -> None:
        from PIL import ImageTk

        selected_order = {frame_index: order for order, frame_index in enumerate(self.selected, start=1)}
        for index, button in enumerate(self.frame_buttons):
            state = ThumbnailState(
                current=index == self.current,
                selected_order=selected_order.get(index),
                start=index == self.start_index,
                end=index == self.end_index,
            )
            photo = ImageTk.PhotoImage(
                render_frame_thumbnail(self.thumbnail_sources[index], _short_frame_label(self.frames[index]), state)
            )
            self.thumb_photos[index] = photo
            button.configure(image=photo)


def launch_frame_picker(
    *,
    run_dir: Path | None = None,
    frames_dir: Path | None = None,
    video: Path | None = None,
    out_dir: Path | None = None,
    action: str | None = None,
    direction: str | None = None,
    reference: Path | None = None,
    frame_count: int = 6,
) -> None:
    import tkinter as tk

    frames = dense_frame_paths(run_dir=run_dir, frames_dir=frames_dir)
    resolved_video = video or (run_dir / "fal" / "raw-video.mp4" if run_dir is not None else None)
    resolved_out = out_dir or default_picker_output_dir(run_dir, frames[0].parent)

    root = tk.Tk()
    from .app_icon import apply_app_icon

    apply_app_icon(root)
    FramePickerApp(
        root,
        frames=frames,
        run_dir=run_dir,
        video=resolved_video,
        out_dir=resolved_out,
        action=action,
        direction=direction,
        reference=reference,
        frame_count=frame_count,
    )
    root.mainloop()
