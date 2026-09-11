"""Load the executable submission package for submission-specific regressions."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
SOURCE = Path(__file__).resolve().parents[1] / "after"
sys.path.insert(0, str(ROOT / "agent" / "tests"))  # Existing test fixtures only.
sys.path.insert(0, str(SOURCE))
for subpackage in ("state", "strategy", "execution", "market"):
    sys.path.insert(0, str(SOURCE / subpackage))
