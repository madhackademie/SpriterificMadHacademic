from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from spriterrific import bria


def test_remove_background_batch_records_outputs(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("FAL_KEY", "test-key")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(source_dir / "frame-01.png")

    calls: list[tuple[str, str]] = []

    def fake_fal_request(method: str, url: str, api_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((method, url))
        if method == "POST":
            assert payload and str(payload["image_url"]).startswith("data:image/png;base64,")
            return {"request_id": "req-1"}
        if url.endswith("/status"):
            return {"status": "COMPLETED"}
        return {"image": {"url": "https://example.test/out.png"}}

    def fake_download(url: str, out: Path) -> None:
        Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(out)

    monkeypatch.setattr(bria, "fal_request", fake_fal_request)
    monkeypatch.setattr(bria, "download", fake_download)

    outputs = bria.remove_background_batch(
        source_dir,
        tmp_path / "out",
        run_dir=tmp_path,
        events_path=tmp_path / "events.jsonl",
    )

    assert outputs == [tmp_path / "out" / "frame-01.png"]
    assert outputs[0].is_file()
    assert (tmp_path / "out" / "bria-bg-remove-metadata.json").is_file()
    assert calls[0][0] == "POST"
