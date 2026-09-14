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

from kaggle_environments import make
from simulations.experiments.agent_zoo import get_agent
import main as agent_module
from strategy.marginal_livestock_valuator import (
    estimate_realized_marginal_animal_value,
    derive_opponent_committed_livestock_supply,
)
from state.observation_parser import parse_observation
import config

# Let's inspect Seat 0 and Seat 1 for seed 100 and 101
for seed in [100, 101]:
    for seat in [0, 1]:
        print(f"\n==================== SEED {seed} SEAT {seat} ====================")
        opp = get_agent("full_production_agent")
        players = [agent_module.agent, opp] if seat == 0 else [opp, agent_module.agent]
        env = make("kaggriculture", configuration={"randomSeed": seed}, debug=False)
        steps = env.run(players)
        
        our_idx = seat
        opp_idx = 1 - seat
        
        # Check opponent final animals
        final_obs = steps[-1][our_idx]["observation"]
        opp_tiles = final_obs["farms"][opp_idx]["tiles"]
        opp_final_animals = [t["animal"] for row in opp_tiles for t in row if isinstance(t, dict) and "animal" in t]
        print(f"Opponent final animals: {opp_final_animals}")

        # Check turn by turn when opp buys animals
        for s_idx in range(0, min(len(steps), 288), 24): # Day 0 to 11 at H0
            obs = steps[s_idx][our_idx]["observation"]
            day = obs["day"]
            hour = obs["hour"]
            opp_t = obs["farms"][opp_idx]["tiles"]
            opp_animals = [t["animal"] for row in opp_t for t in row if isinstance(t, dict) and "animal" in t]
            
            parsed = parse_observation(dict(obs, player=our_idx))
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

            gap_l0 = eval_l0_c["net_realized_value"] - eval_l0_s["net_realized_value"]
            gap_l1 = eval_l1_c["net_realized_value"] - eval_l1_s["net_realized_value"]

            if opp_animals or abs(gap_l1 - gap_l0) > 1.0:
                print(f"Day {day:2d}: Opp: {opp_animals} | Our: {our_counts} | L0 Gap (Cow-Sheep): ${gap_l0:+.1f} | L1 Gap: ${gap_l1:+.1f} | Opp Milk={sum(opp_supply.get('MILK', {}).values()):.1f}u, Wool={sum(opp_supply.get('WOOL', {}).values()):.1f}u, Egg={sum(opp_supply.get('EGG', {}).values()):.1f}u")
