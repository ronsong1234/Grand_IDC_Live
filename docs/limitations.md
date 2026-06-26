# GrandQC-IDC Validation Scope and Limitations

## Validated Scope

The quantitative validation in this repository is limited to five TCGA-BRCA diagnostic DX slide microscopy series with GrandQC reference masks. Those reference masks are treated as ground truth for this wrapper-level comparison. The purpose is to verify that the GrandQC-IDC direct-DICOM path reproduces the validated GrandQC reference outputs on the same narrow reference set.

This is not external pathologist validation. It is a reproducibility validation against GrandQC reference outputs.

## Not Validated

The current reference-mask validation does not establish accuracy for:

- Frozen sections or other non-DX tissue preparations.
- Non-BRCA organs or cancer types.
- TIFF conversion paths.
- Manual human artifact annotations.
- Clinical usability beyond the GrandQC model's intended QC categories.

Frozen-section outputs should be interpreted as model behavior requiring manual confirmation, not validated accuracy.

## MPP Sensitivity

GrandQC inference is sensitive to microns-per-pixel handling. Prior local validation showed direct-DICOM tile streaming matched reference masks substantially better than a 1.0-MPP TIFF workflow. For that reason, this project treats direct DICOM via `wsidicom` as the preferred validation path and avoids hardcoded MPP assumptions.

Any new conversion or reader path must prove that source MPP is extracted from DICOM metadata and that the downstream tile MPP matches the intended GrandQC artifact model scale.

## Frozen-Section Non-Transfer

DX performance should not be assumed to transfer to frozen-like `TS` or `BS` slide IDs. The tissue-type analysis script compares artifact fraction distributions between DX and frozen-like slides, but this is behavioral and exploratory. It can show that a class is systematically elevated, but it cannot say which group is more accurate without ground truth.

A conservative conclusion is appropriate: GrandQC outputs on frozen sections require manual review in IDC SLIM.

## Darkspot / Foreign-Object Failure Mode

The LUAD slide `TCGA-05-4425-01Z-00-DX1` and the COAD dashboard example `TCGA-AA-3506-01Z-00-DX1` have shown high class-3 darkspot/foreign-object burden on visually clean tissue. The failure-mode notebook tests channel order, MPP scale, and morphology. Until that notebook is run and reviewed, these slides should be treated as known stress cases for the darkspot/foreign-object class.

If the notebook demonstrates a true channel-order or MPP bug, the inference fix should be proposed separately with before/after evidence. The validated inference path should not be silently edited as part of the validation study.


## Validation Outlier

`TCGA-AC-A62V-01Z-00-DX1` remains the lowest macro-Dice validation slide after the tissue fix because rare artifact classes disagree, even though pixel agreement and tissue-weighted Dice are high; this per-class discrepancy is under review rather than treated as a tissue-detection failure.

## Cohort Recheck

The stale 9-slide notebook cohort was rerun after the tissue-detection fix. Its unusable rate stayed at 6 / 9 (66.7%), so the high unusable rate in that cohort is driven by artifact-model outputs, not by the corrected tissue edge-tiling bug. The recheck lives in `outputs/cohort_recheck/` and should supersede the old notebook `cohort_qc_summary.parquet` for this cohort.

## Manual-Review Flag Rule

The dashboard and validation utilities use this documented rule:

- Flag a slide if any single artifact class exceeds `0.60` of tissue area.
- Flag a slide if total artifact fraction exceeds `0.90` of tissue area.

The flag is a review prompt, not a diagnosis. It is intended to catch possible failure modes such as extreme single-class darkspot/foreign-object calls and very high total artifact burden. A flagged slide should be reviewed in IDC SLIM before being excluded or interpreted.

## Reporting Principle

Headline Dice should always be reported as mean plus standard deviation, with a background-excluded variant. Background and normal tissue can dominate whole-slide masks, so rare artifact classes must be shown in the per-class table instead of hidden behind a high macro score.

## Regression Cause And Fix: Tissue Detection On Small Thumbnails

The validation harness caught an upstream tissue-detection regression. Three of the five BRCA reference slides initially collapsed because the wrapper padded partial tissue-detection tiles from the top-left, while the GrandQC reference script crops right/bottom edge tiles from `width - 512` and `height - 512`. On smaller tissue thumbnails this changed the model input enough that tissue detection returned almost no class-1 normal tissue. The artifact model then saw background instead of tissue.

The surgical fix mirrors GrandQC's reference edge-crop behavior for tissue detection only. Artifact model loading, artifact inference, label mapping, and artifact scoring were not changed.

Before/after evidence:

| slide_id | before_agreement | after_agreement | ref_normal_tissue_px | before_normal_tissue_px | after_normal_tissue_px |
|:---|---:|---:|---:|---:|---:|
| TCGA-A8-A0AB-01Z-00-DX1 | 0.999981 | 0.995223 | 10482410 | 10481961 | 10371697 |
| TCGA-AC-A23C-01Z-00-DX1 | 0.059034 | 0.962273 | 6118045 | 13 | 6294950 |
| TCGA-AC-A23G-01Z-00-DX1 | 0.161158 | 0.930329 | 3030150 | 0 | 3937143 |
| TCGA-AC-A62V-01Z-00-DX1 | 0.071517 | 0.960222 | 7298700 | 0 | 7926342 |
| TCGA-MS-A51U-01Z-00-DX1 | 0.999948 | 0.976861 | 15559674 | 15558591 | 15078113 |

After the fix, the corrected validation headline is macro Dice `0.712024 +/- 0.141771`, background-excluded macro Dice `0.654914 +/- 0.164388`, and tissue-weighted Dice `0.958583` across the five BRCA DX reference slides. This is intentionally reported honestly rather than rounded to the earlier informal 0.999 claim.
