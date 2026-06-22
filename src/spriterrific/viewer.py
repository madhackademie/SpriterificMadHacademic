"""Spriterrific run viewer: browse runs, preview exports, launch frame tools.

A read-mostly Tkinter GUI over the canonical run-folder contract. The left
pane lists projects and their discovered runs (raw CLI and SDK animation
groups); the right pane previews the spritesheet, animated GIF, frame strips,
and metadata. Edit actions delegate to the existing frame-picker,
frame-aligner, and sprite-cleanup tools in separate processes so the viewer
never re-implements pipeline semantics.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from .discovery import (
    KIND_ANIMATION_GROUP,
    KIND_ANIMATION_RUN,
    KIND_BOOTSTRAP_RUN,
    RunArtifacts,
    RunEntry,
    discover_runs,
    export_branch_label,
    find_project_root,
    list_export_dirs,
    resolve_artifacts,
)

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk

    from PIL import ImageTk

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
}

_STATE_DIR = Path.home() / ".config" / "spriterrific"
_STATE_FILE = _STATE_DIR / "viewer.json"
_MAX_RECENTS = 10
_DEFAULT_PREVIEW_FPS = 10
_MAX_ZOOM = 8


def load_viewer_state() -> dict:
    """Load persisted viewer state (recent projects), tolerating corruption."""
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_viewer_state(state: dict) -> None:
    """Persist viewer state to the user config directory, best effort."""
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def remember_project(project_dir: Path) -> list[str]:
    """Add ``project_dir`` to the persisted recents list and return it."""
    state = load_viewer_state()
    recents = [str(item) for item in state.get("recentProjects", []) if isinstance(item, str)]
    entry = str(project_dir.resolve())
    recents = [entry] + [item for item in recents if item != entry]
    recents = recents[:_MAX_RECENTS]
    state["recentProjects"] = recents
    save_viewer_state(state)
    return recents


def open_in_system(path: Path) -> None:
    """Open a file or folder with the platform default application."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_in_file_browser(path: Path) -> None:
    """Reveal ``path`` in Finder/Explorer, selecting files where supported."""
    if path.is_dir():
        open_in_system(path)
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        open_in_system(path.parent)


def spawn_tool(arguments: list[str]) -> None:
    """Launch a spriterrific CLI tool in a separate process.

    Separate processes keep the tools' own Tk mainloops isolated from the
    viewer's.
    """
    subprocess.Popen([sys.executable, "-m", "spriterrific", *arguments])


def _entry_status_text(entry: RunEntry) -> str:
    """Human-readable status column text for a run entry."""
    if entry.kind == KIND_ANIMATION_GROUP:
        return f"{len(entry.children)} actions"
    if entry.kind == KIND_BOOTSTRAP_RUN:
        return entry.character or "anchors"
    parts = [part for part in (entry.action, entry.direction, entry.status) if part]
    return " ".join(parts)


class ViewerApp:
    """Main viewer window: project selector, run tree, and preview tabs."""

    def __init__(self, root: "tk.Tk", *, project_dir: Path, focus_run: Path | None = None) -> None:
        """Build the UI, scan ``project_dir``, and optionally focus one run."""
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.project_dir = project_dir
        self.entries_by_id: dict[str, RunEntry] = {}
        self.selected_entry: RunEntry | None = None
        self.artifacts: RunArtifacts | None = None
        self._photo_refs: list["ImageTk.PhotoImage"] = []
        self._gif_frames: list["ImageTk.PhotoImage"] = []
        self._gif_job: str | None = None
        self._gif_index = 0
        self._gif_delay_ms = 1000 // _DEFAULT_PREVIEW_FPS
        self._sheet_zoom = 1
        self._sheet_image: Image.Image | None = None
        self._video_paths: list[Path] = []
        self._video_photos: dict[int, "ImageTk.PhotoImage"] = {}
        self._video_index = 0
        self._video_job: str | None = None
        self._video_playing = False
        self._export_dirs: list[Path] = []

        root.title("Spriterrific Viewer")
        root.geometry("1280x800")
        self._apply_theme()
        self._build_layout()
        self.refresh_runs()
        if focus_run is not None:
            self._focus_run(focus_run)

    def _apply_theme(self) -> None:
        """Apply the shared dark palette to ttk widgets."""
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        p = _PALETTE
        self.root.configure(bg=p["bg"])
        style.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["panel"])
        style.configure("TFrame", background=p["bg"])
        style.configure("TLabel", background=p["bg"], foreground=p["text"])
        style.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"])
        style.configure("TButton", background=p["panel_alt"], foreground=p["text"], borderwidth=0, padding=(10, 5))
        style.map("TButton", background=[("active", p["border"]), ("pressed", p["border"])])
        style.configure("Accent.TButton", background=p["accent"], foreground="#ffffff", padding=(12, 6))
        style.map("Accent.TButton", background=[("active", p["accent_hover"]), ("pressed", p["accent_hover"])])
        style.configure("Treeview", background=p["panel"], fieldbackground=p["panel"], foreground=p["text"], borderwidth=0)
        style.map("Treeview", background=[("selected", p["accent"])], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=p["panel_alt"], foreground=p["text"], borderwidth=0)
        style.configure("TNotebook", background=p["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=p["panel"], foreground=p["text"], padding=(14, 7))
        style.map("TNotebook.Tab", background=[("selected", p["panel_alt"])])

    def _build_layout(self) -> None:
        """Create the top bar, run tree, preview notebook, and action bar."""
        tk, ttk = self.tk, self.ttk

        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Button(top, text="Open Project…", command=self._choose_project).pack(side="left")
        ttk.Button(top, text="Rescan", command=self.refresh_runs).pack(side="left", padx=(8, 0))
        self.project_label = ttk.Label(top, text=str(self.project_dir), style="Muted.TLabel")
        self.project_label.pack(side="left", padx=(12, 0))

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self.tree = ttk.Treeview(body, columns=("info",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Run")
        self.tree.heading("info", text="Info")
        self.tree.column("#0", width=380, stretch=False)
        self.tree.column("info", width=180, stretch=False)
        self.tree.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._on_select())

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        branch_bar = ttk.Frame(right)
        branch_bar.pack(fill="x", pady=(0, 6))
        ttk.Label(branch_bar, text="Export:", style="Muted.TLabel").pack(side="left")
        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(branch_bar, textvariable=self.branch_var, state="disabled", width=56)
        self.branch_combo.pack(side="left", padx=(8, 8))
        self.branch_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_branch_change())
        ttk.Button(branch_bar, text="Reveal Export", command=self._reveal_export).pack(side="left")

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        self.sheet_tab = self._make_canvas_tab("Spritesheet", toolbar_buttons=(("Reveal File", self._reveal_sheet),))
        self.preview_tab = self._make_canvas_tab("Preview", toolbar_buttons=(("Reveal File", self._reveal_preview),))
        self._build_video_tab()
        self.frames_tab = self._make_canvas_tab(
            "Frames",
            toolbar_buttons=(
                ("Open Frame Picker", self._launch_picker),
                ("Reveal Folder", self._reveal_frames_dir),
            ),
        )
        self.info_text = tk.Text(
            self.notebook,
            bg=_PALETTE["preview_bg"],
            fg=_PALETTE["text"],
            insertbackground=_PALETTE["text"],
            borderwidth=0,
            wrap="none",
        )
        self.notebook.add(self.info_text, text="Info")

        actions = ttk.Frame(self.root)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        self.action_buttons: dict[str, "ttk.Button"] = {}
        for key, label, command in (
            ("picker", "Frame Picker", self._launch_picker),
            ("aligner", "Frame Aligner", self._launch_aligner),
            ("cleanup", "Sprite Cleanup", self._launch_cleanup),
            ("video", "Open Video", self._open_video),
            ("review", "Open Review", self._open_review),
            ("folder", "Open Folder", self._open_folder),
        ):
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side="left", padx=(0, 8))
            self.action_buttons[key] = button
        zoom_box = ttk.Frame(actions)
        zoom_box.pack(side="right")
        ttk.Button(zoom_box, text="−", width=3, command=lambda: self._set_zoom(self._sheet_zoom - 1)).pack(side="left")
        self.zoom_label = ttk.Label(zoom_box, text="1x", style="Muted.TLabel")
        self.zoom_label.pack(side="left", padx=6)
        ttk.Button(zoom_box, text="+", width=3, command=lambda: self._set_zoom(self._sheet_zoom + 1)).pack(side="left")

        self.status = tk.StringVar(value="Select a run to preview its artifacts.")
        ttk.Label(self.root, textvariable=self.status, style="Muted.TLabel").pack(fill="x", padx=12, pady=(0, 8))

    def _make_canvas_tab(self, title: str, *, toolbar_buttons: tuple[tuple[str, object], ...] = ()) -> "tk.Canvas":
        """Add one scrollable canvas tab, with optional toolbar buttons."""
        tk, ttk = self.tk, self.ttk
        holder = ttk.Frame(self.notebook)
        if toolbar_buttons:
            toolbar = ttk.Frame(holder)
            toolbar.pack(fill="x", pady=(4, 4))
            for label, command in toolbar_buttons:
                ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=(4, 8))
        body = ttk.Frame(holder)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, bg=_PALETTE["preview_bg"], highlightthickness=0)
        vbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        hbar = ttk.Scrollbar(body, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side="right", fill="y")
        hbar.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True)
        self.notebook.add(holder, text=title)
        return canvas

    def _build_video_tab(self) -> None:
        """Build the Video tab: dense-frame player with transport controls."""
        tk, ttk = self.tk, self.ttk
        holder = ttk.Frame(self.notebook)

        toolbar = ttk.Frame(holder)
        toolbar.pack(fill="x", pady=(4, 4))
        self.video_play_button = ttk.Button(toolbar, text="Play", command=self._toggle_video_play)
        self.video_play_button.pack(side="left", padx=(4, 8))
        ttk.Label(toolbar, text="fps", style="Muted.TLabel").pack(side="left")
        self.video_fps_var = tk.IntVar(value=15)
        ttk.Spinbox(toolbar, from_=1, to=60, width=4, textvariable=self.video_fps_var).pack(side="left", padx=(4, 12))
        self.video_scale_var = tk.IntVar(value=0)
        self.video_scale = ttk.Scale(toolbar, from_=0, to=0, orient="horizontal", command=self._on_video_scrub)
        self.video_scale.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.video_pos_label = ttk.Label(toolbar, text="0/0", style="Muted.TLabel")
        self.video_pos_label.pack(side="left", padx=(0, 12))
        ttk.Button(toolbar, text="Open Frame Picker", command=self._launch_picker).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Open MP4", command=self._open_video).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="Reveal MP4", command=self._reveal_video).pack(side="left")

        self.video_canvas = tk.Canvas(holder, bg=_PALETTE["preview_bg"], highlightthickness=0)
        self.video_canvas.pack(fill="both", expand=True)
        self.notebook.add(holder, text="Video")

    # ------------------------------------------------------------------ scanning

    def refresh_runs(self) -> None:
        """Rescan the project's run roots and rebuild the run tree."""
        self.tree.delete(*self.tree.get_children())
        self.entries_by_id.clear()
        total = 0
        for root, entries in discover_runs(self.project_dir):
            try:
                root_label = str(root.relative_to(self.project_dir))
            except ValueError:
                root_label = str(root)
            root_id = self.tree.insert("", "end", text=root_label, values=(f"{len(entries)} runs",), open=True)
            for entry in entries:
                self._insert_entry(root_id, entry)
                total += 1
        self.project_label.configure(text=str(self.project_dir))
        self.status.set(f"Found {total} runs in {self.project_dir}")

    def _insert_entry(self, parent_id: str, entry: RunEntry) -> None:
        """Insert one run entry (and any group children) into the tree."""
        node_id = self.tree.insert(parent_id, "end", text=entry.label, values=(_entry_status_text(entry),))
        self.entries_by_id[node_id] = entry
        for child in entry.children:
            self._insert_entry(node_id, child)

    def _choose_project(self) -> None:
        """Prompt for a project folder and rescan it."""
        from tkinter import filedialog

        chosen = filedialog.askdirectory(initialdir=str(self.project_dir), title="Choose a project folder")
        if not chosen:
            return
        self.project_dir = find_project_root(Path(chosen))
        remember_project(self.project_dir)
        self.refresh_runs()

    def _focus_run(self, run_dir: Path) -> None:
        """Select the tree node matching ``run_dir`` when present."""
        target = run_dir.resolve()
        for node_id, entry in self.entries_by_id.items():
            if entry.path.resolve() == target:
                self.tree.selection_set(node_id)
                self.tree.see(node_id)
                return

    # ------------------------------------------------------------------ selection

    def _on_select(self) -> None:
        """Load artifacts and refresh all preview tabs for the selection."""
        selection = self.tree.selection()
        self._stop_gif()
        self._stop_video()
        self.selected_entry = self.entries_by_id.get(selection[0]) if selection else None
        if self.selected_entry is None:
            self.artifacts = None
            return
        entry = self.selected_entry
        self._populate_branches(entry)
        export_dir = self._export_dirs[0] if self._export_dirs else None
        self.artifacts = resolve_artifacts(entry.path, export_dir) if entry.kind != KIND_ANIMATION_GROUP else None
        self._render_video_tab()
        self._render_branch_views()
        self.status.set(str(entry.path))

    def _populate_branches(self, entry: RunEntry) -> None:
        """Fill the export-branch dropdown for the selected run."""
        self._export_dirs = list_export_dirs(entry.path) if entry.kind == KIND_ANIMATION_RUN else []
        labels = [export_branch_label(entry.path, export_dir) for export_dir in self._export_dirs]
        self.branch_combo.configure(values=labels)
        if labels:
            self.branch_combo.configure(state="readonly")
            self.branch_combo.current(0)
        else:
            self.branch_var.set("")
            self.branch_combo.configure(state="disabled")

    def _on_branch_change(self) -> None:
        """Re-resolve artifacts against the chosen export branch."""
        if self.selected_entry is None or not self._export_dirs:
            return
        index = self.branch_combo.current()
        if index < 0 or index >= len(self._export_dirs):
            return
        self._stop_gif()
        self.artifacts = resolve_artifacts(self.selected_entry.path, self._export_dirs[index])
        self._render_branch_views()
        self.status.set(f"{self.selected_entry.path}  [{self.branch_var.get()}]")

    def _render_branch_views(self) -> None:
        """Refresh every view that depends on the selected export branch."""
        self._render_sheet_tab()
        self._render_preview_tab()
        self._render_frames_tab()
        self._render_info_tab()
        self._update_action_states()

    def _update_action_states(self) -> None:
        """Enable or disable action buttons based on available artifacts."""
        entry, artifacts = self.selected_entry, self.artifacts
        is_run = entry is not None and entry.kind == KIND_ANIMATION_RUN

        def set_state(key: str, enabled: bool) -> None:
            """Toggle one action button between normal and disabled."""
            self.action_buttons[key].state(["!disabled"] if enabled else ["disabled"])

        set_state("picker", is_run and artifacts is not None and artifacts.dense_frames_dir is not None)
        set_state("aligner", is_run and artifacts is not None and artifacts.runtime_frames_dir is not None)
        set_state("cleanup", is_run and artifacts is not None and artifacts.runtime_frames_dir is not None)
        set_state("video", artifacts is not None and artifacts.raw_video is not None)
        set_state("review", artifacts is not None and artifacts.review_index is not None)
        set_state("folder", entry is not None)

    # ------------------------------------------------------------------ rendering

    def _render_sheet_tab(self) -> None:
        """Render the spritesheet (or bootstrap anchor) at the current zoom."""
        canvas = self.sheet_tab
        canvas.delete("all")
        self._sheet_image = None
        source: Path | None = None
        if self.artifacts is not None and self.artifacts.spritesheet is not None:
            source = self.artifacts.spritesheet
        elif self.selected_entry is not None and self.selected_entry.kind == KIND_BOOTSTRAP_RUN:
            source = self._bootstrap_preview_image(self.selected_entry.path)
        if source is None:
            self._canvas_message(canvas, "No spritesheet found for this selection.")
            return
        try:
            self._sheet_image = Image.open(source).convert("RGBA")
        except OSError:
            self._canvas_message(canvas, f"Could not read {source.name}.")
            return
        self._draw_zoomed_sheet()

    def _draw_zoomed_sheet(self) -> None:
        """Draw the cached sheet image at the current integer zoom."""
        from PIL import ImageTk

        canvas = self.sheet_tab
        canvas.delete("all")
        if self._sheet_image is None:
            return
        image = self._sheet_image
        if self._sheet_zoom > 1:
            image = image.resize((image.width * self._sheet_zoom, image.height * self._sheet_zoom), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(image)
        self._photo_refs = [photo]
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, image.width, image.height))
        self.zoom_label.configure(text=f"{self._sheet_zoom}x")

    def _set_zoom(self, zoom: int) -> None:
        """Clamp and apply a new spritesheet zoom level."""
        self._sheet_zoom = max(1, min(_MAX_ZOOM, zoom))
        self._draw_zoomed_sheet()

    def _render_preview_tab(self) -> None:
        """Start animated GIF playback for the selected run, if available."""
        canvas = self.preview_tab
        canvas.delete("all")
        if self.artifacts is None or self.artifacts.preview_gif is None:
            self._canvas_message(canvas, "No preview GIF found for this selection.")
            return
        from PIL import ImageSequence, ImageTk

        try:
            gif = Image.open(self.artifacts.preview_gif)
            frames = [ImageTk.PhotoImage(frame.convert("RGBA")) for frame in ImageSequence.Iterator(gif)]
        except OSError:
            self._canvas_message(canvas, "Could not read preview GIF.")
            return
        if not frames:
            self._canvas_message(canvas, "Preview GIF has no frames.")
            return
        self._gif_frames = frames
        self._gif_index = 0
        self._gif_delay_ms = max(20, 1000 // self._manifest_fps())
        canvas.configure(scrollregion=(0, 0, frames[0].width(), frames[0].height()))
        self._advance_gif()

    def _manifest_fps(self) -> int:
        """Read fps from the resolved export manifest, with a safe default."""
        if self.artifacts is not None and self.artifacts.manifest is not None:
            try:
                manifest = json.loads(self.artifacts.manifest.read_text(encoding="utf-8"))
                fps = int(manifest.get("fps", _DEFAULT_PREVIEW_FPS))
                if fps > 0:
                    return fps
            except (OSError, ValueError, TypeError):
                pass
        return _DEFAULT_PREVIEW_FPS

    def _advance_gif(self) -> None:
        """Draw the next GIF frame and schedule the following one."""
        if not self._gif_frames:
            return
        canvas = self.preview_tab
        canvas.delete("all")
        canvas.create_image(0, 0, image=self._gif_frames[self._gif_index], anchor="nw")
        self._gif_index = (self._gif_index + 1) % len(self._gif_frames)
        self._gif_job = self.root.after(self._gif_delay_ms, self._advance_gif)

    def _stop_gif(self) -> None:
        """Cancel pending GIF playback callbacks."""
        if self._gif_job is not None:
            self.root.after_cancel(self._gif_job)
            self._gif_job = None
        self._gif_frames = []

    # ------------------------------------------------------------------ video tab

    def _render_video_tab(self) -> None:
        """Load the run's dense video frames into the player."""
        self._video_paths = []
        self._video_photos = {}
        self._video_index = 0
        self.video_canvas.delete("all")
        if self.artifacts is None or self.artifacts.dense_frames_dir is None:
            self.video_scale.configure(to=0)
            self.video_pos_label.configure(text="0/0")
            self._canvas_message(self.video_canvas, "No dense video frames found for this selection.")
            return
        self._video_paths = sorted(self.artifacts.dense_frames_dir.glob("frame-*.png"))
        if not self._video_paths:
            self.video_scale.configure(to=0)
            self.video_pos_label.configure(text="0/0")
            self._canvas_message(self.video_canvas, "No dense video frames found for this selection.")
            return
        self.video_fps_var.set(self._video_fps_default())
        self.video_scale.configure(to=len(self._video_paths) - 1)
        self._show_video_frame(0)

    def _video_fps_default(self) -> int:
        """Pick a sensible playback fps from run metadata."""
        if self.selected_entry is not None:
            run_json = self.selected_entry.path / "run.json"
            try:
                payload = json.loads(run_json.read_text(encoding="utf-8"))
                fps = payload.get("videoFramesPerSecond")
                if isinstance(fps, (int, float)) and fps > 0:
                    return int(fps)
            except (OSError, ValueError):
                pass
        return 15

    def _video_photo(self, index: int) -> "ImageTk.PhotoImage | None":
        """Decode and cache one dense frame, downscaled for display."""
        from PIL import ImageTk

        cached = self._video_photos.get(index)
        if cached is not None:
            return cached
        try:
            image = Image.open(self._video_paths[index]).convert("RGBA")
        except OSError:
            return None
        image.thumbnail((720, 720), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self._video_photos[index] = photo
        return photo

    def _show_video_frame(self, index: int) -> None:
        """Display dense frame ``index`` and update transport readouts."""
        if not self._video_paths:
            return
        self._video_index = index % len(self._video_paths)
        photo = self._video_photo(self._video_index)
        self.video_canvas.delete("all")
        if photo is not None:
            self.video_canvas.create_image(8, 8, image=photo, anchor="nw")
        self.video_scale.set(self._video_index)
        self.video_pos_label.configure(text=f"{self._video_index + 1}/{len(self._video_paths)}")

    def _on_video_scrub(self, value: str) -> None:
        """Jump playback to the scrubbed slider position."""
        if not self._video_paths:
            return
        index = int(float(value))
        if index != self._video_index:
            self._show_video_frame(index)

    def _toggle_video_play(self) -> None:
        """Start or pause dense-frame playback."""
        if self._video_playing:
            self._stop_video()
            return
        if not self._video_paths:
            return
        self._video_playing = True
        self.video_play_button.configure(text="Pause")
        self._advance_video()

    def _advance_video(self) -> None:
        """Show the next dense frame and schedule the following tick."""
        if not self._video_playing or not self._video_paths:
            return
        self._show_video_frame(self._video_index + 1)
        fps = max(1, min(60, int(self.video_fps_var.get() or 15)))
        self._video_job = self.root.after(1000 // fps, self._advance_video)

    def _stop_video(self) -> None:
        """Pause playback and cancel any scheduled video tick."""
        self._video_playing = False
        if self._video_job is not None:
            self.root.after_cancel(self._video_job)
            self._video_job = None
        if hasattr(self, "video_play_button"):
            self.video_play_button.configure(text="Play")

    def _render_frames_tab(self) -> None:
        """Render a contact strip of runtime (or dense) frames."""
        from PIL import ImageTk

        canvas = self.frames_tab
        canvas.delete("all")
        frames_dir = None
        if self.artifacts is not None:
            frames_dir = self.artifacts.runtime_frames_dir or self.artifacts.dense_frames_dir
        if frames_dir is None:
            self._canvas_message(canvas, "No frame folders found for this selection.")
            return
        paths = sorted(frames_dir.glob("frame-*.png"))[:60]
        if not paths:
            self._canvas_message(canvas, f"No frames in {frames_dir.name}.")
            return
        thumb_size = 160
        columns = 5
        x = y = 8
        photos: list["ImageTk.PhotoImage"] = []
        for index, path in enumerate(paths):
            try:
                image = Image.open(path).convert("RGBA")
            except OSError:
                continue
            image.thumbnail((thumb_size, thumb_size), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(image)
            photos.append(photo)
            col, row = index % columns, index // columns
            x = 8 + col * (thumb_size + 12)
            y = 8 + row * (thumb_size + 28)
            canvas.create_image(x, y, image=photo, anchor="nw")
            canvas.create_text(x, y + thumb_size + 4, text=path.name, anchor="nw", fill=_PALETTE["text_muted"])
        self._photo_refs.extend(photos)
        rows = (len(paths) + columns - 1) // columns
        canvas.configure(scrollregion=(0, 0, 8 + columns * (thumb_size + 12), 8 + rows * (thumb_size + 28)))

    def _render_info_tab(self) -> None:
        """Show run metadata and resolved artifact paths as text."""
        self.info_text.delete("1.0", "end")
        if self.selected_entry is None:
            return
        entry = self.selected_entry
        lines = [f"path: {entry.path}", f"kind: {entry.kind}", ""]
        for name in ("run.json", "bootstrap.json", "animation-plan.json"):
            payload = entry.path / name
            if payload.is_file():
                try:
                    parsed = json.loads(payload.read_text(encoding="utf-8"))
                    lines += [f"== {name} ==", json.dumps(parsed, indent=2), ""]
                except (OSError, ValueError):
                    lines += [f"== {name} == (unreadable)", ""]
        if self.artifacts is not None:
            lines.append("== resolved artifacts ==")
            for field_name in ("export_dir", "manifest", "spritesheet", "preview_gif", "raw_video", "dense_frames_dir", "runtime_frames_dir", "review_index"):
                lines.append(f"{field_name}: {getattr(self.artifacts, field_name)}")
        self.info_text.insert("1.0", "\n".join(lines))

    def _canvas_message(self, canvas: "tk.Canvas", message: str) -> None:
        """Show a muted placeholder message in an empty canvas tab."""
        canvas.create_text(16, 16, text=message, anchor="nw", fill=_PALETTE["text_muted"])

    # ------------------------------------------------------------------ actions

    def _launch_picker(self) -> None:
        """Open the frame picker on the selected run's dense frames."""
        if self.selected_entry is None:
            return
        spawn_tool(["frame-picker", "--run-dir", str(self.selected_entry.path)])
        self.status.set(f"Launched frame-picker for {self.selected_entry.label}")

    def _launch_aligner(self) -> None:
        """Open the frame aligner on the selected run's runtime frames."""
        if self.artifacts is None or self.artifacts.runtime_frames_dir is None:
            return
        spawn_tool(["frame-aligner", "--input-dir", str(self.artifacts.runtime_frames_dir), "--fps", str(self._manifest_fps())])
        self.status.set(f"Launched frame-aligner on {self.artifacts.runtime_frames_dir}")

    def _launch_cleanup(self) -> None:
        """Open sprite cleanup on the selected run's runtime frames."""
        if self.artifacts is None or self.artifacts.runtime_frames_dir is None:
            return
        spawn_tool(["sprite-cleanup", "--input-dir", str(self.artifacts.runtime_frames_dir), "--fps", str(self._manifest_fps())])
        self.status.set(f"Launched sprite-cleanup on {self.artifacts.runtime_frames_dir}")

    def _open_video(self) -> None:
        """Open the raw generation video in the system player."""
        if self.artifacts is not None and self.artifacts.raw_video is not None:
            open_in_system(self.artifacts.raw_video)

    def _open_review(self) -> None:
        """Open the run's review index in the system default app."""
        if self.artifacts is not None and self.artifacts.review_index is not None:
            open_in_system(self.artifacts.review_index)

    def _open_folder(self) -> None:
        """Reveal the selected run folder in the system file browser."""
        if self.selected_entry is not None:
            open_in_system(self.selected_entry.path)

    def _reveal_export(self) -> None:
        """Reveal the selected export branch folder."""
        if self.artifacts is not None and self.artifacts.export_dir is not None:
            reveal_in_file_browser(self.artifacts.export_dir)

    def _reveal_sheet(self) -> None:
        """Reveal the spritesheet file in the system file browser."""
        if self.artifacts is not None and self.artifacts.spritesheet is not None:
            reveal_in_file_browser(self.artifacts.spritesheet)

    def _reveal_preview(self) -> None:
        """Reveal the preview GIF file in the system file browser."""
        if self.artifacts is not None and self.artifacts.preview_gif is not None:
            reveal_in_file_browser(self.artifacts.preview_gif)

    def _reveal_video(self) -> None:
        """Reveal the raw MP4 in the system file browser."""
        if self.artifacts is not None and self.artifacts.raw_video is not None:
            reveal_in_file_browser(self.artifacts.raw_video)

    def _reveal_frames_dir(self) -> None:
        """Reveal the runtime (or dense) frames folder."""
        if self.artifacts is None:
            return
        target = self.artifacts.runtime_frames_dir or self.artifacts.dense_frames_dir
        if target is not None:
            reveal_in_file_browser(target)

    def _bootstrap_preview_image(self, run_dir: Path) -> Path | None:
        """Pick a representative anchor image for a bootstrap run."""
        candidates = [
            *sorted(run_dir.glob("anchors/*/anchor-snapped-1024-chroma.png")),
            *sorted(run_dir.glob("anchors/*/anchor-1024-chroma.png")),
            run_dir / "candidate" / "front" / "snapped-1024-chroma.png",
            run_dir / "candidate" / "front" / "anchor-1024-chroma.png",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None


def launch_viewer(*, project_dir: Path | None = None, run_dir: Path | None = None) -> None:
    """Open the Spriterrific viewer window.

    ``project_dir`` defaults to the project resolved from the current working
    directory (or from ``run_dir`` when given). ``run_dir`` preselects one run.
    """
    try:
        import tkinter as tk
    except ImportError as exc:
        raise SystemExit(
            "spriterrific viewer needs tkinter, which is missing from this Python. "
            "Install it (for example `brew install python-tk` on macOS or `apt install python3-tk` on Debian/Ubuntu) and retry."
        ) from exc

    start = run_dir if run_dir is not None else (project_dir or Path.cwd())
    resolved_project = project_dir or find_project_root(start)
    remember_project(resolved_project)

    root = tk.Tk()
    from .app_icon import apply_app_icon

    apply_app_icon(root)
    ViewerApp(root, project_dir=resolved_project, focus_run=run_dir)
    root.mainloop()
