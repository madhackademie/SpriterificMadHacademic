"""Shared application-icon helper for the Spriterrific Tk GUIs.

Resolves the bundled brand icon and applies it to a Tk window so the app shows
the Spriterrific mark instead of the generic interpreter icon. On Windows and
Linux this sets the window/taskbar icon via ``wm iconphoto``; on macOS it also
sets the Dock icon through AppKit when PyObjC is available (a best-effort no-op
otherwise, since ``iconphoto`` does not affect the macOS Dock).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

_ICON_RELPATH = "assets/app-icon.png"


def icon_path() -> Path | None:
    """Return the on-disk path to the bundled app icon, or ``None`` if absent.

    Resolves the packaged ``spriterrific/assets/app-icon.png`` via
    :mod:`importlib.resources`, falling back to a path relative to this module
    for editable installs and source checkouts.
    """
    try:
        from importlib.resources import files

        candidate = Path(str(files("spriterrific").joinpath(_ICON_RELPATH)))
        if candidate.is_file():
            return candidate
    except (ModuleNotFoundError, FileNotFoundError, TypeError, ValueError):
        pass
    candidate = Path(__file__).resolve().parent / _ICON_RELPATH
    return candidate if candidate.is_file() else None


def _load_photo(root: "tk.Tk", path: Path) -> "tk.PhotoImage | None":
    """Load ``path`` as a Tk ``PhotoImage``, trying PIL when native PNG fails.

    Tk 8.6 reads PNG natively; older builds need Pillow's ``ImageTk`` bridge.
    Returns ``None`` if neither path can decode the image.
    """
    import tkinter as tk

    try:
        return tk.PhotoImage(file=str(path), master=root)
    except tk.TclError:
        pass
    try:
        from PIL import Image, ImageTk

        return ImageTk.PhotoImage(Image.open(path).convert("RGBA"), master=root)
    except Exception:
        return None


def _set_macos_dock_icon(path: Path) -> bool:
    """Set the macOS Dock icon via AppKit; return ``True`` on success.

    Requires PyObjC (the ``AppKit`` module). When it is unavailable this is a
    silent no-op so the GUIs never hard-depend on PyObjC.
    """
    try:
        from AppKit import NSApplication, NSImage
    except Exception:
        return False
    try:
        image = NSImage.alloc().initWithContentsOfFile_(str(path))
        if image is None:
            return False
        NSApplication.sharedApplication().setApplicationIconImage_(image)
        return True
    except Exception:
        return False


def apply_app_icon(root: "tk.Tk") -> bool:
    """Apply the Spriterrific icon to ``root`` (window/taskbar and macOS Dock).

    Keeps a reference to the loaded image on ``root`` so Tk does not garbage
    collect it. Returns ``True`` if any icon surface was set, ``False`` if the
    asset is missing or could not be decoded. Always safe to call.
    """
    path = icon_path()
    if path is None:
        return False

    applied = False
    photo = _load_photo(root, path)
    if photo is not None:
        try:
            root.iconphoto(True, photo)
            root._spriterrific_icon_ref = photo  # type: ignore[attr-defined]
            applied = True
        except Exception:
            pass

    if sys.platform == "darwin" and _set_macos_dock_icon(path):
        applied = True

    return applied
