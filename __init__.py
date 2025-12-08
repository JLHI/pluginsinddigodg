# -*- coding: utf-8 -*-
"""
Initialisation du plugin PluginsInddigoDG
"""

import sys, os
plugin_dir = os.path.dirname(__file__)
lib_dir = os.path.join(plugin_dir, "lib")
sys.path.insert(0, lib_dir)
# Répertoire réel du plugin
plugin_path = os.path.dirname(__file__)
plugin_dir = os.path.basename(plugin_path)

if "-" in plugin_dir:
    safe_name = plugin_dir.replace("-", "_")

    # Ajout au sys.modules pour que Python le traite comme un package valide
    sys.modules.setdefault(safe_name, sys.modules[__package__])

    # Correction du __package__ interne
    __package__ = safe_name

__author__ = 'JLHI'
__date__ = '2024-11-22'
__copyright__ = '(C) 2024'

def classFactory(iface):
    """
    Charge la classe principale du plugin
    """
    from .PluginsInddigoDG import PluginsInddigoDGPlugin
    return PluginsInddigoDGPlugin()