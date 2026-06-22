from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def append_event(events_path: Path, event: str, **fields: Any) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now_iso(), "event": event, **fields}
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
