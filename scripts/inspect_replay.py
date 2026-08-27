import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "replays/land buy roi based/100976069.json"
with open(path) as f:
    data = json.load(f)

step0 = data["steps"][0][0]
obs = step0["observation"]
print("Observation keys:", list(obs.keys()))
print("farms type:", type(obs["farms"]))

farms = obs["farms"]
if isinstance(farms, dict):
    for k, v in farms.items():
        print(f"  {k}: {type(v)}")
        if isinstance(v, dict):
            print(f"    keys: {list(v.keys())[:10]}")
elif isinstance(farms, list):
    for i, v in enumerate(farms):
        if isinstance(v, dict):
            print(f"  [{i}]: keys={list(v.keys())[:10]}")
        else:
            print(f"  [{i}]: {type(v)}")

# Check how observation_parser processes it
print("\n--- Info ---")
print("player:", obs.get("player"))
print("day:", obs.get("day"))
print("hour:", obs.get("hour"))

# Check the opponent info
info = step0.get("info", {})
print("\ninfo keys:", list(info.keys())[:10] if isinstance(info, dict) else type(info))

# Check rewards
print("reward:", step0.get("reward"))
print("status:", step0.get("status"))
