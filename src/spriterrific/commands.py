from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .events import append_event, now_iso, write_json


@dataclass(frozen=True)
class CommandResult:
    stage: str
    args: list[str]
    exit_code: int
    stdout_path: Path
    stderr_path: Path


SAFE_ENV_KEYS = ("FAL_KEY", "FAL_API_KEY", "REMOVE_BG_API_KEY")
_ENV_LOADED = False


def run_command(
    args: list[str],
    *,
    stage: str,
    run_dir: Path,
    events_path: Path,
    cwd: Path | None = None,
) -> CommandResult:
    _load_repo_env()
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    safe_stage = stage.replace("/", "-").replace(" ", "-")
    stdout_path = logs_dir / f"{safe_stage}.stdout.txt"
    stderr_path = logs_dir / f"{safe_stage}.stderr.txt"
    command_path = logs_dir / f"{safe_stage}.command.json"

    started_at = now_iso()
    append_event(events_path, "stage_started", stage=stage, args=args)
    write_json(
        command_path,
        {
            "stage": stage,
            "args": args,
            "cwd": str(cwd) if cwd else None,
            "status": "running",
            "startedAt": started_at,
            "updatedAt": started_at,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "envPresent": {key: bool(os.environ.get(key)) for key in SAFE_ENV_KEYS},
        },
    )
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result = CommandResult(stage, args, completed.returncode, stdout_path, stderr_path)
    write_json(
        command_path,
        {
            "stage": stage,
            "args": args,
            "cwd": str(cwd) if cwd else None,
            "status": "completed" if completed.returncode == 0 else "failed",
            "startedAt": started_at,
            "completedAt": now_iso(),
            "exitCode": completed.returncode,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "envPresent": {key: bool(os.environ.get(key)) for key in SAFE_ENV_KEYS},
        },
    )

    if completed.returncode != 0:
        append_event(events_path, "stage_failed", stage=stage, exitCode=completed.returncode)
        raise RuntimeError(f"{stage} failed with exit code {completed.returncode}; see {stderr_path}")

    append_event(events_path, "stage_completed", stage=stage, exitCode=completed.returncode)
    return result


def _load_repo_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
