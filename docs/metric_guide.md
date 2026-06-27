# GrandQC-IDC Metric Guide

The project reports several metrics that answer different questions. They should not be collapsed into a single "Dice" claim.

| Metric | Current value | Scope | What it means |
|:--|:--|:--|:--|
| Pixel agreement | 0.960 to 0.995 per slide after the tissue fix | 5 BRCA DX reference-mask slides | Fraction of valid pixels with identical labels. Dominated by normal/background tissue. |
| Tissue-weighted Dice | Mean 0.958583 | 5 BRCA DX reference-mask slides | Dice averaged over tissue classes with reference-pixel weighting. Best headline for wrapper reproducibility on tissue area. |
| Macro Dice, all classes | 0.712024 +/- 0.141771 | 5 BRCA DX reference-mask slides | Unweighted per-class Dice. Sensitive to rare classes, which is why A62V is low. |
| Background-excluded macro Dice | 0.654914 +/- 0.164388 | 5 BRCA DX reference-mask slides | Same as macro Dice, excluding background. Useful for surfacing rare artifact disagreement. |
| Two-slide fidelity check | >= 99.99% pixel agreement and Dice >= 0.9956 on present classes | A8-A0AB and MS-A51U only | Historical narrow smoke/fidelity subset, not the full validation headline. |

Canonical wording: the direct-DICOM path now reproduces GrandQC reference masks with high pixel and tissue-weighted agreement on the 5-slide BRCA DX validation set, while rare artifact classes remain the main source of macro-Dice disagreement. The darkspot/foreign-object over-call seen in LUAD/COAD dashboard examples is a separate model behavior under audit, not resolved by the tissue-detection fix.
