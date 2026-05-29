# -*- coding: utf-8 -*-

def classFactory(iface):
    """Load WaterMaskingPlugin class from file plugin.py.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .plugin import WaterMaskingPlugin
    return WaterMaskingPlugin()
