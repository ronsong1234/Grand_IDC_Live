"""Thin live-dashboard wrapper around the validated GrandQC direct-DICOM path."""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from PIL import Image

from modules import grandqc_qc
from modules.dicom_to_tiff import download_idc_series

from .config import (
    ARTIFACT_COLUMNS,
    ARTIFACT_FILE_MAP,
    ARTIFACT_LABELS,
    CLASS_COLORS,
    DEFAULT_USABILITY_THRESHOLD,
    OUTPUT_DIR,
    OVERALL_ARTIFACT_FLAG_THRESHOLD,
    RAW_INPUT_DIR,
    RETAIN_RAW_INPUTS,
    SINGLE_CLASS_FLAG_THRESHOLD,
)
from .idc_catalog import find_slide, safe_name, safe_slide_dir

MODEL_CACHE: dict[tuple[float, str], tuple[Any, Any, Any]] = {}


def run_slide_job(
    *,
    collection_id: str,
    series_instance_uid: str,
    artifact_mpp: float,
    force: bool,
    progress: Callable[[str, str], None],
) -> dict[str, Any]:
    slide_meta = find_slide(collection_id, series_instance_uid)
    slide_id = slide_meta["slide_id"]
    slide_dir = safe_slide_dir(collection_id, slide_id)
    if not force and completed_result_exists(slide_dir):
        progress("done", "Using existing outputs")
        return load_result(slide_dir)

    slide_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ["mask_qc", "tiles", "summaries", "overlays_qc", "maps_qc", "tis_det_thumbnail"]:
        (slide_dir / subdir).mkdir(parents=True, exist_ok=True)

    raw_root = RAW_INPUT_DIR / safe_name(collection_id) / safe_name(slide_id)
    series_dir: Path | None = None
    started = time.perf_counter()
    try:
        progress("downloading", "Downloading IDC DICOM series")
        manifest = download_idc_series(series_instance_uid, download_dir=raw_root)
        series_dir = Path(manifest.iloc[0]["series_dir"])

        progress("running_qc", "Running GrandQC direct-DICOM inference")
        device = grandqc_qc._default_device()
        grandqc_qc.check_weights(artifact_mpp=artifact_mpp)
        tissue_model, artifact_model, preprocessing_fn = get_model_bundle(artifact_mpp, device)
        slide = grandqc_qc.open_slide(series_dir, input_type="dicom", slide_id=slide_id)
        try:
            result = grandqc_qc.score_slide(
                slide,
                tissue_model=tissue_model,
                artifact_model=artifact_model,
                preprocessing_fn=preprocessing_fn,
                artifact_mpp=artifact_mpp,
                device=device,
                usability_artifact_threshold=DEFAULT_USABILITY_THRESHOLD,
            )
            thumb_w = min(1000, max(1, int(slide.width)))
            thumb_h = max(1, int(round(slide.height * (thumb_w / slide.width))))
            slide_thumbnail = grandqc_qc._make_thumbnail_streamed(slide, thumb_w, thumb_h)
        finally:
            close = getattr(slide, "close", None)
            if close is not None:
                close()

        progress("rendering", "Rendering mask, map, overlay, and thumbnail")
        summary = result.summary.copy()
        for key, value in slide_meta.items():
            if key not in summary.columns:
                summary[key] = value
        summary["reader_path_used"] = "dicom"
        summary["runtime_seconds"] = round(time.perf_counter() - started, 3)
        summary["raw_dicom_inputs_kept"] = bool(RETAIN_RAW_INPUTS)
        summary = add_review_flags(summary)

        mask_path = slide_dir / "mask_qc" / f"{slide_id}_mask.png"
        tile_path = slide_dir / "tiles" / f"{slide_id}_tiles.parquet"
        summary_path = slide_dir / "summaries" / f"{slide_id}_summary.parquet"
        Image.fromarray(result.mask.astype(np.uint8)).save(mask_path)
        result.tile_scores.to_parquet(tile_path, index=False)
        summary["mask_path"] = rel_to_output(mask_path)
        summary["tile_parquet_path"] = rel_to_output(tile_path)
        summary["per_slide_summary_path"] = rel_to_output(summary_path)
        summary.to_parquet(summary_path, index=False)

        render_images(slide_dir, slide_id, result.mask, slide_thumbnail)
        payload = build_payload(slide_dir, summary.iloc[0].to_dict())
        write_json(slide_dir / "summary.json", payload)
        assert_no_absolute_paths(payload)
        return payload
    finally:
        if not RETAIN_RAW_INPUTS:
            if series_dir is not None and series_dir.exists():
                remove_tree(series_dir)
            if raw_root.exists():
                try:
                    remove_tree(raw_root)
                except Exception:
                    pass


def get_model_bundle(artifact_mpp: float, device: str):
    key = (artifact_mpp, device)
    if key not in MODEL_CACHE:
        MODEL_CACHE[key] = grandqc_qc._load_models(artifact_mpp, device)
    return MODEL_CACHE[key]


def add_review_flags(summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    reasons = []
    for _, row in out.iterrows():
        row_reasons = []
        total = float(row.get("artifact_percentage_of_tissue", 0.0) or 0.0)
        if total > OVERALL_ARTIFACT_FLAG_THRESHOLD:
            row_reasons.append(f"total artifact fraction {total:.3f} > {OVERALL_ARTIFACT_FLAG_THRESHOLD:.2f}")
        values = {col: float(row.get(col, 0.0) or 0.0) for col in ARTIFACT_COLUMNS}
        dominant_col, dominant_value = max(values.items(), key=lambda item: item[1])
        if dominant_value > SINGLE_CLASS_FLAG_THRESHOLD:
            row_reasons.append(f"{ARTIFACT_LABELS[dominant_col]} fraction {dominant_value:.3f} > {SINGLE_CLASS_FLAG_THRESHOLD:.2f}")
        reasons.append("; ".join(row_reasons))
    out["qc_flag_reason"] = reasons
    out["qc_flag_review"] = out["qc_flag_reason"].astype(bool)
    return out


def render_images(slide_dir: Path, slide_id: str, mask: np.ndarray, slide_thumbnail: Image.Image) -> None:
    mask_rgb = colorize_mask(mask)
    Image.fromarray(mask.astype(np.uint8)).save(slide_dir / "mask_qc" / f"{slide_id}_mask.png")
    Image.fromarray(mask_rgb).save(slide_dir / "maps_qc" / f"{slide_id}_map_QC.png")

    thumb = slide_thumbnail.convert("RGB")
    thumb.save(slide_dir / "tis_det_thumbnail" / f"{slide_id}.jpg", quality=90)
    overlay_mask = Image.fromarray(mask_rgb).resize(thumb.size, Image.Resampling.NEAREST).convert("RGB")
    overlay = Image.blend(thumb, overlay_mask, 0.35)
    overlay.save(slide_dir / "overlays_qc" / f"{slide_id}_overlay_QC.jpg", quality=90)


def colorize_mask(mask: np.ndarray) -> np.ndarray:
    rgb = np.zeros((*mask.shape, 3), dtype=np.uint8)
    for cls, color in CLASS_COLORS.items():
        rgb[mask == cls] = color
    return rgb


def make_mask_thumbnail(mask_rgb: np.ndarray, max_width: int = 1000) -> Image.Image:
    image = Image.fromarray(mask_rgb)
    scale = min(1.0, max_width / max(image.width, 1))
    if scale < 1.0:
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.NEAREST)
    return image.convert("RGB")


def build_payload(slide_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    slide_id = str(row["slide_id"])
    artifacts = {name: f"/api/results/{slide_id}/{name}" for name in ARTIFACT_FILE_MAP}
    payload = {
        "slide_id": slide_id,
        "collection_id": str(row.get("collection_id") or ""),
        "SeriesInstanceUID": str(row.get("SeriesInstanceUID") or ""),
        "StudyInstanceUID": str(row.get("StudyInstanceUID") or ""),
        "PatientID": str(row.get("PatientID") or ""),
        "tissue_percentage": as_float(row.get("tissue_percentage")),
        "artifact_percentage_of_tissue": as_float(row.get("artifact_percentage_of_tissue")),
        "usable": bool(row.get("usable")),
        "qc_flag_review": bool(row.get("qc_flag_review")),
        "qc_flag_reason": str(row.get("qc_flag_reason") or ""),
        "slim_url": str(row.get("slim_url") or ""),
        "reader_path_used": str(row.get("reader_path_used") or "dicom"),
        "runtime_seconds": as_float(row.get("runtime_seconds")),
        "raw_dicom_inputs_kept": bool(row.get("raw_dicom_inputs_kept")),
        "artifact_fractions": {col: as_float(row.get(col)) for col in ARTIFACT_COLUMNS},
        "artifact_urls": artifacts,
        "relative_output_dir": rel_to_output(slide_dir),
        "summary_url": f"/api/results/{slide_id}/summary",
    }
    return json_safe(payload)


def completed_result_exists(slide_dir: Path) -> bool:
    return (slide_dir / "summary.json").exists() and all((slide_dir / pattern.format(slide_id=slide_dir.name)).exists() for pattern in ARTIFACT_FILE_MAP.values())


def load_result(slide_dir: Path) -> dict[str, Any]:
    return json.loads((slide_dir / "summary.json").read_text(encoding="utf-8"))


def result_for_slide_id(slide_id: str) -> dict[str, Any] | None:
    matches = list(OUTPUT_DIR.glob(f"*/{safe_name(slide_id)}/summary.json"))
    if not matches:
        return None
    return json.loads(matches[0].read_text(encoding="utf-8"))


def artifact_path(slide_id: str, artifact_name: str) -> Path | None:
    if artifact_name not in ARTIFACT_FILE_MAP:
        return None
    matches = list(OUTPUT_DIR.glob(f"*/{safe_name(slide_id)}"))
    if not matches:
        return None
    path = matches[0] / ARTIFACT_FILE_MAP[artifact_name].format(slide_id=safe_name(slide_id))
    return path if path.exists() else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def rel_to_output(path: Path) -> str:
    return path.relative_to(OUTPUT_DIR).as_posix()


def as_float(value: Any) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def json_safe(value: Any):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def assert_no_absolute_paths(payload: dict[str, Any]) -> None:
    text = json.dumps(payload)
    if "C:\\" in text or "C:/" in text:
        raise AssertionError("Absolute Windows path leaked into API payload")


def remove_tree(path: Path) -> None:
    def onerror(function, item, exc_info):
        os.chmod(item, stat.S_IWRITE)
        function(item)

    shutil.rmtree(path, onerror=onerror)
