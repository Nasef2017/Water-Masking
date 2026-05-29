# -*- coding: utf-8 -*-

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
from .water_masking_algorithm import WaterMaskingAlgorithm
import os

class WaterMaskingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(WaterMaskingAlgorithm())

    def id(self):
        return 'watermasking'

    def name(self):
        return 'Water Masking'

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon()
