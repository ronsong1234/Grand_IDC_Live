import os
import subprocess
import sys

import pytest


@pytest.mark.gpu
def test_gpu_regression_recomputes_reference_masks_when_enabled() -> None:
    if os.environ.get("GRANDQC_RUN_GPU_REGRESSION") != "1":
        pytest.skip("Set GRANDQC_RUN_GPU_REGRESSION=1 to rerun GrandQC validation inference.")

    completed = subprocess.run(
        [sys.executable, "scripts/run_validation.py"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert completed.returncode == 0, completed.stdout
