import os
import sys

_plugin_dir = os.path.dirname(os.path.dirname(__file__))
_lib_dir = os.path.join(_plugin_dir, 'lib')

if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

# lazperf.dll (dépendance de copclib) doit être dans le search path DLL avant l'import
_copclib_bin = os.path.join(_lib_dir, 'copclib', 'bin')
if os.path.isdir(_copclib_bin) and hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(_copclib_bin)
