# -*- coding: utf-8 -*-
"""
Water Masking Algorithm (Standalone Plugin)
Advanced Scientific Waterbody Extraction & Shoreline Segmentation
Zero External Dependencies (Pure QGIS + NumPy Native Engine)
Global Log-Transformation Pipeline
Author: Mohamed Aly Nasef
"""

import json
import math
import os
import numpy as np
import rasterio
from rasterio.features import geometry_mask, sieve

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingUtils,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterBand,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFolderDestination,
    QgsProcessingOutputRasterLayer,
    QgsProcessingOutputVectorLayer,
    QgsProcessingException,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsVectorFileWriter,
    QgsDistanceArea,
)
import processing


def detect_and_scale_radiometry(bands_dict, valid_mask=None, feedback=None):
    """
    Scientifically analyzes data type, bit depth, and pixel value distribution
    to profile sensor format and scale to physical surface reflectance [0.0, 1.0].
    """
    sample = bands_dict.get('nir', list(bands_dict.values())[0])
    dtype = sample.dtype
    
    if valid_mask is not None and np.any(valid_mask):
        valid_vals = sample[valid_mask]
        p99 = float(np.percentile(valid_vals, 99))
        p_max = float(np.max(valid_vals))
        p_min = float(np.min(valid_vals))
    else:
        p99 = float(np.nanpercentile(sample, 99))
        p_max = float(np.nanmax(sample))
        p_min = float(np.nanmin(sample))
        
    sensor_info = ""
    scale_factor = 1.0
    offset = 0.0
    
    if np.issubdtype(dtype, np.floating):
        if p99 <= 1.5 and p_max <= 2.5:
            sensor_info = "Float Physical Surface Reflectance (0.0 - 1.0)"
            scale_factor = 1.0
            offset = 0.0
        else:
            sensor_info = f"Float Scaled Raster (Max={p_max:.1f})"
            scale_factor = 1.0 / p99 if p99 > 0 else 1.0
            offset = 0.0
    elif dtype == np.uint8:
        sensor_info = "8-Bit Standard Digital Numbers (Range 0 - 255)"
        scale_factor = 1.0 / 255.0
        offset = 0.0
    elif dtype in (np.uint16, np.int16, np.int32, np.uint32):
        if p_min >= 6000 and p_max > 25000 and p99 > 15000:
            sensor_info = "Landsat 8/9 Collection 2 Surface Reflectance (Scale=0.0000275, Offset=-0.2)"
            scale_factor = 0.0000275
            offset = -0.2
        elif p99 > 1000 or p_max > 1500:
            sensor_info = "Sentinel-2 / Landsat Scaled Integer Reflectance (Range 0 - 10000)"
            scale_factor = 1.0 / 10000.0
            offset = 0.0
        elif p99 > 255:
            sensor_info = f"16-Bit Scaled Integer Raster (Dynamic P99={p99:.0f})"
            scale_factor = 1.0 / p99 if p99 > 0 else 1.0 / 65535.0
            offset = 0.0
        else:
            sensor_info = "Integer 8-bit equivalent"
            scale_factor = 1.0 / 255.0
            offset = 0.0
            
    if feedback:
        feedback.pushInfo(f"📡 [Sensor & Radiometry Auto-Profiling]: {sensor_info}")
        feedback.pushInfo(f"   Applied Reflectance Scale Factor: {scale_factor:.7f} | Additive Offset: {offset:.2f}")

    scaled_bands = {}
    for k, v in bands_dict.items():
        scaled = v.astype(np.float32) * scale_factor + offset
        scaled_bands[k] = np.clip(scaled, 0.0, 1.5)
        
    return scaled_bands


def pure_numpy_smooth_histogram(hist, radius=2):
    """
    Pure NumPy 1D Gaussian-weighted moving average filter for histogram smoothing.
    """
    if radius <= 0 or len(hist) < 5:
        return hist.astype(np.float32)
    
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / (radius / 2.0)) ** 2)
    kernel /= np.sum(kernel)
    
    padded = np.pad(hist.astype(np.float32), radius, mode='edge')
    smoothed = np.convolve(padded, kernel, mode='valid')
    return smoothed


def pure_numpy_bilinear_grid(grid, target_h, target_w):
    """
    Pure NumPy bilinear spatial interpolation for local threshold grids.
    """
    ny, nx = grid.shape
    if ny == 1 and nx == 1:
        return np.full((target_h, target_w), grid[0, 0], dtype=np.float32)
    
    y_coords = np.linspace(0, ny - 1, target_h, dtype=np.float32)
    x_coords = np.linspace(0, nx - 1, target_w, dtype=np.float32)
    
    y0 = np.floor(y_coords).astype(int)
    y1 = np.clip(y0 + 1, 0, ny - 1)
    wy = (y_coords - y0)[:, np.newaxis]
    
    x0 = np.floor(x_coords).astype(int)
    x1 = np.clip(x0 + 1, 0, nx - 1)
    wx = (x_coords - x0)[np.newaxis, :]
    
    ia = grid[y0[:, np.newaxis], x0[np.newaxis, :]]
    ib = grid[y0[:, np.newaxis], x1[np.newaxis, :]]
    ic = grid[y1[:, np.newaxis], x0[np.newaxis, :]]
    id_ = grid[y1[:, np.newaxis], x1[np.newaxis, :]]
    
    top = ia * (1.0 - wx) + ib * wx
    bottom = ic * (1.0 - wx) + id_ * wx
    result = top * (1.0 - wy) + bottom * wy
    return result.astype(np.float32)


def filter_polygons_scientifically(features_list, mode_choice=0, min_area_ha=1.0, max_count=3, significance_ratio=0.005):
    """
    Scientifically filters waterbody polygons based on physical area, dominance ratio, and Pareto coverage.
    """
    if not features_list:
        return []
    
    sorted_feats = sorted(features_list, key=lambda x: x[0], reverse=True)
    a1 = sorted_feats[0][0]
    total_area = sum(x[0] for x in sorted_feats)
    
    if mode_choice == 1:
        return [sorted_feats[0]]
    elif mode_choice == 2:
        return sorted_feats[:max_count]
    elif mode_choice == 3:
        return [x for x in sorted_feats if x[0] >= min_area_ha]
    else:
        selected = []
        cum_area = 0.0
        for i, item in enumerate(sorted_feats):
            a_ha = item[0]
            if i == 0:
                selected.append(item)
                cum_area += a_ha
                continue
            
            is_significant = (a_ha >= min_area_ha) and ((a_ha >= a1 * significance_ratio) or (a_ha >= 10.0))
            
            if is_significant and len(selected) < max_count:
                selected.append(item)
                cum_area += a_ha
                if total_area > 0 and (cum_area / total_area) >= 0.995:
                    break
            else:
                break
                
        return selected


class WaterMaskingAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    BAND_COASTAL = "BAND_COASTAL"
    BAND_BLUE = "BAND_BLUE"
    BAND_GREEN = "BAND_GREEN"
    BAND_RED = "BAND_RED"
    BAND_NIR = "BAND_NIR"
    BAND_SWIR = "BAND_SWIR"

    INPUT_WATER_POLY = "INPUT_WATER_POLY"
    MASKING_METHOD = "MASKING_METHOD"
    MANUAL_THRESHOLD = "MANUAL_THRESHOLD"
    OTSU_ADJUSTMENT = "OTSU_ADJUSTMENT"
    SMOOTH_PIXELS = "SMOOTH_PIXELS"
    VECTOR_SMOOTHING = "VECTOR_SMOOTHING"

    POLY_SELECTION_MODE = "POLY_SELECTION_MODE"
    MIN_POLY_AREA = "MIN_POLY_AREA"
    MAX_POLY_COUNT = "MAX_POLY_COUNT"
    DISSOLVE_POLYGONS = "DISSOLVE_POLYGONS"
    SAVE_INDICES = "SAVE_INDICES"
    REPROJECT_WGS84 = "REPROJECT_WGS84"

    OUTPUT_MASK = "OUTPUT_MASK"
    OUTPUT_POLYGON = "OUTPUT_POLYGON"

    MASK_METHODS = [
        "Otsu (Automatic NDWI)",
        "Manual NDWI Threshold",
        "3 Indices Equation (NDWI, MNDWI, NWI)",
        "Smart Hybrid (Dynamic Auto)",
        "Tiled / Local Adaptive Otsu",
        "Modified AWEI (Single-SWIR)",
        "Spectral Slope & Profile Tree",
    ]

    POLY_MODES = [
        "Adaptive Significance (Auto 1-3 Major Waterbodies) [Recommended]",
        "Primary Waterbody Only (Strict 1 Polygon)",
        "Top N Major Waterbodies (Select Count)",
        "All Polygons Exceeding Minimum Area",
    ]

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return WaterMaskingAlgorithm()

    def name(self):
        return "watermask_v5"

    def displayName(self):
        return self.tr("Water Mask (Scientific Extraction & Geometry)")

    def group(self):
        return self.tr("Water Analysis")

    def groupId(self):
        return "wateranalysis"

    def shortHelpString(self):
        return """
        <div style="font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.5; color: #2C3E50;">
            <h2 style="margin-bottom: 5px; color: #2E86C1;">🌊 Water Masking: Scientific Waterbody Extraction & Boundary Polygons</h2>
            <p style="margin-top: 0; margin-bottom: 12px; font-size: 13px;">
                Extracts accurate water masks and generates scientifically filtered, smooth waterbody polygons from multispectral satellite imagery (Sentinel-2, Landsat 8/9, PlanetScope, etc.).
            </p>

            <h3 style="color: #117A65; margin-bottom: 4px; border-bottom: 2px solid #117A65; padding-bottom: 2px;">⚙️ Available Masking Methods</h3>
            <ul style="font-size: 12px; margin-top: 4px; padding-left: 18px;">
                <li><b>Otsu (Automatic NDWI):</b> Global Otsu threshold on McFeeters NDWI with manual adjustment offset.</li>
                <li><b>Manual NDWI Threshold:</b> User-defined fixed threshold on NDWI (e.g. 0.0).</li>
                <li><b>3 Indices Equation:</b> Physics-based combination of <code>(MNDWI > 0) & (NWI > 0) & (NDVI < 0.12) & (NIR < 0.18)</code>.</li>
                <li><b>Smart Hybrid (Dynamic Auto):</b> Valley-Emphasis smoothed Otsu with unimodal/bimodal scene variance detection.</li>
                <li><b>Tiled / Local Adaptive Otsu:</b> Divides scene into 512x512 spatial tiles, calculating local Otsu thresholds with bilinear interpolation to resolve severe class imbalance across large scenes.</li>
                <li><b>Modified AWEI (Single-SWIR):</b> Optimized Automated Water Extraction Index (<code>Blue + 2.5*Green - 1.5*NIR - 2.0*SWIR</code>), eliminating shadows, dark roofs, and asphalt.</li>
                <li><b>Spectral Slope & Profile Tree:</b> Full spectral decision tree tailored for turbid shallow waters, intertidal flats, and coastal reefs.</li>
            </ul>

            <h3 style="color: #117A65; margin-bottom: 4px; border-bottom: 2px solid #117A65; padding-bottom: 2px;">📋 Parameter Descriptions</h3>
            <ul style="font-size: 12px; margin-top: 4px; padding-left: 18px;">
                <li><b>Input Multispectral Satellite Image:</b> Source raster containing at least Blue, Green, Red, and NIR bands (plus Coastal and SWIR if available).</li>
                <li><b>Output Folder:</b> Destination folder for outputs (Mask raster, Vector GPKG, and optional spectral indices).</li>
                <li><b>Band Assignments:</b> Select band numbers matching your satellite sensor (Sentinel-2 L2A defaults: Coastal=1, Blue=2, Green=3, Red=4, NIR=8, SWIR=11).</li>
                <li><b>Input Water Polygon (Optional):</b> Vector polygon layer to directly override automated masking with a custom Region of Interest.</li>
                <li><b>Water Masking Method:</b> The radiometric algorithm used for land-water segmentation.</li>
                <li><b>Manual Threshold:</b> Threshold value applied when "Manual NDWI Threshold" is selected.</li>
                <li><b>Otsu Threshold Adjustment Offset:</b> Additive offset applied to the computed Otsu threshold (+ for stricter water, - for broader water).</li>
                <li><b>Raster Noise Removal (Speckle Filter):</b> Sieve pixel size to eliminate isolated noisy pixels (0 = no filtering).</li>
                <li><b>Vector Edge Smoothing Iterations:</b> Sub-pixel geometry smoothing iterations (0 = raw pixels, 3 = smooth natural coastlines).</li>
                <li><b>Polygon Selection & Filtering Mode:</b> Filter polygons by scientific significance (Adaptive Dominance, Primary Only, Top N, or Min Area).</li>
                <li><b>Minimum Polygon Area Filter (ha):</b> Smallest polygon area to retain in hectares.</li>
                <li><b>Dissolve Polygons:</b> Merge all valid water polygons into a single MultiPolygon feature.</li>
                <li><b>Save Intermediate Spectral Indices:</b> Exports NDVI, MNDWI, NWI, AWEI, and log bands to a subfolder for quality review.</li>
                <li><b>Reproject to WGS84:</b> Reprojects output raster and polygon to EPSG:4326 (Default keeps source projected CRS).</li>
            </ul>
            <br><b>Developer:</b> Mohamed Aly Nasef
        </div>
        """

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT, self.tr("Input Multispectral Satellite Image")
            )
        )

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER, self.tr("Output Folder (For All Results)")
            )
        )

        self.addParameter(
            QgsProcessingParameterBand(
                self.BAND_COASTAL,
                self.tr("Coastal / Aerosol Band (Optional)"),
                parentLayerParameterName=self.INPUT,
                defaultValue=1,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBand(
                self.BAND_BLUE,
                self.tr("Blue Band"),
                parentLayerParameterName=self.INPUT,
                defaultValue=2,
            )
        )
        self.addParameter(
            QgsProcessingParameterBand(
                self.BAND_GREEN,
                self.tr("Green Band"),
                parentLayerParameterName=self.INPUT,
                defaultValue=3,
            )
        )
        self.addParameter(
            QgsProcessingParameterBand(
                self.BAND_RED,
                self.tr("Red Band"),
                parentLayerParameterName=self.INPUT,
                defaultValue=4,
            )
        )
        self.addParameter(
            QgsProcessingParameterBand(
                self.BAND_NIR,
                self.tr("NIR Band"),
                parentLayerParameterName=self.INPUT,
                defaultValue=8,
            )
        )
        self.addParameter(
            QgsProcessingParameterBand(
                self.BAND_SWIR,
                self.tr("SWIR Band"),
                parentLayerParameterName=self.INPUT,
                defaultValue=11,
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_WATER_POLY,
                self.tr("Input Water Polygon (Optional - Overrides Auto Mask)"),
                types=[QgsProcessing.TypeVectorPolygon],
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.MASKING_METHOD,
                self.tr("Water Masking Method"),
                options=self.MASK_METHODS,
                defaultValue=3,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MANUAL_THRESHOLD,
                self.tr("Manual Threshold (If Manual Method Selected)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OTSU_ADJUSTMENT,
                self.tr("Otsu Threshold Adjustment Offset"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SMOOTH_PIXELS,
                self.tr("Raster Noise Removal (Speckle Filter Size in Pixels)"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=10,
                minValue=0,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.VECTOR_SMOOTHING,
                self.tr("Vector Edge Smoothing Iterations (0 = None, 3 = Smooth)"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=3,
                minValue=0,
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.POLY_SELECTION_MODE,
                self.tr("Polygon Selection & Filtering Mode"),
                options=self.POLY_MODES,
                defaultValue=0,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_POLY_AREA,
                self.tr("Minimum Polygon Area Filter (Hectares)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.0,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_POLY_COUNT,
                self.tr("Maximum Major Waterbodies Count (If Top N / Adaptive selected)"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=3,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.DISSOLVE_POLYGONS,
                self.tr("Dissolve All Valid Water Polygons into a Single Feature"),
                defaultValue=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SAVE_INDICES,
                self.tr("Save Intermediate Spectral Indices (NDVI, MNDWI, NWI, AWEI)"),
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.REPROJECT_WGS84,
                self.tr("Reproject Outputs to WGS84 (EPSG:4326) [False keeps Source CRS]"),
                defaultValue=False,
            )
        )

        self.addOutput(
            QgsProcessingOutputRasterLayer(
                self.OUTPUT_MASK, self.tr("Output Water Mask")
            )
        )
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.OUTPUT_POLYGON, self.tr("Output Waterbody Polygon")
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        if not input_layer:
            raise QgsProcessingException("Input Multispectral Image is missing!")

        in_f = input_layer.source()

        out_dir = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        if not out_dir:
            out_dir = QgsProcessingAlgorithm.tempFolder()
        os.makedirs(out_dir, exist_ok=True)

        out_mask_path = os.path.join(out_dir, "01_Land_Water_Mask.tif")
        out_poly_path = os.path.join(out_dir, "01_Waterbody_Polygon.gpkg")

        c_idx = self.parameterAsInt(parameters, self.BAND_COASTAL, context)
        b_idx = self.parameterAsInt(parameters, self.BAND_BLUE, context)
        g_idx = self.parameterAsInt(parameters, self.BAND_GREEN, context)
        r_idx = self.parameterAsInt(parameters, self.BAND_RED, context)
        n_idx = self.parameterAsInt(parameters, self.BAND_NIR, context)
        s_idx = self.parameterAsInt(parameters, self.BAND_SWIR, context)

        water_poly_layer = self.parameterAsVectorLayer(parameters, self.INPUT_WATER_POLY, context)
        mask_choice = self.parameterAsInt(parameters, self.MASKING_METHOD, context)
        manual_val = self.parameterAsDouble(parameters, self.MANUAL_THRESHOLD, context)
        otsu_adj = self.parameterAsDouble(parameters, self.OTSU_ADJUSTMENT, context)
        k_size = self.parameterAsInt(parameters, self.SMOOTH_PIXELS, context)
        vector_smooth_iters = self.parameterAsInt(parameters, self.VECTOR_SMOOTHING, context)

        poly_mode_choice = self.parameterAsInt(parameters, self.POLY_SELECTION_MODE, context)
        min_poly_area_ha = self.parameterAsDouble(parameters, self.MIN_POLY_AREA, context)
        max_poly_count = self.parameterAsInt(parameters, self.MAX_POLY_COUNT, context)
        dissolve_polygons = self.parameterAsBool(parameters, self.DISSOLVE_POLYGONS, context)
        save_indices = self.parameterAsBool(parameters, self.SAVE_INDICES, context)
        reproject_wgs84 = self.parameterAsBool(parameters, self.REPROJECT_WGS84, context)

        if feedback.isCanceled():
            return {}

        feedback.pushInfo("🚀 Step 1/4: Analyzing Image Radiometry & Computing Reflectance Indices...")

        with rasterio.open(in_f) as src:
            nbands = src.count
            prof = src.profile.copy()
            h, w = src.height, src.width

            b_safe = min(max(1, b_idx), nbands)
            g_safe = min(max(1, g_idx), nbands)
            r_safe = min(max(1, r_idx), nbands)
            n_safe = min(max(1, n_idx), nbands)
            s_safe = min(max(1, s_idx), nbands) if (s_idx and s_idx <= nbands) else n_safe
            c_safe = min(max(1, c_idx), nbands) if (c_idx and 1 <= c_idx <= nbands) else b_safe

            raw_b = src.read(b_safe)
            raw_g = src.read(g_safe)
            raw_r = src.read(r_safe)
            raw_n = src.read(n_safe)
            raw_s = src.read(s_safe)
            raw_c = src.read(c_safe)

            nodata = src.nodata if src.nodata is not None else -9999.0
            invalid_mask = (raw_b == nodata) & (raw_g == nodata) & (raw_r == nodata)
            if nodata == 0:
                invalid_mask = (raw_b == 0) & (raw_g == 0) & (raw_r == 0)
            invalid_mask |= (
                np.isnan(raw_b)
                | np.isnan(raw_g)
                | np.isnan(raw_r)
                | np.isnan(raw_n)
                | np.isnan(raw_s)
                | (raw_b <= -9999)
                | (raw_g <= -9999)
            )
            valid_mask = ~invalid_mask

            # Scientific Radiometric Profiling and Reflectance Scaling
            raw_bands = {
                'coastal': raw_c,
                'blue': raw_b,
                'green': raw_g,
                'red': raw_r,
                'nir': raw_n,
                'swir': raw_s
            }
            scaled_bands = detect_and_scale_radiometry(raw_bands, valid_mask=valid_mask, feedback=feedback)

            c = scaled_bands['coastal']
            b = scaled_bands['blue']
            g = scaled_bands['green']
            r = scaled_bands['red']
            n = scaled_bands['nir']
            s = scaled_bands['swir']

            # Surface reflectance is linear [0.0, 1.5] for physical radiometric indices.
            # Log bands are computed on-demand if save_indices is enabled for downstream bathymetric analysis.
            SCALE = 1000.0

            b_c = np.clip(b, 1e-6, None)
            g_c = np.clip(g, 1e-6, None)
            r_c = np.clip(r, 1e-6, None)
            n_c = np.clip(n, 1e-6, None)
            s_c = np.clip(s, 1e-6, None)
            c_c = np.clip(c, 1e-6, None)

            # Calculate Indices
            denom_ndvi = np.where((n_c + r_c) == 0, 1e-6, n_c + r_c)
            ndvi = (n_c - r_c) / denom_ndvi

            denom_ndwi = np.where((g_c + n_c) == 0, 1e-6, g_c + n_c)
            ndwi = (g_c - n_c) / denom_ndwi

            denom_mndwi = np.where((g_c + s_c) == 0, 1e-6, g_c + s_c)
            mndwi = (g_c - s_c) / denom_mndwi

            vis_mean = (b_c + g_c + r_c) / 3.0
            ir_mean = (n_c + s_c) / 2.0
            denom_nwi = np.where((vis_mean + ir_mean) == 0, 1e-6, vis_mean + ir_mean)
            nwi = (vis_mean - ir_mean) / denom_nwi

            awei = b_c + 2.5 * g_c - 1.5 * n_c - 2.0 * s_c

            # Save optional index rasters to subfolder
            if save_indices:
                indices_dir = os.path.join(out_dir, "1_Review_Indices")
                os.makedirs(indices_dir, exist_ok=True)
                feedback.pushInfo(f"   Saving Spectral Indices & Log Bands to: {indices_dir}...")
                
                def write_index(arr, fname):
                    p_idx = prof.copy()
                    p_idx.update(count=1, dtype="float32", nodata=np.nan)
                    out_arr = arr.copy()
                    out_arr[~valid_mask] = np.nan
                    fpath = os.path.join(indices_dir, fname)
                    with rasterio.open(fpath, "w", **p_idx) as dst:
                        dst.write(out_arr.astype(np.float32), 1)

                write_index(ndvi, "NDVI.tif")
                write_index(mndwi, "MNDWI.tif")
                write_index(nwi, "NWI.tif")
                write_index(awei, "AWEI.tif")

                # Compute log bands specifically for bathymetric depth inversion review
                log_b = np.log(np.clip(b * SCALE, 1e-4, None))
                log_g = np.log(np.clip(g * SCALE, 1e-4, None))
                write_index(log_b, "Log_Blue.tif")
                write_index(log_g, "Log_Green.tif")
                del log_b, log_g

            feedback.pushInfo("🌊 Step 2/4: Computing Water Mask...")

            water_mask = np.zeros((h, w), dtype=bool)

            if water_poly_layer is not None:
                feedback.pushInfo("   Using provided Vector Polygon for Water Masking...")
                source_crs = water_poly_layer.crs()
                dest_crs = input_layer.crs()
                transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
                geoms = []
                for feat in water_poly_layer.getFeatures():
                    geom = feat.geometry()
                    geom.transform(transform)
                    geoms.append(json.loads(geom.asJson()))
                if not geoms:
                    raise QgsProcessingException("The provided water polygon layer is empty!")
                water_mask = geometry_mask(
                    geoms, out_shape=(h, w), transform=src.transform, invert=True
                )
            else:
                method_name = self.MASK_METHODS[mask_choice]
                feedback.pushInfo(f"   Selected Method: {method_name}")

                if method_name == "Otsu (Automatic NDWI)":
                    valid_ndwi = ndwi[valid_mask]
                    thresh = 0.0
                    if valid_ndwi.size > 100:
                        hist, bins = np.histogram(valid_ndwi, bins=256, range=(-1.0, 1.0))
                        total = valid_ndwi.size
                        sum_total = np.dot(np.arange(256), hist)
                        sum_b, weight_b, max_var, thresh_idx = 0, 0, 0, 0
                        for i in range(256):
                            weight_b += hist[i]
                            if weight_b == 0: continue
                            weight_f = total - weight_b
                            if weight_f == 0: break
                            sum_b += i * hist[i]
                            m_b = sum_b / weight_b
                            m_f = (sum_total - sum_b) / weight_f
                            var_b = weight_b * weight_f * (m_b - m_f) ** 2
                            if var_b > max_var:
                                max_var = var_b
                                thresh_idx = i
                        thresh = float(bins[thresh_idx]) + otsu_adj
                    effective_thresh = max(-0.05, min(thresh, 0.35))
                    feedback.pushInfo(f"   Calculated Otsu NDWI Threshold: {effective_thresh:.4f}")
                    water_mask = (ndwi > effective_thresh) & (n_c < 0.18) & valid_mask

                elif method_name == "Manual NDWI Threshold":
                    feedback.pushInfo(f"   Applying Manual NDWI Threshold: {manual_val:.4f}")
                    water_mask = (ndwi > manual_val) & (n_c < 0.18) & valid_mask

                elif method_name == "3 Indices Equation (NDWI, MNDWI, NWI)":
                    water_mask = (mndwi > 0.0) & (nwi > 0.0) & (ndvi < 0.12) & (n_c < 0.18) & valid_mask

                elif method_name == "Smart Hybrid (Dynamic Auto)":
                    valid_ndwi = ndwi[valid_mask]
                    if valid_ndwi.size > 100:
                        std_dev = float(np.std(valid_ndwi))
                        if std_dev < 0.05:
                            water_mask = (mndwi > 0.0) & (n_c < 0.18) & (ndvi < 0.15) & valid_mask
                        else:
                            hist, bins = np.histogram(valid_ndwi, bins=256, range=(-1.0, 1.0))
                            total = valid_ndwi.size
                            hist_smoothed = pure_numpy_smooth_histogram(hist, radius=2)
                            sum_total = np.dot(np.arange(256), hist)
                            max_val, thresh_idx, sum_b, weight_b = 0, 0, 0, 0
                            for i in range(256):
                                weight_b += hist[i]
                                if weight_b == 0: continue
                                weight_f = total - weight_b
                                if weight_f == 0: break
                                sum_b += i * hist[i]
                                m_b = sum_b / weight_b
                                m_f = (sum_total - sum_b) / weight_f
                                var_b = weight_b * weight_f * (m_b - m_f) ** 2
                                p_t = hist_smoothed[i] / total
                                score = (1.0 - p_t) * var_b
                                if score > max_val:
                                    max_val = score
                                    thresh_idx = i
                            otsu_thresh = float(bins[thresh_idx]) + otsu_adj
                            effective_thresh = max(-0.05, min(otsu_thresh, 0.30))
                            water_mask = (
                                (ndwi > effective_thresh)
                                & (mndwi > -0.08)
                                & (n_c < 0.18)
                                & (ndvi < 0.18)
                                & valid_mask
                            )
                    else:
                        water_mask = (mndwi > 0.0) & (n_c < 0.18) & (ndvi < 0.12) & valid_mask

                elif method_name == "Tiled / Local Adaptive Otsu":
                    tile_size = 512
                    valid_vals = mndwi[valid_mask]
                    global_thresh = 0.0
                    if valid_vals.size > 100:
                        hist, bins = np.histogram(valid_vals, bins=256, range=(-1.0, 1.0))
                        total = valid_vals.size
                        sum_total = np.dot(np.arange(256), hist)
                        sum_b, weight_b, max_var, thresh_idx = 0, 0, 0, 0
                        for i in range(256):
                            weight_b += hist[i]
                            if weight_b == 0: continue
                            weight_f = total - weight_b
                            if weight_f == 0: break
                            sum_b += i * hist[i]
                            m_b = sum_b / weight_b
                            m_f = (sum_total - sum_b) / weight_f
                            var_b = weight_b * weight_f * (m_b - m_f) ** 2
                            if var_b > max_var:
                                max_var = var_b
                                thresh_idx = i
                        global_thresh = float(bins[thresh_idx]) + otsu_adj

                    n_tiles_y = max(1, int(np.ceil(h / tile_size)))
                    n_tiles_x = max(1, int(np.ceil(w / tile_size)))
                    thresh_grid = np.full((n_tiles_y, n_tiles_x), global_thresh, dtype=np.float32)

                    for ty in range(n_tiles_y):
                        for tx in range(n_tiles_x):
                            y0, y1 = ty * tile_size, min((ty + 1) * tile_size, h)
                            x0, x1 = tx * tile_size, min((tx + 1) * tile_size, w)
                            tile_mndwi = mndwi[y0:y1, x0:x1]
                            tile_valid = valid_mask[y0:y1, x0:x1]
                            t_vals = tile_mndwi[tile_valid]
                            if t_vals.size > 150:
                                t_min, t_max = float(np.min(t_vals)), float(np.max(t_vals))
                                t_std = float(np.std(t_vals))

                                if t_max < -0.05:
                                    thresh_grid[ty, tx] = 1.0
                                elif t_min > 0.10:
                                    thresh_grid[ty, tx] = -1.0
                                elif (t_min < -0.05) and (t_max > 0.05) and (t_std > 0.04):
                                    t_hist, t_bins = np.histogram(t_vals, bins=128, range=(-1.0, 1.0))
                                    t_tot = t_vals.size
                                    t_sum_total = np.dot(np.arange(128), t_hist)
                                    t_sum_b, t_weight_b, t_max_var, t_idx = 0, 0, 0, 0
                                    for i in range(128):
                                        t_weight_b += t_hist[i]
                                        if t_weight_b == 0: continue
                                        t_weight_f = t_tot - t_weight_b
                                        if t_weight_f == 0: break
                                        t_sum_b += i * t_hist[i]
                                        m_b = t_sum_b / t_weight_b
                                        m_f = (t_sum_total - t_sum_b) / t_weight_f
                                        var_b = t_weight_b * t_weight_f * (m_b - m_f) ** 2
                                        if var_b > t_max_var:
                                            t_max_var = var_b
                                            t_idx = i
                                    local_t = float(t_bins[t_idx]) + otsu_adj
                                    thresh_grid[ty, tx] = np.clip(local_t, -0.15, 0.25)
                                else:
                                    thresh_grid[ty, tx] = global_thresh

                    smooth_thresh_map = pure_numpy_bilinear_grid(thresh_grid, h, w)
                    water_mask = (mndwi > smooth_thresh_map) & (mndwi > -0.10) & (n_c < 0.18) & valid_mask

                elif method_name == "Modified AWEI (Single-SWIR)":
                    water_mask = (awei > 0.0) & (mndwi > -0.08) & (n_c < 0.18) & (s_c < 0.12) & (ndvi < 0.20) & valid_mask

                elif method_name == "Spectral Slope & Profile Tree":
                    vis_sum = c_c + b_c + g_c
                    ir_sum = n_c + s_c
                    safe_ir = np.where(ir_sum <= 1e-6, 1e-6, ir_sum)
                    vis_ir_ratio = vis_sum / safe_ir
                    water_mask = (
                        (vis_ir_ratio > 1.20)
                        & (g_c > s_c)
                        & (n_c < 0.18)
                        & (s_c < 0.12)
                        & (mndwi > -0.08)
                        & (ndvi < 0.18)
                        & valid_mask
                    )

            # Sieve speckle noise cleanup
            mask_uint8 = water_mask.astype(np.uint8)
            if k_size > 0:
                try:
                    mask_uint8 = sieve(mask_uint8, size=k_size, connectivity=8)
                except Exception:
                    pass

            mask_uint8[~valid_mask] = 255

            feedback.pushInfo("💾 Step 3/4: Writing Final Water Mask Raster...")
            prof.update(count=1, dtype="uint8", nodata=255)

            temp_mask_path = out_mask_path
            if reproject_wgs84:
                temp_mask_path = os.path.join(out_dir, "temp_mask_native.tif")

            with rasterio.open(temp_mask_path, "w", **prof) as dst:
                dst.write(mask_uint8, 1)

            # Free large memory buffers before child algorithm vectorization
            try:
                del raw_b, raw_g, raw_r, raw_n, raw_s, raw_c
                del b_c, g_c, r_c, n_c, s_c, c_c
                del ndvi, ndwi, mndwi, nwi, awei, water_mask, mask_uint8
            except Exception:
                pass

            final_raster_out = temp_mask_path
            if reproject_wgs84:
                feedback.pushInfo("   Reprojecting Water Mask to WGS84 (EPSG:4326)...")
                reproj_res = processing.run(
                    "gdal:warpreproject",
                    {
                        "INPUT": temp_mask_path,
                        "TARGET_CRS": "EPSG:4326",
                        "NODATA": 255,
                        "RESAMPLING": 0,
                        "OUTPUT": out_mask_path,
                    },
                    context=context,
                    feedback=feedback,
                    is_child_algorithm=True,
                )
                final_raster_out = reproj_res["OUTPUT"]
                if os.path.exists(temp_mask_path):
                    try: os.remove(temp_mask_path)
                    except Exception: pass

        if feedback.isCanceled():
            return {}

        feedback.pushInfo("📐 Step 4/4: Scientific Vectorization & Geometry Filtering...")

        poly_res = processing.run(
            "gdal:polygonize",
            {
                "INPUT": final_raster_out,
                "BAND": 1,
                "FIELD": "DN",
                "EIGHT_CONNECTEDNESS": True,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True,
        )

        extract_res = processing.run(
            "native:extractbyexpression",
            {
                "INPUT": poly_res["OUTPUT"],
                "EXPRESSION": '"DN" = 1',
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True,
        )

        geom_layer_source = extract_res["OUTPUT"]
        if vector_smooth_iters > 0:
            feedback.pushInfo(f"   Applying Geometry Smoothing ({vector_smooth_iters} iterations)...")
            smooth_res = processing.run(
                "native:smoothgeometry",
                {
                    "INPUT": extract_res["OUTPUT"],
                    "ITERATIONS": vector_smooth_iters,
                    "OFFSET": 0.25,
                    "MAX_ANGLE": 180,
                    "OUTPUT": "TEMPORARY_OUTPUT",
                },
                context=context,
                feedback=feedback,
                is_child_algorithm=True,
            )
            geom_layer_source = smooth_res["OUTPUT"]

        if isinstance(geom_layer_source, QgsVectorLayer):
            source_vec = geom_layer_source
        else:
            source_vec = QgsProcessingUtils.mapLayerFromString(str(geom_layer_source), context)
            if not source_vec or not source_vec.isValid():
                source_vec = QgsVectorLayer(str(geom_layer_source), "temp_src", "ogr")

        # Initialize QgsDistanceArea for accurate geodesic/ellipsoidal area & perimeter measurements
        da = QgsDistanceArea()
        da.setSourceCrs(source_vec.crs(), context.transformContext())
        ellipsoid = context.project().ellipsoid() if (context.project() and context.project().ellipsoid()) else "WGS84"
        da.setEllipsoid(ellipsoid)

        def measure_geom_metrics(geometry):
            try:
                m2 = abs(da.measureArea(geometry))
            except Exception:
                m2 = abs(geometry.area())
            try:
                perim_m = abs(da.measurePerimeter(geometry))
            except Exception:
                try:
                    perim_m = abs(da.measureLength(geometry))
                except Exception:
                    perim_m = abs(geometry.length())
            ha = m2 / 10000.0
            km2 = m2 / 1e6
            p_km = perim_m / 1000.0
            return m2, ha, km2, p_km

        raw_candidates = []
        for feat in source_vec.getFeatures():
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                _, a_ha, _, _ = measure_geom_metrics(geom)
                raw_candidates.append((a_ha, geom, feat))

        feedback.pushInfo(f"   Raw vectorization yielded {len(raw_candidates)} polygon fragments.")
        feedback.pushInfo(f"   Applying Scientific Selection Mode: {self.POLY_MODES[poly_mode_choice]}...")

        selected_candidates = filter_polygons_scientifically(
            raw_candidates,
            mode_choice=poly_mode_choice,
            min_area_ha=min_poly_area_ha,
            max_count=max_poly_count,
            significance_ratio=0.005,
        )

        if not selected_candidates and raw_candidates:
            raw_candidates.sort(key=lambda x: x[0], reverse=True)
            selected_candidates = [raw_candidates[0]]

        feedback.pushInfo(f"   ✨ Retained {len(selected_candidates)} genuine scientific waterbody feature(s).")
        for rank, (a_h, _, _) in enumerate(selected_candidates, 1):
            feedback.pushInfo(f"      • Polygon #{rank}: Area = {a_h:.2f} ha ({a_h/100.0:.4f} km²)")

        crs = source_vec.crs()
        wkb_type = "MultiPolygon" if dissolve_polygons else "Polygon"
        mem_layer = QgsVectorLayer(f"{wkb_type}?crs={crs.authid()}", "Waterbody_Polygons", "memory")
        pr = mem_layer.dataProvider()
        pr.addAttributes([
            QgsField("ID", QVariant.Int),
            QgsField("Name", QVariant.String),
            QgsField("Area_km2", QVariant.Double),
            QgsField("Area_ha", QVariant.Double),
            QgsField("Perim_km", QVariant.Double),
            QgsField("Dominance_%", QVariant.Double),
        ])
        mem_layer.updateFields()

        fields = mem_layer.fields()
        to_add = []
        primary_area_ha = selected_candidates[0][0] if selected_candidates else 1.0

        if dissolve_polygons and len(selected_candidates) > 1:
            combined_geom = selected_candidates[0][1]
            for _, g, _ in selected_candidates[1:]:
                combined_geom = combined_geom.combine(g)

            _, tot_a_ha, tot_a_km2, tot_p_km = measure_geom_metrics(combined_geom)

            f = QgsFeature(fields)
            f.setGeometry(combined_geom)
            f.setAttributes([1, "Unified Major Waterbodies", round(tot_a_km2, 4), round(tot_a_ha, 2), round(tot_p_km, 3), 100.0])
            to_add.append(f)
        else:
            for idx, (a_ha, g, _) in enumerate(selected_candidates, 1):
                _, a_ha_meas, a_km2, p_km = measure_geom_metrics(g)
                dominance = (a_ha_meas / primary_area_ha) * 100.0 if primary_area_ha > 0 else 100.0
                
                if idx == 1:
                    w_name = "Primary Coastal Sea / Ocean"
                elif dominance >= 5.0:
                    w_name = "Major Coastal Lagoon / Bay"
                else:
                    w_name = "Secondary Waterbody"

                f = QgsFeature(fields)
                f.setGeometry(g)
                f.setAttributes([idx, w_name, round(a_km2, 4), round(a_ha_meas, 2), round(p_km, 3), round(dominance, 2)])
                to_add.append(f)

        pr.addFeatures(to_add)
        mem_layer.updateExtents()

        if os.path.exists(out_poly_path):
            try: os.remove(out_poly_path)
            except Exception: pass

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        options.layerName = "01_Waterbody_Polygon"

        try:
            QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer,
                out_poly_path,
                context.transformContext(),
                options
            )
        except Exception:
            try:
                QgsVectorFileWriter.writeAsVectorFormat(
                    mem_layer,
                    out_poly_path,
                    "UTF-8",
                    crs,
                    "GPKG"
                )
            except Exception:
                processing.run(
                    "native:savefeatures",
                    {"INPUT": mem_layer, "OUTPUT": out_poly_path},
                    context=context,
                    feedback=feedback,
                    is_child_algorithm=True,
                )

        feedback.pushInfo(f"🎉 Scientific Water Masking & Polygon Extraction Completed! Output saved to: {out_dir}")

        return {
            self.OUTPUT_MASK: final_raster_out,
            self.OUTPUT_POLYGON: out_poly_path,
        }
