from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .events import append_event, now_iso, write_json


ENDPOINT_ID = "fal-ai/bria/background/remove"
QUEUE_BASE = f"https://queue.fal.run/{ENDPOINT_ID}"


def require_fal_key() -> str:
    key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not key:
        raise RuntimeError("FAL_KEY or FAL_API_KEY is required for Bria background removal")
    return key


def image_data_uri(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def fal_request(method: str, url: str, api_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
            "X-Fal-Store-IO": "1",
            "x-app-fal-disable-fallback": "true",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"fal request failed: HTTP {exc.code} {exc.reason}: {detail}") from exc


def download(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=180) as response:
        out.write_bytes(response.read())


def remove_background_batch(
    input_dir: Path,
    out_dir: Path,
    *,
    run_dir: Path,
    events_path: Path,
    glob: str = "frame-*.png",
    poll_interval: float = 3.0,
    timeout: int = 900,
) -> list[Path]:
    frames = sorted(input_dir.glob(glob))
    if not frames:
        raise ValueError(f"no frames matched {glob} in {input_dir}")

    api_key = require_fal_key()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = run_dir / "fal" / "bria-bg-remove"
    raw_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    records: list[dict[str, Any]] = []
    for frame in frames:
        frame_id = frame.stem
        out = out_dir / frame.name
        if out.exists():
            record = {
                "timestamp": now_iso(),
                "endpointId": ENDPOINT_ID,
                "input": str(frame),
                "status": "skipped_existing",
                "requestId": None,
                "output": str(out),
                "rawFiles": {},
            }
            records.append(record)
            append_event(events_path, "bria_bg_remove_skipped_existing", frame=str(frame), output=str(out))
            continue
        append_event(events_path, "bria_bg_remove_started", frame=str(frame))
        manifest_path = raw_dir / f"{frame_id}-run.json"
        record: dict[str, Any] = {
            "timestamp": now_iso(),
            "endpointId": ENDPOINT_ID,
            "input": str(frame),
            "status": "pending",
            "requestId": None,
            "output": None,
            "rawFiles": {},
        }
        write_json(manifest_path, record)

        create = fal_request("POST", QUEUE_BASE, api_key, {"image_url": image_data_uri(frame), "sync_mode": False})
        request_id = create.get("request_id")
        if not isinstance(request_id, str):
            raise RuntimeError(f"Bria queue response did not include request_id for {frame}")
        status_url = create.get("status_url") or f"{QUEUE_BASE}/requests/{request_id}/status"
        response_url = create.get("response_url") or f"{QUEUE_BASE}/requests/{request_id}"
        if not isinstance(status_url, str) or not isinstance(response_url, str):
            raise RuntimeError(f"Bria queue response did not include status/response URLs for {frame}")
        create_path = raw_dir / f"{frame_id}-create.json"
        write_json(create_path, create)
        record["requestId"] = request_id
        record["status"] = "submitted"
        record["rawFiles"]["create"] = str(create_path)
        write_json(manifest_path, record)

        deadline = time.time() + timeout
        while True:
            status = fal_request("GET", status_url, api_key)
            status_path = raw_dir / f"{frame_id}-status.json"
            write_json(status_path, status)
            record["status"] = str(status.get("status", "")).lower() or "unknown"
            record["rawFiles"]["status"] = str(status_path)
            write_json(manifest_path, record)
            if str(status.get("status", "")).upper() == "COMPLETED":
                break
            if time.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for Bria request {request_id}")
            time.sleep(poll_interval)

        result = fal_request("GET", response_url, api_key)
        result_path = raw_dir / f"{frame_id}-final.json"
        write_json(result_path, result)
        image = result.get("image")
        image_url = image.get("url") if isinstance(image, dict) else None
        if not isinstance(image_url, str):
            raise RuntimeError(f"Bria result did not include image.url for {frame}")
        download(image_url, out)
        record["status"] = "completed"
        record["output"] = str(out)
        record["rawFiles"]["final"] = str(result_path)
        write_json(manifest_path, record)
        records.append(record)
        outputs.append(out)
        append_event(events_path, "bria_bg_remove_completed", frame=str(frame), output=str(out))

    write_json(out_dir / "bria-bg-remove-metadata.json", records)
    return outputs
