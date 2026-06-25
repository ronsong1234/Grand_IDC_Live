#!/bin/bash
# setting
SLIDE_FOLDER="/path/to/the/slides/"
OUTPUT_DIR="/path/to/the/output/"
QC_MPP_MODEL=1.5
CREATE_GEOJSON="Y"

python wsi_tis_detect.py --slide_folder "$SLIDE_FOLDER" --output_dir "$OUTPUT_DIR"

python main.py --slide_folder "$SLIDE_FOLDER" --output_dir "$OUTPUT_DIR" --create_geojson "$CREATE_GEOJSON" --mpp_model "$QC_MPP_MODEL"

echo "All processes completed!"
