import os
import sys

# Ensure project root and package directory are in sys.path
pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
root_dir = os.path.dirname(os.path.dirname(pkg_dir))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
