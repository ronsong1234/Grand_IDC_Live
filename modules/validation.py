"""Validation helpers for the GrandQC-IDC study.

The functions in this module compare GrandQC label masks and summarize QC
behavior. They do not call or modify the inference path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from PIL import Image


CLASS_LABELS = {
    1: "normal_tissue",
    2: "fold",
    3: "darkspot_foreign_object",
    4: "pen_marking",
    5: "edge_air_bubble",
    6: "out_of_focus",
    7: "background",
}
ARTIFACT_CLASSES = (2, 3, 4, 5, 6)
TISSUE_CLASSES = (1, 2, 3, 4, 5, 6)
BACKGROUND_CLASS = 7
IGNORE_LABEL = 0


@dataclass(frozen=True)
class MaskPair:
    """Reference/prediction mask pair matched by TCGA slide barcode."""

    slide_id: str
    reference_path: Path
    prediction_path: Path


def extract_tcga_slide_id(path_or_name: str | Path) -> str:
    """Extract a TCGA slide barcode from a mask filename.

    Handles both GrandQC reference names such as
    ``TCGA-AC-A23G-01Z-00-DX1.<uuid>.svs_mask.png`` and dashboard names such
    as ``TCGA-AC-A23G-01Z-00-DX1_mask.png``.
    """

    name = Path(path_or_name).name
    match = re.search(r"(TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}-[A-Z0-9]{3}-[A-Z0-9]{2}-[A-Z0-9]{3})", name)
    if not match:
        raise ValueError(f"Could not extract TCGA slide id from {name}")
    return match.group(1)


def discover_mask_pairs(reference_dir: Path, prediction_dir: Path) -> list[MaskPair]:
    """Match reference and prediction masks by TCGA slide barcode."""

    refs = {extract_tcga_slide_id(path): path for path in sorted(reference_dir.glob("*.png"))}
    preds = {extract_tcga_slide_id(path): path for path in sorted(prediction_dir.glob("*.png"))}
    missing = sorted(set(refs) - set(preds))
    if missing:
        raise FileNotFoundError(f"Missing prediction masks for: {', '.join(missing)}")
    return [MaskPair(slide_id, refs[slide_id], preds[slide_id]) for slide_id in sorted(refs)]


def load_label_mask(path: Path) -> np.ndarray:
    """Load a single-channel integer GrandQC label mask."""

    arr = np.asarray(Image.open(path))
    if arr.ndim == 3:
        arr = arr[..., 0]
    return arr.astype(np.uint8, copy=False)


def align_prediction_to_reference(reference: np.ndarray, prediction: np.ndarray) -> np.ndarray:
    """Nearest-neighbor resize prediction if dimensions differ."""

    if reference.shape == prediction.shape:
        return prediction
    image = Image.fromarray(prediction.astype(np.uint8))
    resized = image.resize((reference.shape[1], reference.shape[0]), Image.Resampling.NEAREST)
    return np.asarray(resized, dtype=np.uint8)


def valid_mask(reference: np.ndarray, prediction: np.ndarray, labels: Iterable[int] = CLASS_LABELS) -> np.ndarray:
    """Pixels eligible for validation, excluding black padding/unknown labels."""

    label_set = np.array(list(labels), dtype=np.uint8)
    ref_valid = np.isin(reference, label_set)
    pred_valid = np.isin(prediction, label_set)
    return ref_valid & pred_valid


def dice_iou_for_class(reference: np.ndarray, prediction: np.ndarray, cls: int, valid: np.ndarray) -> dict[str, float | int]:
    """Compute one-vs-rest metrics for one class."""

    ref = (reference == cls) & valid
    pred = (prediction == cls) & valid
    tp = int(np.sum(ref & pred))
    fp = int(np.sum(~ref & pred & valid))
    fn = int(np.sum(ref & ~pred & valid))
    tn = int(np.sum(~ref & ~pred & valid))
    denom_dice = (2 * tp + fp + fn)
    denom_iou = (tp + fp + fn)
    precision = tp / (tp + fp) if (tp + fp) else np.nan
    recall = tp / (tp + fn) if (tp + fn) else np.nan
    dice = (2 * tp) / denom_dice if denom_dice else np.nan
    iou = tp / denom_iou if denom_iou else np.nan
    return {
        "class_id": cls,
        "class_name": CLASS_LABELS[cls],
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "reference_px": int(np.sum(ref)),
        "prediction_px": int(np.sum(pred)),
        "dice": float(dice) if not np.isnan(dice) else np.nan,
        "iou": float(iou) if not np.isnan(iou) else np.nan,
        "precision": float(precision) if not np.isnan(precision) else np.nan,
        "recall": float(recall) if not np.isnan(recall) else np.nan,
        "f1": float(dice) if not np.isnan(dice) else np.nan,
    }


def compare_mask_pair(pair: MaskPair) -> tuple[pd.DataFrame, dict[str, float | int | str], np.ndarray]:
    """Compare one reference/prediction mask pair."""

    reference = load_label_mask(pair.reference_path)
    prediction = align_prediction_to_reference(reference, load_label_mask(pair.prediction_path))
    valid = valid_mask(reference, prediction)
    rows = []
    for cls in CLASS_LABELS:
        row = dice_iou_for_class(reference, prediction, cls, valid)
        row["slide_id"] = pair.slide_id
        rows.append(row)
    class_df = pd.DataFrame(rows)
    confusion = confusion_matrix(reference, prediction, valid)
    agreement = float(np.mean(reference[valid] == prediction[valid])) if np.any(valid) else np.nan
    macro = float(class_df["dice"].mean(skipna=True))
    macro_no_bg = float(class_df.loc[class_df["class_id"] != BACKGROUND_CLASS, "dice"].mean(skipna=True))
    tissue_weights = class_df.loc[class_df["class_id"].isin(TISSUE_CLASSES), "reference_px"].astype(float)
    tissue_dice = class_df.loc[class_df["class_id"].isin(TISSUE_CLASSES), "dice"].astype(float)
    weighted = float(np.average(tissue_dice.fillna(0), weights=tissue_weights)) if tissue_weights.sum() else np.nan
    summary = {
        "slide_id": pair.slide_id,
        "valid_px": int(np.sum(valid)),
        "ignored_px": int(reference.size - np.sum(valid)),
        "pixel_agreement": agreement,
        "macro_dice": macro,
        "macro_dice_excluding_background": macro_no_bg,
        "tissue_weighted_dice": weighted,
    }
    return class_df, summary, confusion


def confusion_matrix(reference: np.ndarray, prediction: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Return a 7x7 raw confusion matrix, rows=reference and cols=prediction."""

    matrix = np.zeros((len(CLASS_LABELS), len(CLASS_LABELS)), dtype=np.int64)
    ref = reference[valid]
    pred = prediction[valid]
    for r, p in zip(ref, pred):
        matrix[int(r) - 1, int(p) - 1] += 1
    return matrix


def normalize_confusion(matrix: np.ndarray) -> pd.DataFrame:
    """Row-normalize a confusion matrix as a tidy DataFrame."""

    totals = matrix.sum(axis=1, keepdims=True)
    norm = np.divide(matrix, totals, out=np.zeros_like(matrix, dtype=float), where=totals != 0)
    labels = [CLASS_LABELS[i] for i in CLASS_LABELS]
    return pd.DataFrame(norm, index=labels, columns=labels)


def aggregate_validation(pairs: list[MaskPair]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Compare all mask pairs and return per-slide, per-class, confusion tables."""

    class_tables = []
    slide_rows = []
    aggregate_confusion = np.zeros((len(CLASS_LABELS), len(CLASS_LABELS)), dtype=np.int64)
    for pair in pairs:
        class_df, slide_summary, confusion = compare_mask_pair(pair)
        class_tables.append(class_df)
        slide_rows.append(slide_summary)
        aggregate_confusion += confusion
    per_class = pd.concat(class_tables, ignore_index=True)
    per_slide = pd.DataFrame(slide_rows)
    confusion_df = normalize_confusion(aggregate_confusion).reset_index(names="reference_class")
    return per_slide, per_class, confusion_df, aggregate_confusion


def apply_review_flag(row: pd.Series, single_class_threshold: float = 0.60, total_threshold: float = 0.90) -> tuple[bool, str]:
    """Apply the documented manual-review flag rule to a summary row."""

    reasons = []
    total = float(row.get("artifact_percentage_of_tissue", 0.0) or 0.0)
    if total > total_threshold:
        reasons.append(f"total artifact fraction {total:.3f} > {total_threshold:.2f}")
    for class_name in ["fold", "darkspot_foreign_object", "pen_marking", "edge_air_bubble", "out_of_focus"]:
        value = float(row.get(f"{class_name}_fraction", 0.0) or 0.0)
        if value > single_class_threshold:
            reasons.append(f"{class_name} fraction {value:.3f} > {single_class_threshold:.2f}")
    return bool(reasons), "; ".join(reasons)


def summarize_flag_precision(summary_df: pd.DataFrame, clean_slide_ids: Iterable[str]) -> dict[str, float | int]:
    """Report available-set flag precision using known-clean validated slides."""

    clean_set = set(clean_slide_ids)
    flags = summary_df.apply(lambda row: apply_review_flag(row)[0], axis=1)
    expected_positive = ~summary_df["slide_id"].isin(clean_set)
    tp = int(np.sum(flags & expected_positive))
    fp = int(np.sum(flags & ~expected_positive))
    fn = int(np.sum(~flags & expected_positive))
    precision = tp / (tp + fp) if (tp + fp) else np.nan
    recall = tp / (tp + fn) if (tp + fn) else np.nan
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}
