# -*- coding: utf-8 -*-
"""
Initialisation du plugin PluginsInddigoDG
"""

import sys, os, types
plugin_dir = os.path.dirname(__file__)
lib_dir = os.path.join(plugin_dir, "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)
# Répertoire réel du plugin
plugin_path = os.path.dirname(__file__)
plugin_dir = os.path.basename(plugin_path)

if "-" in plugin_dir:
    # Normalize folder names like 'pluginsinddigodg-main' -> 'pluginsinddigodg_main'
    safe_name = plugin_dir.replace("-", "_")

    # Ensure there's a module object registered under the expected safe name
    current = sys.modules.get(__name__)
    if current is None:
        current = types.ModuleType(__name__)
        sys.modules[__name__] = current

    # Register alias module names so importlib can find the package under
    # different names that GitHub or installers might produce.
    # e.g. 'pluginsinddigodg-main' -> 'pluginsinddigodg_main' and also
    # a clean base name 'pluginsinddigodg' (without suffix).
    sys.modules.setdefault(safe_name, current)
    # also register the base name without any '-main' suffix
    base_name = safe_name
    if base_name.endswith('_main'):
        base_name_no_main = base_name[:-5]
        if base_name_no_main:
            sys.modules.setdefault(base_name_no_main, current)

    # Adjust __package__ so relative imports inside the package work when aliased
    try:
        __package__ = safe_name
    except Exception:
        pass

__author__ = 'JLHI'
__date__ = '2024-11-22'
__copyright__ = '(C) 2024'

def classFactory(iface):
    """
    Charge la classe principale du plugin
    """
    from .PluginsInddigoDG import PluginsInddigoDGPlugin
    return PluginsInddigoDGPlugin()