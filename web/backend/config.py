"""Configuration for the local GrandQC-IDC live dashboard."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
FRONTEND_DIR = WEB_ROOT / "frontend"
OUTPUT_DIR = Path(os.environ.get("GRANDQC_LIVE_OUTPUT_DIR", WEB_ROOT / "output")).resolve()
RAW_INPUT_DIR = OUTPUT_DIR / "_raw"
STATE_DIR = WEB_ROOT / "state"
JOBS_STATE_PATH = STATE_DIR / "jobs.json"

DEFAULT_ARTIFACT_MPP = float(os.environ.get("GRANDQC_ARTIFACT_MPP", "1.5"))
DEFAULT_USABILITY_THRESHOLD = float(os.environ.get("GRANDQC_USABILITY_THRESHOLD", "0.20"))
SINGLE_CLASS_FLAG_THRESHOLD = float(os.environ.get("GRANDQC_SINGLE_CLASS_FLAG_THRESHOLD", "0.60"))
OVERALL_ARTIFACT_FLAG_THRESHOLD = float(os.environ.get("GRANDQC_OVERALL_ARTIFACT_FLAG_THRESHOLD", "0.90"))
RETAIN_RAW_INPUTS = os.environ.get("GRANDQC_RETAIN_RAW_INPUTS", "0").lower() in {"1", "true", "yes"}

ARTIFACT_COLUMNS = [
    "fold_fraction",
    "darkspot_foreign_object_fraction",
    "pen_marking_fraction",
    "edge_air_bubble_fraction",
    "out_of_focus_fraction",
]

ARTIFACT_LABELS = {
    "fold_fraction": "Fold",
    "darkspot_foreign_object_fraction": "Darkspot / foreign object",
    "pen_marking_fraction": "Pen marking",
    "edge_air_bubble_fraction": "Edge / air bubble",
    "out_of_focus_fraction": "Out of focus",
}

CLASS_COLORS = {
    1: (128, 128, 128),
    2: (255, 99, 71),
    3: (0, 255, 0),
    4: (255, 0, 0),
    5: (255, 0, 255),
    6: (75, 0, 130),
    7: (255, 255, 255),
}

ARTIFACT_FILE_MAP = {
    "mask": "mask_qc/{slide_id}_mask.png",
    "overlay": "overlays_qc/{slide_id}_overlay_QC.jpg",
    "map": "maps_qc/{slide_id}_map_QC.png",
    "thumbnail": "tis_det_thumbnail/{slide_id}.jpg",
}


def ensure_directories() -> None:
    for path in (OUTPUT_DIR, RAW_INPUT_DIR, STATE_DIR):
        path.mkdir(parents=True, exist_ok=True)
