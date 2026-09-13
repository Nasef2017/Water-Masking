# 🌊 Water Masking Plugin for QGIS

**Water Masking Plugin** is a high-performance, scientific geospatial toolkit designed for QGIS to extract highly accurate water masks and generate clean, smoothed vector waterbody boundaries from multispectral satellite imagery (Sentinel-2, Landsat 8/9, PlanetScope, etc.).

Powered by algorithms developed for high-precision coastal and hydrological modeling, this plugin provides automated sensor radiometry profiling, seven specialized radiometric segmentation methods, speckle noise reduction, and geodesic ellipsoidal polygon filtering.

---

## 📑 Table of Contents
1. [Key Features](#-key-features)
2. [Supported Sensors & Radiometric Profiling](#-supported-sensors--radiometric-profiling)
3. [The 7 Water Masking Methods](#-the-7-water-masking-methods)
4. [Parameters Reference](#-parameters-reference)
5. [Outputs & Data Products](#-outputs--data-products)
6. [Polygon Selection & Dominance Modes](#-polygon-selection--dominance-modes)
7. [Recommended Workflows](#-recommended-workflows)
8. [Changelog](#-changelog)
9. [Author & License](#-author--license)

---

## 🚀 Key Features

* **7 Advanced Masking Algorithms:** Ranging from adaptive local Otsu thresholding to single-SWIR shadow-immune indices and multi-band spectral slope decision trees.
* **Intelligent Sensor Radiometry Profiling:** Automatically detects data bit depth (8-bit DN, 16-bit scaled integers, Landsat C2 SR, Sentinel-2 L2A BOA, 32-bit float reflectance) and scales data to physical surface reflectance $[0.0, 1.0]$.
* **True Geodesic/Ellipsoidal Geometry Engine:** Polygon area and perimeter are computed using `QgsDistanceArea` with WGS-84 ellipsoidal geometry, eliminating projection distortions across both Projected (UTM) and Geographic (`EPSG:4326`) coordinate reference systems.
* **Vector Polygon Override:** Seamlessly accepts custom vector regions of interest (ROI) to override or refine automated spectral extraction.
* **Speckle & Sieve Noise Suppression:** Eliminates salt-and-pepper noise and small isolated false-positive water pixels using spatial connectivity sieve filtering.
* **Sub-Pixel Edge Smoothing:** Applies iterative geometry smoothing (Hermite / Chaikin spline smoothing) to replace jagged raster stair-stepping with clean, natural shoreline contours.

---

## 📡 Supported Sensors & Radiometric Profiling

The algorithm ingests multispectral rasters and dynamically profiles pixel value distributions to compute linear surface reflectance:

| Sensor / Format | Typical Input Range | Auto Scale Factor | Offset |
| :--- | :--- | :--- | :--- |
| **Float Surface Reflectance** | `0.0` – `1.0` | `1.0` | `0.0` |
| **Sentinel-2 L2A (BOA)** | `0` – `10,000` | `0.0001` ($1/10000$) | `0.0` |
| **Landsat 8/9 Collection 2 SR** | `7,273` – `43,636` | `0.0000275` | `-0.20` |
| **16-Bit Scaled Integer** | `0` – `65,535` | Dynamic $1/P_{99}$ | `0.0` |
| **8-Bit Digital Numbers (DN)** | `0` – `255` | $1/255.0$ | `0.0` |

---

## ⚙️ The 7 Water Masking Methods

### 1. Otsu (Automatic NDWI)
* **Principle:** Maximizes between-class variance ($\sigma_B^2$) on the Normalized Difference Water Index (McFeeters, 1996):
  $$\text{NDWI} = \frac{\rho_{\text{Green}} - \rho_{\text{NIR}}}{\rho_{\text{Green}} + \rho_{\text{NIR}}}$$
* **Threshold Selection:**
  $$\tau = \text{clamp}(\tau_{\text{Otsu}} + \text{offset}, -0.05, 0.35)$$
* **Condition:** $(\text{NDWI} > \tau) \land (\rho_{\text{NIR}} < 0.18)$
* **Best Used For:** Standard open-water bodies (lakes, reservoirs, open ocean) with balanced land and water distribution.

### 2. Manual NDWI Threshold
* **Principle:** Allows direct user definition of the threshold value on the McFeeters NDWI raster.
* **Condition:** $(\text{NDWI} > \text{Threshold}_{\text{manual}}) \land (\rho_{\text{NIR}} < 0.18)$
* **Best Used For:** Precise calibration when matching known ground truth, historical gauge lines, or high-turbidity regions.

### 3. 3 Indices Equation (NDWI, MNDWI, NWI)
* **Principle:** Multi-index logical intersection combining green-NIR, green-SWIR, and broad visible-IR contrasts with strict vegetation and reflectance cutoffs:
  $$\text{MNDWI} = \frac{\rho_{\text{Green}} - \rho_{\text{SWIR}}}{\rho_{\text{Green}} + \rho_{\text{SWIR}}}$$
  $$\text{NWI} = \frac{\overline{\rho}_{\text{Visible}} - \overline{\rho}_{\text{IR}}}{\overline{\rho}_{\text{Visible}} + \overline{\rho}_{\text{IR}}}$$
  $$\text{NDVI} = \frac{\rho_{\text{NIR}} - \rho_{\text{Red}}}{\rho_{\text{NIR}} + \rho_{\text{Red}}}$$
* **Condition:** $(\text{MNDWI} > 0.0) \land (\text{NWI} > 0.0) \land (\text{NDVI} < 0.12) \land (\rho_{\text{NIR}} < 0.18)$
* **Best Used For:** Coastal wetlands, estuaries, and inland lakes with heavy riparian or submerged vegetation.

### 4. Smart Hybrid (Dynamic Auto)
* **Principle:** Employs Valley-Emphasis Otsu thresholding coupled with 1D Gaussian histogram smoothing. If scene variance is unimodal or low ($\sigma < 0.05$), it automatically defaults to a conservative multi-index equation to prevent threshold collapse.
* **Condition (Bimodal):** $(\text{NDWI} > \tau_{\text{VE}}) \land (\text{MNDWI} > -0.08) \land (\rho_{\text{NIR}} < 0.18) \land (\text{NDVI} < 0.18)$
* **Best Used For:** Large satellite scenes where water constitutes a small fraction of the image (prevents global Otsu over-segmentation).

### 5. Tiled / Local Adaptive Otsu
* **Principle:** Spatially partitions the scene into $512 \times 512$ pixel blocks. For each tile exhibiting mixed spectral variance ($\sigma > 0.04$), local Otsu thresholding is computed using tile-specific class weights:
  $$\sigma_{B,\text{tile}}^2 = \omega_{b,\text{tile}} \cdot \omega_{f,\text{tile}} \cdot (\mu_{b,\text{tile}} - \mu_{f,\text{tile}})^2$$
  Tiles with pure water or pure land are anchored to extreme values, and the resulting threshold grid is interpolated back to full image resolution via bilinear interpolation.
* **Condition:** $(\text{MNDWI} > \text{Grid}_{\text{bilinear}}) \land (\text{MNDWI} > -0.10) \land (\rho_{\text{NIR}} < 0.18)$
* **Best Used For:** Complex coastal scenes with large expanses of land and varied water depths or atmospheric haze variations across the scene.

### 6. Modified AWEI (Single-SWIR)
* **Principle:** Automated Water Extraction Index optimized for sensors with a single SWIR channel (Feyisa et al., 2014 adaptation):
  $$\text{AWEI} = \rho_{\text{Blue}} + 2.5 \cdot \rho_{\text{Green}} - 1.5 \cdot \rho_{\text{NIR}} - 2.0 \cdot \rho_{\text{SWIR}}$$
* **Condition:** $(\text{AWEI} > 0.0) \land (\text{MNDWI} > -0.08) \land (\rho_{\text{NIR}} < 0.18) \land (\rho_{\text{SWIR}} < 0.12) \land (\text{NDVI} < 0.20)$
* **Best Used For:** Urban coastal zones, ports, and mountainous regions to eliminate terrain shadows, dark roofs, and asphalt roads.

### 7. Spectral Slope & Profile Tree
* **Principle:** 6-band hierarchical spectral decision tree exploiting the rapid attenuation of infrared radiation in water relative to visible wavelengths:
  $$\text{Ratio}_{\text{Vis/IR}} = \frac{\rho_{\text{Coastal}} + \rho_{\text{Blue}} + \rho_{\text{Green}}}{\rho_{\text{NIR}} + \rho_{\text{SWIR}}}$$
* **Condition:** $(\text{Ratio}_{\text{Vis/IR}} > 1.20) \land (\rho_{\text{Green}} > \rho_{\text{SWIR}}) \land (\rho_{\text{NIR}} < 0.18) \land (\rho_{\text{SWIR}} < 0.12) \land (\text{MNDWI} > -0.08) \land (\text{NDVI} < 0.18)$
* **Best Used For:** Turbid shallow waters, intertidal mudflats, and coral reef environments.

---

## 📋 Parameters Reference

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **Input Multispectral Satellite Image** | Raster Layer | *Required* | Input multi-band satellite raster (GeoTIFF, VRT, etc.). |
| **Output Folder** | Folder | *Temp folder* | Target directory where all result files and intermediate indices are saved. |
| **Coastal / Aerosol Band** | Band | `1` (Optional) | Band index for Coastal Blue (~443 nm). Defaults to Band 2 if omitted. |
| **Blue Band** | Band | `2` | Band index for Blue (~490 nm). |
| **Green Band** | Band | `3` | Band index for Green (~560 nm). |
| **Red Band** | Band | `4` | Band index for Red (~665 nm). |
| **NIR Band** | Band | `8` | Band index for Near-Infrared (~842 nm). |
| **SWIR Band** | Band | `11` | Band index for Shortwave Infrared (~1610 nm). Defaults to NIR if unavailable. |
| **Input Water Polygon** | Vector Layer | *None* | Optional polygon layer (ROI) that directly overrides automated spectral extraction. |
| **Water Masking Method** | Enum | `Smart Hybrid` | Selection of one of the 7 masking algorithms described above. |
| **Manual Threshold** | Double | `0.0` | Custom threshold value used only when "Manual NDWI Threshold" is selected. |
| **Otsu Threshold Adjustment Offset** | Double | `0.0` | Additive offset applied to computed Otsu thresholds (+ stricter, - broader). |
| **Raster Noise Removal (Speckle Filter)** | Integer | `10` | Minimum pixel cluster size for sieve filtering. Eliminates isolated noise pixels. |
| **Vector Edge Smoothing Iterations** | Integer | `3` | Geometry smoothing passes (0 = raw stair-step pixels, 3 = natural coastal curves). |
| **Polygon Selection & Filtering Mode** | Enum | `Adaptive` | Strategy for filtering extracted waterbody polygons. |
| **Minimum Polygon Area Filter (ha)** | Double | `1.0` | Minimum physical area (in hectares) required to retain a polygon. |
| **Maximum Major Waterbodies Count** | Integer | `3` | Maximum number of candidate waterbodies to retain in Top N or Adaptive mode. |
| **Dissolve All Valid Water Polygons** | Boolean | `False` | Merges all retained polygons into a single MultiPolygon feature. |
| **Save Intermediate Spectral Indices** | Boolean | `True` | Exports NDVI, MNDWI, NWI, AWEI, and log bands into a `1_Review_Indices/` folder. |
| **Reproject Outputs to WGS84** | Boolean | `False` | Reprojects output raster and GPKG to `EPSG:4326` (Default keeps source CRS). |

---

## 📦 Outputs & Data Products

All outputs are written to the directory specified in `Output Folder`:

```text
📁 Your_Output_Folder/
├── 📄 01_Land_Water_Mask.tif      # Binary Water Mask (1 = Water, 0 = Land, 255 = NoData)
├── 📄 01_Waterbody_Polygon.gpkg   # OGC GeoPackage with smoothed waterbody boundaries
└── 📁 1_Review_Indices/           # (Optional) Spectral diagnostic index rasters
    ├── NDVI.tif
    ├── MNDWI.tif
    ├── NWI.tif
    ├── AWEI.tif
    ├── Log_Blue.tif
    └── Log_Green.tif
```

### Vector Polygon Attribute Table Schema

| Attribute | Data Type | Description |
| :--- | :--- | :--- |
| `ID` | Integer | Unique identifier / rank of the waterbody polygon. |
| `Name` | String | Descriptive designation (e.g. *Primary Coastal Sea / Ocean*, *Major Coastal Lagoon / Bay*). |
| `Area_km2` | Double | True geodesic area in square kilometers ($km^2$). |
| `Area_ha` | Double | True geodesic area in hectares ($ha$). |
| `Perim_km` | Double | True geodesic perimeter in kilometers ($km$). |
| `Dominance_%` | Double | Area relative to the primary dominant waterbody in the scene ($0.0$ – $100.0\%$). |

---

## 🎯 Polygon Selection & Dominance Modes

1. **Adaptive Significance (Auto 1–3 Major Waterbodies) [Recommended]:**
   Calculates dominance ratios relative to the largest detected waterbody. Retains significant features ($> 0.5\%$ of primary or $> 10$ ha) up to $99.5\%$ of cumulative water area.
2. **Primary Waterbody Only (Strict 1 Polygon):**
   Retains only the single largest contiguous waterbody (ideal for offshore bathymetric modeling).
3. **Top N Major Waterbodies:**
   Retains the largest $N$ polygons sorted strictly by physical area.
4. **All Polygons Exceeding Minimum Area:**
   Retains every polygon whose area exceeds `Minimum Polygon Area Filter (ha)`.

---

## 💡 Recommended Workflows

* **Open Coastlines & Clear Marine Waters:**
  Use **Otsu (Automatic NDWI)** or **Smart Hybrid (Dynamic Auto)** with Vector Smoothing $= 3$.
* **Inland Reservoirs & Agricultural Landscapes:**
  Use **3 Indices Equation** to prevent false positives over wet crops or dark soils.
* **Large Satellite Granules with High Land-to-Water Ratio:**
  Use **Tiled / Local Adaptive Otsu** to eliminate class imbalance artifacts.
* **Coastal Cities, Ports, and Steep Topography:**
  Use **Modified AWEI (Single-SWIR)** to suppress building shadows, asphalt, and cloud shadow contamination.
* **Shallow Lagoons, Intertidal Reefs & Turbid Estuaries:**
  Use **Spectral Slope & Profile Tree**.

---

## 🔄 Changelog

### v2.1 (Current)
* **Fixed:** Resolved critical class-weight bug in Tiled Local Adaptive Otsu variance calculation (`t_weight_b * t_weight_f`).
* **Enhanced:** Full geodesic/ellipsoidal area and perimeter measurement via `QgsDistanceArea`, resolving geographic CRS (`EPSG:4326`) distortion.
* **Protected:** Added division-by-zero guards in spectral slope and band ratio calculations.
* **Optimized:** Memory footprint reduction via on-demand computation and explicit garbage collection of large raster buffers.
* **Enriched:** Complete parameter tooltips and documentation inside the QGIS Processing dialog (`shortHelpString`).

### v2.0
* Added Tiled Adaptive Otsu, Modified AWEI Single-SWIR, and Spectral Slope Tree.
* Implemented pure NumPy / Rasterio acceleration engine.

---

## 👨‍💻 Author & License

* **Author:** Mohamed Aly Nasef
* **Email:** [Eng.m.nasef2017@gmail.com](mailto:Eng.m.nasef2017@gmail.com)
* **GitHub:** [https://github.com/Nasef2017/Water-Masking](https://github.com/Nasef2017/Water-Masking)
* **License:** Apache License v2.0
