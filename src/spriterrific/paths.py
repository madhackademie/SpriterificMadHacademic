from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .presets import VIDEO_PLATE_SIZE


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def run_id(self) -> str:
        return self.root.name

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def direction_dir(self) -> Path:
        return self.root / "direction"

    @property
    def guide_dir(self) -> Path:
        return self.root / "guide"

    @property
    def anchors_dir(self) -> Path:
        return self.root / "anchors"

    @property
    def fal_dir(self) -> Path:
        return self.root / "fal"

    @property
    def generated_dir(self) -> Path:
        return self.root / "generated"

    @property
    def extracted_dense_dir(self) -> Path:
        return self.root / "extracted" / "dense-frames"

    @property
    def selected_dir(self) -> Path:
        return self.root / "selected"

    @property
    def selection_manifest(self) -> Path:
        return self.selected_dir / "selection.json"

    @property
    def recovered_dir(self) -> Path:
        return self.root / "recovered"

    @property
    def recovered_native_dir(self) -> Path:
        return self.root / "recovered-native"

    @property
    def recovered_native_frames_dir(self) -> Path:
        return self.recovered_native_dir / "frames"

    @property
    def recovered_native_metadata(self) -> Path:
        return self.recovered_native_dir / "metadata.json"

    @property
    def pixel_snapped_dir(self) -> Path:
        return self.root / "pixel-snapped"

    @property
    def pixel_snap_source_dir(self) -> Path:
        return self.pixel_snapped_dir / "source"

    @property
    def pixel_snapped_native_dir(self) -> Path:
        return self.pixel_snapped_dir / "native"

    @property
    def pixel_snapped_keyed_dir(self) -> Path:
        return self.pixel_snapped_dir / "keyed"

    @property
    def pixel_snapped_fringe_cleaned_dir(self) -> Path:
        return self.pixel_snapped_dir / "green-fringe-cleaned"

    @property
    def pixel_snapped_native_frames_dir(self) -> Path:
        return self.pixel_snapped_dir / "native-layout"

    @property
    def pixel_snapped_native_metadata(self) -> Path:
        return self.pixel_snapped_dir / "native-layout-metadata.json"

    @property
    def grid_review_cells_dir(self) -> Path:
        return self.root / "sheet-cells" / "grid-review"

    @property
    def bg_removed_dir(self) -> Path:
        return self.root / "bg-removed"

    @property
    def chroma_dir(self) -> Path:
        return self.root / "chroma-keyed"

    @property
    def normalized_dir(self) -> Path:
        return self.root / "normalized"

    @property
    def scaled_dir(self) -> Path:
        return self.root / "scaled"

    @property
    def review_dir(self) -> Path:
        return self.root / "review"

    @property
    def export_dir(self) -> Path:
        return self.root / "export"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def run_json(self) -> Path:
        return self.root / "run.json"

    @property
    def events_jsonl(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def source_image(self) -> Path:
        return self.input_dir / "source.png"

    @property
    def raw_source_image(self) -> Path:
        return self.input_dir / "source-original.png"

    @property
    def preprocess_metadata(self) -> Path:
        return self.input_dir / "preprocess-metadata.json"

    @property
    def prompt_text(self) -> Path:
        return self.input_dir / "prompt.txt"

    @property
    def direction_anchor(self) -> Path:
        return self.direction_dir / "anchor.png"

    @property
    def video_plate(self) -> Path:
        width, height = VIDEO_PLATE_SIZE
        return self.direction_dir / f"plate-{width}x{height}.png"

    @property
    def end_reference(self) -> Path:
        return self.input_dir / "end-reference.png"

    @property
    def end_video_plate(self) -> Path:
        width, height = VIDEO_PLATE_SIZE
        return self.direction_dir / f"end-plate-{width}x{height}.png"

    @property
    def generated_sheet(self) -> Path:
        return self.generated_dir / "sheet.png"

    @property
    def raw_video(self) -> Path:
        return self.fal_dir / "raw-video.mp4"

    @property
    def export_sheet_raw(self) -> Path:
        return self.export_dir / "spritesheet.raw.png"

    @property
    def export_sheet(self) -> Path:
        return self.export_dir / "spritesheet.png"

    @property
    def export_preview(self) -> Path:
        return self.export_dir / "preview.gif"

    @property
    def review_contact(self) -> Path:
        return self.review_dir / "contact.png"

    @property
    def review_preview(self) -> Path:
        return self.review_dir / "preview.gif"

    @property
    def review_selected_contact(self) -> Path:
        return self.review_dir / "selected-contact.png"

    @property
    def review_selected_preview(self) -> Path:
        return self.review_dir / "selected-preview.gif"

    @property
    def export_manifest(self) -> Path:
        return self.export_dir / "manifest.json"

    @property
    def baseline_report(self) -> Path:
        return self.export_dir / "baseline-report.json"


def create_run_paths(run_dir: Path) -> RunPaths:
    paths = RunPaths(run_dir)
    for directory in [
        paths.input_dir,
        paths.direction_dir,
        paths.guide_dir,
        paths.anchors_dir,
        paths.fal_dir,
        paths.generated_dir,
        paths.extracted_dense_dir,
        paths.selected_dir,
        paths.recovered_dir,
        paths.recovered_native_frames_dir,
        paths.pixel_snap_source_dir,
        paths.pixel_snapped_native_dir,
        paths.pixel_snapped_keyed_dir,
        paths.pixel_snapped_fringe_cleaned_dir,
        paths.pixel_snapped_native_frames_dir,
        paths.grid_review_cells_dir,
        paths.bg_removed_dir,
        paths.chroma_dir,
        paths.scaled_dir,
        paths.normalized_dir,
        paths.review_dir,
        paths.export_dir,
        paths.logs_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    return paths
