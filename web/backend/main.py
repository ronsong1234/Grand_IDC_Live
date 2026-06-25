"""FastAPI app for the local live GrandQC-IDC dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR, ensure_directories
from .idc_catalog import list_collections, list_slides
from .jobs import JOB_STORE
from .qc_runner import artifact_path, result_for_slide_id
from .schemas import BatchStatus, CollectionsResponse, JobCreateRequest, JobCreateResponse, JobStatus, SlidesResponse, SummaryResponse

ensure_directories()

app = FastAPI(title="GrandQC IDC Live Dashboard", version="0.1.0")


@app.get("/api/collections", response_model=CollectionsResponse)
def api_collections():
    return list_collections()


@app.get("/api/collections/{collection_id}/slides", response_model=SlidesResponse)
def api_slides(
    collection_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str = "",
    diagnostic_only: bool = False,
):
    return list_slides(collection_id, limit=limit, offset=offset, search=search, diagnostic_only=diagnostic_only)


@app.post("/api/jobs", response_model=JobCreateResponse)
def api_create_jobs(request: JobCreateRequest):
    return JOB_STORE.enqueue(
        collection_id=request.collection_id,
        series=request.series,
        artifact_mpp=request.artifact_mpp,
        force=request.force,
    )


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def api_job(job_id: str):
    job = JOB_STORE.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.__dict__


@app.get("/api/batches/{batch_id}", response_model=BatchStatus)
def api_batch(batch_id: str):
    batch = JOB_STORE.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@app.get("/api/results/{slide_id}/summary", response_model=SummaryResponse)
def api_summary(slide_id: str):
    result = result_for_slide_id(slide_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"slide_id": slide_id, "summary": result}


@app.get("/api/results/{slide_id}/{artifact_name}")
def api_artifact(slide_id: str, artifact_name: str):
    path = artifact_path(slide_id, artifact_name)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return FileResponse(path, media_type=media_type, filename=path.name)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
