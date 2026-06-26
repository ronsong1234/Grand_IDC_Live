# GrandQC-IDC BRCA Reference-Mask Validation

## Scope

This validation compares the GrandQC-IDC direct-DICOM output masks against five GrandQC BRCA DX reference masks. The reference masks are treated as ground truth for this comparison only. This validates the direct-DICOM wrapper on this narrow BRCA DX set; it does not validate frozen sections, other organs, TIFF conversion, or external/manual pathologist truth.

## Headline Results

- Slides validated: 5 BRCA DX slides.
- Macro Dice across all classes: 0.712024 +/- 0.141771.
- Macro Dice excluding background: 0.654914 +/- 0.164388.
- Tissue-class macro Dice: 0.654914.
- Worst slide by macro Dice: TCGA-AC-A62V-01Z-00-DX1 (0.471099); this is driven by rare artifact-class disagreement while pixel agreement and tissue-weighted Dice remain high.
- Worst class by mean Dice: out_of_focus (0.224835).
- Confusion-matrix valid pixels: 117,964,800.

## Per-Slide Summary

| slide_id                |   valid_px |   ignored_px |   pixel_agreement |   macro_dice |   macro_dice_excluding_background |   tissue_weighted_dice |
|:------------------------|-----------:|-------------:|------------------:|-------------:|----------------------------------:|-----------------------:|
| TCGA-A8-A0AB-01Z-00-DX1 |   31457280 |      5085110 |          0.995223 |     0.744941 |                          0.694622 |               0.992343 |
| TCGA-AC-A23C-01Z-00-DX1 |   12582912 |      1539352 |          0.962273 |     0.737549 |                          0.692359 |               0.961376 |
| TCGA-AC-A23G-01Z-00-DX1 |    7864320 |      2045411 |          0.930329 |     0.847799 |                          0.801634 |               0.916700 |
| TCGA-AC-A62V-01Z-00-DX1 |   18874368 |       895102 |          0.960222 |     0.471099 |                          0.371911 |               0.953576 |
| TCGA-MS-A51U-01Z-00-DX1 |   47185920 |      3962344 |          0.976861 |     0.758731 |                          0.714046 |               0.968921 |

## Per-Class Summary

|   class_id | class_name              |   dice_mean |   dice_std |   iou_mean |   reference_px |
|-----------:|:------------------------|------------:|-----------:|-----------:|---------------:|
|          6 | out_of_focus            |    0.224835 |   0.449670 |   0.204273 |         408672 |
|          3 | darkspot_foreign_object |    0.416655 |   0.485255 |   0.360935 |          45848 |
|          4 | pen_marking             |    0.552746 |   0.480813 |   0.473770 |          15954 |
|          2 | fold                    |    0.801438 |   0.086832 |   0.675689 |         241438 |
|          5 | edge_air_bubble         |    0.927327 | nan        |   0.864500 |        3620494 |
|          1 | normal_tissue           |    0.961848 |   0.029446 |   0.927723 |       42488979 |
|          7 | background              |    0.969872 |   0.021186 |   0.942162 |       71143415 |

## Confusion Matrix

The normalized confusion matrix is saved as `confusion_matrix.parquet` and `confusion_matrix.png`. Rows are reference labels; columns are predicted labels.

| reference_class         |   normal_tissue |     fold |   darkspot_foreign_object |   pen_marking |   edge_air_bubble |   out_of_focus |   background |
|:------------------------|----------------:|---------:|--------------------------:|--------------:|------------------:|---------------:|-------------:|
| normal_tissue           |        0.980157 | 0.000258 |                  0.000230 |      0.000072 |          0.000731 |       0.000431 |     0.018122 |
| fold                    |        0.058620 | 0.841541 |                  0.000017 |      0.000000 |          0.000000 |       0.000000 |     0.099823 |
| darkspot_foreign_object |        0.051802 | 0.000000 |                  0.863157 |      0.002705 |          0.000000 |       0.000000 |     0.082337 |
| pen_marking             |        0.006393 | 0.000000 |                  0.065501 |      0.922715 |          0.000000 |       0.000000 |     0.005390 |
| edge_air_bubble         |        0.005182 | 0.000000 |                  0.000000 |      0.000000 |          0.886591 |       0.001946 |     0.106281 |
| out_of_focus            |        0.027702 | 0.000002 |                  0.000000 |      0.000000 |          0.012829 |       0.897654 |     0.061812 |
| background              |        0.021450 | 0.000205 |                  0.000872 |      0.000000 |          0.000790 |       0.000215 |     0.976468 |

## Interpretation

The headline Dice is reported with mean and standard deviation, plus a background-excluded variant, because background and normal tissue can dominate whole-slide masks. Rare artifact classes should be interpreted from the per-class table rather than hidden behind the macro headline. A62V is the main outlier: its macro Dice is low because rare artifact classes differ, while pixel agreement is 0.960222 and tissue-weighted Dice is 0.953576.

## Regression Cause And Fix

The validation harness caught a real upstream tissue-detection failure. The previous wrapper padded partial tissue-detection tiles from the top-left, while GrandQC's reference script crops right/bottom edge tiles from `width - 512` and `height - 512`, always feeding a full 512 x 512 tile. On smaller tissue thumbnails this caused tissue detection to return almost no class-1 normal tissue, so downstream artifact scoring saw background instead of tissue.

The fix mirrors GrandQC's reference edge-crop behavior in tissue detection only. Artifact model loading, artifact inference, label mapping, and artifact scoring were not changed.

| slide_id                |   before_agreement |   after_agreement |   ref_normal_tissue_px |   before_normal_tissue_px |   after_normal_tissue_px |   before_background_px |   after_background_px |
|:------------------------|-------------------:|------------------:|-----------------------:|--------------------------:|-------------------------:|-----------------------:|----------------------:|
| TCGA-A8-A0AB-01Z-00-DX1 |           0.999981 |          0.995223 |               10482410 |                  10481961 |                 10371697 |               20893527 |              26115540 |
| TCGA-AC-A23C-01Z-00-DX1 |           0.059034 |          0.962273 |                6118045 |                        13 |                  6294950 |                4689165 |               7712802 |
| TCGA-AC-A23G-01Z-00-DX1 |           0.161158 |          0.930329 |                3030150 |                         0 |                  3937143 |                4196150 |               5972033 |
| TCGA-AC-A62V-01Z-00-DX1 |           0.071517 |          0.960222 |                7298700 |                         0 |                  7926342 |                8046071 |              11655608 |
| TCGA-MS-A51U-01Z-00-DX1 |           0.999948 |          0.976861 |               15559674 |                  15558591 |                 15078113 |               27592219 |              32357902 |
