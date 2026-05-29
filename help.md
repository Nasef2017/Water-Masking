# Water Masking Algorithm Help Guide

Welcome to the **Water Masking** algorithm documentation. This tool is designed to provide hydrologists, GIS analysts, and remote sensing experts with a one-click solution to extract waterbodies from multispectral satellite imagery.

## Overview
The algorithm takes a raw multispectral image (e.g., Landsat 8/9, Sentinel-2) and applies advanced remote sensing indices to separate water from land, vegetation, and built-up areas.

### The Algorithm Logic
The final water mask is generated using the following combined criteria:
1. **MNDWI > 0**: Enhances open water features while suppressing noise from built-up land, vegetation, and soil.
2. **NWI > 0**: Further isolates water features using a combination of visible and infrared means.
3. **NDVI < 0.1**: Ensures that dense vegetation or floating flora is not falsely classified as open water.

## Parameters Explained

### Inputs
*   **Input Multi-Band Image (UTM)**: The source raster containing the required spectral bands. For accurate geometry processing and area calculations, it is highly recommended that this image is projected in a UTM Coordinate Reference System.
*   **Band Assignments**: You must manually identify which band numbers correspond to Blue, Green, Red, Near-Infrared (NIR), and Short-Wave Infrared (SWIR). 

### Processing Options
*   **Raster Noise Removal (Pixels)**: This applies a "Sieve Filter" to the generated mask. It groups neighboring pixels and removes isolated clusters that are smaller than the specified pixel count. This is extremely useful for removing "salt and pepper" noise from the classification. (Default: 10 pixels).
*   **Vector Edge Smoothing Iterations**: When rasters are converted to vector polygons, they have jagged, stair-stepped boundaries. This option applies a smoothing algorithm to the vector geometry to produce natural-looking shorelines. A value of `3` is recommended. Set to `0` to disable smoothing.

### Outputs
All outputs are automatically reprojected from the input UTM projection to **EPSG:4326 (WGS 84 Lat/Lon)**.
1.  **Output NDVI**: The Normalized Difference Vegetation Index raster.
2.  **Output MNDWI**: The Modified Normalized Difference Water Index raster.
3.  **Output NWI**: The New Water Index raster.
4.  **Final Water Mask Raster**: A binary raster where `1` represents water and `0` (or NoData) represents non-water.
5.  **Final Waterbody Polygon**: A clean, smoothed vector shapefile containing polygons for all detected water bodies.

---
*Developed as a robust Processing tool for QGIS 3 & 4.*
