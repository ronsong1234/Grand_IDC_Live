"""IDC DICOM whole-slide access and optional pyramidal TIFF conversion.

This module is deliberately strict about microns-per-pixel (MPP).  The source
MPP is read from DICOM slide microscopy metadata, not from filenames, objective
power, or OpenSlide properties.  TIFF conversion is optional because direct
DICOM tile streaming has been the highest-concordance path for the GrandQC x IDC
pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
import math
import os
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
import pandas as pd
import pydicom
import tifffile

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]


# =============================================================================
# CONFIG
# =============================================================================

DEFAULT_DOWNLOAD_DIR = REPO_ROOT / "data" / "idc_series"
DEFAULT_TIFF_DIR = REPO_ROOT / "data" / "tiff"
IDC_DIR_TEMPLATE = "%SeriesInstanceUID"
TIFF_TILE_SIZE = 512
TIFF_COMPRESSION = "jpeg"
TIFF_JPEG_QUALITY = 90
MPP_TOLERANCE_UM = 0.002


@dataclass(frozen=True)
class PixelSpacing:
    """Pixel spacing in microns per pixel for one resolution level."""

    x_um: float
    y_um: float
    source: str
    level_index: int | None = None
    sop_instance_uid: str | None = None

    @property
    def isotropic_um(self) -> float:
        """Return mean MPP when x/y differ only within tolerance."""

        if not math.isclose(self.x_um, self.y_um, rel_tol=0, abs_tol=MPP_TOLERANCE_UM):
            raise ValueError(
                f"Anisotropic pixel spacing detected: x={self.x_um:.6f} um, "
                f"y={self.y_um:.6f} um from {self.source}"
            )
        return (self.x_um + self.y_um) / 2.0


@dataclass(frozen=True)
class SlideInfo:
    """Basic source slide metadata needed by downstream QC."""

    path: Path
    width: int
    height: int
    level_count: int
    level_spacings: tuple[PixelSpacing, ...]

    @property
    def mpp_x_um(self) -> float:
        return self.level_spacings[0].x_um

    @property
    def mpp_y_um(self) -> float:
        return self.level_spacings[0].y_um

    @property
    def mpp_um(self) -> float:
        return self.level_spacings[0].isotropic_um


class DirectDicomSlide:
    """Small adapter around wsidicom for direct DICOM tile/region reads."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._wsidicom = _import_wsidicom()
        self._slide = self._open_slide(self.path)
        self.info = get_slide_info(self.path, open_slide=self._slide)

    @staticmethod
    def _open_slide(path: Path):
        from wsidicom import WsiDicom

        if path.is_dir():
            return WsiDicom.open([str(p) for p in sorted(path.glob("*.dcm"))])
        return WsiDicom.open(str(path))

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.info.width, self.info.height

    @property
    def level_count(self) -> int:
        return self.info.level_count

    @property
    def mpp(self) -> float:
        return self.info.mpp_um

    def read_region(self, location: tuple[int, int], level: int, size: tuple[int, int]):
        """Read a region as a PIL RGB image.

        The adapter targets the wsidicom public API but keeps the calls isolated
        because wsidicom has changed naming around levels/regions over time.
        """

        x, y = location
        width, height = size
        if hasattr(self._slide, "read_region"):
            region = self._slide.read_region(location, level, size)
        elif hasattr(self._slide, "level"):
            region = self._slide.level(level).read_region((x, y), (width, height))
        else:
            raise AttributeError("Unsupported wsidicom version: no region read API found.")
        if hasattr(region, "convert"):
            return region.convert("RGB")
        from PIL import Image

        return Image.fromarray(np.asarray(region)).convert("RGB")

    def close(self) -> None:
        close = getattr(self._slide, "close", None)
        if close is not None:
            close()


def _import_wsidicom():
    try:
        import wsidicom
    except ImportError as exc:
        raise ImportError(
            "wsidicom is required for direct DICOM slide streaming. "
            "Install with: pip install wsidicom"
        ) from exc
    return wsidicom


def download_idc_series(
    series_instance_uid: str | Sequence[str],
    download_dir: str | os.PathLike[str] = DEFAULT_DOWNLOAD_DIR,
) -> pd.DataFrame:
    """Download one or more IDC series with idc-index.

    Returns a manifest DataFrame containing the requested series and local
    directories.  IDC version is logged for reproducibility.
    """

    try:
        from idc_index import IDCClient
    except ImportError as exc:
        raise ImportError("Install IDC access support with: pip install --upgrade idc-index") from exc

    series = [series_instance_uid] if isinstance(series_instance_uid, str) else list(series_instance_uid)
    client = IDCClient()
    LOGGER.info("IDC data version: %s", client.get_idc_version())
    download_root = Path(download_dir)
    download_root.mkdir(parents=True, exist_ok=True)
    client.download_from_selection(
        seriesInstanceUID=series,
        downloadDir=str(download_root),
        dirTemplate=IDC_DIR_TEMPLATE,
    )
    rows = [
        {"SeriesInstanceUID": uid, "series_dir": str((download_root / uid).resolve())}
        for uid in series
    ]
    return pd.DataFrame(rows)


def iter_dicom_files(path: str | os.PathLike[str]) -> Iterator[Path]:
    """Yield DICOM files from a local series folder or a single file."""

    root = Path(path)
    if root.is_file():
        yield root
        return
    yield from sorted(p for p in root.rglob("*.dcm") if p.is_file())


def extract_pixel_spacings(path: str | os.PathLike[str]) -> tuple[PixelSpacing, ...]:
    """Extract per-instance DICOM pixel spacings in microns.

    DICOM `PixelSpacing` is in millimeters, so values are multiplied by 1000.
    For slide microscopy objects, the most reliable path is usually
    `SharedFunctionalGroupsSequence[0].PixelMeasuresSequence[0].PixelSpacing`.
    """

    spacings: list[PixelSpacing] = []
    for dcm_path in iter_dicom_files(path):
        ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=True, force=True)
        sop_uid = str(getattr(ds, "SOPInstanceUID", dcm_path.name))
        for spacing, source in _spacing_candidates(ds):
            y_um, x_um = float(spacing[0]) * 1000.0, float(spacing[1]) * 1000.0
            level_index = _level_index(ds)
            spacings.append(
                PixelSpacing(
                    x_um=x_um,
                    y_um=y_um,
                    source=f"{dcm_path.name}:{source}",
                    level_index=level_index,
                    sop_instance_uid=sop_uid,
                )
            )
            break

    if not spacings:
        raise ValueError(
            f"No DICOM PixelSpacing found under {Path(path)}. "
            "Expected PixelSpacing or SharedFunctionalGroupsSequence/"
            "PixelMeasuresSequence/PixelSpacing."
        )
    return tuple(spacings)


def _spacing_candidates(ds) -> Iterator[tuple[Sequence[float], str]]:
    if "PixelSpacing" in ds:
        yield ds.PixelSpacing, "PixelSpacing"
    shared = getattr(ds, "SharedFunctionalGroupsSequence", None)
    if shared:
        for s_idx, group in enumerate(shared):
            measures = getattr(group, "PixelMeasuresSequence", None)
            if measures:
                for m_idx, measure in enumerate(measures):
                    if "PixelSpacing" in measure:
                        yield (
                            measure.PixelSpacing,
                            f"SharedFunctionalGroupsSequence[{s_idx}]."
                            f"PixelMeasuresSequence[{m_idx}].PixelSpacing",
                        )
    yield from _recursive_pixel_spacing(ds, "Dataset", max_depth=4)


def _recursive_pixel_spacing(obj, path: str, max_depth: int) -> Iterator[tuple[Sequence[float], str]]:
    """Find nested PixelSpacing values, including optical-path/vendor nesting."""

    if max_depth <= 0 or not hasattr(obj, "iterall"):
        return
    for elem in obj:
        keyword = elem.keyword or elem.name.replace(" ", "")
        elem_path = f"{path}.{keyword}"
        if keyword == "PixelSpacing":
            yield elem.value, elem_path
        if elem.VR == "SQ":
            for index, item in enumerate(elem.value):
                yield from _recursive_pixel_spacing(item, f"{elem_path}[{index}]", max_depth - 1)


def _level_index(ds) -> int | None:
    for name in (
        "ConcatenationFrameOffsetNumber",
        "TotalPixelMatrixFocalPlanes",
        "ImageType",
    ):
        value = getattr(ds, name, None)
        if isinstance(value, int):
            return value
    return None


def summarize_spacings(spacings: Iterable[PixelSpacing]) -> tuple[PixelSpacing, ...]:
    """Collapse equivalent spacings and preserve distinct per-level MPP values."""

    unique: list[PixelSpacing] = []
    for spacing in spacings:
        if not any(
            math.isclose(spacing.x_um, seen.x_um, rel_tol=0, abs_tol=MPP_TOLERANCE_UM)
            and math.isclose(spacing.y_um, seen.y_um, rel_tol=0, abs_tol=MPP_TOLERANCE_UM)
            for seen in unique
        ):
            unique.append(spacing)
    unique.sort(key=lambda s: s.isotropic_um)
    return tuple(unique)


def get_slide_info(path: str | os.PathLike[str], open_slide=None) -> SlideInfo:
    """Read slide dimensions, level count, and DICOM-derived MPP."""

    root = Path(path)
    spacings = summarize_spacings(extract_pixel_spacings(root))
    slide = open_slide
    close_after = False
    if slide is None:
        slide = DirectDicomSlide._open_slide(root)
        close_after = True
    try:
        try:
            width, height = _wsidicom_dimensions(slide)
        except AttributeError:
            width, height = _dicom_total_pixel_matrix(root)
        level_count = max(_wsidicom_level_count(slide), len(spacings))
    finally:
        if close_after and hasattr(slide, "close"):
            slide.close()

    info = SlideInfo(root, width, height, level_count, spacings)
    LOGGER.info(
        "Slide %s: MPP x=%.6f y=%.6f um, dimensions=%sx%s, levels=%s",
        root,
        info.mpp_x_um,
        info.mpp_y_um,
        info.width,
        info.height,
        info.level_count,
    )
    if len(spacings) > 1:
        LOGGER.info(
            "Detected differing MPP values by level/source: %s",
            [(s.x_um, s.y_um, s.source) for s in spacings],
        )
    return info


def _wsidicom_dimensions(slide) -> tuple[int, int]:
    for attr in ("size", "image_size"):
        value = getattr(slide, attr, None)
        if value is not None:
            return _size_to_tuple(value)
    if hasattr(slide, "level"):
        level0 = slide.level(0)
        for attr in ("size", "image_size"):
            value = getattr(level0, attr, None)
            if value is not None:
                return _size_to_tuple(value)
    raise AttributeError("Could not determine wsidicom slide dimensions.")


def _wsidicom_level_count(slide) -> int:
    levels = getattr(slide, "levels", None)
    if levels is not None:
        return len(levels)
    pyramid = getattr(slide, "pyramid", None)
    if pyramid is not None and hasattr(pyramid, "levels"):
        return len(pyramid.levels)
    return 1


def _dicom_total_pixel_matrix(path: Path) -> tuple[int, int]:
    for dcm_path in iter_dicom_files(path):
        ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=True, force=True)
        columns = getattr(ds, "TotalPixelMatrixColumns", None)
        rows = getattr(ds, "TotalPixelMatrixRows", None)
        if columns and rows:
            return int(columns), int(rows)
        if getattr(ds, "Columns", None) and getattr(ds, "Rows", None):
            return int(ds.Columns), int(ds.Rows)
    raise AttributeError(f"Could not determine DICOM slide dimensions under {path}.")


def _size_to_tuple(value) -> tuple[int, int]:
    if hasattr(value, "width") and hasattr(value, "height"):
        return int(value.width), int(value.height)
    if isinstance(value, Sequence):
        return int(value[0]), int(value[1])
    raise TypeError(f"Unsupported size object: {value!r}")


def convert_dicom_to_tiff(
    source: str | os.PathLike[str],
    output_tiff: str | os.PathLike[str] | None = None,
    *,
    tile_size: int = TIFF_TILE_SIZE,
    compression: str = TIFF_COMPRESSION,
    jpeg_quality: int = TIFF_JPEG_QUALITY,
    validate: bool = True,
) -> Path:
    """Convert a DICOM WSI series to tiled pyramidal TIFF with MPP tags.

    The TIFF resolution tags are written as pixels per centimeter.  Since MPP is
    microns per pixel, pixels/cm = 10000 / MPP.
    """

    info = get_slide_info(source)
    out_path = Path(output_tiff) if output_tiff else DEFAULT_TIFF_DIR / (Path(source).name + ".tif")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import pyvips
    except ImportError as exc:
        raise ImportError("pyvips is required for TIFF conversion. Install with: pip install pyvips") from exc

    slide = DirectDicomSlide(source)
    try:
        image = _direct_slide_to_vips(slide, pyvips)
        xres = 10000.0 / info.mpp_x_um
        yres = 10000.0 / info.mpp_y_um
        image.set_type(pyvips.GValue.gdouble_type, "xres", xres)
        image.set_type(pyvips.GValue.gdouble_type, "yres", yres)
        image.set_type(pyvips.GValue.gstr_type, "resolution-unit", "cm")
        image.tiffsave(
            str(out_path),
            tile=True,
            pyramid=True,
            tile_width=tile_size,
            tile_height=tile_size,
            compression=compression,
            Q=jpeg_quality,
            bigtiff=True,
        )
    finally:
        slide.close()

    if validate:
        validate_tiff_mpp(out_path, info.mpp_x_um, info.mpp_y_um)
    LOGGER.info("Wrote %s with MPP x=%.6f y=%.6f um", out_path, info.mpp_x_um, info.mpp_y_um)
    return out_path


def _direct_slide_to_vips(slide: DirectDicomSlide, pyvips):
    """Build a pyvips image from direct DICOM reads.

    This is memory-backed by design for tutorial-sized slides.  For very large
    production batches, replace this with a pyvips source that pulls regions
    lazily from wsidicom.
    """

    from PIL import Image

    width, height = slide.dimensions
    rows = []
    for y in range(0, height, TIFF_TILE_SIZE):
        row_tiles = []
        for x in range(0, width, TIFF_TILE_SIZE):
            tile_w = min(TIFF_TILE_SIZE, width - x)
            tile_h = min(TIFF_TILE_SIZE, height - y)
            tile = slide.read_region((x, y), 0, (tile_w, tile_h)).convert("RGB")
            if tile.size != (tile_w, tile_h):
                tile = tile.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
            arr = np.asarray(tile)
            row_tiles.append(arr)
        rows.append(np.concatenate(row_tiles, axis=1))
    full = np.concatenate(rows, axis=0)
    return pyvips.Image.new_from_memory(full.tobytes(), width, height, 3, "uchar")


def read_tiff_mpp(path: str | os.PathLike[str]) -> tuple[float, float]:
    """Read MPP from TIFF X/YResolution tags."""

    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        unit_tag = page.tags.get("ResolutionUnit")
        unit = unit_tag.value if unit_tag else 2
        x_resolution = _ratio_to_float(page.tags["XResolution"].value)
        y_resolution = _ratio_to_float(page.tags["YResolution"].value)
    if unit == 3:  # centimeter
        factor_um = 10000.0
    elif unit == 2:  # inch
        factor_um = 25400.0
    else:
        raise ValueError(f"Unsupported TIFF ResolutionUnit {unit!r}; expected inch or centimeter.")
    return factor_um / x_resolution, factor_um / y_resolution


def _ratio_to_float(value) -> float:
    if isinstance(value, tuple):
        return float(value[0]) / float(value[1])
    return float(value)


def validate_tiff_mpp(
    path: str | os.PathLike[str],
    expected_x_um: float,
    expected_y_um: float,
    tolerance_um: float = MPP_TOLERANCE_UM,
) -> None:
    """Assert that TIFF resolution tags round-trip to the source MPP."""

    observed_x, observed_y = read_tiff_mpp(path)
    if not (
        math.isclose(observed_x, expected_x_um, rel_tol=0, abs_tol=tolerance_um)
        and math.isclose(observed_y, expected_y_um, rel_tol=0, abs_tol=tolerance_um)
    ):
        raise AssertionError(
            f"TIFF MPP round-trip failed for {path}: expected "
            f"({expected_x_um:.6f}, {expected_y_um:.6f}) um, observed "
            f"({observed_x:.6f}, {observed_y:.6f}) um."
        )


def open_direct_dicom(source: str | os.PathLike[str]) -> DirectDicomSlide:
    """Open a DICOM WSI for direct tile streaming."""

    return DirectDicomSlide(source)
