from __future__ import annotations

import json
import subprocess
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PIL import Image, ImageDraw, ImageFont

from .anchor_wizard import AnchorWizardOptions, candidate_dir_for, default_candidate_anchor, existing_candidate_anchor, run_anchor_wizard
from .bootstrap_anchors import BootstrapAnchorsOptions, run_bootstrap_anchors
from .frame_picker import _PALETTE, _apply_dark_theme
from .runids import default_run_dir

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk

    from PIL import ImageTk


PREVIEW_SIZE = (256, 256)
SPINNER = "|/-\\"


def launch_anchor_wizard_gui(*, run_dir: Path | None = None) -> None:
    import tkinter as tk

    root = tk.Tk()
    from .app_icon import apply_app_icon

    apply_app_icon(root)
    AnchorWizardApp(root, run_dir=run_dir)
    root.mainloop()


class AnchorWizardApp:
    def __init__(self, root: "tk.Tk", *, run_dir: Path | None) -> None:
        import tkinter as tk

        self.root = root
        self.root.title("VibeGameDev Sprite Tool — Anchor Wizard")
        self.root.geometry("1280x860")
        self._style = _apply_dark_theme(root)

        default_run = run_dir or default_run_dir("anchor-wizard", ["character"])
        self.character_var = tk.StringVar(value="character")
        self.run_dir_var = tk.StringVar(value=str(default_run))
        self.input_mode_var = tk.StringVar(value="source-image")
        self.source_image_var = tk.StringVar()
        self.candidate_image_var = tk.StringVar()
        self.candidate_facing_var = tk.StringVar(value="front")
        self.accepted_candidate_var = tk.StringVar()
        self.anchors_dir_var = tk.StringVar()
        self.direction_vars = {
            "n": tk.BooleanVar(value=True),
            "s": tk.BooleanVar(value=True),
            "e": tk.BooleanVar(value=True),
            "w": tk.BooleanVar(value=True),
        }
        self.k_colors_var = tk.IntVar(value=256)
        self.chroma_var = tk.StringVar(value="#00FF00")
        self.dry_fal_var = tk.BooleanVar(value=False)
        self.show_advanced_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.busy = False
        self.preview_photos: list["ImageTk.PhotoImage"] = []
        self._last_status_text = ""
        self._last_preview_signature = ""
        self._poll_count = 0
        self.direction_checkbuttons: list[object] = []

        self._build_ui()
        self._refresh_previews()
        self._last_preview_signature = self._preview_signature()

    def _build_ui(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        root = self.root
        p = _PALETTE

        header = ttk.Frame(root, padding=(14, 12, 14, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, text="ANCHOR WIZARD", style="Heading.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            header,
            text="source -> front candidate -> optional N/S/E/W anchors",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(header, text="Refresh", command=self._refresh_previews).pack(side=tk.RIGHT)
        ttk.Button(header, text="Open Review", command=self._open_review).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(header, text="Open Folder", command=self._open_folder).pack(side=tk.RIGHT, padx=(0, 8))

        body = ttk.Frame(root, padding=(14, 0, 14, 8))
        body.pack(fill=tk.BOTH, expand=True)

        form_panel = ttk.Frame(body, style="Panel.TFrame")
        form_panel.pack(side=tk.LEFT, fill=tk.Y)
        form_panel.configure(width=430)
        form_panel.pack_propagate(False)

        self.form_canvas = tk.Canvas(form_panel, bg=p["panel"], highlightthickness=0)
        form_scroll = ttk.Scrollbar(form_panel, orient=tk.VERTICAL, command=self.form_canvas.yview)
        form = ttk.Frame(self.form_canvas, style="Panel.TFrame", padding=12)
        form_window = self.form_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _e: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind(
            "<Configure>",
            lambda event: self.form_canvas.itemconfigure(form_window, width=max(1, event.width)),
        )
        self.form_canvas.configure(yscrollcommand=form_scroll.set)
        self.form_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        form_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        _bind_canvas_mousewheel(self.form_canvas, form)

        preview_panel = ttk.Frame(body, padding=(14, 0, 0, 0))
        preview_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._entry_row(form, "Character", self.character_var)
        self._path_row(form, "Run Dir", self.run_dir_var, self._choose_run_dir)
        ttk.Separator(form).pack(fill=tk.X, pady=10)

        ttk.Label(form, text="Start From", style="Muted.TLabel").pack(anchor="w", pady=(2, 5))
        mode_row = ttk.Frame(form)
        mode_row.pack(fill=tk.X)
        ttk.Radiobutton(
            mode_row,
            text="Source Image",
            value="source-image",
            variable=self.input_mode_var,
            command=self._refresh_input_mode,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            mode_row,
            text="Text Prompt",
            value="text-prompt",
            variable=self.input_mode_var,
            command=self._refresh_input_mode,
        ).pack(side=tk.LEFT, padx=(14, 0))

        self.input_mode_content = ttk.Frame(form)
        self.input_mode_content.pack(fill=tk.X)
        self.source_image_section = ttk.Frame(self.input_mode_content)
        self._path_row(self.source_image_section, "Source Image", self.source_image_var, self._choose_source_image)

        self.prompt_section = ttk.Frame(self.input_mode_content)
        ttk.Label(self.prompt_section, text="Character Prompt", style="Muted.TLabel").pack(anchor="w", pady=(8, 3))
        self.prompt_text = tk.Text(
            self.prompt_section,
            height=7,
            wrap="word",
            bg=p["panel_alt"],
            fg=p["text"],
            insertbackground=p["text"],
            relief=tk.FLAT,
            padx=8,
            pady=6,
        )
        self.prompt_text.pack(fill=tk.X)
        ttk.Label(
            self.prompt_section,
            text="The tool will generate the source image, then the lower-fidelity front-facing candidate.",
            style="Muted.TLabel",
            wraplength=390,
        ).pack(anchor="w", pady=(5, 0))

        ttk.Label(form, text="Base Anchor", style="Muted.TLabel").pack(anchor="w", pady=(10, 3))
        ttk.Combobox(
            form,
            textvariable=self.candidate_facing_var,
            values=("front", "south"),
            state="readonly",
        ).pack(fill=tk.X)

        candidate_buttons = ttk.Frame(form)
        candidate_buttons.pack(fill=tk.X, pady=(10, 4))
        self.candidate_button = ttk.Button(candidate_buttons, text="Generate Reference", style="Accent.TButton", command=self._run_candidate)
        self.candidate_button.pack(side=tk.LEFT)

        ttk.Separator(form).pack(fill=tk.X, pady=10)
        ttk.Label(
            form,
            text="Direction Handoff",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 2))
        self.handoff_hint_var = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.handoff_hint_var, style="Muted.TLabel", wraplength=390).pack(anchor="w", pady=(0, 5))
        self.accepted_entry, self.accepted_browse_button = self._path_row(
            form,
            "Accepted 1024 Chroma Anchor",
            self.accepted_candidate_var,
            self._choose_accepted_candidate,
        )
        self.use_accepted_button = ttk.Button(form, text="Use Generated 1024 Chroma", command=self._use_default_candidate)
        self.use_accepted_button.pack(anchor="w", pady=(7, 0))
        ttk.Label(form, text="Directions", style="Muted.TLabel").pack(anchor="w", pady=(10, 3))
        directions_row = ttk.Frame(form)
        directions_row.pack(fill=tk.X)
        for direction, label in (("n", "N"), ("s", "S"), ("e", "E"), ("w", "W")):
            checkbox = ttk.Checkbutton(directions_row, text=label, variable=self.direction_vars[direction])
            checkbox.pack(side=tk.LEFT, padx=(0, 16))
            self.direction_checkbuttons.append(checkbox)

        direction_buttons = ttk.Frame(form)
        direction_buttons.pack(fill=tk.X, pady=(10, 4))
        self.run_directions_button = ttk.Button(direction_buttons, text="Generate Directions", style="Accent.TButton", command=self._run_directions)
        self.run_directions_button.pack(side=tk.LEFT)
        self.run_all_button = ttk.Button(direction_buttons, text="Run All", command=self._run_all)
        self.run_all_button.pack(side=tk.LEFT, padx=(8, 0))
        self.bootstrap_w_button = ttk.Button(direction_buttons, text="Bootstrap Front + W", command=self._run_bootstrap)
        self.bootstrap_w_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(form).pack(fill=tk.X, pady=10)
        ttk.Checkbutton(
            form,
            text="Show Advanced / Testing",
            variable=self.show_advanced_var,
            command=self._refresh_advanced,
        ).pack(anchor="w")
        self.advanced_section = ttk.Frame(form)
        advanced = ttk.Frame(self.advanced_section)
        self._path_row(
            self.advanced_section,
            "Existing Reference Image",
            self.candidate_image_var,
            self._choose_candidate_image,
        )
        ttk.Label(
            self.advanced_section,
            text="Dev/test override. Normal users should leave this blank.",
            style="Muted.TLabel",
            wraplength=390,
        ).pack(anchor="w", pady=(3, 8))
        self._path_row(self.advanced_section, "Generated Anchors Dir", self.anchors_dir_var, self._choose_anchors_dir)
        ttk.Label(
            self.advanced_section,
            text="Dev/test override for pre-generated N/S/E/W anchors.",
            style="Muted.TLabel",
            wraplength=390,
        ).pack(anchor="w", pady=(3, 8))
        ttk.Label(advanced, text="K colors", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(advanced, from_=8, to=512, increment=8, textvariable=self.k_colors_var, width=7).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(advanced, text="Chroma", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(advanced, textvariable=self.chroma_var, width=10).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Checkbutton(self.advanced_section, text="Dry fal", variable=self.dry_fal_var).pack(anchor="w", pady=(8, 0))
        advanced.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(root, textvariable=self.status_var, style="Status.TLabel", anchor="w").pack(fill=tk.X, padx=14, pady=(0, 12))

        ttk.Label(form, text="Run Status", style="Muted.TLabel").pack(anchor="w", pady=(12, 3))
        status_frame = ttk.Frame(form)
        status_frame.pack(fill=tk.BOTH, expand=True)
        self.status_text = tk.Text(
            status_frame,
            height=8,
            wrap="word",
            bg=p["panel_alt"],
            fg=p["text"],
            relief=tk.FLAT,
            padx=8,
            pady=6,
        )
        status_scroll = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.status_text.yview)
        self.status_text.configure(yscrollcommand=status_scroll.set)
        self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        status_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.configure(state=tk.DISABLED)

        self.preview_canvas = tk.Canvas(preview_panel, bg=p["bg"], highlightthickness=0)
        yscroll = ttk.Scrollbar(preview_panel, orient=tk.VERTICAL, command=self.preview_canvas.yview)
        self.preview_grid = tk.Frame(self.preview_canvas, bg=p["bg"])
        self.preview_grid.bind("<Configure>", lambda _e: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all")))
        self.preview_canvas.create_window((0, 0), window=self.preview_grid, anchor="nw")
        self.preview_canvas.configure(yscrollcommand=yscroll.set)
        self.preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        _bind_canvas_mousewheel(self.preview_canvas, self.preview_grid)
        self._refresh_input_mode()
        self._refresh_advanced()
        self.accepted_candidate_var.trace_add("write", lambda *_args: self._refresh_handoff_state())
        self._refresh_handoff_state()
        self._schedule_status_poll()

    def _entry_row(self, parent: "ttk.Frame", label: str, variable: "tk.StringVar") -> None:
        from tkinter import ttk

        ttk.Label(parent, text=label, style="Muted.TLabel").pack(anchor="w", pady=(7, 3))
        ttk.Entry(parent, textvariable=variable).pack(fill="x")

    def _path_row(self, parent: "ttk.Frame", label: str, variable: "tk.StringVar", command: Callable[[], None]) -> tuple[object, object]:
        import tkinter as tk
        from tkinter import ttk

        ttk.Label(parent, text=label, style="Muted.TLabel").pack(anchor="w", pady=(7, 3))
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        button = ttk.Button(row, text="Browse", command=command)
        button.pack(side=tk.LEFT, padx=(6, 0))
        return entry, button

    def _refresh_input_mode(self) -> None:
        if self.input_mode_var.get() == "text-prompt":
            self.source_image_section.pack_forget()
            self.prompt_section.pack(fill="x")
            self.candidate_button.configure(text="Generate Source")
        else:
            self.prompt_section.pack_forget()
            self.source_image_section.pack(fill="x")
            self.candidate_button.configure(text="Generate Reference")
        self._refresh_previews()

    def _refresh_advanced(self) -> None:
        if self.show_advanced_var.get():
            self.advanced_section.pack(fill="x", pady=(8, 0))
        else:
            self.advanced_section.pack_forget()

    def _choose_run_dir(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(initialdir=str(Path.cwd() / "runs"))
        if path:
            self.run_dir_var.set(path)
            self._refresh_previews()
            self._refresh_handoff_state()

    def _choose_source_image(self) -> None:
        self._choose_file(self.source_image_var)

    def _choose_candidate_image(self) -> None:
        self._choose_file(self.candidate_image_var)

    def _choose_accepted_candidate(self) -> None:
        self._choose_file(self.accepted_candidate_var)

    def _choose_anchors_dir(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory()
        if path:
            self.anchors_dir_var.set(path)

    def _choose_file(self, variable: "tk.StringVar") -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
        if path:
            variable.set(path)

    def _use_default_candidate(self) -> None:
        candidate = existing_candidate_anchor(self._run_dir(), self.candidate_facing_var.get()) or default_candidate_anchor(
            self._run_dir(), self.candidate_facing_var.get()
        )
        if candidate.exists():
            self.accepted_candidate_var.set(str(candidate))
        self._refresh_previews()
        self._refresh_handoff_state()

    def _run_candidate(self) -> None:
        self._run_stage("candidate")

    def _run_directions(self) -> None:
        self._run_stage("directions")

    def _run_all(self) -> None:
        self._run_stage("all")

    def _run_bootstrap(self) -> None:
        from tkinter import messagebox

        if self.busy:
            self._refresh_run_status()
            self.status_var.set("Still running the current stage. Wait for it to complete before starting Bootstrap Front + W.")
            return
        try:
            options = self._bootstrap_options()
        except ValueError as exc:
            messagebox.showerror("Missing input", str(exc))
            return

        self.busy = True
        self._refresh_handoff_state()
        self.status_var.set("Bootstrap Front + W started. See Run Status below.")
        thread = threading.Thread(target=self._run_bootstrap_worker, args=(options,), daemon=True)
        thread.start()

    def _run_stage(self, stage: str) -> None:
        from tkinter import messagebox

        if self.busy:
            self._refresh_run_status()
            self.status_var.set(f"Still running the current stage. Wait for it to complete before starting {stage}.")
            return
        try:
            options = self._options(stage)
        except ValueError as exc:
            messagebox.showerror("Missing input", str(exc))
            return

        self.busy = True
        self._refresh_handoff_state()
        self.status_var.set(f"{_stage_action_label(stage, self.input_mode_var.get())} started. See Run Status below.")
        thread = threading.Thread(target=self._run_worker, args=(options,), daemon=True)
        thread.start()

    def _run_worker(self, options: AnchorWizardOptions) -> None:
        try:
            result = run_anchor_wizard(options)
        except Exception as exc:  # pragma: no cover - exercised manually in Tk
            error = exc
            self.root.after(0, lambda error=error: self._stage_failed(error))
            return
        self.root.after(0, lambda: self._stage_completed(result.run_dir, options.stage))

    def _run_bootstrap_worker(self, options: BootstrapAnchorsOptions) -> None:
        try:
            result = run_bootstrap_anchors(options)
        except Exception as exc:  # pragma: no cover - exercised manually in Tk
            error = exc
            self.root.after(0, lambda error=error: self._stage_failed(error))
            return
        self.root.after(0, lambda: self._stage_completed(result.run_dir, "bootstrap"))

    def _stage_completed(self, run_dir: Path, stage: str) -> None:
        self.busy = False
        self.status_var.set(f"Completed. Wrote {run_dir}")
        candidate = existing_candidate_anchor(run_dir, self.candidate_facing_var.get()) or default_candidate_anchor(
            run_dir, self.candidate_facing_var.get()
        )
        if candidate.exists() and not self.accepted_candidate_var.get().strip():
            self.accepted_candidate_var.set(str(candidate))
        self._refresh_previews()
        self._refresh_handoff_state()

    def _stage_failed(self, exc: Exception) -> None:
        from tkinter import messagebox

        self.busy = False
        self.status_var.set(f"Failed: {exc}")
        self._refresh_handoff_state()
        messagebox.showerror("Anchor wizard failed", str(exc))

    def _options(self, stage: str) -> AnchorWizardOptions:
        source_prompt = (
            self.prompt_text.get("1.0", "end").strip() or None
            if self.input_mode_var.get() == "text-prompt"
            else None
        )
        source_image = (
            _path_or_none(self.source_image_var.get())
            if self.input_mode_var.get() == "source-image"
            else None
        )
        candidate_image = _path_or_none(self.candidate_image_var.get())
        accepted_candidate = _path_or_none(self.accepted_candidate_var.get())
        anchors_dir = _path_or_none(self.anchors_dir_var.get())
        directions = tuple(direction for direction, variable in self.direction_vars.items() if variable.get())

        if stage in {"candidate", "all"} and source_image is None and source_prompt is None:
            if self.input_mode_var.get() == "text-prompt":
                raise ValueError("Enter a character prompt before running the candidate stage.")
            raise ValueError("Choose a source image before running the candidate stage.")
        if stage == "candidate" and candidate_image is None and self.dry_fal_var.get():
            raise ValueError("Dry fal candidate runs need an Existing Candidate Image in Advanced / Testing because no live output will be produced.")
        if stage == "directions" and accepted_candidate is None:
            accepted_candidate = existing_candidate_anchor(self._run_dir(), self.candidate_facing_var.get())
        if stage == "directions" and accepted_candidate is None:
            raise ValueError("Set an accepted 1024 chroma anchor before generating directions.")
        if stage in {"directions", "all"} and not directions:
            raise ValueError("Choose at least one direction.")

        return AnchorWizardOptions(
            run_dir=self._run_dir(),
            character_id=self.character_var.get().strip() or "character",
            stage=stage,
            source_image=source_image,
            source_prompt=source_prompt,
            candidate_image=candidate_image,
            candidate_facing=self.candidate_facing_var.get(),
            accepted_candidate=accepted_candidate,
            anchors_dir=anchors_dir,
            directions=directions,
            dry_fal=self.dry_fal_var.get(),
            chroma=self.chroma_var.get().strip() or "#00FF00",
            k_colors=int(self.k_colors_var.get()),
        )

    def _bootstrap_options(self) -> BootstrapAnchorsOptions:
        source_prompt = (
            self.prompt_text.get("1.0", "end").strip() or None
            if self.input_mode_var.get() == "text-prompt"
            else None
        )
        source_image = (
            _path_or_none(self.source_image_var.get())
            if self.input_mode_var.get() == "source-image"
            else None
        )
        candidate_image = _path_or_none(self.candidate_image_var.get())
        anchors_dir = _path_or_none(self.anchors_dir_var.get())

        if source_image is None and source_prompt is None:
            if self.input_mode_var.get() == "text-prompt":
                raise ValueError("Enter a character prompt before running Bootstrap Front + W.")
            raise ValueError("Choose a source image before running Bootstrap Front + W.")
        if candidate_image is None and self.dry_fal_var.get():
            raise ValueError("Dry fal bootstrap runs need an Existing Reference Image in Advanced / Testing because no live output will be produced.")

        return BootstrapAnchorsOptions(
            run_dir=self._run_dir(),
            character_id=self.character_var.get().strip() or "character",
            source_image=source_image,
            source_prompt=source_prompt,
            candidate_image=candidate_image,
            candidate_facing=self.candidate_facing_var.get(),
            anchors_dir=anchors_dir,
            directions=("w",),
            dry_fal=self.dry_fal_var.get(),
            chroma=self.chroma_var.get().strip() or "#00FF00",
            k_colors=int(self.k_colors_var.get()),
        )

    def _run_dir(self) -> Path:
        return Path(self.run_dir_var.get()).expanduser()

    def _refresh_previews(self) -> None:
        import tkinter as tk
        from PIL import ImageTk

        for child in self.preview_grid.winfo_children():
            child.destroy()
        self.preview_photos = []
        self._refresh_handoff_state()

        run_dir = self._run_dir()
        sections = _preview_sections(run_dir, candidate_facing=self.candidate_facing_var.get())

        row = 0
        for title, assets in sections:
            tk.Label(
                self.preview_grid,
                text=title,
                bg=_PALETTE["bg"],
                fg=_PALETTE["text"],
                font=("TkDefaultFont", 12, "bold"),
                anchor="w",
            ).grid(row=row, column=0, columnspan=4, sticky="ew", pady=(12, 6))
            row += 1
            col = 0
            for label, path in assets:
                card = self._preview_card(label, path)
                photo = ImageTk.PhotoImage(card)
                self.preview_photos.append(photo)
                button = tk.Button(
                    self.preview_grid,
                    image=photo,
                    bg=_PALETTE["bg"],
                    activebackground=_PALETTE["panel_alt"],
                    borderwidth=0,
                    highlightthickness=0,
                    command=lambda p=path: _open_path(p),
                )
                button.grid(row=row, column=col, padx=5, pady=5, sticky="n")
                col += 1
                if col >= 4:
                    col = 0
                    row += 1
            row += 1

    def _preview_card(self, label: str, path: Path) -> Image.Image:
        width, height = 260, 304
        card = Image.new("RGBA", (width, height), (34, 41, 54, 255))
        draw = ImageDraw.Draw(card)
        font = ImageFont.load_default()
        draw.text((10, 9), label, fill=(229, 231, 235, 255), font=font)
        draw.text((10, 26), path.name if path.exists() else "missing", fill=(156, 163, 175, 255), font=font)
        if path.exists():
            try:
                image = Image.open(path).convert("RGBA")
                image.thumbnail(PREVIEW_SIZE, Image.Resampling.NEAREST)
                x = (width - image.width) // 2
                y = 44 + (PREVIEW_SIZE[1] - image.height) // 2
                bg = Image.new("RGBA", PREVIEW_SIZE, (15, 18, 24, 255))
                bg.alpha_composite(image, ((PREVIEW_SIZE[0] - image.width) // 2, (PREVIEW_SIZE[1] - image.height) // 2))
                card.alpha_composite(bg, ((width - PREVIEW_SIZE[0]) // 2, 44))
                draw.rectangle((x - 1, y - 1, x + image.width, y + image.height), outline=(55, 65, 81, 255))
            except Exception as exc:
                draw.text((10, 130), str(exc), fill=(248, 113, 113, 255), font=font)
        else:
            progress = _asset_progress_label(path, self._poll_count)
            draw.rectangle((2, 2, width - 3, height - 3), outline=(55, 65, 81, 255), width=2)
            draw.text((54, 140), progress or "not generated", fill=(156, 163, 175, 255), font=font)
        return card

    def _schedule_status_poll(self) -> None:
        self._poll_count += 1
        self._refresh_run_status()
        self._refresh_previews_if_changed()
        self.root.after(2000, self._schedule_status_poll)

    def _refresh_previews_if_changed(self) -> None:
        signature = self._preview_signature()
        if signature == self._last_preview_signature:
            return
        self._last_preview_signature = signature
        self._refresh_previews()

    def _preview_signature(self) -> str:
        parts: list[str] = []
        for _section, assets in _preview_sections(self._run_dir(), candidate_facing=self.candidate_facing_var.get()):
            for _label, path in assets:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
        run_dir = self._run_dir()
        for path in [*run_dir.glob("**/*-status.json"), *run_dir.glob("**/logs/*.command.json")]:
            try:
                stat = path.stat()
            except OSError:
                continue
            parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
        return "\n".join(parts)

    def _refresh_run_status(self) -> None:
        lines = _run_status_lines(self._run_dir(), poll_count=self._poll_count)
        text = "\n".join(lines)
        if text == self._last_status_text:
            return
        self._last_status_text = text
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.insert("1.0", text or "No run activity yet.")
        self.status_text.configure(state="disabled")
        if self.busy and text:
            self.status_var.set(_status_bar_line(lines))
        self._refresh_handoff_state()

    def _refresh_handoff_state(self) -> None:
        generated_candidate = existing_candidate_anchor(self._run_dir(), self.candidate_facing_var.get()) or default_candidate_anchor(
            self._run_dir(), self.candidate_facing_var.get()
        )
        generated_candidate_exists = generated_candidate.exists()
        accepted_candidate = _path_or_none(self.accepted_candidate_var.get())
        accepted_exists = accepted_candidate.exists() if accepted_candidate is not None else False
        direction_state = "normal" if accepted_exists and not self.busy else "disabled"
        candidate_state = "disabled" if self.busy else "normal"
        for widget in (
            self.candidate_button,
            self.accepted_entry,
            self.accepted_browse_button,
            self.use_accepted_button,
            self.run_directions_button,
            self.run_all_button,
            self.bootstrap_w_button,
        ):
            widget.configure(state=candidate_state)
        for widget in (
            self.run_directions_button,
            *self.direction_checkbuttons,
        ):
            widget.configure(state=direction_state)
        self.use_accepted_button.configure(state="normal" if generated_candidate_exists and not self.busy else "disabled")
        if accepted_exists:
            self.handoff_hint_var.set("Ready: accepted 1024 chroma anchor is set. Choose directions, then generate directions.")
        elif generated_candidate_exists:
            self.handoff_hint_var.set("Generated 1024 chroma anchor exists. Click Use Generated 1024 Chroma to accept it before generating directions.")
        elif self.busy:
            self.handoff_hint_var.set("Locked while generation is running. Direction generation unlocks after an accepted 1024 chroma anchor is set.")
        else:
            try:
                candidate_label = generated_candidate.relative_to(self._run_dir())
            except ValueError:
                candidate_label = generated_candidate
            self.handoff_hint_var.set(f"Generate a reference first, then accept {candidate_label}.")

    def _open_review(self) -> None:
        bootstrap_review = self._run_dir() / "review" / "bootstrap" / "index.md"
        _open_path(bootstrap_review if bootstrap_review.exists() else self._run_dir() / "review" / "index.md")

    def _open_folder(self) -> None:
        _open_path(self._run_dir())


def _path_or_none(value: str) -> Path | None:
    stripped = value.strip()
    return Path(stripped).expanduser() if stripped else None


def _bind_canvas_mousewheel(canvas: object, *hover_widgets: object) -> None:
    def on_mousewheel(event: object) -> str:
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        if num == 4:
            units = -1
        elif num == 5:
            units = 1
        elif delta:
            units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        else:
            units = 0
        if units:
            canvas.yview_scroll(units, "units")
        return "break"

    def bind_wheel(_event: object) -> None:
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        canvas.bind_all("<Button-4>", on_mousewheel)
        canvas.bind_all("<Button-5>", on_mousewheel)

    def unbind_wheel(_event: object) -> None:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    for widget in (canvas, *hover_widgets):
        widget.bind("<Enter>", bind_wheel)
        widget.bind("<Leave>", unbind_wheel)


def _preview_sections(run_dir: Path, *, candidate_facing: str = "front") -> list[tuple[str, list[tuple[str, Path]]]]:
    candidate_dir = _candidate_preview_dir(run_dir, candidate_facing)
    return [
        (
            "Source + Reference",
            [
                ("Source", run_dir / "input" / "source.png"),
                ("Reference", candidate_dir / "candidate-raw.png"),
                ("Native Pixel Snap", candidate_dir / "snapped-native.png"),
                ("1024 Chroma Anchor", candidate_dir / "snapped-1024-chroma.png"),
            ],
        ),
        (
            "Direction Anchors",
            [
                (direction.upper(), run_dir / "anchors" / direction / "anchor-snapped-1024-chroma.png")
                for direction in ("n", "s", "e", "w")
            ],
        ),
        (
            "Review Sheets",
            [
                ("Candidate Overview", run_dir / "review" / "candidate-overview.png"),
                ("Direction Comparison", run_dir / "review" / "direction-anchor-comparison.png"),
                ("Direction Detail", run_dir / "review" / "direction-anchor-detail.png"),
                ("Bootstrap Metadata", run_dir / "bootstrap.json"),
            ],
        ),
    ]


def _stage_action_label(stage: str, input_mode: str) -> str:
    if stage == "candidate" and input_mode == "text-prompt":
        return "Generate Source"
    if stage == "candidate":
        return "Generate Reference"
    if stage == "directions":
        return "Generate Directions"
    if stage == "bootstrap":
        return "Bootstrap Front + W"
    return "Run All"


def _candidate_preview_dir(run_dir: Path, candidate_facing: str = "front") -> Path:
    existing = existing_candidate_anchor(run_dir, candidate_facing)
    if existing is not None:
        return existing.parent
    return candidate_dir_for(run_dir, candidate_facing)


def _asset_progress_label(path: Path, poll_count: int) -> str | None:
    run_dir = _preview_asset_run_dir(path)
    if run_dir is None:
        return None
    heartbeat = SPINNER[poll_count % len(SPINNER)]
    if path.name == "source.png" and path.parent.name == "input":
        if _stage_or_fal_active(run_dir, "fal-source", "source-fal"):
            return f"{heartbeat} generating source"
        return "source not generated"
    if path.name == "candidate-raw.png":
        if _stage_or_fal_active(run_dir, "fal-candidate-front", "fal-candidate-s", "candidate-fal"):
            return f"{heartbeat} generating reference"
        if (run_dir / "input" / "source.png").exists():
            return "ready for reference"
        return "waiting for source"
    if path.name in {"snapped-native.png", "snapped-1024-chroma.png"}:
        if _stage_or_fal_active(run_dir, "fal-candidate-front", "fal-candidate-s", "candidate-fal"):
            return "after reference"
        if path.with_name("candidate-raw.png").exists():
            return "pixel snap pending"
        return "waiting for reference"
    if path.name == "anchor-snapped-1024-chroma.png":
        direction = path.parent.name.upper()
        if _anchors_nsew_active(run_dir):
            return f"{heartbeat} generating {direction}"
        generated = run_dir / "anchors-nsew" / "anchors" / f"character-{path.parent.name}-chroma.png"
        if generated.exists():
            return "pixel snap pending"
        return "waiting"
    return None


def _preview_asset_run_dir(path: Path) -> Path | None:
    if path.name == "source.png" and path.parent.name == "input":
        return path.parents[1]
    if path.parent.name in {"front", "s"} and path.parent.parent.name == "candidate":
        return path.parents[2]
    if path.name == "anchor-snapped-1024-chroma.png" and path.parent.parent.name == "anchors":
        return path.parents[2]
    return None


def _stage_or_fal_active(run_dir: Path, *command_stages_and_fal_dir: str) -> bool:
    if len(command_stages_and_fal_dir) < 2:
        return False
    *command_stages, fal_dir_name = command_stages_and_fal_dir
    for command_stage in command_stages:
        command = _read_status_json(run_dir / "logs" / f"{command_stage}.command.json")
        if _is_active_status(str(command.get("status", ""))):
            return True
    for path in [*run_dir.glob(f"{fal_dir_name}/*-status.json"), *run_dir.glob(f"{fal_dir_name}/*-run.json")]:
        data = _read_status_json(path)
        if _is_active_status(str(data.get("status", ""))):
            return True
    return False


def _anchors_nsew_active(run_dir: Path) -> bool:
    for path in (run_dir / "anchors-nsew" / "logs").glob("*.command.json"):
        data = _read_status_json(path)
        if _is_active_status(str(data.get("status", ""))):
            return True
    for path in (run_dir / "anchors-nsew" / "fal").glob("anchor-*/*-status.json"):
        data = _read_status_json(path)
        if _is_active_status(str(data.get("status", ""))):
            return True
    return False


def _run_status_lines(run_dir: Path, *, poll_count: int = 0, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    heartbeat = SPINNER[poll_count % len(SPINNER)]
    lines: list[str] = []
    stage_started: dict[str, datetime] = {}
    stage_completed: dict[str, datetime] = {}
    event_paths = [path for path in run_dir.glob("**/events.jsonl") if "/snap/" not in str(path)]
    for events_path in sorted(event_paths):
        events = events_path.read_text(encoding="utf-8").splitlines()[-6:]
        prefix = _relative_status_prefix(run_dir, events_path.parent)
        for raw in events:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            name = event.get("event", "event")
            stage = event.get("stage")
            timestamp = _parse_iso(event.get("timestamp"))
            if stage and timestamp and name == "stage_started":
                stage_started[str(stage)] = timestamp
            if stage and timestamp and name in {"stage_completed", "stage_failed"}:
                stage_completed[str(stage)] = timestamp
            if stage:
                lines.append(f"{event.get('timestamp', '')}  {prefix}{name}: {stage}")
            else:
                lines.append(f"{event.get('timestamp', '')}  {prefix}{name}")

    for status_path in sorted(run_dir.glob("**/*-status.json")):
        data = _read_status_json(status_path)
        if not data:
            continue
        status = str(data.get("status", "unknown"))
        request_id = data.get("request_id") or data.get("requestId") or "-"
        prefix = heartbeat if _is_active_status(status) else " "
        name = _status_file_label(run_dir, status_path)
        lines.append(
            f"{prefix} {name}: {status}  request {request_id}  "
            f"status updated {_file_age(status_path, now)} ago"
        )

    for run_path in sorted(run_dir.glob("*-fal/*-run.json")):
        data = _read_status_json(run_path)
        if not data:
            continue
        status = str(data.get("status", "unknown"))
        request_id = data.get("request_id") or "-"
        outputs = data.get("output_files") or []
        suffix = f"  outputs {len(outputs)}" if isinstance(outputs, list) and outputs else ""
        prefix = heartbeat if _is_active_status(status) else " "
        lines.append(
            f"{prefix} {run_path.parent.name}: {status}  request {request_id}{suffix}  "
            f"run file updated {_file_age(run_path, now)} ago"
        )

    for command_path in sorted(run_dir.glob("**/logs/*.command.json")):
        data = _read_status_json(command_path)
        if not data:
            continue
        status = str(data.get("status", "unknown"))
        stage = data.get("stage", command_path.stem)
        prefix = heartbeat if _is_active_status(status) else " "
        name = _command_file_label(run_dir, command_path, str(stage))
        if _is_active_status(status):
            started = _parse_iso(data.get("startedAt")) or stage_started.get(str(stage))
            elapsed = _human_duration((now - started).total_seconds()) if started else "unknown time"
            lines.append(f"{prefix} command {name}: running for {elapsed}")
        else:
            duration = _command_duration(data, stage_started.get(str(stage)), stage_completed.get(str(stage)))
            suffix = f" in {duration}" if duration else ""
            lines.append(f"{prefix} command {name}: {status}{suffix}")
    if any(_line_is_active(line) for line in lines):
        lines.append(f"{heartbeat} polling every 2s; last checked {now.strftime('%H:%M:%S UTC')}")
    return lines[-12:]


def _read_status_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _relative_status_prefix(run_dir: Path, path: Path) -> str:
    if path == run_dir:
        return ""
    try:
        return f"{path.relative_to(run_dir)}: "
    except ValueError:
        return f"{path.name}: "


def _status_file_label(run_dir: Path, path: Path) -> str:
    try:
        parent = path.parent.relative_to(run_dir)
    except ValueError:
        return path.parent.name
    parts = parent.parts
    if len(parts) >= 3 and parts[-2] == "fal":
        return "/".join(parts[-3:])
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return path.parent.name


def _command_file_label(run_dir: Path, path: Path, stage: str) -> str:
    try:
        parent = path.parent.parent.relative_to(run_dir)
    except ValueError:
        return stage
    if str(parent) == ".":
        return stage
    return f"{parent}/{stage}"


def _status_bar_line(lines: list[str]) -> str:
    for line in reversed(lines):
        if _line_is_active(line) and "polling every 2s" not in line:
            return line
    return lines[-1] if lines else "No run activity yet."


def _line_is_active(line: str) -> bool:
    return line.startswith(tuple(SPINNER))


def _is_active_status(status: str) -> bool:
    return status.strip().lower() in {"running", "queued", "in_progress", "in progress", "processing"}


def _file_age(path: Path, now: datetime) -> str:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return "unknown"
    return _human_duration(max(0.0, (now - modified).total_seconds()))


def _command_duration(data: dict[str, object], fallback_started: datetime | None, fallback_ended: datetime | None) -> str | None:
    started = _parse_iso(data.get("startedAt")) or fallback_started
    ended = _parse_iso(data.get("completedAt")) or fallback_ended
    if started is None or ended is None:
        return None
    return _human_duration(max(0.0, (ended - started).total_seconds()))


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _human_duration(seconds: float) -> str:
    seconds_i = int(seconds)
    if seconds_i < 60:
        return f"{seconds_i}s"
    minutes, seconds_i = divmod(seconds_i, 60)
    if minutes < 60:
        return f"{minutes}m {seconds_i:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _open_path(path: Path) -> None:
    if not path.exists():
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/c", "start", "", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        webbrowser.open(path.resolve().as_uri())
