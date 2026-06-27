from pathlib import Path

import pandas as pd
import pytest


@pytest.mark.validation
def test_saved_five_slide_validation_outputs_meet_documented_thresholds() -> None:
    path = Path("outputs/validation/validation_per_slide.parquet")
    assert path.exists(), "Run scripts/run_validation.py to regenerate validation outputs."
    df = pd.read_parquet(path)

    assert len(df) == 5
    assert df["pixel_agreement"].min() >= 0.93
    assert df["tissue_weighted_dice"].mean() >= 0.95
    assert df["macro_dice"].mean() >= 0.70
    assert set(df["slide_id"]) == {
        "TCGA-A8-A0AB-01Z-00-DX1",
        "TCGA-AC-A23C-01Z-00-DX1",
        "TCGA-AC-A23G-01Z-00-DX1",
        "TCGA-AC-A62V-01Z-00-DX1",
        "TCGA-MS-A51U-01Z-00-DX1",
    }
