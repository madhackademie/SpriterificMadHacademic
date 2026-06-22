from __future__ import annotations

import json
import mimetypes
import os
import re
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .bootstrap_anchors import bootstrap_options_from_mapping, run_bootstrap_anchors
from .events import now_iso, write_json

WEB_DIR = Path(__file__).parent / "web"
API_STATUS_FILE = "api-status.json"
ARTIFACT_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".json", ".md", ".png", ".txt"}
ARTIFACTS = {
    "source": Path("input/source.png"),
    "candidate-front": Path("candidate/front/snapped-1024-chroma.png"),
    "candidate-s": Path("candidate/s/snapped-1024-chroma.png"),
    "candidate-south": Path("candidate/s/snapped-1024-chroma.png"),
    "anchor-w": Path("anchors/w/anchor-snapped-1024-chroma.png"),
    "bootstrap-json": Path("bootstrap.json"),
    "character-json": Path("character.json"),
    "review": Path("review/bootstrap/index.md"),
}


def create_app(*, run_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="Spriterrific API", version=APP_VERSION)
    api_run_root = _api_run_root(run_root)
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def web_app() -> FileResponse:
        index = WEB_DIR / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="web app is not bundled")
        return FileResponse(index)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", **_app_info()}

    @app.get("/app-info")
    def app_info() -> dict[str, Any]:
        return _app_info()

    @app.get("/runs/{run_id}")
    def run_status(run_id: str) -> dict[str, Any]:
        run_dir = _run_dir_for_id(api_run_root, run_id)
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")
        return _run_status_response(run_id, run_dir)

    @app.get("/runs/{run_id}/artifacts/{artifact}")
    def run_artifact(run_id: str, artifact: str) -> FileResponse:
        artifact_path = _run_artifact_path(api_run_root, run_id, artifact)
        media_type = mimetypes.guess_type(artifact_path.name)[0]
        return FileResponse(artifact_path, media_type=media_type)

    @app.post("/bootstrap-anchors", status_code=status.HTTP_202_ACCEPTED)
    async def bootstrap_anchors(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            data = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="request body must be JSON") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="request body must be a JSON object")
        data = dict(data)
        run_id = _assign_api_run_dir(data, api_run_root)
        run_dir = api_run_root / run_id
        try:
            bootstrap_options_from_mapping(data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _write_api_status(
            run_dir,
            {
                "version": 1,
                "runId": run_id,
                "status": "queued",
                "createdAt": now_iso(),
                "updatedAt": now_iso(),
                "request": _public_request(data),
                "app": _app_info(),
            },
        )
        background_tasks.add_task(_run_bootstrap_job, api_run_root, run_id, data)
        return _run_status_response(run_id, run_dir)

    return app


def _package_version() -> str:
    try:
        return version("spriterrific")
    except PackageNotFoundError:
        return "0.0.0+local"


APP_VERSION = _package_version()


def _app_info() -> dict[str, Any]:
    deployment_id = os.environ.get("RAILWAY_DEPLOYMENT_ID") or os.environ.get("RAILWAY_SERVICE_ID")
    git_sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    sdk_version = os.environ.get("SPRITERRIFIC_SDK_VERSION") or APP_VERSION
    cli_version = os.environ.get("SPRITERRIFIC_CLI_VERSION") or APP_VERSION
    return {
        "version": APP_VERSION,
        "appVersion": APP_VERSION,
        "sdkVersion": sdk_version,
        "cliVersion": cli_version,
        "deploymentId": deployment_id,
        "gitSha": git_sha[:12] if git_sha else None,
        "service": os.environ.get("RAILWAY_SERVICE_NAME"),
    }


def _api_run_root(run_root: Path | None) -> Path:
    if run_root is not None:
        return run_root
    return Path(os.environ.get("SPRITERRIFIC_API_RUN_ROOT", "runs/api"))


def _assign_api_run_dir(data: dict[str, Any], run_root: Path) -> str:
    character = str(data.get("characterId") or data.get("character_id") or "character")
    label = str(data.get("runLabel") or data.get("run_label") or character)
    run_id = _new_api_run_id(label)
    data["runDir"] = str(run_root / run_id)
    return run_id


def _run_bootstrap_job(run_root: Path, run_id: str, data: dict[str, Any]) -> None:
    run_dir = run_root / run_id
    _write_api_status(
        run_dir,
        {
            **_read_api_status(run_dir),
            "runId": run_id,
            "status": "running",
            "startedAt": now_iso(),
            "updatedAt": now_iso(),
            "artifactUrls": _available_artifact_urls(run_id, run_dir),
        },
    )
    try:
        options = bootstrap_options_from_mapping(data)
        result = run_bootstrap_anchors(options)
    except Exception as exc:
        _write_api_status(
            run_dir,
            {
                **_read_api_status(run_dir),
                "runId": run_id,
                "status": "failed",
                "failedAt": now_iso(),
                "updatedAt": now_iso(),
                "error": str(exc),
                "artifactUrls": _available_artifact_urls(run_id, run_dir),
            },
        )
        return

    _write_api_status(
        run_dir,
        {
            **_read_api_status(run_dir),
            "runId": run_id,
            "status": "completed",
            "completedAt": now_iso(),
            "updatedAt": now_iso(),
            "artifactUrls": _available_artifact_urls(run_id, run_dir),
            "anchors": {direction: _artifact_url(run_id, f"anchor-{direction}") for direction in result.anchors},
        },
    )


def _run_status_response(run_id: str, run_dir: Path) -> dict[str, Any]:
    data = _read_api_status(run_dir)
    if not data:
        data = {
            "version": 1,
            "runId": run_id,
            "status": _infer_run_status(run_dir),
            "updatedAt": now_iso(),
        }
    data = dict(data)
    data["runId"] = run_id
    data["artifactUrls"] = _available_artifact_urls(run_id, run_dir)
    anchors = dict(data.get("anchors") or {})
    for direction in ("w",):
        artifact_name = f"anchor-{direction}"
        if artifact_name in data["artifactUrls"]:
            anchors[direction] = data["artifactUrls"][artifact_name]
    data["anchors"] = anchors
    data["pollUrl"] = f"/runs/{run_id}"
    return data


def _infer_run_status(run_dir: Path) -> str:
    bootstrap_json = run_dir / "bootstrap.json"
    if bootstrap_json.exists():
        try:
            data = json.loads(bootstrap_json.read_text(encoding="utf-8"))
        except Exception:
            return "completed"
        status = data.get("status")
        return str(status) if status else "completed"
    if run_dir.exists():
        return "running"
    return "unknown"


def _read_api_status(run_dir: Path) -> dict[str, Any]:
    path = run_dir / API_STATUS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_api_status(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / API_STATUS_FILE, data)


def _public_request(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key != "runDir"}


def _new_api_run_id(label: str) -> str:
    timestamp = datetime.now(ZoneInfo("Europe/London")).strftime("%Y%m%d-%H%M%S")
    slug = _slug(label) or "character"
    suffix = uuid4().hex[:8]
    return f"{timestamp}-api-bootstrap-{slug}-{suffix}"


def _slug(value: str) -> str:
    lowered = value.strip().lower().replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:48]


def _artifact_urls(run_id: str) -> dict[str, str]:
    return {artifact: _artifact_url(run_id, artifact) for artifact in ARTIFACTS}


def _available_artifact_urls(run_id: str, run_dir: Path) -> dict[str, str]:
    urls = {artifact: _artifact_url(run_id, artifact) for artifact, relative in ARTIFACTS.items() if (run_dir / relative).is_file()}
    if "candidate-front" in urls and "candidate-s" not in urls:
        urls["candidate"] = urls["candidate-front"]
    elif "candidate-s" in urls and "candidate" not in urls:
        urls["candidate"] = urls["candidate-s"]
    return urls


def _artifact_url(run_id: str, artifact: str) -> str:
    return f"/runs/{run_id}/artifacts/{artifact}"


def _run_artifact_path(run_root: Path, run_id: str, artifact: str) -> Path:
    run_dir = _run_dir_for_id(run_root, run_id)
    relative = ARTIFACTS.get(artifact)
    if relative is None and artifact == "candidate":
        for candidate_artifact in ("candidate-front", "candidate-s", "candidate-south"):
            candidate_relative = ARTIFACTS[candidate_artifact]
            if (run_dir / candidate_relative).is_file():
                relative = candidate_relative
                break
    if relative is None:
        raise HTTPException(status_code=404, detail="unknown artifact")
    path = run_dir / relative
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    root = run_root.resolve()
    if root not in resolved.parents:
        raise HTTPException(status_code=400, detail="artifact path escapes run root")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    if resolved.suffix.lower() not in ARTIFACT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="artifact type is not supported")
    return resolved


def _run_dir_for_id(run_root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    return run_root / run_id


app = create_app()
