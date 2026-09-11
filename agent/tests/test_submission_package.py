"""CI Validation Suite for the Official Multi-File Submission ZIP Package.

Verifies:
1. dist/submission.zip exists and conforms to the canonical layout.
2. main.py and config.py are located directly at the root of the ZIP archive.
3. All required runtime subpackages (state, strategy, execution, market) are present.
4. ZIP contains no tests, __pycache__, .pyc bytecode, .pytest_cache, or standalone submission.py.
5. Runtime sync: every runtime Python module in agent/ is present in submission/.
6. Package isolation: ZIP extracts to a clean temporary directory and imports without relying on repo checkout.
7. End-to-end 720-turn live match execution using the extracted ZIP artifact with zero errors.
8. Engine compliance: market orders never exceed MAX_MARKET_ORDERS (10).
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import pytest
import kaggle_environments
from config import MAX_MARKET_ORDERS


@pytest.fixture(scope="module")
def repo_paths():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    agent_dir = os.path.dirname(test_dir)
    repo_root = os.path.dirname(agent_dir)
    sub_dir = os.path.join(repo_root, "submission")
    dist_dir = os.path.join(repo_root, "dist")
    zip_path = os.path.join(dist_dir, "submission.zip")
    return {
        "repo_root": repo_root,
        "agent_dir": agent_dir,
        "sub_dir": sub_dir,
        "dist_dir": dist_dir,
        "zip_path": zip_path,
    }


def test_submission_zip_exists_and_layout(repo_paths):
    """Verify dist/submission.zip exists and contains expected root structure."""
    zip_path = repo_paths["zip_path"]
    if not os.path.exists(zip_path):
        # Run build script to generate artifact if needed
        build_script = os.path.join(repo_paths["repo_root"], "scripts", "build_submission.py")
        subprocess.check_call([sys.executable, build_script], cwd=repo_paths["repo_root"])

    assert os.path.exists(zip_path), f"Missing submission artifact: {zip_path}"
    assert os.path.getsize(zip_path) > 10000, f"Zip file is unexpectedly small: {os.path.getsize(zip_path)} bytes"

    with zipfile.ZipFile(zip_path, "r") as z:
        names = z.namelist()

        # Root files
        assert "main.py" in names, "main.py must be present at the root of submission.zip"
        assert "config.py" in names, "config.py must be present at the root of submission.zip"

        # Required subpackages
        for pkg in ["state", "strategy", "execution", "market"]:
            has_pkg = any(n.startswith(f"{pkg}/") for n in names)
            assert has_pkg, f"Required subpackage '{pkg}/' missing from submission.zip"

        # Prohibited artifacts
        for n in names:
            assert not n.startswith("tests/"), f"Prohibited tests file in ZIP: {n}"
            assert "test_" not in os.path.basename(n), f"Test file found in ZIP: {n}"
            assert "__pycache__" not in n, f"Prohibited __pycache__ in ZIP: {n}"
            assert not n.endswith(".pyc"), f"Prohibited .pyc bytecode in ZIP: {n}"
            assert ".pytest_cache" not in n, f"Prohibited .pytest_cache in ZIP: {n}"
            assert n != "submission.py", f"Prohibited standalone submission.py in ZIP: {n}"
            assert not n.startswith("submission/"), f"ZIP must not wrap contents in redundant top-level submission/: {n}"


def test_runtime_sync_from_agent_to_submission(repo_paths):
    """Verify all runtime Python files in agent/ are present in submission/."""
    agent_dir = repo_paths["agent_dir"]
    sub_dir = repo_paths["sub_dir"]

    agent_runtime_files = []
    for root, dirs, files in os.walk(agent_dir):
        # Exclude tests, caches, and hidden directories like .pytest_tmp
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("tests", "__pycache__")]
        if "tests" in root or "__pycache__" in root or ".pytest" in root:
            continue
        for f in files:
            if f.endswith(".py") and not f.startswith("test_") and not f.startswith("."):
                rel = os.path.relpath(os.path.join(root, f), agent_dir)
                agent_runtime_files.append(rel)

    missing_in_sub = [
        rel for rel in agent_runtime_files
        if not os.path.exists(os.path.join(sub_dir, rel))
    ]
    assert not missing_in_sub, f"Runtime files missing from submission/: {missing_in_sub}"


def test_zip_clean_environment_isolation_and_import(repo_paths):
    """Verify extracted ZIP loads and executes without dependencies on the repo checkout."""
    zip_path = repo_paths["zip_path"]
    assert os.path.exists(zip_path), f"Missing {zip_path}"

    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_dir)

        # Remove repo_root and agent_dir from sys.path to simulate a pure isolated environment
        repo_root = repo_paths["repo_root"]
        agent_dir = repo_paths["agent_dir"]
        sub_dir = repo_paths["sub_dir"]

        orig_sys_path = list(sys.path)
        isolated_sys_path = [p for p in orig_sys_path if p not in (repo_root, agent_dir, sub_dir)]
        isolated_sys_path.insert(0, temp_dir)

        # Clear any cached agent modules from sys.modules to force clean load from temp_dir
        modules_to_unload = [
            m for m in list(sys.modules.keys())
            if m.startswith(("config", "state", "strategy", "execution", "market", "main"))
        ]
        saved_modules = {m: sys.modules.pop(m) for m in modules_to_unload}

        try:
            sys.path = isolated_sys_path
            # Import main from temp_dir
            extracted_main_file = os.path.join(temp_dir, "main.py")
            spec = importlib.util.spec_from_file_location("isolated_main", extracted_main_file)
            assert spec is not None and spec.loader is not None
            isolated_mod = importlib.util.module_from_spec(spec)
            sys.modules["isolated_main"] = isolated_mod
            spec.loader.exec_module(isolated_mod)

            assert hasattr(isolated_mod, "agent"), "Extracted main.py must define entrypoint 'agent'"
            assert callable(isolated_mod.agent), "agent must be callable"

        finally:
            sys.path = orig_sys_path
            # Restore saved modules
            sys.modules.update(saved_modules)
            sys.modules.pop("isolated_main", None)


def test_zip_extracted_720_turn_live_match(repo_paths):
    """Run full 720-turn live match directly from extracted ZIP package."""
    zip_path = repo_paths["zip_path"]
    assert os.path.exists(zip_path), f"Missing {zip_path}"

    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_dir)

        extracted_main = os.path.join(temp_dir, "main.py")

        env = kaggle_environments.make(
            "kaggriculture",
            configuration={"episodeSteps": 720, "seed": 11},
            debug=True,
        )
        env.run([extracted_main, "random"])

        # Check for engine or agent runtime errors
        errors = [s for s in env.steps if s[0].status == "ERROR"]
        assert not errors, f"Extracted package produced engine error: {errors[0][0]}"

        # Verify episode ran to completion
        assert len(env.steps) >= 720, f"Match terminated prematurely: {len(env.steps)} steps"

        # Check market order cap compliance at every turn
        for step_idx, step_state in enumerate(env.steps):
            act = step_state[0].action
            if isinstance(act, dict):
                orders = act.get("market", [])
                assert len(orders) <= MAX_MARKET_ORDERS, (
                    f"Turn {step_idx}: market order count {len(orders)} exceeded cap {MAX_MARKET_ORDERS}"
                )

        # Check final score validity
        final_money = env.steps[-1][0].observation["farms"][0]["money"]
        assert final_money > 0, f"Final money was non-positive: {final_money}"
