"""Run the existing regression suite against submission/, in an isolated copy.

The tests normally insert agent/ into sys.path. Staging submission/ at that
location makes the executable package authoritative without changing the tests.
Standalone parity is checked against a bundle built from the same source.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    staging_parent = root / ".pytest_tmp"
    staging_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="submission-source-", dir=staging_parent) as tmp:
        stage = Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest*", "tests")
        for name in ("agent", "submission"):
            shutil.copytree(root / "submission", stage / name, ignore=ignore)
        shutil.copytree(root / "agent" / "tests", stage / "agent" / "tests",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for regression in (root / "tests").glob("test_*.py"):
            shutil.copy2(regression, stage / "agent" / "tests" / regression.name)
        shutil.copy2(root / "agent" / "pytest.ini", stage / "pytest.ini")
        reference = Path("simulations/monte_carlo_shops/results/exhaustive/town_only_reference.npz")
        if (root / reference).exists():
            (stage / reference).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / reference, stage / reference)
        (stage / "dist").mkdir()
        from build_submission import build_single_file_submission
        build_single_file_submission(str(stage / "submission"), str(stage / "dist"))
        args = sys.argv[1:] or ["-q"]
        return subprocess.call([sys.executable, "-m", "pytest", "agent/tests", *args], cwd=stage)


if __name__ == "__main__":
    raise SystemExit(main())
