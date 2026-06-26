"""Compare GrandQC behavior on diagnostic DX slides versus frozen-like TS/BS slides.

This is a behavior characterization, not an accuracy validation, because no
ground-truth masks are available for the frozen-section group.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
OUTPUT_DIR = REPO_ROOT / "outputs" / "tissue_type"
DEFAULT_INPUTS = [
    REPO_ROOT / "web" / "output",
    REPO_ROOT / "outputs" / "cohort",
]
ARTIFACT_COLUMNS = [
    "fold_fraction",
    "darkspot_foreign_object_fraction",
    "pen_marking_fraction",
    "edge_air_bubble_fraction",
    "out_of_focus_fraction",
    "artifact_percentage_of_tissue",
    "tissue_percentage",
]


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df = load_inputs(args.inputs)
    if df.empty:
        raise RuntimeError("No cohort summary rows found. Provide --inputs with summary parquet/csv/json or a directory containing summary.json files.")
    df = df.drop_duplicates(subset=["slide_id"]).copy()
    df["prep_group"] = df["slide_id"].map(prep_group)
    df = df[df["prep_group"].isin(["DX", "frozen"])]
    if df.empty:
        raise RuntimeError("No DX or TS/BS frozen-like slides found in available summaries.")

    summary = summarize(df)
    tests = mann_whitney_tests(df)
    summary.to_parquet(args.output_dir / "tissue_type_summary.parquet", index=False)
    tests.to_parquet(args.output_dir / "tissue_type_tests.parquet", index=False)
    write_boxplots(df, args.output_dir)
    write_report(df, summary, tests, args.output_dir / "tissue_type_analysis.md")
    print(f"Wrote tissue type outputs to {relative(args.output_dir)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="*", type=Path, default=DEFAULT_INPUTS, help="Summary files or directories to scan.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def load_inputs(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("summary.json")):
                row = pd.read_json(child, typ="series").to_dict()
                if isinstance(row.get("artifact_fractions"), dict):
                    row.update(row.pop("artifact_fractions"))
                frames.append(pd.DataFrame([row]))
            for child in sorted(path.rglob("*summary*.parquet")):
                frames.append(pd.read_parquet(child))
            for child in sorted(path.rglob("*summary*.csv")):
                frames.append(pd.read_csv(child))
        elif path.exists():
            if path.suffix == ".parquet":
                frames.append(pd.read_parquet(path))
            elif path.suffix == ".csv":
                frames.append(pd.read_csv(path))
            elif path.suffix == ".json":
                frames.append(pd.DataFrame([pd.read_json(path, typ="series").to_dict()]))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    if "summary" in df.columns:
        expanded = pd.json_normalize(df["summary"])
        df = pd.concat([df.drop(columns=["summary"]), expanded], axis=1)
    return df


def prep_group(slide_id: str) -> str:
    text = str(slide_id).upper()
    if "-DX" in text:
        return "DX"
    if "-TS" in text or "-BS" in text:
        return "frozen"
    return "other"


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in ARTIFACT_COLUMNS:
        if metric not in df.columns:
            continue
        for group, group_df in df.groupby("prep_group"):
            values = pd.to_numeric(group_df[metric], errors="coerce").dropna()
            rows.append(
                {
                    "metric": metric,
                    "prep_group": group,
                    "n": int(values.size),
                    "mean": float(values.mean()) if values.size else None,
                    "median": float(values.median()) if values.size else None,
                    "std": float(values.std(ddof=1)) if values.size > 1 else None,
                    "min": float(values.min()) if values.size else None,
                    "max": float(values.max()) if values.size else None,
                }
            )
    return pd.DataFrame(rows)


def mann_whitney_tests(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    try:
        from scipy.stats import mannwhitneyu
    except Exception:
        mannwhitneyu = None
    for metric in ARTIFACT_COLUMNS:
        if metric not in df.columns:
            continue
        dx = pd.to_numeric(df.loc[df["prep_group"] == "DX", metric], errors="coerce").dropna()
        frozen = pd.to_numeric(df.loc[df["prep_group"] == "frozen", metric], errors="coerce").dropna()
        row = {"metric": metric, "dx_n": int(dx.size), "frozen_n": int(frozen.size), "test": "mann_whitney_u"}
        if mannwhitneyu is not None and dx.size > 0 and frozen.size > 0:
            stat = mannwhitneyu(dx, frozen, alternative="two-sided")
            row.update({"u_statistic": float(stat.statistic), "p_value": float(stat.pvalue)})
        else:
            row.update({"u_statistic": None, "p_value": None})
        rows.append(row)
    return pd.DataFrame(rows)


def write_boxplots(df: pd.DataFrame, output_dir: Path) -> None:
    metrics = [metric for metric in ARTIFACT_COLUMNS if metric in df.columns]
    for metric in metrics:
        data = [pd.to_numeric(df.loc[df["prep_group"] == group, metric], errors="coerce").dropna() for group in ["DX", "frozen"]]
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.boxplot(data, tick_labels=["DX", "Frozen TS/BS"], showmeans=True)
        ax.set_ylabel(metric)
        ax.set_title(f"{metric}: DX vs frozen-like")
        fig.tight_layout()
        fig.savefig(output_dir / f"{metric}_boxplot.png", dpi=160)
        plt.close(fig)


def write_report(df: pd.DataFrame, summary: pd.DataFrame, tests: pd.DataFrame, path: Path) -> None:
    group_counts = df["prep_group"].value_counts().to_dict()
    lines = [
        "# DX vs Frozen-Section GrandQC Behavior Analysis",
        "",
        "## Scope",
        "",
        "This analysis compares GrandQC output distributions for diagnostic DX slides versus frozen-like TS/BS slides. It is exploratory and behavioral; it does not estimate accuracy for frozen sections because no frozen-section ground truth masks are available.",
        "",
        "## Cohort Counts",
        "",
        f"- DX slides: {group_counts.get('DX', 0)}",
        f"- Frozen-like TS/BS slides: {group_counts.get('frozen', 0)}",
        "",
        "## Summary Statistics",
        "",
        summary.to_markdown(index=False, floatfmt=".6f"),
        "",
        "## Mann-Whitney U Tests",
        "",
        "These tests are exploratory and unadjusted; use them as distribution-screening evidence, not confirmatory inference.",
        "",
        tests.to_markdown(index=False, floatfmt=".6g"),
        "",
        "## Interpretation",
        "",
        "GrandQC's BRCA DX reference-mask validation does not automatically transfer to frozen sections. Elevated artifact classes in TS/BS slides should be treated as behavior requiring manual confirmation in IDC SLIM, not as validated frozen-section accuracy.",
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
