#
# SPDX-License-Identifier: BSD-2-Clause
#
# Copyright (c) 2013-2025, John McNamara, jmcnamara@cpan.org
#
import sys, os
plugin_dir = os.path.dirname(__file__)
lib_dir = os.path.join(plugin_dir, "lib")

if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)