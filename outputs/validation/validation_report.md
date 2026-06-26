# GrandQC-IDC BRCA Reference-Mask Validation

## Scope

This validation compares the GrandQC-IDC direct-DICOM output masks against five GrandQC BRCA DX reference masks. The reference masks are treated as ground truth for this comparison only. This validates the direct-DICOM wrapper on this narrow BRCA DX set; it does not validate frozen sections, other organs, TIFF conversion, or external/manual pathologist truth.

## Headline Results

- Slides validated: 5 BRCA DX slides.
- Macro Dice across all classes: 0.417251 +/- 0.530984.
- Macro Dice excluding background: 0.401734 +/- 0.544912.
- Tissue-class macro Dice: 0.401734.
- Worst slide by macro Dice: TCGA-AC-A62V-01Z-00-DX1 (0.019785).
- Worst class by mean Dice: pen_marking (0.248895).
- Confusion-matrix valid pixels: 117,964,800.

## Per-Slide Summary

| slide_id                |   valid_px |   ignored_px |   pixel_agreement |   macro_dice |   macro_dice_excluding_background |   tissue_weighted_dice |
|:------------------------|-----------:|-------------:|------------------:|-------------:|----------------------------------:|-----------------------:|
| TCGA-A8-A0AB-01Z-00-DX1 |   31457280 |      5085110 |          0.999981 |     0.998431 |                          0.998119 |               0.999953 |
| TCGA-AC-A23C-01Z-00-DX1 |   12582912 |      1539352 |          0.059034 |     0.028647 |                          0.011404 |               0.000439 |
| TCGA-AC-A23G-01Z-00-DX1 |    7864320 |      2045411 |          0.161158 |     0.040100 |                          0.000000 |               0.000000 |
| TCGA-AC-A62V-01Z-00-DX1 |   18874368 |       895102 |          0.071517 |     0.019785 |                          0.000000 |               0.000000 |
| TCGA-MS-A51U-01Z-00-DX1 |   47185920 |      3962344 |          0.999948 |     0.999289 |                          0.999150 |               0.999892 |

## Per-Class Summary

|   class_id | class_name              |   dice_mean |   dice_std |   iou_mean |   reference_px |
|-----------:|:------------------------|------------:|-----------:|-----------:|---------------:|
|          4 | pen_marking             |    0.248895 |   0.497790 |   0.247799 |          15954 |
|          5 | edge_air_bubble         |    0.249960 |   0.499919 |   0.249919 |        3620494 |
|          2 | fold                    |    0.399386 |   0.546883 |   0.398775 |         241438 |
|          6 | out_of_focus            |    0.399704 |   0.547317 |   0.399408 |         408672 |
|          1 | normal_tissue           |    0.399984 |   0.547699 |   0.399967 |       42488979 |
|          3 | darkspot_foreign_object |    0.412796 |   0.534746 |   0.405313 |          45848 |
|          7 | background              |    0.510257 |   0.450993 |   0.461670 |       71143415 |

## Confusion Matrix

The normalized confusion matrix is saved as `confusion_matrix.parquet` and `confusion_matrix.png`. Rows are reference labels; columns are predicted labels.

| reference_class         |   normal_tissue |     fold |   darkspot_foreign_object |   pen_marking |   edge_air_bubble |   out_of_focus |   background |
|:------------------------|----------------:|---------:|--------------------------:|--------------:|------------------:|---------------:|-------------:|
| normal_tissue           |        0.612868 | 0.000009 |                  0.004686 |      0.014964 |          0.050265 |       0.001500 |     0.315708 |
| fold                    |        0.000000 | 0.335378 |                  0.000000 |      0.018158 |          0.075759 |       0.005393 |     0.565313 |
| darkspot_foreign_object |        0.000044 | 0.000000 |                  0.355981 |      0.226051 |          0.030187 |       0.000000 |     0.387738 |
| pen_marking             |        0.000000 | 0.000000 |                  0.003447 |      0.035289 |          0.014040 |       0.000000 |     0.947223 |
| edge_air_bubble         |        0.000054 | 0.000000 |                  0.000000 |      0.000000 |          0.999882 |       0.000040 |     0.000024 |
| out_of_focus            |        0.000078 | 0.000000 |                  0.000000 |      0.000000 |          0.000132 |       0.999743 |     0.000046 |
| background              |        0.000003 | 0.000001 |                  0.001379 |      0.238322 |          0.027769 |       0.003948 |     0.728578 |

## Interpretation

The headline Dice is reported with mean and standard deviation, plus a background-excluded variant, because background and normal tissue can dominate whole-slide masks. Rare artifact classes should be interpreted from the per-class table rather than hidden behind the macro headline.
