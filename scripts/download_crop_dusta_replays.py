"""
Download matches for a specific submission of Kaggle player 'Crop Dusta'.
Supports downloading up to 100+ matches with resume capability, rate limiting, and structured indexing.
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error

SUBMISSION_MAP = {
    "latest": 55829779,
    "55829779": 55829779,
    "current": 55829779,
    "previous": 55714252,
    "55714252": 55714252
}

def fetch_submission_episodes(submission_id):
    url = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
    payload = {"submissionId": submission_id}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data

def parse_episodes(data, submission_id):
    episodes = data.get("episodes", [])
    teams = {t["id"]: t["teamName"] for t in data.get("teams", [])}
    
    parsed = []
    for ep in episodes:
        agents = ep.get("agents", [])
        crop_dusta_agent = next((a for a in agents if a.get("submissionId") == submission_id), None)
        opp_agent = next((a for a in agents if a.get("submissionId") != submission_id), None)
        
        crop_dusta_reward = crop_dusta_agent.get("reward") if crop_dusta_agent else None
        opp_reward = opp_agent.get("reward") if opp_agent else None
        
        winner = "Crop Dusta" if (crop_dusta_reward is not None and opp_reward is not None and crop_dusta_reward > opp_reward) else \
                 ("Opponent" if (crop_dusta_reward is not None and opp_reward is not None and opp_reward > crop_dusta_reward) else "Tie/Unknown")
        
        ep_info = {
            "episode_id": ep["id"],
            "submission_id": submission_id,
            "create_time": ep.get("createTime"),
            "end_time": ep.get("endTime"),
            "state": ep.get("state"),
            "crop_dusta_reward": crop_dusta_reward,
            "crop_dusta_initial_score": crop_dusta_agent.get("initialScore") if crop_dusta_agent else None,
            "crop_dusta_updated_score": crop_dusta_agent.get("updatedScore") if crop_dusta_agent else None,
            "crop_dusta_index": crop_dusta_agent.get("index", 0) if crop_dusta_agent else 0,
            "opp_submission_id": opp_agent.get("submissionId") if opp_agent else None,
            "opp_team_id": opp_agent.get("teamId") if opp_agent else None,
            "opp_team_name": teams.get(opp_agent.get("teamId")) if opp_agent else "Unknown",
            "opp_reward": opp_reward,
            "opp_initial_score": opp_agent.get("initialScore") if opp_agent else None,
            "opp_updated_score": opp_agent.get("updatedScore") if opp_agent else None,
            "winner": winner
        }
        parsed.append(ep_info)
        
    parsed.sort(key=lambda x: x.get("create_time", ""), reverse=True)
    return parsed

def main():
    parser = argparse.ArgumentParser(description="Download Crop Dusta replays for a submission")
    parser.add_argument("--submission", "-s", default="55829779", help="Submission ID or 'latest' (55829779) / 'previous' (55714252)")
    parser.add_argument("--limit", "-n", type=int, default=100, help="Number of matches to download (default: 100)")
    parser.add_argument("--output", "-o", default=None, help="Output directory for replays")
    args = parser.parse_args()
    
    sub_key = str(args.submission).lower()
    submission_id = SUBMISSION_MAP.get(sub_key, int(args.submission) if args.submission.isdigit() else 55829779)
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = args.output or os.path.join(base_dir, "replays", "crop_dusta", f"submission_{submission_id}")
    os.makedirs(out_dir, exist_ok=True)
    
    print(f"==================================================")
    print(f" Crop Dusta Replay Downloader")
    print(f" Submission ID: {submission_id}")
    print(f" Target Matches: {args.limit}")
    print(f" Output Folder: {out_dir}")
    print(f"==================================================")
    
    print("\n[1/3] Querying Kaggle for match history...")
    raw_data = fetch_submission_episodes(submission_id)
    episodes = parse_episodes(raw_data, submission_id)
    print(f"Found {len(episodes)} total matches played by submission {submission_id} on Kaggle.")
    
    # Save index for this submission
    index_file = os.path.join(out_dir, f"submission_{submission_id}_matches.json")
    with open(index_file, "w") as f:
        json.dump(episodes, f, indent=2)
    print(f"Saved complete match index to: {index_file}")
    
    target_episodes = episodes[:args.limit]
    print(f"\n[2/3] Preparing {len(target_episodes)} target matches...")
    
    # Check existing local replays
    existing_files = {
        os.path.splitext(f)[0]: os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.endswith(".json") and not f.startswith("submission_")
    }
    
    # Also check if replays exist in parent crop_dusta or toppers 28_8 folders
    search_dirs = [
        os.path.join(base_dir, "replays", "crop_dusta"),
        os.path.join(base_dir, "replays", "toppers 28_8")
    ]
    for sdir in search_dirs:
        if os.path.exists(sdir):
            for fname in os.listdir(sdir):
                if fname.endswith(".json") and fname[:-5].isdigit():
                    epid = fname[:-5]
                    if epid not in existing_files:
                        src = os.path.join(sdir, fname)
                        dst = os.path.join(out_dir, fname)
                        try:
                            import shutil
                            shutil.copy2(src, dst)
                            existing_files[epid] = dst
                        except Exception:
                            pass
                            
    print(f"Matches already available on disk: {len(existing_files)} / {len(target_episodes)}")
    
    # Try Kaggle API auth
    kaggle_api = None
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        kaggle_api = api
        print("Kaggle API successfully authenticated.")
    except (Exception, SystemExit):
        kaggle_api = None
        
    print("\n[3/3] Downloading replay JSONs...")
    downloaded = len(existing_files)
    failed = 0
    
    if kaggle_api:
        for idx, ep in enumerate(target_episodes, 1):
            ep_id = str(ep["episode_id"])
            dest = os.path.join(out_dir, f"{ep_id}.json")
            if ep_id in existing_files or os.path.exists(dest):
                continue
            
            print(f"[{idx}/{len(target_episodes)}] Downloading {ep_id} ({ep['create_time'][:10]} vs {ep['opp_team_name'][:18]})...", end="", flush=True)
            try:
                kaggle_api.competition_episode_replay(int(ep_id), path=out_dir, quiet=True)
                downloaded += 1
                print(" DONE")
                time.sleep(0.3)
            except Exception as e:
                failed += 1
                print(f" FAILED ({e})")
    else:
        print("\nNote: Kaggle API authentication token is required to download remaining replay files.")
        print("To download the remaining files:")
        print("  1. Go to https://www.kaggle.com/settings -> API -> 'Create New Token' (downloads kaggle.json)")
        print("  2. Place kaggle.json in ~/.kaggle/kaggle.json (or set KAGGLE_API_TOKEN environment variable)")
        print(f"  3. Re-run: python scripts/download_crop_dusta_replays.py --submission {submission_id} --limit {args.limit}")

    # Summary
    saved_count = len([f for f in os.listdir(out_dir) if f.endswith(".json") and not f.startswith("submission_")])
    print(f"\n==================================================")
    print(f" Summary for Submission {submission_id}:")
    print(f"   Total matches on Kaggle: {len(episodes)}")
    print(f"   Target matches requested: {len(target_episodes)}")
    print(f"   Replays saved on disk: {saved_count}")
    print(f"   Match catalog: {index_file}")
    print(f"==================================================")
    
    # Display top 15 target matches
    print("\nTop 15 matches for this submission:")
    print(f"{'Episode ID':<11} | {'Date':<19} | {'CD Score':<10} | {'CD Reward':<10} | {'Opponent':<20} | {'Opp Reward':<10} | {'Winner':<10}")
    print("-" * 105)
    for ep in target_episodes[:15]:
        cd_rew = f"${ep['crop_dusta_reward']:,}" if ep['crop_dusta_reward'] is not None else "N/A"
        op_rew = f"${ep['opp_reward']:,}" if ep['opp_reward'] is not None else "N/A"
        cd_sc = f"{ep['crop_dusta_updated_score']:.1f}" if ep['crop_dusta_updated_score'] is not None else "N/A"
        print(f"{ep['episode_id']:<11} | {ep['create_time'][:19]:<19} | {cd_sc:<10} | {cd_rew:<10} | {ep['opp_team_name'][:20]:<20} | {op_rew:<10} | {ep['winner']:<10}")

if __name__ == "__main__":
    main()
