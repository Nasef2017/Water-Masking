# 🌊 Water Masking Plugin - Quick Start & User Guide

This guide provides practical step-by-step instructions and troubleshooting tips for operating the **Water Masking** plugin in QGIS.

---

## 🚀 Quick Start in 4 Steps

1. **Open the Tool:**
   In QGIS, go to **Processing Toolbox** $\rightarrow$ **Water Masking** $\rightarrow$ **Water Analysis** $\rightarrow$ **Water Mask (Scientific Extraction & Geometry)**.
2. **Select Satellite Imagery:**
   Choose your multispectral raster layer. Ensure the band assignments correspond to your satellite sensor:
   - **Sentinel-2 L2A (10m/20m):** Blue = 2, Green = 3, Red = 4, NIR = 8 (or 8A), SWIR = 11.
   - **Landsat 8/9 OLI/TIRS (30m):** Coastal = 1, Blue = 2, Green = 3, Red = 4, NIR = 5, SWIR = 6.
   - **PlanetScope (3m):** Blue = 1, Green = 2, Red = 3, NIR = 4.
3. **Choose the Extraction Method:**
   - For most coastal and lake scenes, keep the default: **Smart Hybrid (Dynamic Auto)**.
   - If deep building/cloud shadows or urban features are present, choose **Modified AWEI (Single-SWIR)**.
   - For scenes with tiny water fractions or complex contrast across tiles, choose **Tiled / Local Adaptive Otsu**.
4. **Run the Algorithm:**
   Specify an **Output Folder** and click **Run**.
   The tool outputs:
   - `01_Land_Water_Mask.tif`: Binary raster (1 = Water, 0 = Land, 255 = NoData).
   - `01_Waterbody_Polygon.gpkg`: Vector layer with calculated geodesic area ($km^2$, $ha$), perimeter ($km$), and dominance ratio.

---

## ❓ Frequently Asked Questions (FAQ)

### Q1: Why are my small ponds or canals disappearing?
* **Cause:** The **Minimum Polygon Area Filter (ha)** default is set to `1.0 ha` (10,000 $m^2$) and the **Polygon Selection Mode** defaults to *Adaptive Significance* (which filters out non-dominant water fragments).
* **Fix:**
  1. Change **Polygon Selection & Filtering Mode** to **All Polygons Exceeding Minimum Area**.
  2. Reduce **Minimum Polygon Area Filter (ha)** to `0.05` or `0.0` to preserve small water bodies.
  3. Reduce **Raster Noise Removal (Speckle Filter)** from `10` to `2` or `0`.

### Q2: Why are coastal shadows or dark asphalt detected as water?
* **Cause:** NDWI uses NIR contrast, which is low over dark urban surfaces and asphalt.
* **Fix:** Switch the **Water Masking Method** to **Modified AWEI (Single-SWIR)** or **3 Indices Equation**. These indices leverage SWIR reflectance ($\rho_{\text{SWIR}}$) to strictly suppress dark soil, asphalt, and mountain shadows.

### Q3: How do I smooth jagged pixel edges along the coast?
* **Answer:** Adjust the **Vector Edge Smoothing Iterations** parameter:
  - `0`: Raw raster grid stairs (exact pixel boundaries).
  - `1` – `2`: Mild corner beveling.
  - `3` (Default): Smooth, natural cartographic curves suitable for coastal charting.

### Q4: Does the area calculation work on geographic coordinates (WGS84 / EPSG:4326)?
* **Answer:** **Yes!** Starting from version 2.1, the algorithm uses QGIS's ellipsoidal distance and area engine (`QgsDistanceArea`), accurately computing geodesic area ($m^2$, $ha$, $km^2$) on the WGS-84 ellipsoid regardless of whether your input raster is in UTM meters or EPSG:4326 degrees.

### Q5: Can I supply my own polygon ROI boundary?
* **Answer:** Yes. Under **Input Water Polygon (Optional)**, select any vector polygon layer. The plugin will use this boundary to mask the water area, apply noise removal, smooth the geometry, and generate complete standardized geometric metrics.

---

## 🛠️ Band Assignment Quick Reference

| Sensor | Coastal | Blue | Green | Red | NIR | SWIR |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Sentinel-2 L2A** | Band 1 | Band 2 | Band 3 | Band 4 | Band 8 | Band 11 |
| **Landsat 8 / 9** | Band 1 | Band 2 | Band 3 | Band 4 | Band 5 | Band 6 |
| **PlanetScope (4-Band)** | — | Band 1 | Band 2 | Band 3 | Band 4 | Band 4 (Fallback) |
| **PlanetScope (8-Band)** | Band 1 | Band 2 | Band 4 | Band 6 | Band 8 | Band 8 (Fallback) |

---
*Developed by Mohamed Aly Nasef — [GitHub Repository](https://github.com/Nasef2017/Water-Masking)*
