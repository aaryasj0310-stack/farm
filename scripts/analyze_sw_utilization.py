"""Analyze SW tile utilization by baseline after early purchase.

Measures:
- Tiles owned (25 tiles, or 24 excluding shop)
- Tiles planted on D+0, D+1, D+3, D+5
- Tiles watered on D+0, D+1, D+3, D+5
- Effective utilization percentage: planted / 24 tiles
"""

import json
import os
import sys

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _AGENT_DIR)
for sub in ["state", "strategy", "execution", "market", "economy"]:
    p = os.path.join(_AGENT_DIR, sub)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

from kaggle_environments import make
from agent.main import agent as our_agent
from agent.config import set_sw_forward_architecture_mode
from agent.state.observation_parser import parse_observation

def analyze_seed_sw_utilization(seed=96501, seat=0):
    set_sw_forward_architecture_mode("OFF")
    
    sw_tiles = [(x, y) for y in range(5, 10) for x in range(0, 5) if (x, y) != (4, 5)]
    total_sw_tiles = len(sw_tiles) # 24
    
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    
    p0 = our_agent if seat == 0 else "pass"
    p1 = "pass" if seat == 0 else our_agent
    
    env.run([p0, p1])
    steps = env.steps
    
    purchase_day = None
    daily_stats = {}
    
    for s_idx, step in enumerate(steps):
        agent_state = step[seat]
        obs = agent_state.get("observation", {})
        ctx = parse_observation(obs)
        if not ctx:
            continue
        
        day = ctx["day"]
        hour = ctx["hour"]
        farm = ctx["farm"]
        unlocked = farm.unlocked
        
        if ("SW" in unlocked or 3 in unlocked) and purchase_day is None:
            purchase_day = day
            
        if purchase_day is not None and hour == 12: # Midday sample
            planted_sw = 0
            watered_sw = 0
            for (x, y) in sw_tiles:
                t = farm.tile_at((x, y))
                if t and (t.is_plant or t.crop):
                    planted_sw += 1
                    if t.watered_today:
                        watered_sw += 1
            daily_stats[day] = {
                "day": day,
                "days_since_purchase": day - purchase_day,
                "planted_sw": planted_sw,
                "watered_sw": watered_sw,
                "utilization_pct": round(planted_sw / total_sw_tiles * 100, 1),
            }
            
    return purchase_day, daily_stats

if __name__ == "__main__":
    print("=" * 70)
    print("BASELINE SW TILE UTILIZATION AFTER EARLY PURCHASE")
    print("=" * 70)
    for seed in [96501, 96502, 96503]:
        p_day, stats = analyze_seed_sw_utilization(seed, 0)
        print(f"\nSeed {seed} -> Purchase Day: Day {p_day}")
        for d, st in sorted(stats.items()):
            rel = st["days_since_purchase"]
            if rel in (0, 1, 2, 3, 5, 7, 10):
                print(f"  Day {d:02d} (D+{rel:02d}): Planted: {st['planted_sw']:2d}/24 ({st['utilization_pct']:5.1f}%) | Watered: {st['watered_sw']:2d}")
