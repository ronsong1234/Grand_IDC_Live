# Grand_IDC_Live

Local live GrandQC x IDC dashboard for on-demand TCGA whole-slide QC.

This repo is the live FastAPI/job-queue companion to `Grand_IDC`. It lets you pick an IDC collection, select slide microscopy series, run GrandQC locally through the validated direct-DICOM path, and view generated QC masks/maps/overlays in the browser.

## What This App Does

- Queries IDC using `idc-index`.
- Downloads selected DICOM WSI series temporarily.
- Runs GrandQC using the copied validated `modules/grandqc_qc.py` direct-DICOM path.
- Serializes inference through one background worker so local GPU inference never overlaps.
- Saves only rendered outputs, per-slide parquet, and JSON summaries under `web/output/`.
- Deletes raw DICOM inputs by default.

## Install

```powershell
python -m pip install -r requirements.txt
```

GrandQC model checkpoints are not committed. Put the official weights in:

```text
grandqc/01_WSI_inference_OPENSLIDE_QC/models/td/Tissue_Detection_MPP10.pth
grandqc/01_WSI_inference_OPENSLIDE_QC/models/qc/GrandQC_MPP15.pth
```

The preflight error names the official Zenodo sources if a file is missing.

## Launch

```powershell
python -m uvicorn web.backend.main:app --reload --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Demo Walkthrough

1. Pick an IDC collection in the left panel.
2. Toggle `Diagnostic only` if you want DX slides only, then load slides.
3. Select one or more slides and click `Run QC on selected`.
4. Watch each job move through `queued`, `downloading`, `running_qc`, `rendering`, and `done`, then inspect the mask, overlay, map, thumbnail, QC numbers, and SLIM link.

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

## Validation Note

This app calls the same direct-DICOM GrandQC scoring path that previously reached mean Dice 0.999 against the Zenodo `14041578` reference masks. Very high single-class artifact burden, especially darkspot / foreign object, is flagged for manual review because it can be a model edge case.
