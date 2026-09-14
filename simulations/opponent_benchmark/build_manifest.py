"""Build manifest for the 100+ Crop Dusta replay benchmark.

Computes:
- filename
- match/game ID
- turn count
- Crop Dusta seat/side (0 or 1)
- opponent name and final scores
- SHA256 file hash

Splits deterministically:
- 20 games: dev / debugging
- 20 games: calibration
- 60 games: final evaluation
- remaining 6 games: auxiliary / extra
"""

import os
import json
import hashlib
from typing import Dict, List, Any

REPLAY_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "replays", "crop_dusta", "submission_55829779"
))
OUT_DIR = os.path.abspath(os.path.dirname(__file__))
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest.json")


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build_manifest() -> Dict[str, Any]:
    print(f"Scanning replay directory: {REPLAY_DIR}")
    # Filter only numeric episode JSON files (excluding metadata like submission_55829779_matches.json)
    files = sorted([f for f in os.listdir(REPLAY_DIR) if f.endswith(".json") and f.split(".")[0].isdigit()])
    print(f"Found {len(files)} gameplay replay JSON files.")

    records = []
    for idx, fname in enumerate(files):
        fpath = os.path.join(REPLAY_DIR, fname)
        file_hash = compute_sha256(fpath)

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            steps = data
            game_id = fname.split(".")[0]
            info = steps[0][0].get("info", {}) if steps and len(steps[0]) > 0 and isinstance(steps[0][0], dict) else {}
        else:
            steps = data.get("steps", [])
            game_id = str(data.get("id") or data.get("info", {}).get("EpisodeId") or fname.split(".")[0])
            info = data.get("info", {})

        turn_count = len(steps)

        # Determine Crop Dusta seat
        team_names = info.get("TeamNames", [])
        agents = info.get("Agents", [])

        cd_seat = None
        opp_name = "Unknown"

        if len(team_names) >= 2:
            if "Crop Dusta" in team_names[0]:
                cd_seat = 0
                opp_name = team_names[1]
            elif "Crop Dusta" in team_names[1]:
                cd_seat = 1
                opp_name = team_names[0]
        elif len(agents) >= 2:
            name0 = agents[0].get("Name", "")
            name1 = agents[1].get("Name", "")
            if "Crop Dusta" in name0:
                cd_seat = 0
                opp_name = name1
            elif "Crop Dusta" in name1:
                cd_seat = 1
                opp_name = name0

        if cd_seat is None:
            # Default to seat 0 if ambiguous
            cd_seat = 0

        # Extract final scores
        cd_score = 0.0
        opp_score = 0.0
        if steps:
            final_step = steps[-1]
            if len(final_step) >= 2:
                cd_score = float(final_step[cd_seat].get("reward") or 0.0)
                opp_score = float(final_step[1 - cd_seat].get("reward") or 0.0)

        record = {
            "filename": fname,
            "game_id": game_id,
            "turn_count": turn_count,
            "crop_dusta_seat": cd_seat,
            "crop_dusta_score": cd_score,
            "opponent_name": opp_name,
            "opponent_score": opp_score,
            "sha256": file_hash,
        }
        records.append(record)
        if (idx + 1) % 20 == 0 or (idx + 1) == len(files):
            print(f"Processed {idx + 1}/{len(files)} replays...")

    # Deterministic sort by game_id
    records.sort(key=lambda r: r["game_id"])

    # Split into 20 dev, 20 calibration, 60 eval, remainder auxiliary
    dev_records = records[:20]
    cal_records = records[20:40]
    eval_records = records[40:100]
    extra_records = records[100:]

    for r in dev_records:
        r["split"] = "dev"
    for r in cal_records:
        r["split"] = "calibration"
    for r in eval_records:
        r["split"] = "eval"
    for r in extra_records:
        r["split"] = "extra"

    manifest = {
        "dataset_name": "Crop Dusta Leader Replays (Submission 55829779)",
        "source_dir": REPLAY_DIR,
        "total_files": len(records),
        "split_counts": {
            "dev": len(dev_records),
            "calibration": len(cal_records),
            "eval": len(eval_records),
            "extra": len(extra_records),
        },
        "records": records,
    }

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest built successfully: {MANIFEST_PATH}")
    print(f"Splits: dev={len(dev_records)}, calibration={len(cal_records)}, eval={len(eval_records)}, extra={len(extra_records)}")
    return manifest


if __name__ == "__main__":
    build_manifest()
