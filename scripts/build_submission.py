"""Helper script to package and validate the Kaggle multi-file submission archive.

Packages the real closed-loop adaptive agent from `agent/` into `submission/`
and builds the upload archives in `dist/`.
"""

import os
import shutil
import tarfile
import zipfile
from kaggle_environments import make


def sync_agent_to_submission(agent_dir: str, sub_dir: str):
    """Synchronize source code from agent/ to submission/ excluding tests and caches."""
    print(f"Syncing agent code from {agent_dir} -> {sub_dir}...")
    os.makedirs(sub_dir, exist_ok=True)
    
    # Ensure baked price table exists
    baked_table_path = os.path.join(agent_dir, "strategy", "baked_price_table.py")
    if not os.path.exists(baked_table_path):
        print("Generating baked price table...")
        from agent.strategy.price_forecast import PriceForecast, write_baked_table
        fc = PriceForecast.from_reference()
        write_baked_table(fc, baked_table_path)

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


def validate_submission(main_path: str):
    """Execute a full 720-step match against baseline to assert engine executability."""
    print(f"\nValidating closed-loop adaptive agent at: {main_path} (720 steps)...")
    env = make("kaggriculture", configuration={"seed": 11}, debug=True)
    env.run([main_path, "random"])
    
    # Check for any errors
    errors = [s for s in env.steps if s[0].status == "ERROR"]
    if errors:
        raise RuntimeError(f"Agent produced {len(errors)} engine errors: {errors[0][0]}")
    
    reward0 = env.steps[-1][0].observation["farms"][0]["money"]
    reward1 = env.steps[-1][0].observation["farms"][1]["money"]
    print(f"Validation successful! Match completed with scores: P0=${reward0:,.2f}, P1=${reward1:,.2f}")


def package_submission(src_dir: str, dist_dir: str):
    os.makedirs(dist_dir, exist_ok=True)
    
    # 1. Create submission.tar.gz
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

    # 2. Create submission.zip
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


if __name__ == "__main__":
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_dir = os.path.join(pkg_root, "agent")
    sub_dir = os.path.join(pkg_root, "submission")
    dist_dir = os.path.join(pkg_root, "dist")
    main_file = os.path.join(sub_dir, "main.py")

    sync_agent_to_submission(agent_dir, sub_dir)
    validate_submission(main_file)
    package_submission(sub_dir, dist_dir)
    print("\nClosed-loop adaptive submission package is successfully verified and ready in 'submission/' and 'dist/'!")
