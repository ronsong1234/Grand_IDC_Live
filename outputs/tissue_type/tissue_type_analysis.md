# DX vs Frozen-Section GrandQC Behavior Analysis

## Scope

This analysis compares GrandQC output distributions for diagnostic DX slides versus frozen-like TS/BS slides. It is exploratory and behavioral; it does not estimate accuracy for frozen sections because no frozen-section ground truth masks are available.

## Cohort Counts

- DX slides: 20
- Frozen-like TS/BS slides: 0

## Summary Statistics

| metric                           | prep_group   |   n |     mean |   median |      std |      min |      max |
|:---------------------------------|:-------------|----:|---------:|---------:|---------:|---------:|---------:|
| fold_fraction                    | DX           |  20 | 0.007420 | 0.005255 | 0.007442 | 0.000000 | 0.021353 |
| darkspot_foreign_object_fraction | DX           |  20 | 0.106943 | 0.004806 | 0.245091 | 0.000000 | 0.902176 |
| pen_marking_fraction             | DX           |  20 | 0.000631 | 0.000008 | 0.001303 | 0.000000 | 0.004466 |
| edge_air_bubble_fraction         | DX           |  20 | 0.022705 | 0.000173 | 0.049779 | 0.000000 | 0.175719 |
| out_of_focus_fraction            | DX           |  20 | 0.038108 | 0.001189 | 0.103596 | 0.000000 | 0.461027 |
| artifact_percentage_of_tissue    | DX           |  20 | 0.175807 | 0.027744 | 0.276181 | 0.000141 | 0.993016 |
| tissue_percentage                | DX           |  20 | 0.399547 | 0.409078 | 0.143784 | 0.044486 | 0.715666 |

## Mann-Whitney U Tests

These tests are exploratory and unadjusted; use them as distribution-screening evidence, not confirmatory inference.

| metric                           |   dx_n |   frozen_n | test           | u_statistic   | p_value   |
|:---------------------------------|-------:|-----------:|:---------------|:--------------|:----------|
| fold_fraction                    |     20 |          0 | mann_whitney_u |               |           |
| darkspot_foreign_object_fraction |     20 |          0 | mann_whitney_u |               |           |
| pen_marking_fraction             |     20 |          0 | mann_whitney_u |               |           |
| edge_air_bubble_fraction         |     20 |          0 | mann_whitney_u |               |           |
| out_of_focus_fraction            |     20 |          0 | mann_whitney_u |               |           |
| artifact_percentage_of_tissue    |     20 |          0 | mann_whitney_u |               |           |
| tissue_percentage                |     20 |          0 | mann_whitney_u |               |           |

## Interpretation

GrandQC's BRCA DX reference-mask validation does not automatically transfer to frozen sections. Elevated artifact classes in TS/BS slides should be treated as behavior requiring manual confirmation in IDC SLIM, not as validated frozen-section accuracy.
