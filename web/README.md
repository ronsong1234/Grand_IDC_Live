# Live Web Dashboard

Launch from the repository root:

```powershell
python -m uvicorn web.backend.main:app --reload --port 8000
```

The backend exposes:

- `GET /api/collections`
- `GET /api/collections/{collection_id}/slides`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/batches/{batch_id}`
- `GET /api/results/{slide_id}/{artifact_name}`
- `GET /api/results/{slide_id}/summary`

The frontend is plain HTML/CSS/JS mounted at `/`. It keeps selection state only in page memory and does not use localStorage or sessionStorage.

Generated outputs are written under `web/output/<collection_id>/<slide_id>/`. Raw DICOM files are temporary and deleted unless `GRANDQC_RETAIN_RAW_INPUTS=1` is set.
