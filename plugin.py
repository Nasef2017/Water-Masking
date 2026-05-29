# -*- coding: utf-8 -*-

import os
from qgis.core import QgsApplication
from .water_masking_provider import WaterMaskingProvider

class WaterMaskingPlugin:
    def __init__(self):
        self.provider = None

    def initProcessing(self):
        self.provider = WaterMaskingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
