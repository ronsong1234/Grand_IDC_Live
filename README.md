# Grand_IDC_Live

Local FastAPI/job-queue dashboard for running GrandQC on NCI Imaging Data Commons TCGA slide microscopy series.

This repo is the live companion to `Grand_IDC`: choose an IDC collection, select slide microscopy series, run GrandQC locally through the validated direct-DICOM path, and inspect QC masks, artifact maps, overlays, JSON summaries, and SLIM links in the browser.

## What This App Does

- Queries IDC using `idc-index`.
- Downloads selected DICOM WSI series only as temporary inputs.
- Runs GrandQC through `modules/grandqc_qc.py` using direct DICOM tile streaming.
- Serializes inference through one background worker so local GPU inference never overlaps.
- Saves rendered outputs, per-slide parquet, and JSON summaries under `web/output/` by default.
- Deletes raw DICOM inputs unless `GRANDQC_RETAIN_RAW_INPUTS=1` is set.

## Install

```powershell
python -m pip install -r requirements.txt
```

GrandQC model checkpoints are not committed. Put the official weights in:

```text
grandqc/01_WSI_inference_OPENSLIDE_QC/models/td/Tissue_Detection_MPP10.pth
grandqc/01_WSI_inference_OPENSLIDE_QC/models/qc/GrandQC_MPP15.pth
```

The preflight error names the official Zenodo sources if a file is missing. See `LICENSES.md` before redistributing GrandQC code, weights, or outputs.

## Launch

```powershell
python -m uvicorn web.backend.main:app --reload --port 8000
```

Then open `http://127.0.0.1:8000`.

## Runtime Configuration

Copy `.env.example` if you want a local record of settings. The main knobs are documented in `docs/configuration.md`, including output location, usability threshold, manual-review thresholds, and whether raw DICOM inputs are retained.

## Demo Walkthrough

1. Pick an IDC collection in the left panel.
2. Toggle `Diagnostic only` if you want DX slides only, then load slides.
3. Select one or more slides and click `Run QC on selected`.
4. Watch each job move through `queued`, `downloading`, `running_qc`, `rendering`, and `done`.
5. Inspect the mask, overlay, map, thumbnail, QC numbers, and SLIM link.

## Validation Results

Use the metric definitions in `docs/metric_guide.md` when quoting results:

| Metric | Current value | Scope |
|:--|:--|:--|
| Tissue-weighted Dice | 0.958583 mean | 5 BRCA DX reference-mask slides |
| Pixel agreement | 0.960 to 0.995 per slide | 5 BRCA DX reference-mask slides |
| Macro Dice, all classes | 0.712024 +/- 0.141771 | 5 BRCA DX reference-mask slides |
| Background-excluded macro Dice | 0.654914 +/- 0.164388 | 5 BRCA DX reference-mask slides |
| Historical two-slide fidelity check | >= 99.99% pixel agreement and Dice >= 0.9956 on present classes | A8-A0AB and MS-A51U only |

The direct-DICOM path has high pixel and tissue-weighted agreement with GrandQC reference masks. Rare artifact classes, especially on A62V, drive the lower macro-Dice headline. The darkspot/foreign-object over-call seen in LUAD/COAD examples is tracked as a separate model-behavior audit, not as a tissue-detection issue.

## Tests

Fast, no-GPU tests:

```powershell
pytest -m "not gpu"
```

The marked GPU validation contract is opt-in because it requires GrandQC checkpoints and local inference resources:

```powershell
$env:GRANDQC_RUN_GPU_REGRESSION = "1"
pytest -m gpu
```

## API Smoke Test

With the server running:

```powershell
python - <<'PY'
import requests, time
base = 'http://127.0.0.1:8000'
collections = requests.get(base + '/api/collections').json()
print(collections['idc_version'], collections['collections'][0]['collection_id'])
slides = requests.get(base + '/api/collections/tcga_luad/slides?limit=1&diagnostic_only=true').json()['slides']
job = requests.post(base + '/api/jobs', json={'collection_id':'tcga_luad','series':[slides[0]['SeriesInstanceUID']],'artifact_mpp':1.5,'force':False}).json()
while True:
    batch = requests.get(base + '/api/batches/' + job['batch_id']).json()
    states = [j['state'] for j in batch['jobs']]
    print(states)
    if all(s in {'done','failed'} for s in states):
        print(batch['jobs'][0]['result'])
        break
    time.sleep(2)
PY
```

## Docker

A lightweight Docker/Compose scaffold is included for the web app. GPU inference still depends on host driver/runtime setup and mounted GrandQC checkpoints.

```powershell
docker compose up --build
```
