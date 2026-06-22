from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from spriterrific.anchor_wizard_gui import _asset_progress_label, _preview_sections, _run_status_lines, _stage_action_label, _status_bar_line


def test_run_status_lines_show_active_elapsed_and_heartbeat(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    command = logs / "fal-source.command.json"
    command.write_text(
        json.dumps(
            {
                "stage": "fal-source",
                "status": "running",
                "startedAt": "2026-04-29T13:43:41Z",
            }
        ),
        encoding="utf-8",
    )

    lines = _run_status_lines(
        tmp_path,
        poll_count=1,
        now=datetime(2026, 4, 29, 13, 44, 46, tzinfo=UTC),
    )

    assert any("command fal-source: running for 1m 05s" in line for line in lines)
    assert any("polling every 2s" in line for line in lines)
    assert _status_bar_line(lines).startswith("/")
    assert "command fal-source: running for 1m 05s" in _status_bar_line(lines)


def test_run_status_lines_show_fal_status_freshness(tmp_path: Path) -> None:
    fal = tmp_path / "source-fal"
    fal.mkdir()
    status = fal / "source-status.json"
    status.write_text(
        json.dumps({"status": "IN_PROGRESS", "request_id": "req-123"}),
        encoding="utf-8",
    )
    os.utime(status, (1_777_465_010, 1_777_465_010))

    lines = _run_status_lines(
        tmp_path,
        poll_count=2,
        now=datetime.fromtimestamp(1_777_465_020, UTC),
    )

    assert any("source-fal: IN_PROGRESS" in line for line in lines)
    assert any("request req-123" in line for line in lines)
    assert any("status updated 10s ago" in line for line in lines)


def test_preview_sections_use_reference_naming(tmp_path: Path) -> None:
    labels = [label for _section, assets in _preview_sections(tmp_path) for label, _path in assets]

    assert "Reference" in labels
    assert "Bootstrap Metadata" in labels
    assert "Raw Model Output" not in labels


def test_stage_action_label_includes_bootstrap_w() -> None:
    assert _stage_action_label("bootstrap", "source-image") == "Bootstrap Front + W"


def test_source_card_reports_source_generation_progress(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "fal-source.command.json").write_text(
        json.dumps({"stage": "fal-source", "status": "running"}),
        encoding="utf-8",
    )

    assert _asset_progress_label(tmp_path / "input" / "source.png", 0) == "| generating source"


def test_run_status_lines_include_nested_anchor_generation(tmp_path: Path) -> None:
    nested = tmp_path / "anchors-nsew"
    logs = nested / "logs"
    logs.mkdir(parents=True)
    (nested / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-04-29T14:11:15Z",
                        "event": "stage_started",
                        "stage": "fal-anchor-e",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (logs / "fal-anchor-e.command.json").write_text(
        json.dumps(
            {
                "stage": "fal-anchor-e",
                "status": "running",
                "startedAt": "2026-04-29T14:11:15Z",
            }
        ),
        encoding="utf-8",
    )

    lines = _run_status_lines(
        tmp_path,
        poll_count=0,
        now=datetime(2026, 4, 29, 14, 12, 20, tzinfo=UTC),
    )

    assert any("anchors-nsew: stage_started: fal-anchor-e" in line for line in lines)
    assert any("command anchors-nsew/fal-anchor-e: running for 1m 05s" in line for line in lines)
