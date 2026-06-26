# DX vs Frozen-Section GrandQC Behavior Analysis

## Scope

This analysis compares GrandQC output distributions for diagnostic DX slides versus frozen-like TS/BS slides. It is exploratory and behavioral; it does not estimate accuracy for frozen sections because no frozen-section ground truth masks are available.

## Cohort Counts

- DX slides: 7
- Frozen-like TS/BS slides: 0

## Summary Statistics

| metric                           | prep_group   |   n |     mean |   median |      std |      min |      max |
|:---------------------------------|:-------------|----:|---------:|---------:|---------:|---------:|---------:|
| fold_fraction                    | DX           |   7 | 0.007609 | 0.002688 | 0.008807 | 0.000000 | 0.021353 |
| darkspot_foreign_object_fraction | DX           |   7 | 0.293852 | 0.238050 | 0.356757 | 0.000021 | 0.902176 |
| pen_marking_fraction             | DX           |   7 | 0.001166 | 0.000135 | 0.001892 | 0.000000 | 0.004466 |
| edge_air_bubble_fraction         | DX           |   7 | 0.019817 | 0.009177 | 0.028290 | 0.000000 | 0.075902 |
| out_of_focus_fraction            | DX           |   7 | 0.026216 | 0.007909 | 0.044932 | 0.000014 | 0.124065 |
| artifact_percentage_of_tissue    | DX           |   7 | 0.348659 | 0.285442 | 0.386051 | 0.000208 | 0.993016 |
| tissue_percentage                | DX           |   7 | 0.441394 | 0.419197 | 0.093290 | 0.340154 | 0.581289 |

## Mann-Whitney U Tests

These tests are exploratory and unadjusted; use them as distribution-screening evidence, not confirmatory inference.

| metric                           |   dx_n |   frozen_n | test           | u_statistic   | p_value   |
|:---------------------------------|-------:|-----------:|:---------------|:--------------|:----------|
| fold_fraction                    |      7 |          0 | mann_whitney_u |               |           |
| darkspot_foreign_object_fraction |      7 |          0 | mann_whitney_u |               |           |
| pen_marking_fraction             |      7 |          0 | mann_whitney_u |               |           |
| edge_air_bubble_fraction         |      7 |          0 | mann_whitney_u |               |           |
| out_of_focus_fraction            |      7 |          0 | mann_whitney_u |               |           |
| artifact_percentage_of_tissue    |      7 |          0 | mann_whitney_u |               |           |
| tissue_percentage                |      7 |          0 | mann_whitney_u |               |           |

## Interpretation

GrandQC's BRCA DX reference-mask validation does not automatically transfer to frozen sections. Elevated artifact classes in TS/BS slides should be treated as behavior requiring manual confirmation in IDC SLIM, not as validated frozen-section accuracy.
