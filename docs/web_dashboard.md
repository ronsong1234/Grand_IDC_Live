# Live FastAPI GrandQC-IDC Dashboard

`Grand_IDC_Live` is a local, on-demand dashboard around the validated GrandQC x IDC pipeline. It complements the batch runner and Streamlit results browser in `Grand_IDC`:

- Batch runner: process a defined cohort and generate reports/parquet artifacts.
- Streamlit browser: inspect already generated cohort outputs.
- FastAPI live dashboard: pick IDC slides interactively and run QC jobs on demand.

## Reuse of Validated Pipeline

The live app copies and calls `modules/grandqc_qc.py` and `modules/dicom_to_tiff.py`. It does not change model loading, direct-DICOM slide reading, tissue detection, artifact detection, or scoring. The web layer only handles IDC catalog queries, a serial local job queue, output rendering, and API/frontend display.

## Job Queue

One background worker processes jobs serially so GPU inference does not overlap. Multi-slide submissions create one job per slide with a shared `batch_id`. Failed jobs store the error and traceback and do not stop the worker.

## Outputs

Each slide writes:

- `mask_qc/<slide_id>_mask.png`
- `maps_qc/<slide_id>_map_QC.png`
- `overlays_qc/<slide_id>_overlay_QC.jpg`
- `tis_det_thumbnail/<slide_id>.jpg`
- `tiles/<slide_id>_tiles.parquet`
- `summaries/<slide_id>_summary.parquet`
- `summary.json`

API payloads and stored summaries use relative paths/URLs, not local absolute paths.
