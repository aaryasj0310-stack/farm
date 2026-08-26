import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
sys.path.insert(0, _PKG)
for _sub in ("state", "strategy", "execution", "market"):
    sys.path.insert(0, os.path.join(_PKG, _sub))
