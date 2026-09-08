import urllib.request
import json

def get_episodes(submission_id):
    url = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
    payload = {"submissionId": submission_id}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data

subs = [55714252, 55829779]
all_episodes = []

for sub_id in subs:
    data = get_episodes(sub_id)
    episodes = data.get("episodes", [])
    teams = {t["id"]: t["teamName"] for t in data.get("teams", [])}
    print(f"Submission {sub_id}: found {len(episodes)} episodes")
    for ep in episodes:
        agents = ep.get("agents", [])
        crop_dusta_agent = next((a for a in agents if a.get("submissionId") == sub_id), None)
        opp_agent = next((a for a in agents if a.get("submissionId") != sub_id), None)
        
        ep_info = {
            "episode_id": ep["id"],
            "create_time": ep.get("createTime"),
            "state": ep.get("state"),
            "crop_dusta_reward": crop_dusta_agent.get("reward") if crop_dusta_agent else None,
            "crop_dusta_score": crop_dusta_agent.get("updatedScore") if crop_dusta_agent else None,
            "crop_dusta_index": crop_dusta_agent.get("index", 0) if crop_dusta_agent else 0,
            "opp_submission_id": opp_agent.get("submissionId") if opp_agent else None,
            "opp_team_id": opp_agent.get("teamId") if opp_agent else None,
            "opp_team_name": teams.get(opp_agent.get("teamId")) if opp_agent else "Unknown",
            "opp_reward": opp_agent.get("reward") if opp_agent else None,
            "opp_score": opp_agent.get("updatedScore") if opp_agent else None,
        }
        all_episodes.append(ep_info)

# Sort by create_time descending
all_episodes.sort(key=lambda x: x.get("create_time", ""), reverse=True)
print(f"\nTotal collected episodes: {len(all_episodes)}")
print("\nTop 10 most recent episodes:")
for ep in all_episodes[:10]:
    print(f"Episode {ep['episode_id']} ({ep['create_time'][:19]}): Crop Dusta (score {ep['crop_dusta_score']:.1f}, reward {ep['crop_dusta_reward']}) vs {ep['opp_team_name']} (score {ep['opp_score']:.1f}, reward {ep['opp_reward']})")

# Save episode catalog to json
with open("d:/website project/kaggri ox/replays/crop_dusta_episodes_index.json", "w") as f:
    json.dump(all_episodes, f, indent=2)
print("\nSaved index to replays/crop_dusta_episodes_index.json")
