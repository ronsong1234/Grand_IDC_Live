"""Standalone utility to colorize integer GrandQC label masks.

GrandQC QC masks (and the pre-computed TCGA reference masks) are stored as 2D
integer label images with class ids in the range 0-7. Those values are almost
black in ordinary viewers, so this maps each class to a distinct, high-contrast
RGB color.

This file is intentionally dependency-light (numpy + Pillow only) so it can be
dropped into any environment. The same function is also exported from
``modules.grandqc_qc`` for use inside the pipeline.

Usage
-----
    # As a library
    from colorize_mask import colorize_mask
    rgb = colorize_mask("qc_output/mask_qc/SLIDE_mask.png", "SLIDE_rgb.png")

    # As a CLI (one file or a whole directory of *_mask.png)
    python colorize_mask.py qc_output/mask_qc/SLIDE_mask.png SLIDE_rgb.png
    python colorize_mask.py qc_output/mask_qc/ colorized_out/
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Class -> RGB. Index 0 (unlabeled / off-slide padding) is black; classes 1-7
# follow GrandQC's wsi_colors.colors_QC7 palette.
CLASS_COLORS: dict[int, tuple[int, int, int]] = {
    0: (0, 0, 0),          # unlabeled / off-slide padding
    1: (128, 128, 128),    # normal tissue        - gray
    2: (255, 99, 71),      # fold                  - orange-red
    3: (0, 255, 0),        # darkspot / foreign    - bright green
    4: (255, 0, 0),        # pen marking           - pure red
    5: (255, 0, 255),      # edge / air bubble     - magenta
    6: (75, 0, 130),       # out of focus          - indigo
    7: (255, 255, 255),    # background            - white
}


def colorize_mask(
    mask: str | os.PathLike[str] | np.ndarray,
    output_path: str | os.PathLike[str] | None = None,
) -> np.ndarray:
    """Map an integer label mask (classes 0-7) to a visible ``(H, W, 3)`` RGB array.

    Parameters
    ----------
    mask:
        Path to an integer label image (PNG/TIFF) or a 2D array of class ids. A
        3D input (an already-expanded RGB PNG) uses its first channel.
    output_path:
        Optional path to save the RGB result as an image.
    """

    labels = mask if isinstance(mask, np.ndarray) else np.asarray(Image.open(mask))
    labels = np.asarray(labels)
    if labels.ndim == 3:
        labels = labels[..., 0]
    rgb = np.zeros((labels.shape[0], labels.shape[1], 3), dtype=np.uint8)
    for class_id, color in CLASS_COLORS.items():
        rgb[labels == class_id] = color
    if output_path is not None:
        Image.fromarray(rgb).save(output_path)
    return rgb


def _main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    src = Path(argv[1])
    if src.is_dir():
        out_dir = Path(argv[2]) if len(argv) == 3 else src.parent / (src.name + "_rgb")
        out_dir.mkdir(parents=True, exist_ok=True)
        masks = sorted(src.glob("*_mask.png")) or sorted(src.glob("*.png"))
        if not masks:
            print(f"No mask PNGs found under {src}")
            return 1
        for path in masks:
            out = out_dir / (path.stem + "_rgb.png")
            colorize_mask(path, out)
            print(f"  {path.name} -> {out}")
        print(f"Colorized {len(masks)} mask(s) into {out_dir}/")
    else:
        out = Path(argv[2]) if len(argv) == 3 else src.with_name(src.stem + "_rgb.png")
        colorize_mask(src, out)
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
