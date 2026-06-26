# Cohort Usability Recheck After Tissue-Detection Fix

This report reruns the stale notebook cohort through the current fixed direct-DICOM path. It is intended to replace the old `cohort_qc_summary.parquet` usability rate, which was generated before the tissue-detection edge-tiling fix.

| Metric | Value |
|:--|--:|
| Stale unusable slides | 6 / 9 (66.7%) |
| Post-fix unusable slides | 6 / 9 (66.7%) |

In this cohort, the unusable rate did not change after the tissue-detection fix; the high unusable count is therefore driven by artifact-model outputs rather than the corrected tissue edge-tiling failure.

## Per-Slide Comparison

| slide_id                | collection_id   | SeriesInstanceUID                                             | stale_usable   | postfix_usable   |   stale_tissue_percentage |   postfix_tissue_percentage |   stale_artifact_percentage_of_tissue |   postfix_artifact_percentage_of_tissue | postfix_tissue_detection_suspect   | postfix_tissue_detection_reason   |
|:------------------------|:----------------|:--------------------------------------------------------------|:---------------|:-----------------|--------------------------:|----------------------------:|--------------------------------------:|----------------------------------------:|:-----------------------------------|:----------------------------------|
| TCGA-B0-4841-01A-01-TS1 | tcga_kirc       | 1.3.6.1.4.1.5962.99.1.1860925888.1488516929.1638243498432.2.0 | False          | False            |                  0.141371 |                    0.144681 |                              1.000000 |                                1.000000 | False                              |                                   |
| TCGA-B0-4845-11A-01-TS1 | tcga_kirc       | 1.3.6.1.4.1.5962.99.1.1843889663.227649428.1638226462207.2.0  | False          | False            |                  0.204539 |                    0.201315 |                              0.756443 |                                0.756725 | False                              |                                   |
| TCGA-AK-3460-01A-02-BS2 | tcga_kirc       | 1.3.6.1.4.1.5962.99.1.1866831471.1959268120.1638249404015.2.0 | True           | True             |                  0.315604 |                    0.321920 |                              0.173037 |                                0.176080 | False                              |                                   |
| TCGA-05-4425-01Z-00-DX1 | tcga_luad       | 1.3.6.1.4.1.5962.99.1.1064031772.132625037.1637446604316.2.0  | False          | False            |                  0.448605 |                    0.018175 |                              0.993016 |                                1.000000 | False                              |                                   |
| TCGA-05-5715-01Z-00-DX1 | tcga_luad       | 1.3.6.1.4.1.5962.99.1.1043788931.804112630.1637426361475.2.0  | False          | False            |                  0.275006 |                    0.279365 |                              0.213790 |                                0.216399 | False                              |                                   |
| TCGA-05-5429-01Z-00-DX1 | tcga_luad       | 1.3.6.1.4.1.5962.99.1.1051000742.1678965474.1637433573286.2.0 | False          | False            |                  0.474882 |                    0.460892 |                              0.926341 |                                0.926899 | False                              |                                   |
| TCGA-CH-5794-01A-01-BS1 | tcga_prad       | 1.3.6.1.4.1.5962.99.1.2107846839.1747214737.1638490419383.2.0 | False          | False            |                  0.344898 |                    0.363654 |                              0.289655 |                                0.295044 | False                              |                                   |
| TCGA-CH-5790-01A-01-BS1 | tcga_prad       | 1.3.6.1.4.1.5962.99.1.2084046226.1414687998.1638466618770.2.0 | True           | True             |                  0.380647 |                    0.382275 |                              0.172686 |                                0.174517 | False                              |                                   |
| TCGA-CH-5744-01A-01-BS1 | tcga_prad       | 1.3.6.1.4.1.5962.99.1.2134428633.68667674.1638517001177.2.0   | True           | True             |                  0.168295 |                    0.168557 |                              0.009313 |                                0.009331 | False                              |                                   |
