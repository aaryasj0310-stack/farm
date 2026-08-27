"""Quick test: verify replay opponent is actually being used."""
import json, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
_agent_dir = str(Path(__file__).resolve().parent.parent / "agent")
for _sub in ("state", "strategy", "execution", "market"):
    sys.path.insert(0, os.path.join(_agent_dir, _sub))

import kaggle_environments

# Load replay
with open("replays/land buy roi based/100976069.json") as f:
    data = json.load(f)

opp_actions = []
for step in data["steps"]:
    if isinstance(step, list) and len(step) >= 2:
        p1 = step[1]
        act = p1.get("action", ["PASS"]) if isinstance(p1, dict) else ["PASS"]
        opp_actions.append(act)
    else:
        opp_actions.append(["PASS"])

print(f"Loaded {len(opp_actions)} opponent actions")
print(f"First 5: {opp_actions[:5]}")

_counter = [0]
def replay_agent(obs, config=None):
    i = min(_counter[0], len(opp_actions) - 1)
    _counter[0] += 1
    raw = opp_actions[i]
    result = {"farmer": ["PASS"], "hands": [], "market": []}
    if isinstance(raw, list) and len(raw) > 0:
        farmer_a = raw[0]
        result["farmer"] = [farmer_a] if isinstance(farmer_a, str) else ["PASS"]
        hands_data = []
        if obs and "farms" in obs:
            farms = obs["farms"]
            if isinstance(farms, list) and len(farms) > 0:
                hands_data = farms[0].get("hands", []) if isinstance(farms[0], dict) else []
        n_hands = len(hands_data)
        for hi in range(n_hands):
            if hi + 1 < len(raw):
                ha = raw[hi + 1]
                result["hands"].append([ha] if isinstance(ha, str) else ["PASS"])
            else:
                result["hands"].append(["PASS"])
    if _counter[0] <= 3:
        print(f"  Step {_counter[0]}: obs.player={obs.get('player')}, returning {result}")
    return result

def null_agent(obs, config=None):
    return {"farmer": ["PASS"], "hands": [], "market": []}

# Test: run replay_agent vs null_agent
env = kaggle_environments.make("kaggriculture", configuration={"seed": 11, "loglevel": "ERROR"})
env.run([null_agent, replay_agent])
p0 = env.state[0].get("reward", 0)
p1 = env.state[1].get("reward", 0)
print(f"\nnull_agent (P0) vs replay_agent (P1): P0=${p0}, P1=${p1}")
print(f"Replay agent called {_counter[0]} times")

# Also check: does env.run call agent for both players?
_counter2 = [0]
def counting_agent(obs, config=None):
    _counter2[0] += 1
    return {"farmer": ["PASS"], "hands": [], "market": []}

env2 = kaggle_environments.make("kaggriculture", configuration={"seed": 11, "loglevel": "ERROR"})
env2.run([counting_agent, counting_agent])
print(f"\nTwo counting agents: P0 called {_counter2[0]} times (shared counter)")
print(f"P0 reward: {env2.state[0].get('reward', 0)}")
print(f"P1 reward: {env2.state[1].get('reward', 0)}")
