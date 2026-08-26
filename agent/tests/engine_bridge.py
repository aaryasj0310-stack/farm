"""Bridge to the REAL installed Kaggriculture engine for integration tests."""
import importlib.util
import os


def get_engine():
    """Load the actual kaggriculture.py plugin module (ground truth)."""
    import kaggle_environments
    base = os.path.dirname(kaggle_environments.__file__)
    path = os.path.join(base, "envs", "kaggriculture", "kaggriculture.py")
    spec = importlib.util.spec_from_file_location("kaggriculture_engine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PASS_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}
