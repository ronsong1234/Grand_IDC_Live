"""Re-run a cohort manifest after the tissue-detection fix and compare usability.

The default input is the stale 9-slide cohort summary from the notebook repo.
This script uses idc-index to resolve each slide id back to its IDC series and
forces a fresh direct-DICOM GrandQC run through the current fixed path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.backend.idc_catalog import get_client
from web.backend.qc_runner import run_slide_job


OUTPUT_DIR = REPO_ROOT / "outputs" / "cohort_recheck"
DEFAULT_STALE = Path(os.environ.get("GRANDQC_STALE_SUMMARY", OUTPUT_DIR / "stale_cohort_qc_summary.parquet"))


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stale = pd.read_parquet(args.stale_summary)
    rows = []
    for _, stale_row in stale.iterrows():
        slide_id = str(stale_row["slide_id"])
        meta = resolve_slide(slide_id)
        print(f"{slide_id}: {meta['collection_id']} {meta['SeriesInstanceUID']}")
        if args.skip_run:
            fresh = load_cached_summary(meta["collection_id"], slide_id)
        else:
            fresh = run_slide_job(
                collection_id=meta["collection_id"],
                series_instance_uid=meta["SeriesInstanceUID"],
                artifact_mpp=args.artifact_mpp,
                force=True,
                progress=lambda state, message, sid=slide_id: print(f"  {sid}: {state} - {message}"),
            )
        rows.append(compare_row(stale_row, meta, fresh))

    report_df = pd.DataFrame(rows)
    report_df.to_parquet(args.output_dir / "cohort_recheck.parquet", index=False)
    (args.output_dir / "cohort_recheck.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    write_report(report_df, args.output_dir / "cohort_recheck_report.md")
    print(f"Wrote {rel(args.output_dir)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stale-summary", type=Path, default=DEFAULT_STALE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--artifact-mpp", type=float, default=1.5)
    parser.add_argument("--skip-run", action="store_true", help="Use cached web/output summaries when available; do not rerun GrandQC.")
    return parser.parse_args()


def resolve_slide(slide_id: str) -> dict[str, str]:
    client = get_client()
    query = f"""
        SELECT i.collection_id, i.SeriesInstanceUID, i.StudyInstanceUID, i.PatientID, i.license_short_name
        FROM index i
        JOIN sm_index s ON i.SeriesInstanceUID = s.SeriesInstanceUID
        WHERE i.Modality = 'SM'
          AND s.ContainerIdentifier = '{slide_id}'
        LIMIT 1
    """
    df = client.sql_query(query)
    if df.empty:
        raise RuntimeError(f"Could not resolve {slide_id} in IDC sm_index")
    row = df.iloc[0].to_dict()
    return {key: str(value) for key, value in row.items()}


def load_cached_summary(collection_id: str, slide_id: str) -> dict:
    path = REPO_ROOT / "web" / "output" / collection_id / slide_id / "summary.json"
    if not path.exists():
        print(f"  {slide_id}: cache-miss - {rel(path)}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def compare_row(stale: pd.Series, meta: dict[str, str], fresh: dict) -> dict:
    return {
        "slide_id": str(stale["slide_id"]),
        "collection_id": meta["collection_id"],
        "SeriesInstanceUID": meta["SeriesInstanceUID"],
        "stale_usable": bool(stale.get("usable")),
        "postfix_usable": bool(fresh.get("usable")) if fresh else None,
        "stale_tissue_percentage": float(stale.get("tissue_percentage", 0.0) or 0.0),
        "postfix_tissue_percentage": float(fresh.get("tissue_percentage", 0.0) or 0.0) if fresh else None,
        "stale_artifact_percentage_of_tissue": float(stale.get("artifact_percentage_of_tissue", 0.0) or 0.0),
        "postfix_artifact_percentage_of_tissue": float(fresh.get("artifact_percentage_of_tissue", 0.0) or 0.0) if fresh else None,
        "postfix_tissue_detection_suspect": bool(fresh.get("tissue_detection_suspect", False)) if fresh else None,
        "postfix_tissue_detection_reason": str(fresh.get("tissue_detection_reason", "")) if fresh else "",
    }


def write_report(df: pd.DataFrame, path: Path) -> None:
    stale_unusable = int((~df["stale_usable"].astype(bool)).sum())
    if "postfix_usable" in df and df["postfix_usable"].notna().any():
        post_bool = df["postfix_usable"].astype(bool)
        postfix_unusable = int((~post_bool).sum())
        post_line = f"| Post-fix unusable slides | {postfix_unusable} / {len(df)} ({postfix_unusable / len(df):.1%}) |"
    else:
        post_line = "| Post-fix unusable slides | not rerun |"
    interpretation = ""
    if "postfix_usable" in df and df["postfix_usable"].notna().any():
        if postfix_unusable == stale_unusable:
            interpretation = (
                "In this cohort, the unusable rate did not change after the tissue-detection fix; "
                "the high unusable count is therefore driven by artifact-model outputs rather than the corrected tissue edge-tiling failure."
            )
        else:
            interpretation = (
                "In this cohort, the unusable rate changed after the tissue-detection fix, so downstream summaries should use the post-fix values."
            )
    lines = [
        "# Cohort Usability Recheck After Tissue-Detection Fix",
        "",
        "This report reruns the stale notebook cohort through the current fixed direct-DICOM path. It is intended to replace the old `cohort_qc_summary.parquet` usability rate, which was generated before the tissue-detection edge-tiling fix.",
        "",
        "| Metric | Value |",
        "|:--|--:|",
        f"| Stale unusable slides | {stale_unusable} / {len(df)} ({stale_unusable / len(df):.1%}) |",
        post_line,
        "",
        interpretation,
        "",
        "## Per-Slide Comparison",
        "",
        df.to_markdown(index=False, floatfmt=".6f"),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
