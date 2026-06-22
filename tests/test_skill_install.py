"""Tests for the bundled agent skill resources and install command."""

from __future__ import annotations

from pathlib import Path

import pytest

from spriterrific.skill_install import bundled_skill_root, install_skill, resolve_targets


def test_bundled_skill_resources_exist() -> None:
    """The packaged skill must include SKILL.md and its reference docs."""
    root = bundled_skill_root()
    assert root.is_dir()
    assert root.joinpath("SKILL.md").is_file()
    references = root.joinpath("references")
    assert references.is_dir()
    reference_names = {entry.name for entry in references.iterdir()}
    assert "seven-step-ai-prompting.md" in reference_names
    assert "image-action-pose-boards.md" in reference_names
    assert "happy-path-prompt-templates.md" in reference_names


def test_resolve_targets_defaults_to_claude() -> None:
    """No explicit targets should install only the .claude skill folder."""
    assert resolve_targets(None) == ("claude",)
    assert resolve_targets([]) == ("claude",)


def test_resolve_targets_expands_all_and_dedupes() -> None:
    """`all` expands to every known folder; duplicates collapse."""
    assert resolve_targets(["all"]) == ("claude", "codex", "agents")
    assert resolve_targets(["codex", "codex", "claude"]) == ("codex", "claude")


def test_resolve_targets_rejects_unknown() -> None:
    """Unknown target names should exit with a helpful error."""
    with pytest.raises(SystemExit):
        resolve_targets(["cursor"])


def test_install_skill_copies_into_claude_folder(tmp_path: Path) -> None:
    """Default install writes the full skill tree under .claude/skills/spriterrific."""
    installed = install_skill(tmp_path)
    assert installed == [tmp_path / ".claude" / "skills" / "spriterrific"]
    skill_md = tmp_path / ".claude" / "skills" / "spriterrific" / "SKILL.md"
    assert skill_md.is_file()
    assert "spriterrific" in skill_md.read_text(encoding="utf-8")
    assert (tmp_path / ".claude" / "skills" / "spriterrific" / "references" / "seven-step-ai-prompting.md").is_file()


def test_install_skill_all_targets(tmp_path: Path) -> None:
    """Installing with all targets writes claude, codex, and agents folders."""
    installed = install_skill(tmp_path, targets=["all"])
    assert len(installed) == 3
    for folder in (".claude", ".codex", ".agents"):
        assert (tmp_path / folder / "skills" / "spriterrific" / "SKILL.md").is_file()


def test_install_skill_refuses_overwrite_without_force(tmp_path: Path) -> None:
    """A second install without --force should fail; with force it succeeds."""
    install_skill(tmp_path)
    with pytest.raises(SystemExit):
        install_skill(tmp_path)
    installed = install_skill(tmp_path, force=True)
    assert installed == [tmp_path / ".claude" / "skills" / "spriterrific"]
