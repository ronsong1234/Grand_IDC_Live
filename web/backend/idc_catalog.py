"""IDC catalog queries for slide microscopy collections and series."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ARTIFACT_FILE_MAP, OUTPUT_DIR


_CLIENT = None
_CLIENT_LOCK = threading.Lock()
_COLLECTIONS_CACHE: dict[str, Any] | None = None


def get_client():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from idc_index import IDCClient

            _CLIENT = IDCClient()
            _CLIENT.fetch_index("sm_index")
            try:
                _CLIENT.fetch_index("collections_index")
            except Exception:
                pass
        return _CLIENT


def idc_version() -> str:
    return str(get_client().get_idc_version())


def list_collections() -> dict[str, Any]:
    global _COLLECTIONS_CACHE
    if _COLLECTIONS_CACHE is not None:
        return _COLLECTIONS_CACHE

    client = get_client()
    query = """
        SELECT
            i.collection_id,
            COUNT(DISTINCT i.SeriesInstanceUID) AS slide_count,
            MIN(i.license_short_name) AS license_short_name
        FROM index i
        JOIN sm_index s ON i.SeriesInstanceUID = s.SeriesInstanceUID
        WHERE i.Modality = 'SM'
        GROUP BY i.collection_id
        ORDER BY i.collection_id
    """
    df = client.sql_query(query)
    collections = []
    for row in df.to_dict(orient="records"):
        cid = str(row["collection_id"])
        collections.append(
            {
                "collection_id": cid,
                "display_name": cid.replace("_", " ").upper(),
                "slide_count": int(row.get("slide_count") or 0),
                "license_short_name": str(row.get("license_short_name") or ""),
            }
        )
    _COLLECTIONS_CACHE = {"idc_version": idc_version(), "collections": collections}
    return _COLLECTIONS_CACHE


def list_slides(
    collection_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str = "",
    diagnostic_only: bool = False,
) -> dict[str, Any]:
    client = get_client()
    query = f"""
        SELECT
            i.collection_id,
            i.StudyInstanceUID,
            i.SeriesInstanceUID,
            i.PatientID,
            s.ContainerIdentifier,
            s.primaryAnatomicStructureModifier_CodeMeaning AS tissue_type,
            s.max_TotalPixelMatrixColumns AS width_px,
            s.max_TotalPixelMatrixRows AS height_px,
            s.min_PixelSpacing_2sf AS pixel_spacing_mm,
            s.ObjectiveLensPower AS objective_power,
            ROUND(i.series_size_MB, 1) AS size_MB,
            i.license_short_name
        FROM index i
        JOIN sm_index s ON i.SeriesInstanceUID = s.SeriesInstanceUID
        WHERE i.collection_id = {sql_quote(collection_id)}
          AND i.Modality = 'SM'
        ORDER BY i.series_size_MB ASC
    """
    df = client.sql_query(query).drop_duplicates(subset=["SeriesInstanceUID"]).reset_index(drop=True)
    if df.empty:
        return {"collection_id": collection_id, "total": 0, "limit": limit, "offset": offset, "diagnostic_only": diagnostic_only, "slides": []}

    df["slide_id"] = df["ContainerIdentifier"].fillna(df["SeriesInstanceUID"]).astype(str)
    if diagnostic_only:
        df = df[df["slide_id"].str.contains("-DX", case=False, regex=False)].copy()
    if search:
        needle = search.lower()
        mask = df["slide_id"].str.lower().str.contains(needle, regex=False) | df["PatientID"].fillna("").astype(str).str.lower().str.contains(needle, regex=False)
        df = df[mask].copy()

    total = len(df)
    page = df.iloc[offset : offset + limit].copy()
    rows = []
    for row in page.to_dict(orient="records"):
        slide_id = str(row["slide_id"])
        try:
            slim_url = client.get_viewer_URL(seriesInstanceUID=row["SeriesInstanceUID"])
        except Exception:
            slim_url = ""
        rows.append(
            {
                "collection_id": str(row.get("collection_id") or collection_id),
                "slide_id": slide_id,
                "PatientID": str(row.get("PatientID") or ""),
                "StudyInstanceUID": str(row["StudyInstanceUID"]),
                "SeriesInstanceUID": str(row["SeriesInstanceUID"]),
                "width_px": int(row["width_px"]) if pd.notna(row.get("width_px")) else None,
                "height_px": int(row["height_px"]) if pd.notna(row.get("height_px")) else None,
                "pixel_spacing_mm": float(row["pixel_spacing_mm"]) if pd.notna(row.get("pixel_spacing_mm")) else None,
                "objective_power": row.get("objective_power") if pd.notna(row.get("objective_power")) else None,
                "size_MB": float(row["size_MB"]) if pd.notna(row.get("size_MB")) else None,
                "license_short_name": str(row.get("license_short_name") or ""),
                "tissue_type": str(row.get("tissue_type") or ""),
                "slim_url": slim_url,
                "already_processed": outputs_exist(collection_id, slide_id),
            }
        )
    return {"collection_id": collection_id, "total": total, "limit": limit, "offset": offset, "diagnostic_only": diagnostic_only, "slides": rows}


def find_slide(collection_id: str, series_instance_uid: str) -> dict[str, Any]:
    page = list_slides(collection_id, limit=100000, offset=0, search="", diagnostic_only=False)["slides"]
    for slide in page:
        if slide["SeriesInstanceUID"] == series_instance_uid:
            return slide
    raise KeyError(f"Series {series_instance_uid} not found in {collection_id}")


def outputs_exist(collection_id: str, slide_id: str) -> bool:
    slide_dir = safe_slide_dir(collection_id, slide_id)
    return all((slide_dir / pattern.format(slide_id=slide_id)).exists() for pattern in ARTIFACT_FILE_MAP.values()) and (slide_dir / "summary.json").exists()


def safe_slide_dir(collection_id: str, slide_id: str) -> Path:
    return OUTPUT_DIR / safe_name(collection_id) / safe_name(slide_id)


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))


def sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"
