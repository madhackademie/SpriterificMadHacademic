from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def timestamp_slug() -> str:
    return datetime.now(ZoneInfo("Europe/London")).strftime("%Y%m%d-%H%M%S")


def default_run_dir(kind: str, parts: list[str]) -> Path:
    safe_parts = [part.strip().lower().replace("_", "-") for part in parts if part.strip()]
    return Path("runs") / f"{timestamp_slug()}-{kind}-{'-'.join(safe_parts)}"
