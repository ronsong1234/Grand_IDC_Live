"""Run GrandQC pipeline on N slides from IDC and write a batch validation report.

Picks small DX slides from diverse TCGA collections, skips any already
processed, and writes outputs to web/output/ (same path as the dashboard).
Results are aggregated into outputs/batch_validation/.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from web.backend.config import OUTPUT_DIR
from web.backend.idc_catalog import get_client, list_slides, safe_name, safe_slide_dir
from web.backend.qc_runner import run_slide_job

TARGET_TOTAL = 15
ARTIFACT_MPP = 1.5
# Smallest slides first to keep inference time low; order within each collection
COLLECTIONS = [
    "tcga_brca",
    "tcga_kirc",
    "tcga_esca",
    "tcga_luad",
    "tcga_coad",
]
OUTPUT_DIR_BATCH = REPO_ROOT / "outputs" / "batch_validation"


def already_done() -> set[str]:
    done = set()
    for summary_path in OUTPUT_DIR.rglob("summary.json"):
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            done.add(str(data.get("slide_id", "")))
        except Exception:
            pass
    return done


def pick_slides(target: int) -> list[dict]:
    done = already_done()
    print(f"Already processed: {len(done)} slide(s): {sorted(done)}")
    client = get_client()
    candidates = []
    for cid in COLLECTIONS:
        query = f"""
            SELECT
                i.collection_id,
                i.SeriesInstanceUID,
                i.StudyInstanceUID,
                s.ContainerIdentifier,
                ROUND(i.series_size_MB, 1) AS size_MB
            FROM index i
            JOIN sm_index s ON i.SeriesInstanceUID = s.SeriesInstanceUID
            WHERE i.collection_id = '{cid}'
              AND i.Modality = 'SM'
              AND s.ContainerIdentifier LIKE '%-DX%'
            ORDER BY i.series_size_MB ASC
            LIMIT 20
        """
        try:
            df = client.sql_query(query).drop_duplicates(subset=["SeriesInstanceUID"])
            for row in df.to_dict(orient="records"):
                slide_id = str(row.get("ContainerIdentifier") or row["SeriesInstanceUID"])
                if slide_id not in done:
                    candidates.append({
                        "collection_id": cid,
                        "slide_id": slide_id,
                        "SeriesInstanceUID": str(row["SeriesInstanceUID"]),
                        "size_MB": float(row.get("size_MB") or 0),
                    })
        except Exception as e:
            print(f"  Warning: could not query {cid}: {e}")

    needed = max(0, target - len(done))
    # Prefer diversity: take from each collection round-robin
    from collections import defaultdict
    by_col: dict[str, list] = defaultdict(list)
    for c in candidates:
        by_col[c["collection_id"]].append(c)

    selected = []
    col_keys = list(by_col.keys())
    i = 0
    while len(selected) < needed and any(by_col[k] for k in col_keys):
        key = col_keys[i % len(col_keys)]
        if by_col[key]:
            selected.append(by_col[key].pop(0))
        i += 1
    return selected


def run_batch(slides: list[dict]) -> list[dict]:
    results = []
    for idx, slide in enumerate(slides, 1):
        cid = slide["collection_id"]
        series_uid = slide["SeriesInstanceUID"]
        slide_id = slide["slide_id"]
        print(f"\n[{idx}/{len(slides)}] {cid} / {slide_id}  ({slide['size_MB']} MB)")
        t0 = time.perf_counter()
        try:
            payload = run_slide_job(
                collection_id=cid,
                series_instance_uid=series_uid,
                artifact_mpp=ARTIFACT_MPP,
                force=False,
                progress=lambda state, msg: print(f"  {state}: {msg}"),
            )
            elapsed = round(time.perf_counter() - t0, 1)
            results.append({
                "status": "ok",
                "collection_id": cid,
                "slide_id": slide_id,
                "elapsed_s": elapsed,
                **{k: payload.get(k) for k in [
                    "tissue_percentage", "artifact_percentage_of_tissue",
                    "usable", "qc_flag_review", "qc_flag_reason",
                ]},
                "artifact_fractions": payload.get("artifact_fractions", {}),
            })
            print(f"  Done in {elapsed}s — tissue={payload.get('tissue_percentage', 0):.1%}  artifact={payload.get('artifact_percentage_of_tissue', 0):.1%}")
        except Exception as e:
            elapsed = round(time.perf_counter() - t0, 1)
            print(f"  FAILED after {elapsed}s: {e}")
            results.append({"status": "error", "collection_id": cid, "slide_id": slide_id, "error": str(e), "elapsed_s": elapsed})
    return results


def collect_all_results() -> list[dict]:
    all_results = []
    for summary_path in sorted(OUTPUT_DIR.rglob("summary.json")):
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            all_results.append({
                "status": "ok",
                "collection_id": data.get("collection_id", ""),
                "slide_id": data.get("slide_id", ""),
                "tissue_percentage": data.get("tissue_percentage"),
                "artifact_percentage_of_tissue": data.get("artifact_percentage_of_tissue"),
                "usable": data.get("usable"),
                "qc_flag_review": data.get("qc_flag_review"),
                "qc_flag_reason": data.get("qc_flag_reason", ""),
                "runtime_seconds": data.get("runtime_seconds"),
                "artifact_fractions": data.get("artifact_fractions", {}),
            })
        except Exception:
            pass
    return all_results


def write_report(all_results: list[dict], new_results: list[dict], output_dir: Path) -> None:
    ok = [r for r in all_results if r.get("status") == "ok"]
    new_ok = [r for r in new_results if r.get("status") == "ok"]
    new_err = [r for r in new_results if r.get("status") == "error"]
    collections = sorted({r["collection_id"] for r in ok})

    rows = []
    for r in ok:
        fracs = r.get("artifact_fractions") or {}
        rows.append({
            "collection": r["collection_id"],
            "slide_id": r["slide_id"],
            "tissue_%": f"{float(r.get('tissue_percentage') or 0):.1%}",
            "artifact_%": f"{float(r.get('artifact_percentage_of_tissue') or 0):.1%}",
            "usable": "Yes" if r.get("usable") else "No",
            "flag": "Yes" if r.get("qc_flag_review") else "No",
            "runtime_s": r.get("runtime_seconds", ""),
            "fold_%": f"{float(fracs.get('fold_fraction') or 0):.2%}",
            "darkspot_%": f"{float(fracs.get('darkspot_foreign_object_fraction') or 0):.2%}",
            "pen_%": f"{float(fracs.get('pen_marking_fraction') or 0):.2%}",
            "edge_%": f"{float(fracs.get('edge_air_bubble_fraction') or 0):.2%}",
            "oof_%": f"{float(fracs.get('out_of_focus_fraction') or 0):.2%}",
        })

    df = pd.DataFrame(rows)
    success_rate = len(ok) / len(all_results) * 100 if all_results else 0
    tissue_vals = [float(r.get("tissue_percentage") or 0) for r in ok]
    artifact_vals = [float(r.get("artifact_percentage_of_tissue") or 0) for r in ok]
    usable_count = sum(1 for r in ok if r.get("usable"))

    import numpy as np
    lines = [
        "# GrandQC Direct-DICOM Batch Validation",
        "",
        f"**Date:** 2026-06-25  ",
        f"**Pipeline:** GrandQC direct-DICOM wrapper (Grand_IDC_Live)  ",
        f"**IDC Version:** v24  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|:-------|------:|",
        f"| Slides attempted | {len(all_results)} |",
        f"| Slides succeeded | {len(ok)} ({success_rate:.0f}%) |",
        f"| Slides failed | {len([r for r in all_results if r.get('status') == 'error'])} |",
        f"| TCGA collections | {len(collections)} ({', '.join(collections)}) |",
        f"| Usable slides (artifact < 20%) | {usable_count} / {len(ok)} |",
        f"| Mean tissue coverage | {np.mean(tissue_vals):.1%} ± {np.std(tissue_vals):.1%} |",
        f"| Mean artifact fraction of tissue | {np.mean(artifact_vals):.1%} ± {np.std(artifact_vals):.1%} |",
        "",
        "---",
        "",
        "## Per-Slide Results",
        "",
        df.to_markdown(index=False),
        "",
        "---",
        "",
        "## Interpretation",
        "",
        "Each slide was downloaded from IDC as a DICOM series and processed end-to-end through the",
        "GrandQC direct-DICOM pipeline without any intermediate TIFF conversion. The tissue percentage",
        "and per-class artifact fractions reported above are the direct output of the GrandQC model.",
        "",
        "The pixel-level fidelity of this pipeline to GrandQC reference masks is documented",
        "separately in `docs/pipeline_fidelity_validation.md`, where the direct-DICOM wrapper",
        "achieves ≥ 99.99% pixel agreement and Dice ≥ 0.9956 across all artifact classes",
        "on two TCGA-BRCA DX reference slides.",
        "",
    ]
    if new_err:
        lines += [
            "## Failed Slides",
            "",
            "| collection | slide_id | error |",
            "|:-----------|:---------|:------|",
        ]
        for r in new_err:
            lines.append(f"| {r['collection_id']} | {r['slide_id']} | {r.get('error', '')} |")
        lines.append("")

    path = output_dir / "batch_validation_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote report to {path.relative_to(REPO_ROOT)}")

    json_path = output_dir / "batch_results.json"
    json_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"Wrote raw results to {json_path.relative_to(REPO_ROOT)}")


def main() -> None:
    OUTPUT_DIR_BATCH.mkdir(parents=True, exist_ok=True)
    slides_to_run = pick_slides(TARGET_TOTAL)

    if slides_to_run:
        print(f"\nWill process {len(slides_to_run)} new slide(s):")
        for s in slides_to_run:
            print(f"  {s['collection_id']} / {s['slide_id']}  ({s['size_MB']} MB)")
        new_results = run_batch(slides_to_run)
    else:
        print("Already at target slide count, collecting existing results.")
        new_results = []

    all_results = collect_all_results()
    write_report(all_results, new_results, OUTPUT_DIR_BATCH)
    print(f"\nTotal slides in report: {len(all_results)}")


if __name__ == "__main__":
    main()
