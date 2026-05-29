# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterBand,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterDestination,
                       QgsProcessingParameterVectorDestination)
import processing

class WaterMaskingAlgorithm(QgsProcessingAlgorithm):
    INPUT = 'INPUT'
    BAND_BLUE = 'BAND_BLUE'
    BAND_GREEN = 'BAND_GREEN'
    BAND_RED = 'BAND_RED'
    BAND_NIR = 'BAND_NIR'
    BAND_SWIR = 'BAND_SWIR'
    
    SMOOTH_PIXELS = 'SMOOTH_PIXELS'
    VECTOR_SMOOTHING = 'VECTOR_SMOOTHING'

    OUTPUT_NDVI = 'OUTPUT_NDVI'
    OUTPUT_MNDWI = 'OUTPUT_MNDWI'
    OUTPUT_NWI = 'OUTPUT_NWI'
    OUTPUT_MASK = 'OUTPUT_MASK'
    OUTPUT_POLYGON = 'OUTPUT_POLYGON'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return WaterMaskingAlgorithm()

    def name(self):
        return 'watermask_v5'

    def displayName(self):
        return self.tr('Water Mask (Smooth Edges & Polygon)')

    def group(self):
        return self.tr('Water Analysis')

    def groupId(self):
        return 'wateranalysis'

    def shortHelpString(self):
        return """<h2>Water Masking Plugin: Advanced Waterbody Extraction</h2>
        <p>This module extracts accurate water masks and generates smoothed waterbody polygons from multispectral satellite imagery using a hybrid decision-tree of water indices.</p>

        <h3>Inputs:</h3>
        <ul>
            <li><b>Input Multi-Band Image:</b> The multispectral raster (UTM) containing Blue, Green, Red, NIR, and SWIR bands.</li>
            <li><b>Band Selection:</b> Specify the correct band indices for the calculations.</li>
        </ul>

        <h3>Settings:</h3>
        <ul>
            <li><b>Raster Noise Removal (Pixels):</b> Applies a sieve filter to remove isolated noise pixels below this threshold.</li>
            <li><b>Vector Edge Smoothing:</b> Rounds the sharp stair-step edges of the final polygon. (0 = None, 3 = Smooth).</li>
        </ul>

        <h3>Scientific Methodology (Indices & Equation):</h3>
        <ul>
            <li><b>NDVI (Normalized Difference Vegetation Index):</b> <code>(NIR - Red) / (NIR + Red)</code></li>
            <li><b>MNDWI (Modified Normalized Difference Water Index):</b> <code>(Green - SWIR) / (Green + SWIR)</code></li>
            <li><b>NWI (New Water Index):</b> <code>(VisMean - IRMean) / (VisMean + IRMean)</code></li>
        </ul>
        <p><b>Waterbody Polygon Equation:</b> <code>(MNDWI &gt; 0) AND (NWI &gt; 0) AND (NDVI &lt; 0.1)</code></p>

        <h3>Outputs:</h3>
        <p>All outputs are reprojected to Geodetic Lat/Long (EPSG:4326):</p>
        <ul>
            <li><b>Indices Rasters:</b> Output rasters for NDVI, MNDWI, and NWI.</li>
            <li><b>Final Water Mask Raster:</b> The binary water mask raster.</li>
            <li><b>Final Waterbody Polygon:</b> The extracted and smoothed waterbody vector layer.</li>
        </ul>
        <br>
        <p><i>Developed by Mohamed Aly Nasef</i></p>"""

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT, self.tr('Input Multi-Band Image (UTM)')))
        
        self.addParameter(QgsProcessingParameterBand(self.BAND_BLUE, self.tr('Blue Band'), parentLayerParameterName=self.INPUT, defaultValue=1))
        self.addParameter(QgsProcessingParameterBand(self.BAND_GREEN, self.tr('Green Band'), parentLayerParameterName=self.INPUT, defaultValue=2))
        self.addParameter(QgsProcessingParameterBand(self.BAND_RED, self.tr('Red Band'), parentLayerParameterName=self.INPUT, defaultValue=3))
        self.addParameter(QgsProcessingParameterBand(self.BAND_NIR, self.tr('NIR Band'), parentLayerParameterName=self.INPUT, defaultValue=4))
        self.addParameter(QgsProcessingParameterBand(self.BAND_SWIR, self.tr('SWIR Band'), parentLayerParameterName=self.INPUT, defaultValue=5))

        # Raster Smoothing (Sieve)
        self.addParameter(QgsProcessingParameterNumber(self.SMOOTH_PIXELS, self.tr('Raster Noise Removal (Pixels)'), type=QgsProcessingParameterNumber.Integer, defaultValue=10, minValue=0))
        
        # Vector Edge Smoothing
        self.addParameter(QgsProcessingParameterNumber(self.VECTOR_SMOOTHING, self.tr('Vector Edge Smoothing Iterations (0 = None, 3 = Smooth)'), type=QgsProcessingParameterNumber.Integer, defaultValue=3, minValue=0))

        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT_NDVI, self.tr('Output NDVI (Lat/Lon)')))
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT_MNDWI, self.tr('Output MNDWI (Lat/Lon)')))
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT_NWI, self.tr('Output NWI (Lat/Lon)')))
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT_MASK, self.tr('Final Water Mask Raster (Lat/Lon)')))
        self.addParameter(QgsProcessingParameterVectorDestination(self.OUTPUT_POLYGON, self.tr('Final Waterbody Polygon (Shapefile - Lat/Lon)')))

    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        
        b_idx = self.parameterAsInt(parameters, self.BAND_BLUE, context)
        g_idx = self.parameterAsInt(parameters, self.BAND_GREEN, context)
        r_idx = self.parameterAsInt(parameters, self.BAND_RED, context)
        n_idx = self.parameterAsInt(parameters, self.BAND_NIR, context)
        s_idx = self.parameterAsInt(parameters, self.BAND_SWIR, context)
        smooth_threshold = self.parameterAsInt(parameters, self.SMOOTH_PIXELS, context)
        vector_smooth_iters = self.parameterAsInt(parameters, self.VECTOR_SMOOTHING, context)

        if feedback.isCanceled(): return {}

        name = input_layer.name()
        b = f'"{name}@{b_idx}"'
        g = f'"{name}@{g_idx}"'
        r = f'"{name}@{r_idx}"'
        n = f'"{name}@{n_idx}"'
        s = f'"{name}@{s_idx}"'

        ndvi_formula = f'({n} - {r}) / ({n} + {r})'
        mndwi_formula = f'({g} - {s}) / ({g} + {s})'
        vis_mean = f'(({b} + {g} + {r}) / 3)'
        ir_mean = f'(({n} + {s}) / 2)'
        nwi_formula = f'({vis_mean} - {ir_mean}) / ({vis_mean} + {ir_mean})'
        final_mask_formula = f'(({mndwi_formula}) > 0) * (({nwi_formula}) > 0) * (({ndvi_formula}) < 0.1)'

        extent = input_layer.extent()
        crs_authid = input_layer.crs().authid()
        extent_string = f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()} [{crs_authid}]"

        def calculate_raster(formula):
            calc_params = {
                'EXPRESSION': formula,
                'LAYERS': [input_layer],
                'EXTENT': extent_string,
                'CRS': crs_authid,
                'CELLSIZE': input_layer.rasterUnitsPerPixelX(),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
            return processing.run("qgis:rastercalculator", calc_params, context=context, feedback=feedback, is_child_algorithm=True)['OUTPUT']

        def reproject_to_latlon(input_raster, out_param_name, is_mask=False):
            output_path = self.parameterAsOutputLayer(parameters, out_param_name, context)
            reproject_params = {
                'INPUT': input_raster,
                'TARGET_CRS': 'EPSG:4326',
                'NODATA': None,
                'RESAMPLING': 0 if is_mask else 1, 
                'OUTPUT': output_path
            }
            return processing.run("gdal:warpreproject", reproject_params, context=context, feedback=feedback, is_child_algorithm=True)['OUTPUT']

        # 1-3. Indices
        feedback.pushInfo("Step 1-3: Calculating Indices...")
        temp_ndvi = calculate_raster(ndvi_formula)
        out_ndvi = reproject_to_latlon(temp_ndvi, self.OUTPUT_NDVI)
        
        temp_mndwi = calculate_raster(mndwi_formula)
        out_mndwi = reproject_to_latlon(temp_mndwi, self.OUTPUT_MNDWI)
        
        temp_nwi = calculate_raster(nwi_formula)
        out_nwi = reproject_to_latlon(temp_nwi, self.OUTPUT_NWI)
        
        # 4. Raster Mask & Sieve
        feedback.pushInfo("Step 4/6: Calculating Final Water Mask...")
        temp_mask = calculate_raster(final_mask_formula)

        if smooth_threshold > 0:
            feedback.pushInfo(f"Removing isolated pixels < {smooth_threshold}...")
            sieve_params = {
                'INPUT': temp_mask,
                'THRESHOLD': smooth_threshold,
                'EIGHT_CONNECTEDNESS': True,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
            temp_mask = processing.run("gdal:sieve", sieve_params, context=context, feedback=feedback, is_child_algorithm=True)['OUTPUT']

        out_mask = reproject_to_latlon(temp_mask, self.OUTPUT_MASK, is_mask=True)

        # 5. Polygonize
        feedback.pushInfo("Step 5/6: Generating Polygon (Vectorizing)...")
        polygonize_params = {
            'INPUT': out_mask,
            'BAND': 1,
            'FIELD': 'DN',
            'EIGHT_CONNECTEDNESS': True,
            'OUTPUT': 'TEMPORARY_OUTPUT'
        }
        temp_poly_all = processing.run("gdal:polygonize", polygonize_params, context=context, feedback=feedback, is_child_algorithm=True)['OUTPUT']

        poly_out_path = self.parameterAsOutputLayer(parameters, self.OUTPUT_POLYGON, context)
        
        # Determine if we need an intermediate step based on smoothing
        extract_out = poly_out_path if vector_smooth_iters == 0 else 'TEMPORARY_OUTPUT'

        feedback.pushInfo("Extracting pure water features...")
        extract_params = {
            'INPUT': temp_poly_all,
            'FIELD': 'DN',
            'OPERATOR': 0, # '='
            'VALUE': '1',
            'OUTPUT': extract_out
        }
        temp_water_poly = processing.run("native:extractbyattribute", extract_params, context=context, feedback=feedback, is_child_algorithm=True)['OUTPUT']
        out_poly = temp_water_poly

        # 6. Edge Smoothing
        if vector_smooth_iters > 0:
            feedback.pushInfo(f"Step 6/6: Smoothing Polygon Edges (Iterations: {vector_smooth_iters})...")
            smooth_params = {
                'INPUT': temp_water_poly,
                'ITERATIONS': vector_smooth_iters,
                'OFFSET': 0.25,
                'MAX_ANGLE': 180,
                'OUTPUT': poly_out_path
            }
            out_poly = processing.run("native:smoothgeometry", smooth_params, context=context, feedback=feedback, is_child_algorithm=True)['OUTPUT']

        feedback.pushInfo("All processing successfully completed!")

        return {
            self.OUTPUT_NDVI: out_ndvi,
            self.OUTPUT_MNDWI: out_mndwi,
            self.OUTPUT_NWI: out_nwi,
            self.OUTPUT_MASK: out_mask,
            self.OUTPUT_POLYGON: out_poly
        }
