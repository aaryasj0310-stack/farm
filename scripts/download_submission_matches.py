"""
High-performance batch downloader for Crop Dusta match replays using Kaggle API.
"""
import os
import sys
import json
import time
import shutil
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

from kaggle.api.kaggle_api_extended import KaggleApi

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

def download_single_episode(ep_id, out_dir):
    """Downloads an episode replay and standardizes filename to <ep_id>.json"""
    std_file = os.path.join(out_dir, f"{ep_id}.json")
    kaggle_file = os.path.join(out_dir, f"episode-{ep_id}-replay.json")
    
    # Check if already present and valid
    for target in (std_file, kaggle_file):
        if os.path.exists(target) and os.path.getsize(target) > 10000:
            if not os.path.exists(std_file) and os.path.exists(kaggle_file):
                try:
                    shutil.move(kaggle_file, std_file)
                except Exception:
                    pass
            return ep_id, True, "Already exists"
            
    # Download
    try:
        api = KaggleApi()
        api.authenticate()
        api.competition_episode_replay(int(ep_id), path=out_dir, quiet=True)
        
        # Standardize name to <ep_id>.json
        if os.path.exists(kaggle_file):
            if os.path.exists(std_file):
                os.remove(std_file)
            shutil.move(kaggle_file, std_file)
            
        if os.path.exists(std_file) and os.path.getsize(std_file) > 10000:
            return ep_id, True, f"{os.path.getsize(std_file) / 1024 / 1024:.1f} MB"
        else:
            return ep_id, False, "Downloaded file missing or empty"
    except Exception as e:
        return ep_id, False, str(e)

def main():
    parser = argparse.ArgumentParser(description="Download Crop Dusta replays")
    parser.add_argument("--submission", "-s", default="55829779", help="Submission ID or 'latest' (55829779)")
    parser.add_argument("--limit", "-n", type=int, default=100, help="Number of matches to download (default: 100)")
    parser.add_argument("--workers", "-w", type=int, default=5, help="Number of concurrent download threads (default: 5)")
    args = parser.parse_args()
    
    sub_key = str(args.submission).lower()
    submission_id = SUBMISSION_MAP.get(sub_key, int(args.submission) if args.submission.isdigit() else 55829779)
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(base_dir, "replays", "crop_dusta", f"submission_{submission_id}")
    os.makedirs(out_dir, exist_ok=True)
    
    print("=" * 60)
    print(f" Downloading Crop Dusta Matches")
    print(f" Submission ID: {submission_id}")
    print(f" Target Matches: {args.limit}")
    print(f" Target Directory: {out_dir}")
    print(f" Worker Threads: {args.workers}")
    print("=" * 60)
    
    print("\nFetching match list from Kaggle...")
    raw_data = fetch_submission_episodes(submission_id)
    episodes = parse_episodes(raw_data, submission_id)
    print(f"Found {len(episodes)} total matches for submission {submission_id}.")
    
    # Save index
    index_file = os.path.join(out_dir, f"submission_{submission_id}_matches.json")
    with open(index_file, "w") as f:
        json.dump(episodes, f, indent=2)
    print(f"Match index saved to: {index_file}\n")
    
    target_episodes = episodes[:args.limit]
    
    # Standardize any existing files
    for fname in os.listdir(out_dir):
        if fname.startswith("episode-") and fname.endswith("-replay.json"):
            epid = fname.split("-")[1]
            old_p = os.path.join(out_dir, fname)
            new_p = os.path.join(out_dir, f"{epid}.json")
            if not os.path.exists(new_p):
                shutil.move(old_p, new_p)
            else:
                os.remove(old_p)
                
    start_time = time.time()
    completed = 0
    failed = 0
    
    print(f"Starting download of {len(target_episodes)} matches...")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(download_single_episode, ep["episode_id"], out_dir): ep
            for ep in target_episodes
        }
        for future in as_completed(futures):
            ep = futures[future]
            ep_id = ep["episode_id"]
            try:
                epid, ok, msg = future.result()
                if ok:
                    completed += 1
                    print(f"[{completed + failed}/{len(target_episodes)}] Episode {ep_id} ({ep['create_time'][:10]} vs {ep['opp_team_name'][:18]}): SUCCESS ({msg})")
                else:
                    failed += 1
                    print(f"[{completed + failed}/{len(target_episodes)}] Episode {ep_id} ({ep['create_time'][:10]} vs {ep['opp_team_name'][:18]}): FAILED ({msg})")
            except Exception as exc:
                failed += 1
                print(f"[{completed + failed}/{len(target_episodes)}] Episode {ep_id}: EXCEPTION ({exc})")
                
    elapsed = time.time() - start_time
    saved_files = [f for f in os.listdir(out_dir) if f.endswith(".json") and not f.startswith("submission_")]
    total_bytes = sum(os.path.getsize(os.path.join(out_dir, f)) for f in saved_files)
    
    print("\n" + "=" * 60)
    print(" Download Completed!")
    print(f" Total matches requested: {len(target_episodes)}")
    print(f" Successfully saved: {len(saved_files)} replays ({total_bytes / (1024*1024):.1f} MB)")
    print(f" Time elapsed: {elapsed:.1f}s ({elapsed/max(1, completed):.2f}s/replay)")
    print(f" Directory: {out_dir}")
    print("=" * 60)

if __name__ == "__main__":
    main()
