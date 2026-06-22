"""Install the bundled Spriterrific agent skill into a project.

The skill ships inside the ``spriterrific`` package under
``spriterrific/skills/spriterrific`` so that pip/pipx/uvx installs carry the
same agent guidance as the source repo. ``spriterrific skill install`` copies
it into a project's agent skill folders (``.claude/skills``, ``.codex/skills``,
or ``.agents/skills``) where coding agents discover it.
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

SKILL_NAME = "spriterrific"

SKILL_TARGET_DIRS: dict[str, str] = {
    "claude": ".claude/skills",
    "codex": ".codex/skills",
    "agents": ".agents/skills",
}


def bundled_skill_root() -> Traversable:
    """Return the traversable root of the bundled skill resources."""
    return resources.files("spriterrific").joinpath("skills").joinpath(SKILL_NAME)


def _copy_tree(source: Traversable, dest: Path) -> list[Path]:
    """Recursively copy a traversable resource tree to ``dest`` and return written files."""
    written: list[Path] = []
    dest.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            written.extend(_copy_tree(entry, target))
        else:
            target.write_bytes(entry.read_bytes())
            written.append(target)
    return written


def resolve_targets(targets: list[str] | None) -> tuple[str, ...]:
    """Normalize requested install targets, expanding ``all`` and defaulting to ``claude``."""
    if not targets:
        return ("claude",)
    if "all" in targets:
        return tuple(SKILL_TARGET_DIRS)
    seen: list[str] = []
    for target in targets:
        if target not in SKILL_TARGET_DIRS:
            raise SystemExit(f"Unknown skill target: {target}. Choose from {', '.join(SKILL_TARGET_DIRS)} or all.")
        if target not in seen:
            seen.append(target)
    return tuple(seen)


def install_skill(project_root: Path, targets: list[str] | None = None, force: bool = False) -> list[Path]:
    """Copy the bundled skill into ``project_root`` agent skill folders.

    Returns the list of skill directories that were written. Raises
    ``SystemExit`` if a destination already exists and ``force`` is not set.
    """
    source = bundled_skill_root()
    if not source.is_dir():
        raise SystemExit("Bundled skill resources are missing from this spriterrific installation.")
    installed: list[Path] = []
    for target in resolve_targets(targets):
        dest = project_root / SKILL_TARGET_DIRS[target] / SKILL_NAME
        if dest.is_symlink():
            raise SystemExit(f"Refusing to overwrite symlink at {dest}; remove it first or pick another --target.")
        if dest.exists() and not force:
            raise SystemExit(f"Skill already installed at {dest}. Re-run with --force to overwrite.")
        _copy_tree(source, dest)
        installed.append(dest)
    return installed
