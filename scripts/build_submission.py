"""Helper script to package and validate the Kaggle submission.

Produces:
1. dist/submission.py  (Single-file standalone Python bundle - 100% Kaggle compliant)
2. dist/submission.zip (Multi-file zip archive with main.py at top level)
3. dist/submission.tar.gz (Multi-file tar.gz archive)
"""

import os
import re
import shutil
import tarfile
import zipfile
from kaggle_environments import make


def sync_agent_to_submission(agent_dir: str, sub_dir: str):
    """Synchronize source code from agent/ to submission/ excluding tests and caches."""
    print(f"Syncing agent code from {agent_dir} -> {sub_dir}...")
    os.makedirs(sub_dir, exist_ok=True)
    
    # Subpackages and files to copy
    items_to_copy = ["config.py", "main.py", "state", "strategy", "execution", "market"]
    
    for item in items_to_copy:
        src_path = os.path.join(agent_dir, item)
        dst_path = os.path.join(sub_dir, item)
        if not os.path.exists(src_path):
            continue
        if os.path.isdir(src_path):
            if os.path.exists(dst_path):
                shutil.rmtree(dst_path)
            shutil.copytree(
                src_path, dst_path,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", ".pytest*")
            )
        else:
            shutil.copy2(src_path, dst_path)

    # Strip any BOM from all python files in submission/
    for root, dirs, files in os.walk(sub_dir):
        for file in files:
            if file.endswith(".py"):
                p = os.path.join(root, file)
                with open(p, "rb") as f:
                    data = f.read()
                if data.startswith(b"\xef\xbb\xbf"):
                    with open(p, "wb") as f:
                        f.write(data[3:])


def build_single_file_submission(sub_dir: str, dist_dir: str) -> str:
    """Bundle all agent modules into a single, self-contained Python script."""
    modules = [
        "config.py",
        "strategy/baked_economics.py",
        "strategy/baked_price_table.py",
        "market/price_math.py",
        "state/observation_parser.py",
        "state/state_tracker.py",
        "state/opponent_model.py",
        "strategy/shop_adapter.py",
        "strategy/price_forecast.py",
        "strategy/opponent_advisor.py",
        "execution/pathfinding.py",
        "execution/unit_controller.py",
        "execution/task_scheduler.py",
        "strategy/macro_planner.py",
        "market/order_builder.py",
        "market/market_brain.py",
        "strategy/endgame_liquidator.py",
        "main.py",
    ]

    lines_out = [
        "from __future__ import annotations",
        "import os",
        "import sys",
        "import math",
        "import json",
        "import random",
        "from collections import defaultdict, deque",
        "from dataclasses import dataclass, field",
        "from typing import Any, Dict, List, Optional, Tuple, Set",
        "",
    ]

    internal_mods = [
        "config", "observation_parser", "state_tracker", "opponent_model",
        "shop_adapter", "price_forecast", "baked_price_table", "baked_economics",
        "opponent_advisor", "pathfinding", "unit_controller", "task_scheduler",
        "macro_planner", "price_math", "order_builder", "market_brain", "endgame_liquidator",
    ]

    pattern_internal = re.compile(
        r'^(?:from\s+(?:\.|\w+\.)*(?:' + '|'.join(internal_mods) + r')\s+import\s+(?:\([^\)]*\)|[^\n]+)|import\s+(?:' + '|'.join(internal_mods) + r'))',
        re.MULTILINE | re.DOTALL
    )
    pattern_try_except = re.compile(
        r'^try:\s*\n(?:\s+from\s+[^\n]+\n)+\s*except\s+ImportError:\s*\n(?:\s+from\s+[^\n]+\n)+',
        re.MULTILINE
    )
    pattern_std_imports = re.compile(
        r'^(?:from\s+__future__\s+import\s+[^\n]+|import\s+(?:os|sys|math|json|random)|from\s+(?:typing|dataclasses|collections)\s+import\s+(?:\([^\)]*\)|[^\n]+))',
        re.MULTILINE | re.DOTALL
    )

    for mod in modules:
        path = os.path.join(sub_dir, mod)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if content.startswith("\ufeff"):
            content = content[1:]
        
        content = pattern_try_except.sub("", content)
        content = pattern_internal.sub("", content)
        content = pattern_std_imports.sub("", content)

        if mod == "main.py":
            content = re.sub(r'# Safe path injection.*?(?=PASS_ACTION)', '', content, flags=re.DOTALL)

        lines_out.append(content.strip())
        lines_out.append("\n# " + "="*75 + f"\n# END MODULE: {mod}\n# " + "="*75 + "\n")

    single_file_path = os.path.join(dist_dir, "submission.py")
    bundled_code = "\n".join(lines_out)
    with open(single_file_path, "w", encoding="utf-8") as f:
        f.write(bundled_code)
    
    print(f"Created standalone single-file: {single_file_path} ({len(bundled_code):,} bytes)")
    return single_file_path


def validate_submission(agent_path: str):
    """Execute a full 720-step match against baseline to assert engine executability."""
    print(f"\nValidating agent at: {agent_path} (720 steps)...")
    env = make("kaggriculture", configuration={"seed": 11}, debug=True)
    env.run([agent_path, "random"])
    
    errors = [s for s in env.steps if s[0].status == "ERROR"]
    if errors:
        raise RuntimeError(f"Agent produced {len(errors)} engine errors: {errors[0][0]}")
    
    reward0 = env.steps[-1][0].observation["farms"][0]["money"]
    reward1 = env.steps[-1][0].observation["farms"][1]["money"]
    print(f"Validation successful! Match completed with scores: P0=${reward0:,.2f}, P1=${reward1:,.2f}")


def package_submission(src_dir: str, dist_dir: str):
    os.makedirs(dist_dir, exist_ok=True)
    
    # 1. Create submission.zip
    zip_path = os.path.join(dist_dir, "submission.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".pyc") or "__pycache__" in root or "tests" in root:
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, src_dir)
                z.write(full_path, arcname=rel_path)
    print(f"Created multi-file zip archive: {zip_path}")

    # 2. Create submission.tar.gz
    tar_path = os.path.join(dist_dir, "submission.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".pyc") or "__pycache__" in root or "tests" in root:
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, src_dir)
                tar.add(full_path, arcname=rel_path)
    print(f"Created multi-file tar.gz archive: {tar_path}")


if __name__ == "__main__":
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_dir = os.path.join(pkg_root, "agent")
    sub_dir = os.path.join(pkg_root, "submission")
    dist_dir = os.path.join(pkg_root, "dist")
    main_file = os.path.join(sub_dir, "main.py")

    sync_agent_to_submission(agent_dir, sub_dir)
    validate_submission(main_file)
    package_submission(sub_dir, dist_dir)
    single_file = build_single_file_submission(sub_dir, dist_dir)
    validate_submission(single_file)
    print("\nAll submission packages (dist/submission.py, dist/submission.zip, dist/submission.tar.gz) verified and ready!")
