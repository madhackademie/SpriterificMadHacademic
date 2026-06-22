from __future__ import annotations

import json
import os
import time
from pathlib import Path

from spriterrific.discovery import (
    DEFAULT_RUN_ROOTS,
    KIND_ANIMATION_GROUP,
    KIND_ANIMATION_RUN,
    KIND_BOOTSTRAP_RUN,
    classify_run_folder,
    discover_runs,
    export_branch_label,
    find_project_config,
    find_project_root,
    latest_export_dir,
    list_export_dirs,
    load_run_roots,
    resolve_artifacts,
    scan_run_root,
    write_project_config,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_animation_run(path: Path, *, action: str = "walk", direction: str = "w", status: str = "completed") -> Path:
    _write_json(path / "run.json", {"version": 1, "action": action, "direction": direction, "mode": "video", "status": status, "createdAt": "2026-06-01T00:00:00Z"})
    return path


def test_classify_animation_run(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "20260601-000000-run-walk-w")
    entry = classify_run_folder(run)
    assert entry is not None
    assert entry.kind == KIND_ANIMATION_RUN
    assert entry.action == "walk"
    assert entry.direction == "w"
    assert entry.status == "completed"


def test_classify_bootstrap_run(tmp_path: Path) -> None:
    run = tmp_path / "20260601-000000-bootstrap-anchors-hero"
    _write_json(run / "bootstrap.json", {"type": "bootstrap-anchors", "character": {"id": "hero"}})
    entry = classify_run_folder(run)
    assert entry is not None
    assert entry.kind == KIND_BOOTSTRAP_RUN
    assert entry.character == "hero"


def test_classify_sdk_group_with_children(tmp_path: Path) -> None:
    group = tmp_path / "20260601T000000Z-cursor-sdk-character-w"
    _write_json(group / "animation-plan.json", {"createdAt": "2026-06-01T00:00:00Z"})
    _make_animation_run(group / "idle-w", action="idle")
    _make_animation_run(group / "attack-w", action="attack")
    entry = classify_run_folder(group)
    assert entry is not None
    assert entry.kind == KIND_ANIMATION_GROUP
    assert {child.action for child in entry.children} == {"idle", "attack"}


def test_classify_unmarked_group_by_children(tmp_path: Path) -> None:
    group = tmp_path / "group-without-plan"
    _make_animation_run(group / "idle-w", action="idle")
    entry = classify_run_folder(group)
    assert entry is not None
    assert entry.kind == KIND_ANIMATION_GROUP


def test_classify_skips_junk(tmp_path: Path) -> None:
    junk = tmp_path / "logs"
    junk.mkdir()
    (junk / "notes.txt").write_text("not a run", encoding="utf-8")
    assert classify_run_folder(junk) is None


def test_classify_tolerates_corrupt_run_json(tmp_path: Path) -> None:
    run = tmp_path / "broken"
    run.mkdir()
    (run / "run.json").write_text("{not json", encoding="utf-8")
    assert classify_run_folder(run) is None


def test_scan_run_root_sorts_newest_first(tmp_path: Path) -> None:
    _make_animation_run(tmp_path / "20260601-000000-run-walk-w")
    _make_animation_run(tmp_path / "20260602-000000-run-idle-w", action="idle")
    entries = scan_run_root(tmp_path)
    assert [entry.path.name for entry in entries] == ["20260602-000000-run-idle-w", "20260601-000000-run-walk-w"]


def test_find_project_config_walks_up(tmp_path: Path) -> None:
    write_project_config(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    config = find_project_config(nested)
    assert config is not None
    assert config.parent.parent == tmp_path


def test_find_project_root_falls_back_to_conventional_roots(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    nested = tmp_path / "src"
    nested.mkdir()
    assert find_project_root(nested) == tmp_path.resolve()


def test_load_run_roots_defaults_and_marker(tmp_path: Path) -> None:
    for root in DEFAULT_RUN_ROOTS:
        (tmp_path / root).mkdir(parents=True)
    assert [path.name for path in load_run_roots(tmp_path)] == ["runs", "runs", "animation-runs"]

    write_project_config(tmp_path, run_roots=["custom-runs"])
    (tmp_path / "custom-runs").mkdir()
    roots = load_run_roots(tmp_path)
    assert [path.name for path in roots] == ["custom-runs"]


def test_write_project_config_preserves_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / ".spriterrific" / "config.json"
    _write_json(config_path, {"version": 1, "customKey": "keep-me"})
    write_project_config(tmp_path, run_roots=["runs"])
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["customKey"] == "keep-me"
    assert payload["runRoots"] == ["runs"]


def test_discover_runs_spans_cli_and_sdk_roots(tmp_path: Path) -> None:
    _make_animation_run(tmp_path / "runs" / "20260601-000000-run-walk-w")
    group = tmp_path / "spriterrific-sdk" / "animation-runs" / "20260601T000000Z-cursor-sdk-hero-w"
    _write_json(group / "animation-plan.json", {})
    _make_animation_run(group / "idle-w", action="idle")
    results = dict((root.name, entries) for root, entries in discover_runs(tmp_path))
    assert results["runs"][0].kind == KIND_ANIMATION_RUN
    assert results["animation-runs"][0].kind == KIND_ANIMATION_GROUP


def test_latest_export_prefers_newest_curation_branch(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run")
    direct = run / "export"
    _write_json(direct / "manifest.json", {"version": 1, "fps": 10})
    nested = run / "frame-picker" / "20260602-000000" / "post-selection" / "20260602-000100" / "export"
    _write_json(nested / "manifest.json", {"version": 1, "fps": 10})
    old = time.time() - 3600
    os.utime(direct / "manifest.json", (old, old))
    assert latest_export_dir(run) == nested


def test_resolve_artifacts_full_run(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run")
    export = run / "export"
    _write_json(export / "manifest.json", {"version": 1, "fps": 8})
    (export / "spritesheet.png").write_bytes(b"png")
    (export / "preview.gif").write_bytes(b"gif")
    (run / "fal").mkdir()
    (run / "fal" / "raw-video.mp4").write_bytes(b"mp4")
    dense = run / "extracted" / "dense-frames"
    dense.mkdir(parents=True)
    (dense / "frame-0001.png").write_bytes(b"png")
    normalized = run / "normalized"
    normalized.mkdir()
    (normalized / "frame-01.png").write_bytes(b"png")
    (run / "review").mkdir()
    (run / "review" / "index.md").write_text("# review", encoding="utf-8")

    artifacts = resolve_artifacts(run)
    assert artifacts.export_dir == export
    assert artifacts.spritesheet == export / "spritesheet.png"
    assert artifacts.preview_gif == export / "preview.gif"
    assert artifacts.raw_video == run / "fal" / "raw-video.mp4"
    assert artifacts.dense_frames_dir == dense
    assert artifacts.runtime_frames_dir == normalized
    assert artifacts.review_index == run / "review" / "index.md"


def test_resolve_artifacts_partial_run(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run", status="running")
    artifacts = resolve_artifacts(run)
    assert artifacts.export_dir is None
    assert artifacts.spritesheet is None
    assert artifacts.preview_gif is None
    assert artifacts.raw_video is None


def test_list_export_dirs_orders_newest_first(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run")
    direct = run / "export"
    _write_json(direct / "manifest.json", {"version": 1})
    nested = run / "frame-picker" / "20260602-000000" / "post-selection" / "20260602-000100" / "export"
    _write_json(nested / "manifest.json", {"version": 1})
    old = time.time() - 3600
    os.utime(direct / "manifest.json", (old, old))
    exports = list_export_dirs(run)
    assert exports == [nested, direct]


def test_classify_legacy_run_without_run_json(tmp_path: Path) -> None:
    run = tmp_path / "20260504-090118-legacy-walk-w"
    (run / "extracted").mkdir(parents=True)
    (run / "raw-video.mp4").write_bytes(b"mp4")
    entry = classify_run_folder(run)
    assert entry is not None
    assert entry.kind == KIND_ANIMATION_RUN


def test_list_export_dirs_accepts_legacy_sheet_only_export(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run")
    nested = run / "frame-picker" / "20260504-090656" / "post-selection" / "20260504-092621" / "export"
    nested.mkdir(parents=True)
    (nested / "spritesheet.png").write_bytes(b"png")
    assert list_export_dirs(run) == [nested]


def test_resolve_artifacts_legacy_root_video(tmp_path: Path) -> None:
    run = tmp_path / "legacy-run"
    (run / "extracted").mkdir(parents=True)
    (run / "raw-video.mp4").write_bytes(b"mp4")
    artifacts = resolve_artifacts(run)
    assert artifacts.raw_video == run / "raw-video.mp4"


def test_export_branch_label(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run")
    direct = run / "export"
    nested = run / "frame-picker" / "20260602-000000" / "post-selection" / "20260602-000100" / "export"
    assert export_branch_label(run, direct) == "auto export"
    assert export_branch_label(run, nested) == "frame-picker/20260602-000000/post-selection/20260602-000100"


def test_resolve_artifacts_with_explicit_export_dir(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run")
    direct = run / "export"
    _write_json(direct / "manifest.json", {"version": 1})
    (direct / "spritesheet.png").write_bytes(b"png")
    nested = run / "frame-picker" / "20260602-000000" / "post-selection" / "20260602-000100" / "export"
    _write_json(nested / "manifest.json", {"version": 1})
    (nested / "spritesheet.png").write_bytes(b"png")
    artifacts = resolve_artifacts(run, direct)
    assert artifacts.export_dir == direct
    assert artifacts.spritesheet == direct / "spritesheet.png"
    artifacts = resolve_artifacts(run, nested)
    assert artifacts.export_dir == nested
    assert artifacts.spritesheet == nested / "spritesheet.png"


def test_runtime_frames_follow_curation_branch(tmp_path: Path) -> None:
    run = _make_animation_run(tmp_path / "run")
    branch = run / "frame-picker" / "20260602-000000" / "post-selection" / "20260602-000100"
    _write_json(branch / "export" / "manifest.json", {"version": 1})
    frames = branch / "frames-256x256"
    frames.mkdir(parents=True)
    (frames / "frame-01.png").write_bytes(b"png")
    artifacts = resolve_artifacts(run)
    assert artifacts.runtime_frames_dir == frames
