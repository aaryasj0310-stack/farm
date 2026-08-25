"""Helper script to package and validate the Kaggle multi-file submission archive."""

import os
import tarfile
import zipfile
from kaggle_environments import make


def validate_submission(main_path: str):
    print(f"Validating multi-file submission at: {main_path}...")
    env = make("kaggriculture", configuration={"episodeSteps": 48}, debug=True)
    env.run([main_path, "random"])
    reward0 = env.steps[-1][0].reward
    reward1 = env.steps[-1][1].reward
    print(f"Validation successful! Match completed with scores: P0=${reward0:.0f}, P1=${reward1:.0f}")


def package_submission(src_dir: str, dist_dir: str):
    os.makedirs(dist_dir, exist_ok=True)
    
    # 1. Create submission.tar.gz
    tar_path = os.path.join(dist_dir, "submission.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".pyc") or "__pycache__" in root:
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
                if file.endswith(".pyc") or "__pycache__" in root:
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, src_dir)
                z.write(full_path, arcname=rel_path)
    print(f"Created multi-file zip archive: {zip_path}")


if __name__ == "__main__":
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sub_dir = os.path.join(pkg_root, "submission")
    dist_dir = os.path.join(pkg_root, "dist")
    main_file = os.path.join(sub_dir, "main.py")

    validate_submission(main_file)
    package_submission(sub_dir, dist_dir)
    print("\nMulti-file submission package is ready in 'submission/' and 'dist/'!")
