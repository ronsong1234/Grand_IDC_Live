"""GrandQC quality scoring for IDC DICOM WSI and converted TIFF slides.

The cloned ``grandqc/`` directory is treated as a read-only reference.  This
module keeps all checkpoint paths in the CONFIG block below and reimplements the
thin inference orchestration needed for reproducible IDC pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import logging
import math
import os
from pathlib import Path
import shutil
from typing import Any, Iterable, Protocol
from urllib.request import urlopen

import numpy as np
import pandas as pd
from PIL import Image

from modules.dicom_to_tiff import DirectDicomSlide, get_slide_info, read_tiff_mpp

LOGGER = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = 1_000_000_000


# =============================================================================
# CONFIG
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parents[1]
GRANDQC_ROOT = REPO_ROOT / "grandqc"
WEIGHTS_DIR = GRANDQC_ROOT / "01_WSI_inference_OPENSLIDE_QC" / "models"
ARTIFACT_MODEL_PATHS = {
    1.0: WEIGHTS_DIR / "qc" / "GrandQC_MPP1.pth",
    1.5: WEIGHTS_DIR / "qc" / "GrandQC_MPP15.pth",
    2.0: WEIGHTS_DIR / "qc" / "GrandQC_MPP2.pth",
}
TISSUE_MODEL_PATH = WEIGHTS_DIR / "td" / "Tissue_Detection_MPP10.pth"
TISSUE_MODEL_SOURCE = "https://zenodo.org/records/14507273"
ARTIFACT_MODEL_SOURCE = "https://zenodo.org/records/14041538"
ZENODO_RECORD_API = "https://zenodo.org/api/records/{record_id}"
WEIGHT_DOWNLOAD_RECORDS = {
    "Tissue_Detection_MPP10.pth": "14507273",
    "GrandQC_MPP1.pth": "14041538",
    "GrandQC_MPP15.pth": "14041538",
    "GrandQC_MPP2.pth": "14041538",
}

DEFAULT_ARTIFACT_MPP = 1.5
TISSUE_MPP = 10.0
MODEL_TILE_SIZE = 512
ENCODER_NAME = "timm-efficientnet-b0"
ENCODER_WEIGHTS = "imagenet"
BACKGROUND_CLASS = 7
MIN_TISSUE_PIXELS_PER_TILE = 50
TISSUE_SUSPECT_MAX_FRACTION = 0.002
FOREGROUND_SUSPECT_MIN_FRACTION = 0.02
DEFAULT_USABILITY_ARTIFACT_THRESHOLD = 0.20
DEFAULT_OUTPUT_DIR = Path("grandqc_idc_output")
# Keep production inference aligned with GrandQC's reference scripts, which use
# OpenSlide read_region(...).convert("RGB"). Channel swaps are diagnostic only.
PRODUCTION_COLOR_MODE = "RGB"
IDC_DICOMWEB_URL = (
    "https://proxy.imaging.datacommons.cancer.gov/current/"
    "viewer-only-no-downloads-see-tinyurl-dot-com-slash-3j3d9jyp/dicomWeb"
)

CLASS_NAMES = {
    1: "normal_tissue",
    2: "fold",
    3: "darkspot_foreign_object",
    4: "pen_marking",
    5: "edge_air_bubble",
    6: "out_of_focus",
    7: "background",
}
ARTIFACT_CLASSES = (2, 3, 4, 5, 6)


@dataclass(frozen=True)
class WeightSpec:
    model_name: str
    path: Path
    source: str


@dataclass
class QCResult:
    """GrandQC output for one slide."""

    slide_id: str
    summary: pd.DataFrame
    tile_scores: pd.DataFrame
    mask: np.ndarray | None = None


class SlideLike(Protocol):
    slide_id: str
    width: int
    height: int
    mpp_x: float
    mpp_y: float

    def read_region(self, location: tuple[int, int], level: int, size: tuple[int, int]) -> Image.Image:
        ...

    def close(self) -> None:
        ...


class DirectDicomGrandQCSlide:
    """GrandQC slide adapter backed by wsidicom direct DICOM reads."""

    def __init__(self, source: str | os.PathLike[str], slide_id: str | None = None):
        self.source = Path(source)
        self._slide = DirectDicomSlide(self.source)
        self.slide_id = slide_id or self.source.name
        self.width, self.height = self._slide.dimensions
        self.mpp_x = self._slide.info.mpp_x_um
        self.mpp_y = self._slide.info.mpp_y_um
        self.level_count = self._slide.level_count

    def read_region(self, location: tuple[int, int], level: int, size: tuple[int, int]) -> Image.Image:
        return self._slide.read_region(location, level, size)

    def close(self) -> None:
        self._slide.close()


class TiffGrandQCSlide:
    """GrandQC slide adapter for converted TIFF files."""

    def __init__(self, source: str | os.PathLike[str], slide_id: str | None = None):
        self.source = Path(source)
        self.slide_id = slide_id or self.source.stem
        self.mpp_x, self.mpp_y = read_tiff_mpp(self.source)
        try:
            import pyvips
        except ImportError as exc:
            raise ImportError("pyvips is required to read TIFF slides. Install with: pip install pyvips") from exc
        self._pyvips = pyvips
        self._image = pyvips.Image.new_from_file(str(self.source), access="sequential")
        self.width = int(self._image.width)
        self.height = int(self._image.height)
        self.level_count = int(self._image.get("n-pages")) if "n-pages" in self._image.get_fields() else 1

    def read_region(self, location: tuple[int, int], level: int, size: tuple[int, int]) -> Image.Image:
        if level != 0:
            raise ValueError("TiffGrandQCSlide currently reads level 0 only.")
        x, y = location
        width, height = size
        crop = self._image.crop(x, y, width, height)
        if crop.bands > 3:
            crop = crop[:3]
        arr = np.ndarray(
            buffer=crop.write_to_memory(),
            dtype=np.uint8,
            shape=(height, width, crop.bands),
        )
        return Image.fromarray(arr).convert(PRODUCTION_COLOR_MODE)

    def close(self) -> None:
        self._image = None


class DicomWebGrandQCSlide:
    """GrandQC slide adapter that streams DICOM WSI frames via DICOMweb."""

    def __init__(
        self,
        study_instance_uid: str,
        series_instance_uid: str,
        *,
        slide_id: str | None = None,
        dicomweb_url: str = IDC_DICOMWEB_URL,
    ):
        try:
            from dicomweb_client.api import DICOMwebClient
        except ImportError as exc:
            raise ImportError("dicomweb-client is required for remote DICOMweb streaming.") from exc

        self.study_instance_uid = study_instance_uid
        self.series_instance_uid = series_instance_uid
        self.slide_id = slide_id or series_instance_uid
        self.client = DICOMwebClient(url=dicomweb_url)
        self._levels = self._load_levels()
        self._level = self._levels[0]
        self.width = self._level["width"]
        self.height = self._level["height"]
        self.mpp_x = self._level["mpp_x"]
        self.mpp_y = self._level["mpp_y"]
        self.level_count = len(self._levels)

    def _load_levels(self) -> list[dict[str, Any]]:
        metadata = self.client.retrieve_series_metadata(
            self.study_instance_uid,
            self.series_instance_uid,
        )
        levels = []
        for instance in metadata:
            rows = int(_dicom_json_value(instance, "00280010", 0))
            cols = int(_dicom_json_value(instance, "00280011", 0))
            total_rows = int(_dicom_json_value(instance, "00480007", rows))
            total_cols = int(_dicom_json_value(instance, "00480006", cols))
            number_of_frames = int(_dicom_json_value(instance, "00280008", 1))
            sop_uid = str(_dicom_json_value(instance, "00080018"))
            mpp_y, mpp_x = _dicom_json_pixel_spacing_um(instance)
            frame_map = _dicom_json_frame_map(instance, rows, cols, number_of_frames)
            levels.append(
                {
                    "sop_uid": sop_uid,
                    "tile_rows": rows,
                    "tile_cols": cols,
                    "height": total_rows,
                    "width": total_cols,
                    "mpp_y": mpp_y,
                    "mpp_x": mpp_x,
                    "frame_map": frame_map,
                }
            )
        if not levels:
            raise ValueError(f"No DICOMweb metadata found for series {self.series_instance_uid}")
        levels.sort(key=lambda item: (item["mpp_x"] + item["mpp_y"]) / 2.0)
        LOGGER.info(
            "Remote DICOMweb slide %s: MPP x=%.6f y=%.6f um, dimensions=%sx%s, levels=%s",
            self.slide_id,
            levels[0]["mpp_x"],
            levels[0]["mpp_y"],
            levels[0]["width"],
            levels[0]["height"],
            len(levels),
        )
        return levels

    def read_region(self, location: tuple[int, int], level: int, size: tuple[int, int]) -> Image.Image:
        if level != 0:
            raise ValueError("DicomWebGrandQCSlide currently reads level 0 only.")
        x, y = location
        width, height = size
        canvas = Image.new(PRODUCTION_COLOR_MODE, (width, height), color=(255, 255, 255))
        frame_infos = _overlapping_frames(self._level, x, y, width, height)
        for frame_info in frame_infos:
            frame = self.client.retrieve_instance_frames(
                self.study_instance_uid,
                self.series_instance_uid,
                self._level["sop_uid"],
                [frame_info["frame_number"]],
            )[0]
            tile = _decode_dicomweb_frame(frame, frame_info["tile_rows"], frame_info["tile_cols"])
            src_x = max(0, x - frame_info["x"])
            src_y = max(0, y - frame_info["y"])
            dst_x = max(0, frame_info["x"] - x)
            dst_y = max(0, frame_info["y"] - y)
            crop_w = min(frame_info["tile_cols"] - src_x, width - dst_x)
            crop_h = min(frame_info["tile_rows"] - src_y, height - dst_y)
            if crop_w > 0 and crop_h > 0:
                canvas.paste(tile.crop((src_x, src_y, src_x + crop_w, src_y + crop_h)), (dst_x, dst_y))
        return canvas

    def close(self) -> None:
        return None


def required_weight_specs(include_all_artifact_mpps: bool = True) -> list[WeightSpec]:
    """Return required GrandQC checkpoint specs."""

    specs = [
        WeightSpec("GrandQC tissue segmentation", TISSUE_MODEL_PATH, TISSUE_MODEL_SOURCE),
    ]
    artifact_items = ARTIFACT_MODEL_PATHS.items() if include_all_artifact_mpps else [(DEFAULT_ARTIFACT_MPP, ARTIFACT_MODEL_PATHS[DEFAULT_ARTIFACT_MPP])]
    for mpp, path in artifact_items:
        specs.append(WeightSpec(f"GrandQC artifact model MPP {mpp}", path, ARTIFACT_MODEL_SOURCE))
    return specs


def check_weights(
    *,
    artifact_mpp: float | None = DEFAULT_ARTIFACT_MPP,
    require_all_artifact_models: bool = False,
) -> dict[str, Path]:
    """Verify all required weights exist and are non-empty.

    Raises a FileNotFoundError that names the missing file, expected location,
    and official GrandQC source.
    """

    specs = [WeightSpec("GrandQC tissue segmentation", TISSUE_MODEL_PATH, TISSUE_MODEL_SOURCE)]
    if require_all_artifact_models:
        for mpp, path in ARTIFACT_MODEL_PATHS.items():
            specs.append(WeightSpec(f"GrandQC artifact model MPP {mpp}", path, ARTIFACT_MODEL_SOURCE))
    else:
        if artifact_mpp not in ARTIFACT_MODEL_PATHS:
            raise ValueError(f"artifact_mpp must be one of {sorted(ARTIFACT_MODEL_PATHS)}")
        specs.append(
            WeightSpec(
                f"GrandQC artifact model MPP {artifact_mpp}",
                ARTIFACT_MODEL_PATHS[artifact_mpp],
                ARTIFACT_MODEL_SOURCE,
            )
        )

    missing = []
    resolved: dict[str, Path] = {}
    for spec in specs:
        path = spec.path.resolve()
        if not path.exists() or path.stat().st_size == 0:
            missing.append(
                f"{spec.model_name}: expected {path} "
                f"(official source: {spec.source})"
            )
        else:
            resolved[spec.model_name] = path
            LOGGER.info("Using %s checkpoint: %s", spec.model_name, path)

    if missing:
        raise FileNotFoundError(
            "GrandQC checkpoint preflight failed. Download the files documented "
            "by GrandQC before running inference:\n" + "\n".join(missing)
        )
    return resolved


def download_weights(
    *,
    artifact_mpp: float = DEFAULT_ARTIFACT_MPP,
    require_all_artifact_models: bool = False,
) -> dict[str, Path]:
    """Download required GrandQC weights from the official Zenodo records.

    Existing non-empty files are skipped.  Zenodo file sizes are checked when
    available.  GrandQC does not currently publish checksums in the local README;
    if Zenodo exposes one through its API, this function leaves the size check
    in place and logs the resolved file path.
    """

    specs = [WeightSpec("GrandQC tissue segmentation", TISSUE_MODEL_PATH, TISSUE_MODEL_SOURCE)]
    if require_all_artifact_models:
        for mpp, path in ARTIFACT_MODEL_PATHS.items():
            specs.append(WeightSpec(f"GrandQC artifact model MPP {mpp}", path, ARTIFACT_MODEL_SOURCE))
    else:
        if artifact_mpp not in ARTIFACT_MODEL_PATHS:
            raise ValueError(f"artifact_mpp must be one of {sorted(ARTIFACT_MODEL_PATHS)}")
        specs.append(
            WeightSpec(
                f"GrandQC artifact model MPP {artifact_mpp}",
                ARTIFACT_MODEL_PATHS[artifact_mpp],
                ARTIFACT_MODEL_SOURCE,
            )
        )

    resolved = {}
    for spec in specs:
        target = spec.path.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 0:
            LOGGER.info("Skipping existing %s: %s", spec.model_name, target)
            resolved[spec.model_name] = target
            continue
        filename = target.name
        record_id = WEIGHT_DOWNLOAD_RECORDS[filename]
        file_info = _zenodo_file_info(record_id, filename)
        download_url = file_info["download_url"]
        expected_size = file_info.get("size")
        LOGGER.info("Downloading %s from Zenodo record %s to %s", filename, record_id, target)
        _download_file(download_url, target)
        if expected_size is not None and target.stat().st_size != int(expected_size):
            target.unlink(missing_ok=True)
            raise IOError(
                f"Downloaded size mismatch for {target}: expected {expected_size} bytes, "
                f"got {target.stat().st_size if target.exists() else 0} bytes."
            )
        resolved[spec.model_name] = target
        LOGGER.info("Using %s checkpoint: %s", spec.model_name, target)
    return resolved


def _zenodo_file_info(record_id: str, filename: str) -> dict[str, Any]:
    import json

    with urlopen(ZENODO_RECORD_API.format(record_id=record_id), timeout=60) as response:
        record = json.loads(response.read().decode("utf-8"))
    for file_info in record.get("files", []):
        key = file_info.get("key") or file_info.get("filename")
        if key == filename:
            links = file_info.get("links", {})
            download_url = links.get("self") or links.get("download")
            if not download_url:
                raise KeyError(f"Zenodo record {record_id} does not expose a download link for {filename}.")
            return {"download_url": download_url, "size": file_info.get("size")}
    raise FileNotFoundError(f"{filename} was not found in official Zenodo record {record_id}.")


def _download_file(url: str, target: Path) -> None:
    temp_target = target.with_suffix(target.suffix + ".part")
    with urlopen(url, timeout=120) as response, temp_target.open("wb") as out:
        shutil.copyfileobj(response, out)
    temp_target.replace(target)


def open_slide(source: Any, *, input_type: str = "dicom", slide_id: str | None = None) -> SlideLike:
    """Open a slide for QC.

    Parameters
    ----------
    input_type:
        ``"dicom"`` for a DICOM series directory or single DICOM file,
        ``"tiff"`` for a converted TIFF.
    """

    if input_type == "dicom":
        return DirectDicomGrandQCSlide(source, slide_id=slide_id)
    if input_type == "tiff":
        return TiffGrandQCSlide(source, slide_id=slide_id)
    if input_type == "dicomweb":
        if isinstance(source, dict):
            study_uid = source["StudyInstanceUID"]
            series_uid = source["SeriesInstanceUID"]
        else:
            study_uid, series_uid = source
        return DicomWebGrandQCSlide(study_uid, series_uid, slide_id=slide_id)
    raise ValueError("input_type must be 'dicom', 'tiff', or 'dicomweb'")


def run_grandqc(
    slides: Iterable[str | os.PathLike[str] | SlideLike],
    *,
    input_type: str = "dicom",
    artifact_mpp: float = DEFAULT_ARTIFACT_MPP,
    output_dir: str | os.PathLike[str] = DEFAULT_OUTPUT_DIR,
    save_tile_parquet: bool = True,
    save_mask: bool = True,
    usability_artifact_threshold: float = DEFAULT_USABILITY_ARTIFACT_THRESHOLD,
    device: str | None = None,
    slide_ids: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Run GrandQC on slides and return/save a tidy per-slide summary."""

    check_weights(artifact_mpp=artifact_mpp)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mask_qc").mkdir(exist_ok=True)
    (out_dir / "tiles").mkdir(exist_ok=True)

    device = device or _default_device()
    tissue_model, artifact_model, preprocessing_fn = _load_models(artifact_mpp, device)
    summaries = []
    ids = list(slide_ids) if slide_ids is not None else None

    for index, slide_source in enumerate(slides):
        slide = slide_source if hasattr(slide_source, "read_region") else open_slide(
            slide_source,
            input_type=input_type,
            slide_id=ids[index] if ids else None,
        )
        try:
            result = score_slide(
                slide,
                tissue_model=tissue_model,
                artifact_model=artifact_model,
                preprocessing_fn=preprocessing_fn,
                artifact_mpp=artifact_mpp,
                device=device,
                usability_artifact_threshold=usability_artifact_threshold,
            )
            summaries.append(result.summary)
            if save_mask and result.mask is not None:
                _save_mask(result.mask, out_dir / "mask_qc" / f"{result.slide_id}_mask.png")
            if save_tile_parquet:
                parquet_path = out_dir / "tiles" / f"{result.slide_id}_tiles.parquet"
                result.tile_scores.to_parquet(parquet_path, index=False)
        finally:
            close = getattr(slide, "close", None)
            if close is not None:
                close()

    summary_df = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    summary_path = out_dir / "grandqc_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    LOGGER.info("Wrote GrandQC summary: %s", summary_path.resolve())
    return summary_df


def score_slide(
    slide: SlideLike,
    *,
    tissue_model: Any,
    artifact_model: Any,
    preprocessing_fn: Any,
    artifact_mpp: float,
    device: str,
    usability_artifact_threshold: float,
) -> QCResult:
    """Score one slide and return summary, per-tile scores, and raw mask."""

    _validate_slide_mpp(slide)
    LOGGER.info(
        "Scoring %s: %.6f x %.6f um/px, %sx%s px",
        slide.slide_id,
        slide.mpp_x,
        slide.mpp_y,
        slide.width,
        slide.height,
    )
    tissue_mask = _run_tissue_detection(slide, tissue_model, preprocessing_fn, device)
    result_mask, tile_df = _run_artifact_detection(
        slide,
        tissue_mask,
        artifact_model,
        preprocessing_fn,
        artifact_mpp,
        device,
    )
    summary = summarize_mask(
        result_mask,
        slide_id=slide.slide_id,
        width=slide.width,
        height=slide.height,
        mpp_x=slide.mpp_x,
        mpp_y=slide.mpp_y,
        artifact_mpp=artifact_mpp,
        usability_artifact_threshold=usability_artifact_threshold,
    )
    summary = _add_tissue_detection_guardrail(slide, tissue_mask, summary)
    return QCResult(slide.slide_id, summary, tile_df, result_mask)


def summarize_mask(
    mask: np.ndarray,
    *,
    slide_id: str,
    width: int,
    height: int,
    mpp_x: float,
    mpp_y: float,
    artifact_mpp: float,
    usability_artifact_threshold: float,
) -> pd.DataFrame:
    """Build a one-row tidy summary from a GrandQC class mask."""

    counts = {cls: int(np.sum(mask == cls)) for cls in CLASS_NAMES}
    tissue_px = sum(counts[cls] for cls in CLASS_NAMES if cls != BACKGROUND_CLASS)
    artifact_px = sum(counts[cls] for cls in ARTIFACT_CLASSES)
    total_px = int(mask.size)
    tissue_pct = tissue_px / total_px if total_px else 0.0
    artifact_pct_tissue = artifact_px / tissue_px if tissue_px else 0.0
    row: dict[str, Any] = {
        "slide_id": slide_id,
        "width_px": width,
        "height_px": height,
        "mpp_x_um": mpp_x,
        "mpp_y_um": mpp_y,
        "artifact_model_mpp_um": artifact_mpp,
        "tissue_percentage": tissue_pct,
        "artifact_percentage_of_tissue": artifact_pct_tissue,
        "usability_threshold_artifact_fraction": usability_artifact_threshold,
        "usable": bool(artifact_pct_tissue <= usability_artifact_threshold and tissue_px > 0),
    }
    for cls, name in CLASS_NAMES.items():
        denominator = tissue_px if cls != BACKGROUND_CLASS else total_px
        row[f"{name}_px"] = counts[cls]
        row[f"{name}_fraction"] = counts[cls] / denominator if denominator else 0.0
    return pd.DataFrame([row])


def _load_models(artifact_mpp: float, device: str):
    import segmentation_models_pytorch as smp
    import torch

    preprocessing_fn = smp.encoders.get_preprocessing_fn(ENCODER_NAME, ENCODER_WEIGHTS)
    tissue_model = smp.UnetPlusPlus(
        encoder_name=ENCODER_NAME,
        encoder_weights=ENCODER_WEIGHTS,
        classes=2,
        activation=None,
    )
    tissue_state = torch.load(TISSUE_MODEL_PATH, map_location="cpu")
    tissue_model.load_state_dict(tissue_state)
    tissue_model.to(device)
    tissue_model.eval()

    artifact_model = _load_trusted_grandqc_artifact_model(torch, ARTIFACT_MODEL_PATHS[artifact_mpp], device)
    artifact_model.to(device) if hasattr(artifact_model, "to") else None
    artifact_model.eval() if hasattr(artifact_model, "eval") else None
    return tissue_model, artifact_model, preprocessing_fn


def _load_trusted_grandqc_artifact_model(torch_module: Any, path: Path, device: str) -> Any:
    """Load GrandQC artifact checkpoint from the official configured source.

    GrandQC distributes artifact checkpoints as pickled full model objects. In
    PyTorch 2.6+, ``torch.load`` defaults to ``weights_only=True``, which rejects
    those files. We explicitly opt into full unpickling here because paths are
    centralized in CONFIG and documented as official GrandQC Zenodo assets.
    """

    try:
        return torch_module.load(path, map_location=device, weights_only=False)
    except TypeError:
        return torch_module.load(path, map_location=device)


def _dicom_json_value(instance: dict[str, Any], tag: str, default: Any = None) -> Any:
    item = instance.get(tag)
    if item is None:
        return default
    values = item.get("Value")
    if not values:
        return default
    return values[0]


def _dicom_json_sequence(instance: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    item = instance.get(tag)
    if item is None:
        return []
    values = item.get("Value")
    if not values:
        return []
    return values


def _dicom_json_values(instance: dict[str, Any], tag: str, default: Any = None) -> Any:
    item = instance.get(tag)
    if item is None:
        return default
    values = item.get("Value")
    if not values:
        return default
    return values


def _dicom_json_pixel_spacing_um(instance: dict[str, Any]) -> tuple[float, float]:
    shared = _dicom_json_sequence(instance, "52009229")
    for group in shared:
        measures = _dicom_json_sequence(group, "00289110")
        for measure in measures:
            spacing = _dicom_json_values(measure, "00280030")
            if spacing:
                return float(spacing[0]) * 1000.0, float(spacing[1]) * 1000.0
    spacing = _dicom_json_values(instance, "00280030")
    if spacing:
        return float(spacing[0]) * 1000.0, float(spacing[1]) * 1000.0
    raise ValueError("DICOMweb metadata did not include PixelSpacing.")


def _dicom_json_frame_map(
    instance: dict[str, Any],
    tile_rows: int,
    tile_cols: int,
    number_of_frames: int,
) -> dict[int, dict[str, int]]:
    per_frame = _dicom_json_sequence(instance, "52009230")
    frame_map: dict[int, dict[str, int]] = {}
    for index, frame_group in enumerate(per_frame, start=1):
        positions = _dicom_json_sequence(frame_group, "0048021A")
        if not positions:
            continue
        position = positions[0]
        col = int(_dicom_json_value(position, "0048021E", 1)) - 1
        row = int(_dicom_json_value(position, "0048021F", 1)) - 1
        frame_map[index] = {
            "frame_number": index,
            "x": col,
            "y": row,
            "tile_rows": tile_rows,
            "tile_cols": tile_cols,
        }
    if frame_map:
        return frame_map

    # Fallback for regular full grids if per-frame positions are absent.
    total_cols = int(_dicom_json_value(instance, "00480006", tile_cols))
    tiles_per_row = max(1, math.ceil(total_cols / tile_cols))
    for index in range(1, number_of_frames + 1):
        zero = index - 1
        row_index = zero // tiles_per_row
        col_index = zero % tiles_per_row
        frame_map[index] = {
            "frame_number": index,
            "x": col_index * tile_cols,
            "y": row_index * tile_rows,
            "tile_rows": tile_rows,
            "tile_cols": tile_cols,
        }
    return frame_map


def _overlapping_frames(level: dict[str, Any], x: int, y: int, width: int, height: int) -> list[dict[str, int]]:
    x2 = x + width
    y2 = y + height
    frames = []
    for frame_info in level["frame_map"].values():
        fx = frame_info["x"]
        fy = frame_info["y"]
        fx2 = fx + frame_info["tile_cols"]
        fy2 = fy + frame_info["tile_rows"]
        if fx < x2 and fx2 > x and fy < y2 and fy2 > y:
            frames.append(frame_info)
    return frames


def _decode_dicomweb_frame(frame: bytes, rows: int, cols: int) -> Image.Image:
    frame = _strip_multipart_frame_headers(frame)
    try:
        return Image.open(BytesIO(frame)).convert(PRODUCTION_COLOR_MODE)
    except Exception:
        pass

    try:
        import imagecodecs

        arr = imagecodecs.imread(BytesIO(frame))
        return _array_to_rgb_image(arr)
    except Exception:
        pass

    try:
        import imagecodecs

        if frame.startswith(b"\xff\xd8"):
            arr = imagecodecs.jpeg_decode(frame)
            return _array_to_rgb_image(arr)
        if frame.startswith(b"\xff\x4f") or frame.startswith(b"\x00\x00\x00\x0cjP"):
            arr = imagecodecs.jpeg2k_decode(frame)
            return _array_to_rgb_image(arr)
    except Exception:
        pass

    arr = np.frombuffer(frame, dtype=np.uint8)
    if arr.size == rows * cols * 3:
        return Image.fromarray(arr.reshape(rows, cols, 3), mode="RGB").convert(PRODUCTION_COLOR_MODE)
    if arr.size == rows * cols:
        return Image.fromarray(arr.reshape(rows, cols), mode="L").convert(PRODUCTION_COLOR_MODE)

    raise ValueError(
        f"Could not decode DICOMweb frame bytes as an image. "
        f"Frame length={len(frame)} bytes, expected raw sizes {rows * cols} or {rows * cols * 3}."
    )


def _strip_multipart_frame_headers(frame: bytes) -> bytes:
    """Extract payload if a WADO-RS multipart part slipped through."""

    if not frame.startswith(b"--"):
        return frame
    header_end = frame.find(b"\r\n\r\n")
    if header_end == -1:
        header_end = frame.find(b"\n\n")
        delimiter_len = 2
    else:
        delimiter_len = 4
    if header_end == -1:
        return frame
    payload = frame[header_end + delimiter_len :]
    boundary_start = payload.rfind(b"\r\n--")
    if boundary_start != -1:
        payload = payload[:boundary_start]
    return payload.strip()


def _array_to_rgb_image(arr: np.ndarray) -> Image.Image:
    arr = np.asarray(arr)
    if arr.ndim == 2:
        return Image.fromarray(arr.astype(np.uint8), mode="L").convert(PRODUCTION_COLOR_MODE)
    if arr.ndim == 3:
        if arr.shape[0] in (1, 3, 4) and arr.shape[-1] not in (1, 3, 4):
            arr = np.moveaxis(arr, 0, -1)
        if arr.shape[-1] == 1:
            arr = arr[:, :, 0]
            return Image.fromarray(arr.astype(np.uint8), mode="L").convert(PRODUCTION_COLOR_MODE)
        if arr.shape[-1] >= 3:
            return Image.fromarray(arr[:, :, :3].astype(np.uint8), mode="RGB").convert(PRODUCTION_COLOR_MODE)
    raise ValueError(f"Unsupported decoded frame array shape: {arr.shape}")


def _run_tissue_detection(slide: SlideLike, tissue_model: Any, preprocessing_fn: Any, device: str) -> np.ndarray:
    """Run GrandQC tissue segmentation at 10 um/px."""

    import torch

    reduction = TISSUE_MPP / _isotropic_mpp(slide)
    thumb_w = max(1, int(round(slide.width / reduction)))
    thumb_h = max(1, int(round(slide.height / reduction)))
    thumb = _make_thumbnail_streamed(slide, thumb_w, thumb_h)
    thumb = _jpeg_roundtrip(thumb, quality=80)
    width, height = thumb.size
    mask = np.ones((height, width), dtype=np.uint8)

    wi_n = width // MODEL_TILE_SIZE
    he_n = height // MODEL_TILE_SIZE
    overhang_w = width - wi_n * MODEL_TILE_SIZE
    overhang_h = height - he_n * MODEL_TILE_SIZE

    for h in range(he_n + 1):
        for w in range(wi_n + 1):
            tile = _crop_grandqc_reference_tile(thumb, w, h, wi_n, he_n)
            image_pre = _preprocess(tile, preprocessing_fn)
            x_tensor = torch.from_numpy(image_pre).to(device).unsqueeze(0)
            with torch.no_grad():
                prediction = tissue_model.predict(x_tensor)
            patch_mask = np.argmax(prediction.squeeze().cpu().numpy(), axis=0).astype(np.uint8)
            x0, y0, x1, y1, sx0, sy0 = _grandqc_reference_tile_write_window(
                w,
                h,
                wi_n,
                he_n,
                width,
                height,
                overhang_w,
                overhang_h,
            )
            mask[y0:y1, x0:x1] = patch_mask[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)]
    return mask


def debug_tissue_detection(slide: SlideLike, tissue_model: Any, preprocessing_fn: Any, device: str) -> dict[str, Any]:
    """Return tissue-detection diagnostics without running artifact inference."""

    tissue_mask = _run_tissue_detection(slide, tissue_model, preprocessing_fn, device)
    reduction = TISSUE_MPP / _isotropic_mpp(slide)
    thumb_w = max(1, int(round(slide.width / reduction)))
    thumb_h = max(1, int(round(slide.height / reduction)))
    thumb = _make_thumbnail_streamed(slide, thumb_w, thumb_h)
    foreground_fraction = _thumbnail_foreground_fraction(thumb)
    tissue_px = int(np.count_nonzero(tissue_mask == 0))
    total_px = int(tissue_mask.size)
    return {
        "slide_id": slide.slide_id,
        "width_px": slide.width,
        "height_px": slide.height,
        "mpp_x_um": slide.mpp_x,
        "mpp_y_um": slide.mpp_y,
        "isotropic_mpp_um": _isotropic_mpp(slide),
        "tissue_mpp_um": TISSUE_MPP,
        "tissue_reduction": reduction,
        "thumbnail_width_px": thumb_w,
        "thumbnail_height_px": thumb_h,
        "thumbnail_foreground_fraction": foreground_fraction,
        "tissue_mask_width_px": int(tissue_mask.shape[1]),
        "tissue_mask_height_px": int(tissue_mask.shape[0]),
        "tissue_mask_tissue_px": tissue_px,
        "tissue_mask_total_px": total_px,
        "tissue_mask_tissue_fraction": tissue_px / total_px if total_px else 0.0,
        "tissue_detection_suspect": _is_tissue_detection_suspect(tissue_mask, foreground_fraction),
    }


def _make_thumbnail_streamed(slide: SlideLike, thumb_w: int, thumb_h: int, chunk_px: int = 4096) -> Image.Image:
    """Build a thumbnail from native chunks instead of one giant region read."""

    thumbnail = Image.new(PRODUCTION_COLOR_MODE, (thumb_w, thumb_h), color=(255, 255, 255))
    scale_x = thumb_w / slide.width
    scale_y = thumb_h / slide.height
    for y in range(0, slide.height, chunk_px):
        for x in range(0, slide.width, chunk_px):
            native_w = min(chunk_px, slide.width - x)
            native_h = min(chunk_px, slide.height - y)
            region = slide.read_region((x, y), 0, (native_w, native_h)).convert(PRODUCTION_COLOR_MODE)
            paste_x = int(round(x * scale_x))
            paste_y = int(round(y * scale_y))
            paste_w = max(1, int(round(native_w * scale_x)))
            paste_h = max(1, int(round(native_h * scale_y)))
            thumbnail.paste(
                region.resize((paste_w, paste_h), Image.Resampling.LANCZOS),
                (paste_x, paste_y),
            )
    return thumbnail


def _crop_grandqc_reference_tile(
    image: Image.Image,
    tile_x: int,
    tile_y: int,
    last_x: int,
    last_y: int,
) -> Image.Image:
    """Crop tissue-detection tiles like GrandQC's reference OpenSlide script.

    The original script always feeds a full 512 x 512 tile. For right/bottom
    edges it anchors the crop at ``width - 512`` / ``height - 512`` instead of
    padding the partial edge tile with white. This matters for small thumbnails.
    """

    p_s = MODEL_TILE_SIZE
    if tile_x != last_x and tile_y != last_y:
        box = (tile_x * p_s, tile_y * p_s, (tile_x + 1) * p_s, (tile_y + 1) * p_s)
    elif tile_x == last_x and tile_y != last_y:
        box = (image.width - p_s, tile_y * p_s, image.width, (tile_y + 1) * p_s)
    elif tile_x != last_x and tile_y == last_y:
        box = (tile_x * p_s, image.height - p_s, (tile_x + 1) * p_s, image.height)
    else:
        box = (image.width - p_s, image.height - p_s, image.width, image.height)
    return image.crop(box).convert(PRODUCTION_COLOR_MODE)


def _grandqc_reference_tile_write_window(
    tile_x: int,
    tile_y: int,
    last_x: int,
    last_y: int,
    width: int,
    height: int,
    overhang_w: int,
    overhang_h: int,
) -> tuple[int, int, int, int, int, int]:
    p_s = MODEL_TILE_SIZE
    if tile_x == last_x:
        x0 = max(0, width - max(overhang_w, 0))
        x1 = width
        sx0 = p_s - max(overhang_w, 0)
    else:
        x0 = tile_x * p_s
        x1 = min((tile_x + 1) * p_s, width)
        sx0 = 0
    if tile_y == last_y:
        y0 = max(0, height - max(overhang_h, 0))
        y1 = height
        sy0 = p_s - max(overhang_h, 0)
    else:
        y0 = tile_y * p_s
        y1 = min((tile_y + 1) * p_s, height)
        sy0 = 0
    return x0, y0, x1, y1, sx0, sy0


def _run_artifact_detection(
    slide: SlideLike,
    tissue_mask: np.ndarray,
    artifact_model: Any,
    preprocessing_fn: Any,
    artifact_mpp: float,
    device: str,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Run GrandQC artifact segmentation and collect per-tile class fractions."""

    import torch

    native_patch = max(1, int(artifact_mpp / _isotropic_mpp(slide) * MODEL_TILE_SIZE))
    patch_n_w = max(1, math.ceil(slide.width / native_patch))
    patch_n_h = max(1, math.ceil(slide.height / native_patch))
    mask_h = patch_n_h * MODEL_TILE_SIZE
    mask_w = patch_n_w * MODEL_TILE_SIZE
    full_mask = np.full((mask_h, mask_w), BACKGROUND_CLASS, dtype=np.uint8)
    tissue_for_artifact = np.array(
        Image.fromarray(tissue_mask).resize((mask_w, mask_h), Image.Resampling.NEAREST)
    )
    tile_rows = []

    for he in range(patch_n_h):
        for wi in range(patch_n_w):
            x = wi * native_patch
            y = he * native_patch
            tile_tissue = tissue_for_artifact[
                he * MODEL_TILE_SIZE : (he + 1) * MODEL_TILE_SIZE,
                wi * MODEL_TILE_SIZE : (wi + 1) * MODEL_TILE_SIZE,
            ]
            if int(np.count_nonzero(tile_tissue == 0)) > MIN_TISSUE_PIXELS_PER_TILE:
                region = slide.read_region(
                    (min(x, slide.width - 1), min(y, slide.height - 1)),
                    0,
                    (min(native_patch, slide.width - x), min(native_patch, slide.height - y)),
                )
                tile = region.resize((MODEL_TILE_SIZE, MODEL_TILE_SIZE), Image.Resampling.LANCZOS)
                image_pre = _preprocess(tile, preprocessing_fn)
                x_tensor = torch.from_numpy(image_pre).to(device).unsqueeze(0)
                with torch.no_grad():
                    prediction = artifact_model.predict(x_tensor)
                raw_mask = np.argmax(prediction.squeeze().cpu().numpy(), axis=0).astype(np.uint8)
                raw_mask = _grandqc_raw_to_documented_labels(raw_mask)
                patch_mask = np.where(tile_tissue == 1, BACKGROUND_CLASS, raw_mask)
            else:
                patch_mask = np.full((MODEL_TILE_SIZE, MODEL_TILE_SIZE), BACKGROUND_CLASS, dtype=np.uint8)

            full_mask[
                he * MODEL_TILE_SIZE : (he + 1) * MODEL_TILE_SIZE,
                wi * MODEL_TILE_SIZE : (wi + 1) * MODEL_TILE_SIZE,
            ] = patch_mask
            tile_rows.append(_tile_summary(slide.slide_id, wi, he, x, y, native_patch, patch_mask))

    valid_h = max(1, int(round(slide.height * _isotropic_mpp(slide) / artifact_mpp)))
    valid_w = max(1, int(round(slide.width * _isotropic_mpp(slide) / artifact_mpp)))
    return full_mask[:valid_h, :valid_w], pd.DataFrame(tile_rows)


def _tile_summary(
    slide_id: str,
    tile_x: int,
    tile_y: int,
    x_l0: int,
    y_l0: int,
    native_patch_size: int,
    patch_mask: np.ndarray,
) -> dict[str, Any]:
    tissue_px = int(np.sum(patch_mask != BACKGROUND_CLASS))
    artifact_px = int(sum(np.sum(patch_mask == cls) for cls in ARTIFACT_CLASSES))
    row: dict[str, Any] = {
        "slide_id": slide_id,
        "tile_x": tile_x,
        "tile_y": tile_y,
        "x_l0": x_l0,
        "y_l0": y_l0,
        "native_patch_size_px": native_patch_size,
        "tissue_px": tissue_px,
        "artifact_px": artifact_px,
        "artifact_fraction_of_tissue": artifact_px / tissue_px if tissue_px else 0.0,
    }
    for cls, name in CLASS_NAMES.items():
        row[f"{name}_px"] = int(np.sum(patch_mask == cls))
    return row


def _grandqc_raw_to_documented_labels(raw_mask: np.ndarray) -> np.ndarray:
    """Map GrandQC raw argmax channels to documented class ids.

    The reference scripts use ``np.argmax`` directly and then force tissue-mask
    background to class 7. Their palette/reporting treats class 1 as normal
    tissue and 2-6 as artifacts, so we preserve raw labels 1-6. If a checkpoint
    emits class 0, keep the pipeline documented by treating it as normal tissue
    instead of counting the whole tile as artifact.
    """

    mapped = raw_mask.astype(np.uint8).copy()
    mapped[raw_mask == 0] = 1
    return mapped


def _preprocess(image: Image.Image, preprocessing_fn: Any) -> np.ndarray:
    image = image.convert(PRODUCTION_COLOR_MODE)
    if image.size != (MODEL_TILE_SIZE, MODEL_TILE_SIZE):
        image = image.resize((MODEL_TILE_SIZE, MODEL_TILE_SIZE), Image.Resampling.LANCZOS)
    arr = np.asarray(image)
    arr = preprocessing_fn(arr)
    return arr.transpose(2, 0, 1).astype("float32")



def _add_tissue_detection_guardrail(slide: SlideLike, tissue_mask: np.ndarray, summary: pd.DataFrame) -> pd.DataFrame:
    """Annotate summaries when tissue detection is suspiciously empty."""

    out = summary.copy()
    thumb_w = min(768, max(1, int(slide.width)))
    thumb_h = max(1, int(round(slide.height * (thumb_w / slide.width))))
    thumb = _make_thumbnail_streamed(slide, thumb_w, thumb_h)
    foreground_fraction = _thumbnail_foreground_fraction(thumb)
    tissue_fraction = float(np.count_nonzero(tissue_mask == 0) / tissue_mask.size) if tissue_mask.size else 0.0
    suspect = _is_tissue_detection_suspect(tissue_mask, foreground_fraction)
    reason = ""
    if suspect:
        reason = (
            f"tissue detection fraction {tissue_fraction:.6f} <= {TISSUE_SUSPECT_MAX_FRACTION:.6f} "
            f"while thumbnail foreground fraction {foreground_fraction:.6f} >= {FOREGROUND_SUSPECT_MIN_FRACTION:.6f}"
        )
        LOGGER.warning("Tissue detection suspect for %s: %s", slide.slide_id, reason)
    out["tissue_detection_suspect"] = bool(suspect)
    out["tissue_detection_reason"] = reason
    out["tissue_detection_tissue_fraction"] = tissue_fraction
    out["thumbnail_foreground_fraction"] = foreground_fraction
    return out


def _is_tissue_detection_suspect(tissue_mask: np.ndarray, foreground_fraction: float) -> bool:
    tissue_fraction = float(np.count_nonzero(tissue_mask == 0) / tissue_mask.size) if tissue_mask.size else 0.0
    return tissue_fraction <= TISSUE_SUSPECT_MAX_FRACTION and foreground_fraction >= FOREGROUND_SUSPECT_MIN_FRACTION


def _thumbnail_foreground_fraction(image: Image.Image) -> float:
    """Cheap non-white foreground estimate for suspect tissue-detection guardrail."""

    arr = np.asarray(image.convert(PRODUCTION_COLOR_MODE)).astype(np.int16)
    # Tissue and stains are usually non-white and chromatic; ignore pale slide background.
    max_channel = arr.max(axis=2)
    min_channel = arr.min(axis=2)
    chroma = max_channel - min_channel
    nonwhite = max_channel < 235
    saturated = chroma > 12
    foreground = nonwhite & saturated
    return float(np.mean(foreground)) if foreground.size else 0.0


def _jpeg_roundtrip(image: Image.Image, quality: int) -> Image.Image:
    import io

    buffer = io.BytesIO()
    image.convert(PRODUCTION_COLOR_MODE).save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert(PRODUCTION_COLOR_MODE)


def _save_mask(mask: np.ndarray, path: Path) -> None:
    Image.fromarray(mask.astype(np.uint8)).save(path)


def _validate_slide_mpp(slide: SlideLike) -> None:
    if slide.mpp_x <= 0 or slide.mpp_y <= 0:
        raise ValueError(f"Invalid MPP for {slide.slide_id}: x={slide.mpp_x}, y={slide.mpp_y}")
    if not math.isclose(slide.mpp_x, slide.mpp_y, rel_tol=0, abs_tol=0.002):
        raise ValueError(
            f"GrandQC expects near-square pixels; got x={slide.mpp_x:.6f}, "
            f"y={slide.mpp_y:.6f} for {slide.slide_id}."
        )


def _isotropic_mpp(slide: SlideLike) -> float:
    _validate_slide_mpp(slide)
    return (slide.mpp_x + slide.mpp_y) / 2.0


def _default_device() -> str:
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def inspect_dicom_series(source: str | os.PathLike[str]) -> pd.DataFrame:
    """Return a one-row metadata table for a DICOM series without inference."""

    info = get_slide_info(source)
    return pd.DataFrame(
        [
            {
                "source": str(Path(source)),
                "width_px": info.width,
                "height_px": info.height,
                "level_count": info.level_count,
                "mpp_x_um": info.mpp_x_um,
                "mpp_y_um": info.mpp_y_um,
            }
        ]
    )


def debug_artifact_tile(
    slide_source: str | os.PathLike[str],
    *,
    x_l0: int,
    y_l0: int,
    native_patch_size_px: int,
    input_type: str = "dicom",
    artifact_mpp: float = DEFAULT_ARTIFACT_MPP,
    device: str | None = None,
) -> tuple[pd.DataFrame, Image.Image]:
    """Inspect raw artifact-model channels for one tile.

    This helper is intended for validating wrappers against the GrandQC
    reference scripts. It bypasses tissue gating and reports raw argmax channel
    counts plus the documented-label counts used by this module.
    """

    check_weights(artifact_mpp=artifact_mpp)
    device = device or _default_device()
    _, artifact_model, preprocessing_fn = _load_models(artifact_mpp, device)
    slide = open_slide(slide_source, input_type=input_type)
    try:
        tile = slide.read_region(
            (int(x_l0), int(y_l0)),
            0,
            (int(native_patch_size_px), int(native_patch_size_px)),
        ).convert("RGB")
        model_tile = tile.resize((MODEL_TILE_SIZE, MODEL_TILE_SIZE), Image.Resampling.LANCZOS)
        raw_mask = _predict_raw_artifact_mask(artifact_model, preprocessing_fn, model_tile, device)
        documented = _grandqc_raw_to_documented_labels(raw_mask)
    finally:
        slide.close()

    rows = []
    for label, mask in [("raw_argmax", raw_mask), ("documented", documented)]:
        counts = {int(cls): int(np.sum(mask == cls)) for cls in np.unique(mask)}
        rows.append({"label_space": label, **{f"class_{k}": v for k, v in sorted(counts.items())}})
    return pd.DataFrame(rows).fillna(0), model_tile


def debug_artifact_tile_variants(
    slide_source: str | os.PathLike[str],
    *,
    x_l0: int,
    y_l0: int,
    native_patch_size_px: int,
    input_type: str = "dicom",
    artifact_mpp: float = DEFAULT_ARTIFACT_MPP,
    device: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Image.Image]]:
    """Run one tile through color/input variants to diagnose preprocessing parity."""

    check_weights(artifact_mpp=artifact_mpp)
    device = device or _default_device()
    _, artifact_model, preprocessing_fn = _load_models(artifact_mpp, device)
    slide = open_slide(slide_source, input_type=input_type)
    try:
        tile = slide.read_region(
            (int(x_l0), int(y_l0)),
            0,
            (int(native_patch_size_px), int(native_patch_size_px)),
        ).convert("RGB")
        base = tile.resize((MODEL_TILE_SIZE, MODEL_TILE_SIZE), Image.Resampling.LANCZOS)
    finally:
        slide.close()

    variants = _tile_variants(base)
    rows = []
    for name, image in variants.items():
        raw_mask = _predict_raw_artifact_mask(artifact_model, preprocessing_fn, image, device)
        documented = _grandqc_raw_to_documented_labels(raw_mask)
        raw_counts = {int(cls): int(np.sum(raw_mask == cls)) for cls in np.unique(raw_mask)}
        doc_counts = {int(cls): int(np.sum(documented == cls)) for cls in np.unique(documented)}
        rows.append(
            {
                "variant": name,
                "mean_r": float(np.asarray(image)[:, :, 0].mean()),
                "mean_g": float(np.asarray(image)[:, :, 1].mean()),
                "mean_b": float(np.asarray(image)[:, :, 2].mean()),
                "raw_counts": raw_counts,
                "documented_counts": doc_counts,
            }
        )
    return pd.DataFrame(rows), variants


def debug_compare_openslide_tile(
    slide_source: str | os.PathLike[str],
    *,
    x_l0: int,
    y_l0: int,
    native_patch_size_px: int,
    artifact_mpp: float = DEFAULT_ARTIFACT_MPP,
    device: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Image.Image]]:
    """Compare wsidicom and optional OpenSlide reads for one DICOM tile.

    This is a diagnostic helper only. The production pipeline avoids OpenSlide
    MPP reliance, but comparing pixel reads helps validate DICOM color handling
    against GrandQC's original OpenSlide-based scripts.
    """

    check_weights(artifact_mpp=artifact_mpp)
    device = device or _default_device()
    _, artifact_model, preprocessing_fn = _load_models(artifact_mpp, device)

    images: dict[str, Image.Image] = {}
    wsidicom_slide = open_slide(slide_source, input_type="dicom")
    try:
        images["wsidicom_rgb"] = wsidicom_slide.read_region(
            (int(x_l0), int(y_l0)),
            0,
            (int(native_patch_size_px), int(native_patch_size_px)),
        ).convert("RGB").resize((MODEL_TILE_SIZE, MODEL_TILE_SIZE), Image.Resampling.LANCZOS)
    finally:
        wsidicom_slide.close()

    try:
        import openslide
    except ImportError:
        LOGGER.warning("OpenSlide is not installed; skipping OpenSlide tile comparison.")
    else:
        entry = _first_dicom_file(slide_source)
        os_slide = openslide.OpenSlide(str(entry))
        try:
            images["openslide_rgb"] = os_slide.read_region(
                (int(x_l0), int(y_l0)),
                0,
                (int(native_patch_size_px), int(native_patch_size_px)),
            ).convert("RGB").resize((MODEL_TILE_SIZE, MODEL_TILE_SIZE), Image.Resampling.LANCZOS)
        finally:
            os_slide.close()

    rows = []
    for name, image in images.items():
        arr = np.asarray(image)
        raw_mask = _predict_raw_artifact_mask(artifact_model, preprocessing_fn, image, device)
        rows.append(
            {
                "reader": name,
                "mean_r": float(arr[:, :, 0].mean()),
                "mean_g": float(arr[:, :, 1].mean()),
                "mean_b": float(arr[:, :, 2].mean()),
                "raw_counts": {int(cls): int(np.sum(raw_mask == cls)) for cls in np.unique(raw_mask)},
            }
        )
    if "wsidicom_rgb" in images and "openslide_rgb" in images:
        ws = np.asarray(images["wsidicom_rgb"]).astype(np.int16)
        os_arr = np.asarray(images["openslide_rgb"]).astype(np.int16)
        diff = np.abs(ws - os_arr)
        rows.append(
            {
                "reader": "absdiff_wsidicom_vs_openslide",
                "mean_r": float(diff[:, :, 0].mean()),
                "mean_g": float(diff[:, :, 1].mean()),
                "mean_b": float(diff[:, :, 2].mean()),
                "raw_counts": {},
            }
        )
    return pd.DataFrame(rows), images


def _first_dicom_file(path: str | os.PathLike[str]) -> Path:
    root = Path(path)
    if root.is_file():
        return root
    files = sorted(root.glob("*.dcm"))
    if not files:
        raise FileNotFoundError(f"No .dcm files found under {root}")
    return files[0]


def _tile_variants(image: Image.Image) -> dict[str, Image.Image]:
    """Generate conservative RGB variants for diagnosing DICOM color handling."""

    from PIL import ImageOps

    rgb = image.convert("RGB")
    arr = np.asarray(rgb)
    bgr = Image.fromarray(arr[:, :, ::-1].copy(), mode="RGB")
    return {
        "rgb": rgb,
        "bgr_channel_swap": bgr,
        "autocontrast_rgb": ImageOps.autocontrast(rgb),
        "jpeg_quality_80_rgb": _jpeg_roundtrip(rgb, quality=80),
    }


def _predict_raw_artifact_mask(
    artifact_model: Any,
    preprocessing_fn: Any,
    image: Image.Image,
    device: str,
) -> np.ndarray:
    import torch

    image_pre = _preprocess(image, preprocessing_fn)
    x_tensor = torch.from_numpy(image_pre).to(device).unsqueeze(0)
    with torch.no_grad():
        prediction = artifact_model.predict(x_tensor)
    return np.argmax(prediction.squeeze().cpu().numpy(), axis=0).astype(np.uint8)
