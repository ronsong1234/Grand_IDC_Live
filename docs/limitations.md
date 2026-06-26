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

The LUAD slide `TCGA-05-4425-01Z-00-DX1` has previously shown very high class-3 darkspot/foreign-object burden. The failure-mode notebook tests channel order, MPP scale, and morphology. Until that notebook is run and reviewed, this slide should be treated as a known stress case for the darkspot/foreign-object class.

If the notebook demonstrates a true channel-order or MPP bug, the inference fix should be proposed separately with before/after evidence. The validated inference path should not be silently edited as part of the validation study.

## Manual-Review Flag Rule

The dashboard and validation utilities use this documented rule:

- Flag a slide if any single artifact class exceeds `0.60` of tissue area.
- Flag a slide if total artifact fraction exceeds `0.90` of tissue area.

The flag is a review prompt, not a diagnosis. It is intended to catch possible failure modes such as extreme single-class darkspot/foreign-object calls and very high total artifact burden. A flagged slide should be reviewed in IDC SLIM before being excluded or interpreted.

## Reporting Principle

Headline Dice should always be reported as mean plus standard deviation, with a background-excluded variant. Background and normal tissue can dominate whole-slide masks, so rare artifact classes must be shown in the per-class table instead of hidden behind a high macro score.
