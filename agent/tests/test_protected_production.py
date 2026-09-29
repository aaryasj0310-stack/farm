"""Integrity gates never rebuild or synchronize protected production files."""
import hashlib
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_COMMIT = "faa6cb99f66b2066e639806d0eabc72a0c7d7982"
PRODUCTION_SHA256 = "E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41"


@pytest.mark.protected_artifact
def test_protected_production_artifact():
    assert hashlib.sha256((ROOT / "dist/submission.zip").read_bytes()).hexdigest().upper() == PRODUCTION_SHA256
    assert subprocess.check_output(["git", "cat-file", "-t", CANONICAL_COMMIT], cwd=ROOT).strip() == b"commit"


@pytest.mark.production_release
def test_canonical_submission_source_is_protected_revision():
    result = subprocess.run(
        ["git", "diff", "--exit-code", "--name-only", CANONICAL_COMMIT, "--", "submission"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, "Canonical source diverges from protected revision:\n" + result.stdout + result.stderr
