from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from modules.validation import compare_mask_pair, discover_mask_pairs, extract_tcga_slide_id, MaskPair


def write_mask(path: Path, values: np.ndarray) -> None:
    Image.fromarray(values.astype(np.uint8)).save(path)


def test_extract_tcga_slide_id_handles_reference_and_dashboard_names() -> None:
    assert (
        extract_tcga_slide_id("TCGA-AC-A23G-01Z-00-DX1.2F0326F7-6B77-4B3F-B4FA-59ADB785AA07.svs_mask.png")
        == "TCGA-AC-A23G-01Z-00-DX1"
    )
    assert extract_tcga_slide_id("TCGA-AC-A23G-01Z-00-DX1_mask.png") == "TCGA-AC-A23G-01Z-00-DX1"


def test_extract_tcga_slide_id_rejects_unknown_names() -> None:
    with pytest.raises(ValueError):
        extract_tcga_slide_id("not_a_tcga_mask.png")


def test_discover_mask_pairs_strips_mask_suffix(tmp_path: Path) -> None:
    reference_dir = tmp_path / "reference"
    prediction_dir = tmp_path / "prediction"
    reference_dir.mkdir()
    prediction_dir.mkdir()
    ref = reference_dir / "TCGA-AC-A23G-01Z-00-DX1.uuid.svs_mask.png"
    pred = prediction_dir / "TCGA-AC-A23G-01Z-00-DX1_mask.png"
    write_mask(ref, np.array([[1, 7]], dtype=np.uint8))
    write_mask(pred, np.array([[1, 7]], dtype=np.uint8))

    pairs = discover_mask_pairs(reference_dir, prediction_dir)

    assert len(pairs) == 1
    assert pairs[0].slide_id == "TCGA-AC-A23G-01Z-00-DX1"
    assert pairs[0].reference_path == ref
    assert pairs[0].prediction_path == pred


def test_compare_mask_pair_detects_pixel_and_macro_regression(tmp_path: Path) -> None:
    reference = tmp_path / "TCGA-AC-A23G-01Z-00-DX1.ref.png"
    prediction = tmp_path / "TCGA-AC-A23G-01Z-00-DX1.pred.png"
    write_mask(reference, np.array([[1, 1, 2, 7], [1, 3, 7, 7]], dtype=np.uint8))
    write_mask(prediction, np.array([[1, 1, 2, 7], [1, 3, 7, 7]], dtype=np.uint8))

    class_df, summary, confusion = compare_mask_pair(MaskPair("TCGA-AC-A23G-01Z-00-DX1", reference, prediction))

    assert summary["pixel_agreement"] == 1.0
    assert summary["macro_dice"] == 1.0
    assert int(confusion.sum()) == 8
    assert set(class_df["class_name"]) >= {"normal_tissue", "fold", "darkspot_foreign_object", "background"}
