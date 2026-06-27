# GrandQC Direct-DICOM Batch Validation

**Date:** 2026-06-25
**Pipeline:** GrandQC direct-DICOM wrapper (Grand_IDC_Live)
**IDC Version:** v24

---

## Summary

| Metric | Value |
|:-------|------:|
| Slides attempted | 15 |
| Slides succeeded | 15 (100%) |
| Slides failed | 0 |
| TCGA collections | 5 (tcga_brca, tcga_coad, tcga_esca, tcga_kirc, tcga_luad) |
| Usable slides (artifact < 20%) | 9 / 15 |
| Mean tissue coverage | 40.5% Ã‚Â± 15.8% |
| Mean artifact fraction of tissue | 21.8% Ã‚Â± 29.6% |

---

## Per-Slide Results

| collection   | slide_id                | tissue_%   | artifact_%   | usable   | flag   |   runtime_s | fold_%   | darkspot_%   | pen_%   | edge_%   | oof_%   |
|:-------------|:------------------------|:-----------|:-------------|:---------|:-------|------------:|:---------|:-------------|:--------|:---------|:--------|
| tcga_brca    | TCGA-OL-A5RW-01Z-00-DX1 | 51.4%      | 1.1%         | Yes      | No     |      49.941 | 0.06%    | 0.95%        | 0.00%   | 0.05%    | 0.00%   |
| tcga_brca    | TCGA-OL-A5S0-01Z-00-DX1 | 71.6%      | 1.6%         | Yes      | No     |      58.465 | 1.51%    | 0.07%        | 0.00%   | 0.00%    | 0.01%   |
| tcga_coad    | TCGA-A6-3810-01Z-00-DX1 | 41.9%      | 3.2%         | Yes      | No     |     262.115 | 2.14%    | 0.31%        | 0.00%   | 0.00%    | 0.79%   |
| tcga_coad    | TCGA-AA-3489-01Z-00-DX1 | 16.7%      | 3.8%         | Yes      | No     |      21.231 | 0.11%    | 0.74%        | 0.00%   | 0.00%    | 2.94%   |
| tcga_coad    | TCGA-AA-3506-01Z-00-DX1 | 37.4%      | 28.5%        | No       | No     |      92.523 | 0.27%    | 23.80%       | 0.02%   | 0.92%    | 3.53%   |
| tcga_coad    | TCGA-AA-3511-01Z-00-DX1 | 55.4%      | 71.1%        | No       | Yes    |      38.426 | 1.08%    | 65.74%       | 0.33%   | 3.93%    | 0.00%   |
| tcga_coad    | TCGA-AA-3662-01Z-00-DX1 | 37.3%      | 41.4%        | No       | No     |      31.763 | 1.70%    | 25.56%       | 0.45%   | 1.27%    | 12.41%  |
| tcga_coad    | TCGA-AD-6895-01Z-00-DX1 | 58.1%      | 0.5%         | Yes      | No     |      76.706 | 0.14%    | 0.06%        | 0.00%   | 0.17%    | 0.13%   |
| tcga_coad    | TCGA-AD-6899-01Z-00-DX1 | 34.0%      | 0.0%         | Yes      | No     |     224.23  | 0.00%    | 0.00%        | 0.01%   | 0.00%    | 0.00%   |
| tcga_esca    | TCGA-M9-A5M8-01Z-00-DX1 | 41.8%      | 1.2%         | Yes      | No     |      70.04  | 1.04%    | 0.00%        | 0.01%   | 0.00%    | 0.11%   |
| tcga_esca    | TCGA-V5-A7RE-01Z-00-DX1 | 4.4%       | 48.1%        | No       | No     |      43.009 | 1.96%    | 0.03%        | 0.00%   | 0.00%    | 46.10%  |
| tcga_kirc    | TCGA-A3-3365-01Z-00-DX1 | 44.4%      | 5.9%         | Yes      | No     |     144.489 | 1.38%    | 0.69%        | 0.14%   | 0.11%    | 3.56%   |
| tcga_kirc    | TCGA-A3-3385-01Z-00-DX1 | 40.8%      | 0.2%         | Yes      | No     |     126.166 | 0.10%    | 0.09%        | 0.00%   | 0.03%    | 0.00%   |
| tcga_luad    | TCGA-05-4425-01Z-00-DX1 | 44.9%      | 99.3%        | No       | Yes    |      21.453 | 0.00%    | 90.22%       | 0.00%   | 7.59%    | 1.49%   |
| tcga_luad    | TCGA-05-5715-01Z-00-DX1 | 27.5%      | 21.4%        | No       | No     |      21.294 | 0.56%    | 4.06%        | 0.02%   | 13.77%   | 2.97%   |

---

## Interpretation

Each slide was downloaded from IDC as a DICOM series and processed end-to-end through the
GrandQC direct-DICOM pipeline without any intermediate TIFF conversion. The tissue percentage
and per-class artifact fractions reported above are the direct output of the GrandQC model.

The pixel-level fidelity of this pipeline to GrandQC reference masks is documented
separately in `docs/pipeline_fidelity_validation.md`, where the direct-DICOM wrapper
achieved >= 99.99% pixel agreement and Dice >= 0.9956 across all present classes in the historical two-slide fidelity subset
on two TCGA-BRCA DX reference slides.


## Darkspot Audit Note

The high darkspot/foreign-object slides in this batch are successful pipeline runs, but they remain a model-behavior audit target. Review
otebooks/failure_mode_darkspot.ipynb before treating those calls as confirmed artifacts.
