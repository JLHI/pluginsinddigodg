# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PluginsInddigoDG
                                 A QGIS plugin
 Les plugins non restreint du pôle DG d'Inddigo
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2024-11-22
        copyright            : (C) 2024 by JLHI
        email                : jl.humbert@inddigo.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""

__author__ = 'JLHI'
__date__ = '2024-11-22'
__copyright__ = '(C) 2024 by JLHI'


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load PluginsInddigoDG class from file PluginsInddigoDG.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .PluginsInddigoDG import PluginsInddigoDGPlugin
    return PluginsInddigoDGPlugin()