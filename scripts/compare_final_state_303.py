"""Compare v5.9 vs v5.8 on seed 303 - final farm state."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))
sys.path.insert(0, 'submission_v5_8')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission_v5_8', sub))

import kaggle_environments
import importlib.util

LOG = open("scripts/v59_final_state_303.txt", "w", encoding="utf-8")

for label, path in [("v5.9", "submission/main.py"), ("v5.8", "submission_v5_8/main.py")]:
    spec = importlib.util.spec_from_file_location("agent", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    
    env = kaggle_environments.make("kaggriculture", configuration={"seed": 303, "loglevel": "ERROR"})
    env.run([mod.agent, "random"])
    
    obs = env.steps[-1][0].observation
    farm = obs["farms"][0]
    tiles = farm["tiles"]
    
    planted = {}
    for row in tiles:
        for t in row:
            if t and isinstance(t, dict):
                kind = t.get("kind", "?")
                if kind not in ("LOCKED", None):
                    planted[kind] = planted.get(kind, 0) + 1
    
    animals = farm.get("animals", {})
    animal_counts = {}
    for a in animals:
        atype = a.get("type", "?")
        animal_counts[atype] = animal_counts.get(atype, 0) + 1
    
    seeds = farm.get("seed_slots", {})
    money = farm["money"]
    score = obs.get("farms", [{}])[0].get("money", 0)
    
    print(f"\n=== {label} (seed 303) ===", file=LOG, flush=True)
    print(f"Money: ${money:,.0f}", file=LOG, flush=True)
    print(f"Unlocked: {farm.get('unlocked_quadrants', [])}", file=LOG, flush=True)
    print(f"Tiles planted: {planted}", file=LOG, flush=True)
    print(f"Animals: {animal_counts}", file=LOG, flush=True)
    print(f"Seeds remaining: {seeds}", file=LOG, flush=True)

LOG.close()
