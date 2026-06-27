# Runtime Configuration

The live dashboard reads these environment variables at startup. Defaults are chosen for local research runs and are mirrored in `.env.example`.

| Variable | Default | Purpose |
|:--|:--|:--|
| `GRANDQC_LIVE_OUTPUT_DIR` | `web/output` | Where rendered masks, overlays, parquet summaries, and JSON payloads are written. |
| `GRANDQC_ARTIFACT_MPP` | `1.5` | Artifact model magnification/MMP setting used by default in the UI. |
| `GRANDQC_USABILITY_THRESHOLD` | `0.20` | Slide is marked usable when total artifact fraction of tissue is below this value. |
| `GRANDQC_SINGLE_CLASS_FLAG_THRESHOLD` | `0.60` | Manual-review flag when one artifact class exceeds this tissue fraction. |
| `GRANDQC_OVERALL_ARTIFACT_FLAG_THRESHOLD` | `0.90` | Manual-review flag when total artifact burden exceeds this tissue fraction. |
| `GRANDQC_RETAIN_RAW_INPUTS` | `0` | Keep downloaded DICOM files when set to `1`, `true`, or `yes`; default deletes temporary raw inputs. |
| `GRANDQC_STALE_SUMMARY` | `outputs/cohort_recheck/stale_cohort_qc_summary.parquet` | Optional override for `scripts/rerun_cohort_recheck.py`. |

Raw DICOM inputs are temporary by default. Outputs stay local under `GRANDQC_LIVE_OUTPUT_DIR` unless you move or publish them yourself.
