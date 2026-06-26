"""Run the BRCA GrandQC reference-mask validation study.

Default mode compares the committed cached direct-DICOM prediction masks against
the five GrandQC BRCA reference masks. Use ``--run-inference`` to regenerate
predictions through the existing direct-DICOM wrapper before scoring.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from modules.validation import (
    ARTIFACT_CLASSES,
    aggregate_validation,
    discover_mask_pairs,
    extract_tcga_slide_id,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "data" / "reference_brca" / "reference_masks"
PREDICTION_DIR = REPO_ROOT / "data" / "reference_brca" / "predicted_masks"
OUTPUT_DIR = REPO_ROOT / "outputs" / "validation"


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_dir = args.prediction_dir
    if args.run_inference:
        prediction_dir = regenerate_predictions(args.reference_dir, output_dir, args.artifact_mpp)

    pairs = discover_mask_pairs(args.reference_dir, prediction_dir)
    per_slide, per_class, confusion_norm, confusion_raw = aggregate_validation(pairs)

    per_slide.to_parquet(output_dir / "validation_per_slide.parquet", index=False)
    per_class.to_parquet(output_dir / "validation_per_class.parquet", index=False)
    confusion_norm.to_parquet(output_dir / "confusion_matrix.parquet", index=False)
    np.save(output_dir / "confusion_matrix_raw.npy", confusion_raw)
    write_confusion_heatmap(confusion_norm, output_dir / "confusion_matrix.png")
    write_report(per_slide, per_class, confusion_norm, confusion_raw, output_dir / "validation_report.md", pairs)
    metadata = {
        "reference_dir": relative(args.reference_dir),
        "prediction_dir": relative(prediction_dir),
        "run_inference": args.run_inference,
        "artifact_mpp": args.artifact_mpp,
        "slide_count": len(pairs),
    }
    (output_dir / "validation_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Wrote validation outputs to {relative(output_dir)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--prediction-dir", type=Path, default=PREDICTION_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--artifact-mpp", type=float, default=1.5)
    parser.add_argument("--run-inference", action="store_true", help="Regenerate prediction masks through direct-DICOM GrandQC.")
    return parser.parse_args()


def regenerate_predictions(reference_dir: Path, output_dir: Path, artifact_mpp: float) -> Path:
    """Regenerate validation masks through existing direct-DICOM live wrapper."""

    from web.backend.idc_catalog import get_client
    from web.backend.qc_runner import run_slide_job

    prediction_dir = output_dir / "regenerated_masks"
    prediction_dir.mkdir(parents=True, exist_ok=True)
    client = get_client()
    slide_ids = [extract_tcga_slide_id(path) for path in sorted(reference_dir.glob("*.png"))]
    for slide_id in slide_ids:
        query = f"""
            SELECT i.collection_id, i.SeriesInstanceUID
            FROM index i
            JOIN sm_index s ON i.SeriesInstanceUID = s.SeriesInstanceUID
            WHERE i.Modality = 'SM'
              AND s.ContainerIdentifier = '{slide_id}'
            LIMIT 1
        """
        df = client.sql_query(query)
        if df.empty:
            raise RuntimeError(f"Could not find IDC series for {slide_id}")
        row = df.iloc[0]
        payload = run_slide_job(
            collection_id=str(row["collection_id"]),
            series_instance_uid=str(row["SeriesInstanceUID"]),
            artifact_mpp=artifact_mpp,
            force=True,
            progress=lambda state, message: print(f"{slide_id}: {state} - {message}"),
        )
        source = REPO_ROOT / "web" / "output" / payload["relative_output_dir"] / "mask_qc" / f"{slide_id}_mask.png"
        target = prediction_dir / f"{slide_id}_mask.png"
        target.write_bytes(source.read_bytes())
    return prediction_dir


def write_confusion_heatmap(confusion: pd.DataFrame, path: Path) -> None:
    labels = confusion["reference_class"].tolist()
    values = confusion.drop(columns=["reference_class"]).to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(values, vmin=0, vmax=1, cmap="viridis")
    ax.set_xticks(range(len(labels)), labels=labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels=labels)
    ax.set_xlabel("Predicted class")
    ax.set_ylabel("Reference class")
    ax.set_title("GrandQC BRCA Validation Confusion Matrix")
    fig.colorbar(im, ax=ax, label="Row-normalized fraction")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_report(
    per_slide: pd.DataFrame,
    per_class: pd.DataFrame,
    confusion_norm: pd.DataFrame,
    confusion_raw: np.ndarray,
    path: Path,
    pairs: list,
) -> None:
    slide_mean = per_slide["macro_dice"].mean()
    slide_std = per_slide["macro_dice"].std(ddof=1)
    no_bg_mean = per_slide["macro_dice_excluding_background"].mean()
    no_bg_std = per_slide["macro_dice_excluding_background"].std(ddof=1)
    min_slide = per_slide.sort_values("macro_dice").iloc[0]
    class_summary = (
        per_class.groupby(["class_id", "class_name"], as_index=False)
        .agg(dice_mean=("dice", "mean"), dice_std=("dice", "std"), iou_mean=("iou", "mean"), reference_px=("reference_px", "sum"))
        .sort_values("dice_mean")
    )
    worst_class = class_summary.iloc[0]
    tissue_classes = per_class[per_class["class_id"].isin(ARTIFACT_CLASSES + (1,))]
    tissue_macro = tissue_classes.groupby("slide_id")["dice"].mean().mean()
    total_valid = int(confusion_raw.sum())

    lines = [
        "# GrandQC-IDC BRCA Reference-Mask Validation",
        "",
        "## Scope",
        "",
        "This validation compares the GrandQC-IDC direct-DICOM output masks against five GrandQC BRCA DX reference masks. The reference masks are treated as ground truth for this comparison only. This validates the direct-DICOM wrapper on this narrow BRCA DX set; it does not validate frozen sections, other organs, TIFF conversion, or external/manual pathologist truth.",
        "",
        "## Headline Results",
        "",
        f"- Slides validated: {len(pairs)} BRCA DX slides.",
        f"- Macro Dice across all classes: {slide_mean:.6f} +/- {slide_std:.6f}.",
        f"- Macro Dice excluding background: {no_bg_mean:.6f} +/- {no_bg_std:.6f}.",
        f"- Tissue-class macro Dice: {tissue_macro:.6f}.",
        f"- Worst slide by macro Dice: {min_slide['slide_id']} ({min_slide['macro_dice']:.6f}).",
        f"- Worst class by mean Dice: {worst_class['class_name']} ({worst_class['dice_mean']:.6f}).",
        f"- Confusion-matrix valid pixels: {total_valid:,}.",
        "",
        "## Per-Slide Summary",
        "",
        per_slide.to_markdown(index=False, floatfmt=".6f"),
        "",
        "## Per-Class Summary",
        "",
        class_summary.to_markdown(index=False, floatfmt=".6f"),
        "",
        "## Confusion Matrix",
        "",
        "The normalized confusion matrix is saved as `confusion_matrix.parquet` and `confusion_matrix.png`. Rows are reference labels; columns are predicted labels.",
        "",
        confusion_norm.to_markdown(index=False, floatfmt=".6f"),
        "",
        "## Interpretation",
        "",
        "The headline Dice is reported with mean and standard deviation, plus a background-excluded variant, because background and normal tissue can dominate whole-slide masks. Rare artifact classes should be interpreted from the per-class table rather than hidden behind the macro headline.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


if __name__ == "__main__":
    main()
