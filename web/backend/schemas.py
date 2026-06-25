"""Pydantic schemas for the live dashboard API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


JobState = Literal["queued", "downloading", "running_qc", "rendering", "done", "failed"]


class CollectionInfo(BaseModel):
    collection_id: str
    display_name: str
    slide_count: int
    license_short_name: str = ""


class CollectionsResponse(BaseModel):
    idc_version: str
    collections: list[CollectionInfo]


class SlideInfo(BaseModel):
    collection_id: str
    slide_id: str
    PatientID: str = ""
    StudyInstanceUID: str
    SeriesInstanceUID: str
    width_px: int | None = None
    height_px: int | None = None
    pixel_spacing_mm: float | None = None
    objective_power: float | str | None = None
    size_MB: float | None = None
    license_short_name: str = ""
    tissue_type: str = ""
    slim_url: str = ""
    already_processed: bool = False


class SlidesResponse(BaseModel):
    collection_id: str
    total: int
    limit: int
    offset: int
    diagnostic_only: bool
    slides: list[SlideInfo]


class JobCreateRequest(BaseModel):
    collection_id: str
    series: list[str] = Field(min_length=1)
    artifact_mpp: float = 1.5
    force: bool = False


class JobCreateResponse(BaseModel):
    batch_id: str
    job_ids: list[str]


class JobStatus(BaseModel):
    job_id: str
    batch_id: str
    state: JobState
    collection_id: str
    series_instance_uid: str
    slide_id: str | None = None
    message: str = ""
    error_type: str | None = None
    error: str | None = None
    traceback: str | None = None
    result: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class BatchStatus(BaseModel):
    batch_id: str
    jobs: list[JobStatus]
    counts: dict[str, int]


class SummaryResponse(BaseModel):
    slide_id: str
    summary: dict[str, Any]
