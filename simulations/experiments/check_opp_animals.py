from kaggle_environments import make
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)
for _sub in ("state", "strategy", "execution", "market"):
    _sub_path = os.path.join(AGENT_DIR, _sub)
    if _sub_path not in sys.path:
        sys.path.insert(0, _sub_path)

from simulations.experiments.agent_zoo import get_agent
import main as agent_module
from strategy.marginal_livestock_valuator import (
    estimate_realized_marginal_animal_value,
    derive_opponent_committed_livestock_supply,
)
from state.observation_parser import parse_observation
import config

opp = get_agent("full_production_agent")
env = make("kaggriculture", configuration={"randomSeed": 100}, debug=False)
steps = env.run([agent_module.agent, opp])

print("Total steps:", len(steps))
for s_idx, step in enumerate(steps):
    obs = step[0]["observation"]
    day = obs["day"]
    hour = obs["hour"]
    if hour == 0:
        opp_tiles = obs["farms"][1]["tiles"]
        opp_animals = [t["animal"] for row in opp_tiles for t in row if isinstance(t, dict) and "animal" in t]
        opp_structures = [t.get("kind") for row in opp_tiles for t in row if isinstance(t, dict) and t.get("kind") in ("PASTURE", "COOP")]
        
        parsed = parse_observation(obs)
        opp_farm = parsed["opponent_farm"]
        farm = parsed["farm"]
        our_counts = {}
        for t in farm.iter_tiles():
            if t.is_animal:
                our_counts[t.animal] = our_counts.get(t.animal, 0) + 1

        town_obj = parsed.get("town")
        town_shops = list(getattr(town_obj, "unlocked_shops", []))
        market_obj = parsed.get("market")
        market_inv = dict(getattr(market_obj, "inventory", {}))

        eval_l0_c = estimate_realized_marginal_animal_value("COW", day, our_counts, market_inv, empty_pastures=1, town_shops=town_shops)
        eval_l0_s = estimate_realized_marginal_animal_value("SHEEP", day, our_counts, market_inv, empty_pastures=1, town_shops=town_shops)

        opp_supply = derive_opponent_committed_livestock_supply(opp_farm, day, "BASE")
        eval_l1_c = estimate_realized_marginal_animal_value("COW", day, our_counts, market_inv, empty_pastures=1, town_shops=town_shops, opponent_committed_supply=opp_supply.get("MILK"))
        eval_l1_s = estimate_realized_marginal_animal_value("SHEEP", day, our_counts, market_inv, empty_pastures=1, town_shops=town_shops, opponent_committed_supply=opp_supply.get("WOOL"))

        l0_c = eval_l0_c["net_realized_value"]
        l0_s = eval_l0_s["net_realized_value"]
        l1_c = eval_l1_c["net_realized_value"]
        l1_s = eval_l1_s["net_realized_value"]

        print(f"Day {day:2d}: Opp animals: {opp_animals}, Opp structures: {opp_structures} | Our: {our_counts}")
        print(f"        L0: Cow=${l0_c:.1f}, Sheep=${l0_s:.1f} (gap={l0_c-l0_s:+.1f})")
        print(f"        L1: Cow=${l1_c:.1f}, Sheep=${l1_s:.1f} (gap={l1_c-l1_s:+.1f}) | Opp Milk={sum(opp_supply.get('MILK', {}).values()):.1f}u")
