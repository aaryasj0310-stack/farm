"""Build and validation script for the Kaggriculture multi-file submission package.

Canonical Submission Workflow:
  agent/                  # source of truth
     ↓
  submission/             # synced runtime package
     ↓
  dist/submission.zip     # official competition artifact

Layout in dist/submission.zip:
  submission.zip
  ├── main.py
  ├── config.py
  ├── state/
  ├── strategy/
  ├── execution/
  └── market/
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from kaggle_environments import make


RUNTIME_SUBPACKAGES = ["state", "strategy", "execution", "market"]
RUNTIME_ROOT_FILES = ["config.py", "main.py"]


def clean_obsolete_artifacts(pkg_root: str, dist_dir: str):
    """Remove obsolete single-file and tarball artifacts if present."""
    obsolete_files = [
        os.path.join(dist_dir, "submission.py"),
        os.path.join(dist_dir, "submission.tar.gz"),
        os.path.join(pkg_root, "submission.py"),
    ]
    for p in obsolete_files:
        if os.path.exists(p):
            try:
                os.remove(p)
                print(f"Removed obsolete artifact: {p}")
            except OSError:
                pass


def sync_agent_to_submission(agent_dir: str, sub_dir: str) -> List[str]:
    """Synchronize runtime source code from agent/ to submission/.

    Excludes:
      - tests/
      - __pycache__/
      - *.pyc
      - .pytest_cache/
      - development-only scratch files

    Returns the list of synced relative file paths.
    """
    print(f"Syncing agent code from {agent_dir} -> {sub_dir}...")
    os.makedirs(sub_dir, exist_ok=True)

    synced_files = []

    # 1. Sync root runtime files
    for fname in RUNTIME_ROOT_FILES:
        src = os.path.join(agent_dir, fname)
        dst = os.path.join(sub_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            synced_files.append(fname)

    # 2. Sync runtime subpackages
    for pkg in RUNTIME_SUBPACKAGES:
        src_pkg = os.path.join(agent_dir, pkg)
        dst_pkg = os.path.join(sub_dir, pkg)
        if not os.path.isdir(src_pkg):
            continue

        if os.path.exists(dst_pkg):
            shutil.rmtree(dst_pkg)

        shutil.copytree(
            src_pkg,
            dst_pkg,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", ".pytest*", "*test*"),
        )
        for root, _, files in os.walk(dst_pkg):
            for f in files:
                if f.endswith(".py"):
                    rel = os.path.relpath(os.path.join(root, f), sub_dir)
                    synced_files.append(rel)

    # 3. Strip any UTF-8 BOM from all files in submission/
    for root, _, files in os.walk(sub_dir):
        for file in files:
            if file.endswith(".py"):
                p = os.path.join(root, file)
                with open(p, "rb") as f:
                    data = f.read()
                if data.startswith(b"\xef\xbb\xbf"):
                    with open(p, "wb") as f:
                        f.write(data[3:])

    # 4. Clean any orphaned files in submission/ that do not exist in agent/
    for root, dirs, files in os.walk(sub_dir, topdown=False):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), sub_dir)
            agent_counterpart = os.path.join(agent_dir, rel)
            if not os.path.exists(agent_counterpart):
                orphan_path = os.path.join(root, f)
                os.remove(orphan_path)
                print(f"Removed orphaned file from submission: {rel}")
        for d in dirs:
            dir_path = os.path.join(root, d)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)

    # 5. Verification: ensure all expected agent runtime modules exist in submission/
    expected_modules = []
    for fname in RUNTIME_ROOT_FILES:
        expected_modules.append(fname)
    for pkg in RUNTIME_SUBPACKAGES:
        src_pkg = os.path.join(agent_dir, pkg)
        if os.path.isdir(src_pkg):
            for root, dirs, files in os.walk(src_pkg):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("tests", "__pycache__")]
                if "__pycache__" in root or "tests" in root or ".pytest" in root:
                    continue
                for f in files:
                    if f.endswith(".py") and not f.startswith("test_") and not f.startswith("."):
                        rel = os.path.relpath(os.path.join(root, f), agent_dir)
                        expected_modules.append(rel)

    missing = [m for m in expected_modules if not os.path.exists(os.path.join(sub_dir, m))]
    if missing:
        raise RuntimeError(f"Sync check failed! Missing runtime modules in submission/: {missing}")

    print(f"Sync complete: verified all {len(expected_modules)} runtime modules synced.")
    return synced_files


def package_submission_zip(src_dir: str, dist_dir: str) -> str:
    """Package submission/ directory into dist/submission.zip.

    main.py is located directly at the root of the ZIP archive.
    """
    os.makedirs(dist_dir, exist_ok=True)
    zip_path = os.path.join(dist_dir, "submission.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".pyc") or "__pycache__" in root or "tests" in root:
                    continue
                if file == "submission.py" or file.endswith(".tar.gz"):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, src_dir)
                z.write(full_path, arcname=rel_path)

    size_bytes = os.path.getsize(zip_path)
    print(f"Created official competition zip archive: {zip_path} ({size_bytes:,} bytes)")
    return zip_path


def validate_zip_submission(zip_path: str):
    """Validate submission.zip by extracting into a clean tempdir and running 720 steps."""
    print(f"\nValidating extracted package from {zip_path} in isolated environment...")

    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_dir)

        # 1. Structural assertions
        extracted_main = os.path.join(temp_dir, "main.py")
        extracted_config = os.path.join(temp_dir, "config.py")
        assert os.path.isfile(extracted_main), f"main.py missing from root of {zip_path}"
        assert os.path.isfile(extracted_config), f"config.py missing from root of {zip_path}"

        for pkg in RUNTIME_SUBPACKAGES:
            pkg_path = os.path.join(temp_dir, pkg)
            assert os.path.isdir(pkg_path), f"Runtime package {pkg} missing from {zip_path}"

        # Assert no prohibited files
        for root, dirs, files in os.walk(temp_dir):
            for d in dirs:
                assert d != "__pycache__", f"Prohibited directory {d} found in {zip_path}"
                assert d != "tests", f"Prohibited directory {d} found in {zip_path}"
            for f in files:
                assert not f.endswith(".pyc"), f"Prohibited bytecode file {f} found in {zip_path}"
                assert f != "submission.py", f"Prohibited standalone submission.py found in {zip_path}"

        # 2. Run full 720-step match against baseline using the extracted artifact
        env = make("kaggriculture", configuration={"seed": 11, "episodeSteps": 720}, debug=True)
        env.run([extracted_main, "random"])

        errors = [s for s in env.steps if s[0].status == "ERROR"]
        if errors:
            raise RuntimeError(f"Extracted ZIP produced {len(errors)} engine errors: {errors[0][0]}")

        # Assert market orders never exceeded engine cap
        for step_idx, step_state in enumerate(env.steps):
            agent_action = step_state[0].action
            if isinstance(agent_action, dict):
                market_orders = agent_action.get("market", [])
                assert len(market_orders) <= 10, (
                    f"Step {step_idx}: market orders ({len(market_orders)}) exceeded MAX_MARKET_ORDERS (10)"
                )

        reward0 = env.steps[-1][0].observation["farms"][0]["money"]
        reward1 = env.steps[-1][0].observation["farms"][1]["money"]
        print(f"Isolated validation successful! 720-turn match completed: P0=${reward0:,.2f}, P1=${reward1:,.2f}")


if __name__ == "__main__":
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_dir = os.path.join(pkg_root, "agent")
    sub_dir = os.path.join(pkg_root, "submission")
    dist_dir = os.path.join(pkg_root, "dist")

    clean_obsolete_artifacts(pkg_root, dist_dir)
    sync_agent_to_submission(agent_dir, sub_dir)
    zip_artifact = package_submission_zip(sub_dir, dist_dir)
    validate_zip_submission(zip_artifact)

    print("\n" + "=" * 70)
    print("Build Complete: dist/submission.zip is the canonical competition artifact.")
    print("=" * 70)
