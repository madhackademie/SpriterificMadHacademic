"""Project and run discovery for the Spriterrific viewer.

Resolves where Spriterrific outputs live inside a project (raw CLI ``runs/``
plus SDK ``spriterrific-sdk/runs`` and ``spriterrific-sdk/animation-runs``
layouts), classifies run folders into typed entries, and resolves the
canonical artifacts (spritesheet, preview GIF, raw video, latest export)
for a given run.

The optional ``.spriterrific/config.json`` marker at a project root makes the
run roots explicit; without it, discovery probes the conventional locations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

CONFIG_DIR_NAME = ".spriterrific"
CONFIG_FILE_NAME = "config.json"
CONFIG_VERSION = 1

DEFAULT_RUN_ROOTS: tuple[str, ...] = (
    "runs",
    "spriterrific-sdk/runs",
    "spriterrific-sdk/animation-runs",
)

KIND_ANIMATION_RUN = "animation-run"
KIND_BOOTSTRAP_RUN = "bootstrap-run"
KIND_ANIMATION_GROUP = "animation-group"


@dataclass(frozen=True)
class RunEntry:
    """One discovered run folder, classified by kind.

    ``children`` is populated for animation groups, where each child is an
    action-direction run in the standard CLI layout.
    """

    path: Path
    kind: str
    label: str
    action: str | None = None
    direction: str | None = None
    mode: str | None = None
    status: str | None = None
    created_at: str | None = None
    character: str | None = None
    children: tuple["RunEntry", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RunArtifacts:
    """Resolved canonical artifact paths for a single run.

    Every field is optional: partial or in-flight runs are expected and the
    viewer renders whatever exists.
    """

    export_dir: Path | None = None
    manifest: Path | None = None
    spritesheet: Path | None = None
    preview_gif: Path | None = None
    raw_video: Path | None = None
    dense_frames_dir: Path | None = None
    runtime_frames_dir: Path | None = None
    review_index: Path | None = None
    reference: Path | None = None


def _read_json(path: Path) -> dict | None:
    """Read a JSON object from ``path``, returning None on any failure.

    Discovery must tolerate half-written files from in-flight runs.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_project_config(start: Path) -> Path | None:
    """Walk up from ``start`` looking for ``.spriterrific/config.json``.

    Returns the config file path, or None when no marker exists.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        config = candidate / CONFIG_DIR_NAME / CONFIG_FILE_NAME
        if config.is_file():
            return config
    return None


def find_project_root(start: Path) -> Path:
    """Resolve the project root for ``start``.

    Prefers the directory owning a ``.spriterrific`` marker; otherwise walks
    up looking for a directory that contains at least one conventional run
    root, falling back to ``start`` itself.
    """
    config = find_project_config(start)
    if config is not None:
        return config.parent.parent
    current = start.resolve()
    for candidate in (current, *current.parents):
        for root in DEFAULT_RUN_ROOTS:
            if (candidate / root).is_dir():
                return candidate
    return current


def load_run_roots(project_dir: Path) -> list[Path]:
    """Return the run roots for ``project_dir`` as absolute paths.

    Reads ``runRoots`` from the project marker when present, otherwise probes
    the conventional locations. Only existing directories are returned.
    """
    config_path = project_dir / CONFIG_DIR_NAME / CONFIG_FILE_NAME
    roots: list[str] = list(DEFAULT_RUN_ROOTS)
    config = _read_json(config_path) if config_path.is_file() else None
    if config is not None:
        configured = config.get("runRoots")
        if isinstance(configured, list) and configured:
            roots = [str(item) for item in configured]
    resolved: list[Path] = []
    for root in roots:
        path = (project_dir / root).resolve()
        if path.is_dir() and path not in resolved:
            resolved.append(path)
    return resolved


def write_project_config(project_dir: Path, run_roots: list[str] | None = None) -> Path:
    """Create or update ``.spriterrific/config.json`` in ``project_dir``.

    Performs a read-modify-write that preserves unknown keys so other writers
    (skill install, SDK) are never clobbered. Returns the config path.
    """
    config_path = project_dir / CONFIG_DIR_NAME / CONFIG_FILE_NAME
    existing = _read_json(config_path) if config_path.is_file() else None
    payload = dict(existing) if existing else {}
    payload["version"] = payload.get("version", CONFIG_VERSION)
    if run_roots is not None:
        payload["runRoots"] = run_roots
    elif "runRoots" not in payload:
        payload["runRoots"] = list(DEFAULT_RUN_ROOTS)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return config_path


def classify_run_folder(path: Path) -> RunEntry | None:
    """Classify one folder as an animation run, bootstrap run, or group.

    Returns None for folders that are not recognizable Spriterrific outputs
    (logs, caches, abandoned directories), which callers should skip silently.
    """
    if not path.is_dir():
        return None
    run_json = _read_json(path / "run.json")
    if run_json is not None:
        return RunEntry(
            path=path,
            kind=KIND_ANIMATION_RUN,
            label=path.name,
            action=_opt_str(run_json.get("action")),
            direction=_opt_str(run_json.get("direction")),
            mode=_opt_str(run_json.get("mode")),
            status=_opt_str(run_json.get("status")),
            created_at=_opt_str(run_json.get("createdAt")),
        )
    bootstrap = _read_json(path / "bootstrap.json")
    if bootstrap is not None or (path / "candidate").is_dir() or (path / "anchors").is_dir():
        character = None
        if bootstrap is not None:
            raw_character = bootstrap.get("character")
            if isinstance(raw_character, dict):
                character = _opt_str(raw_character.get("id") or raw_character.get("characterId"))
            else:
                character = _opt_str(raw_character)
        return RunEntry(
            path=path,
            kind=KIND_BOOTSTRAP_RUN,
            label=path.name,
            character=character,
            created_at=_opt_str(bootstrap.get("createdAt")) if bootstrap else None,
        )
    if _looks_like_legacy_animation_run(path):
        return RunEntry(path=path, kind=KIND_ANIMATION_RUN, label=path.name)
    group = _classify_group(path)
    if group is not None:
        return group
    return None


def _looks_like_legacy_animation_run(path: Path) -> bool:
    """Detect pre-``run.json`` animation runs by their pipeline artifacts."""
    if (path / "processing-summary.json").is_file():
        return True
    has_video = (path / "raw-video.mp4").is_file() or (path / "fal" / "raw-video.mp4").is_file()
    return has_video and (path / "extracted").is_dir()


def _classify_group(path: Path) -> RunEntry | None:
    """Detect an SDK animation-group folder and classify its children.

    A group is marked by an ``animation-plan.json``, a ``manifest.json`` with
    ``type: animation-group``, or by containing child folders that are
    themselves animation runs.
    """
    manifest = _read_json(path / "manifest.json")
    is_marked_group = (manifest or {}).get("type") == "animation-group" or (path / "animation-plan.json").is_file()
    children: list[RunEntry] = []
    try:
        entries = sorted(child for child in path.iterdir() if child.is_dir())
    except OSError:
        return None
    for child in entries:
        child_run = _read_json(child / "run.json")
        if child_run is None:
            continue
        children.append(
            RunEntry(
                path=child,
                kind=KIND_ANIMATION_RUN,
                label=child.name,
                action=_opt_str(child_run.get("action")),
                direction=_opt_str(child_run.get("direction")),
                mode=_opt_str(child_run.get("mode")),
                status=_opt_str(child_run.get("status")),
                created_at=_opt_str(child_run.get("createdAt")),
            )
        )
    if not is_marked_group and not children:
        return None
    plan = _read_json(path / "animation-plan.json")
    created_at = _opt_str(plan.get("createdAt")) if plan else None
    return RunEntry(
        path=path,
        kind=KIND_ANIMATION_GROUP,
        label=path.name,
        created_at=created_at,
        children=tuple(children),
    )


def scan_run_root(root: Path) -> list[RunEntry]:
    """Scan one run root and return classified entries, newest first."""
    entries: list[RunEntry] = []
    try:
        candidates = [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return entries
    for child in candidates:
        entry = classify_run_folder(child)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: entry.path.name, reverse=True)
    return entries


def discover_runs(project_dir: Path) -> list[tuple[Path, list[RunEntry]]]:
    """Discover all runs in ``project_dir`` grouped by run root.

    Returns ``(root, entries)`` pairs for each existing run root.
    """
    return [(root, scan_run_root(root)) for root in load_run_roots(project_dir)]


def list_export_dirs(run_dir: Path) -> list[Path]:
    """List every export folder for a run, newest first.

    Includes the run's own ``export/`` plus any nested
    ``frame-picker/<ts>/post-selection/<ts>/export`` curation branches. An
    export counts when it has a ``manifest.json`` or, for legacy runs, a
    ``spritesheet.png``; ordering uses the manifest mtime when available.
    """
    candidates: list[Path] = []
    direct = run_dir / "export"
    if _is_export_dir(direct):
        candidates.append(direct)
    for picker_dir in sorted((run_dir / "frame-picker").glob("*/post-selection/*/export")):
        if _is_export_dir(picker_dir):
            candidates.append(picker_dir)
    candidates.sort(key=_export_sort_key, reverse=True)
    return candidates


def _is_export_dir(path: Path) -> bool:
    """True when ``path`` holds a usable export (manifest or legacy sheet)."""
    return (path / "manifest.json").is_file() or (path / "spritesheet.png").is_file()


def _export_sort_key(path: Path) -> float:
    """Sort key for export dirs: manifest mtime, falling back to the sheet."""
    for probe in (path / "manifest.json", path / "spritesheet.png"):
        try:
            return probe.stat().st_mtime
        except OSError:
            continue
    return 0.0


def latest_export_dir(run_dir: Path) -> Path | None:
    """Resolve the most recent export folder for a run, or None."""
    exports = list_export_dirs(run_dir)
    return exports[0] if exports else None


def export_branch_label(run_dir: Path, export_dir: Path) -> str:
    """Human-readable label for one export branch of ``run_dir``."""
    if export_dir.parent == run_dir:
        return "auto export"
    try:
        relative = export_dir.parent.relative_to(run_dir)
    except ValueError:
        return str(export_dir.parent)
    return str(relative)


def resolve_artifacts(run_dir: Path, export_dir: Path | None = None) -> RunArtifacts:
    """Resolve the canonical viewable artifacts for ``run_dir``.

    ``export_dir`` selects a specific curation branch; when omitted, the
    newest export wins. All fields are best-effort; missing stages simply
    resolve to None.
    """
    if export_dir is None:
        export_dir = latest_export_dir(run_dir)
    artifacts = RunArtifacts(export_dir=export_dir)
    if export_dir is not None:
        artifacts = replace(
            artifacts,
            manifest=_existing(export_dir / "manifest.json"),
            spritesheet=_existing(export_dir / "spritesheet.png"),
            preview_gif=_existing(export_dir / "preview.gif"),
        )
    if artifacts.spritesheet is None:
        artifacts = replace(artifacts, spritesheet=_existing(run_dir / "generated" / "sheet.png"))
    if artifacts.preview_gif is None:
        for fallback in (
            run_dir / "review" / "preview.gif",
            run_dir / "review" / "selected-preview.gif",
        ):
            if fallback.is_file():
                artifacts = replace(artifacts, preview_gif=fallback)
                break
    return replace(
        artifacts,
        raw_video=_existing(run_dir / "fal" / "raw-video.mp4") or _existing(run_dir / "raw-video.mp4"),
        dense_frames_dir=_existing_dir(run_dir / "extracted" / "dense-frames"),
        runtime_frames_dir=_resolve_runtime_frames_dir(run_dir, artifacts.export_dir),
        review_index=_existing(run_dir / "review" / "index.md"),
        reference=_existing(run_dir / "input" / "source.png"),
    )


def _resolve_runtime_frames_dir(run_dir: Path, export_dir: Path | None) -> Path | None:
    """Find the runtime frame cells that pair with the resolved export."""
    if export_dir is not None and export_dir.parent != run_dir:
        for sibling in sorted(export_dir.parent.glob("frames-*")):
            if sibling.is_dir() and any(sibling.glob("frame-*.png")):
                return sibling
    normalized = run_dir / "normalized"
    if normalized.is_dir() and any(normalized.glob("frame-*.png")):
        return normalized
    return None


def _existing(path: Path) -> Path | None:
    """Return ``path`` when it is an existing file, else None."""
    return path if path.is_file() else None


def _existing_dir(path: Path) -> Path | None:
    """Return ``path`` when it is an existing directory, else None."""
    return path if path.is_dir() else None


def _opt_str(value: object) -> str | None:
    """Coerce a JSON value to ``str`` or None."""
    return str(value) if isinstance(value, str) and value else None
