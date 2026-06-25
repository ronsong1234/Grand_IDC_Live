"""Single-worker in-process job queue for local GrandQC inference."""

from __future__ import annotations

import json
import queue
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import JOBS_STATE_PATH, ensure_directories
from .idc_catalog import find_slide, outputs_exist, safe_slide_dir
from .qc_runner import load_result, run_slide_job


@dataclass
class JobRecord:
    job_id: str
    batch_id: str
    state: str
    collection_id: str
    series_instance_uid: str
    artifact_mpp: float
    force: bool
    slide_id: str | None = None
    message: str = ""
    error_type: str | None = None
    error: str | None = None
    traceback: str | None = None
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: utc_now())
    updated_at: str = field(default_factory=lambda: utc_now())


class JobStore:
    def __init__(self) -> None:
        ensure_directories()
        self._jobs: dict[str, JobRecord] = {}
        self._batches: dict[str, list[str]] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        self._load_state()

    def enqueue(self, *, collection_id: str, series: list[str], artifact_mpp: float, force: bool) -> dict[str, Any]:
        batch_id = uuid.uuid4().hex
        job_ids = []
        for series_uid in series:
            job_id = uuid.uuid4().hex
            slide_meta = find_slide(collection_id, series_uid)
            slide_id = slide_meta["slide_id"]
            record = JobRecord(
                job_id=job_id,
                batch_id=batch_id,
                state="queued",
                collection_id=collection_id,
                series_instance_uid=series_uid,
                artifact_mpp=artifact_mpp,
                force=force,
                slide_id=slide_id,
                message="Queued",
            )
            slide_dir = safe_slide_dir(collection_id, slide_id)
            if not force and outputs_exist(collection_id, slide_id):
                record.state = "done"
                record.message = "Using existing outputs"
                record.result = load_result(slide_dir)
            with self._lock:
                self._jobs[job_id] = record
                self._batches.setdefault(batch_id, []).append(job_id)
                self._save_state_locked()
            job_ids.append(job_id)
            if record.state == "queued":
                self._queue.put(job_id)
        return {"batch_id": batch_id, "job_ids": job_ids}

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            ids = self._batches.get(batch_id)
            if ids is None:
                return None
            jobs = [self._jobs[job_id] for job_id in ids]
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.state] = counts.get(job.state, 0) + 1
        return {"batch_id": batch_id, "jobs": [asdict(job) for job in jobs], "counts": counts}

    def _progress(self, job_id: str, state: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = state
            job.message = message
            job.updated_at = utc_now()
            self._save_state_locked()

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                with self._lock:
                    job = self._jobs[job_id]
                result = run_slide_job(
                    collection_id=job.collection_id,
                    series_instance_uid=job.series_instance_uid,
                    artifact_mpp=job.artifact_mpp,
                    force=job.force,
                    progress=lambda state, message: self._progress(job_id, state, message),
                )
                with self._lock:
                    job = self._jobs[job_id]
                    job.state = "done"
                    job.message = "Done"
                    job.result = result
                    job.slide_id = result.get("slide_id") or job.slide_id
                    job.updated_at = utc_now()
                    self._save_state_locked()
            except Exception as exc:
                with self._lock:
                    job = self._jobs[job_id]
                    job.state = "failed"
                    job.error_type = type(exc).__name__
                    job.error = str(exc)
                    job.traceback = traceback.format_exc()
                    job.message = "Failed"
                    job.updated_at = utc_now()
                    self._save_state_locked()
            finally:
                self._queue.task_done()

    def _load_state(self) -> None:
        if not JOBS_STATE_PATH.exists():
            return
        try:
            data = json.loads(JOBS_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        with self._lock:
            for payload in data.get("jobs", []):
                if payload.get("state") in {"queued", "downloading", "running_qc", "rendering"}:
                    payload["state"] = "failed"
                    payload["message"] = "Interrupted by server restart"
                    payload["error_type"] = "Interrupted"
                job = JobRecord(**payload)
                self._jobs[job.job_id] = job
                self._batches.setdefault(job.batch_id, []).append(job.job_id)

    def _save_state_locked(self) -> None:
        JOBS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"jobs": [asdict(job) for job in self._jobs.values()]}
        JOBS_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


JOB_STORE = JobStore()
