"""Phase 1 Audit: Deep Inspection of L1 Divergence against full_production_agent.

Inspects matches from seeds 100-109 against full_production_agent where L1 substituted
Cow -> Sheep or made different livestock decisions.

Logs and reports:
- day / hour
- candidate species evaluated
- L0 Cow, Sheep, Goose marginal values
- visible opponent animals & structures
- opponent committed Milk/Wool/Egg production added
- commitment-aware (L1) Cow, Sheep, Goose values
- projected Milk, Wool, Egg inventory/price paths
- town drain by product, shop contributions, remaining days, feed cost
- exact decision changed and resulting gap
"""

import os
import sys
import json
from typing import Dict, List, Any

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
import config
from strategy.marginal_livestock_valuator import (
    estimate_realized_marginal_animal_value,
    derive_opponent_committed_livestock_supply,
)
from state.observation_parser import parse_observation, FarmView
from config import ANIMALS, CROPS


def audit_match(seed: int, seat: int = 0):
    from simulations.experiments.agent_zoo import get_agent
    import main as agent_module

    opp_name = "full_production_agent"
    opp_callable = get_agent(opp_name)

    env = make("kaggriculture", configuration={"randomSeed": seed}, debug=False)
    
    # We want to trace each turn where dynamic herd plan or live purchase evaluates animals
    # We will step through the game and log the exact evaluations under L0 vs L1
    players = [agent_module.agent, opp_callable] if seat == 0 else [opp_callable, agent_module.agent]
    our_idx = seat
    opp_idx = 1 - seat

    # Run step by step
    env.reset()
    
    audit_events = []

    # Reset agent state
    config.set_sw_experiment_arm("ArmA")
    config.set_opponent_intelligence_mode("O0_SHADOW")
    agent_module.reset_agent_state()

    done = False
    step_num = 0

    while not done:
        state = env.state[0]
        obs = state.observation
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)

        # We are especially interested in Hour 0 when livestock planning happens (Days 0-11)
        if hour == 0 and day < 12:
            obs_copy = dict(obs)
            obs_copy["player"] = our_idx
            parsed = parse_observation(obs_copy)
            farm = parsed["farm"]
            opp_farm = parsed["opponent_farm"]
            town_obj = parsed.get("town")
            town_shops = list(getattr(town_obj, "unlocked_shops", []))
            market_obj = parsed.get("market")
            market_inv = dict(getattr(market_obj, "inventory", {}))

            # Count our current animals
            our_counts = {}
            for t in farm.iter_tiles():
                if t.is_animal:
                    our_counts[t.animal] = our_counts.get(t.animal, 0) + 1

            # Count opp animals and structures
            opp_counts = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
            opp_structures = {"PASTURE": 0, "COOP": 0}
            for t in opp_farm.iter_tiles():
                if t.is_animal and t.animal in opp_counts:
                    opp_counts[t.animal] += 1
                elif getattr(t, "kind", "") in opp_structures:
                    opp_structures[t.kind] += 1

            # Check if opponent has any animals
            opp_has_livestock = sum(opp_counts.values()) > 0 or sum(opp_structures.values()) > 0

            # Evaluate L0 (no opponent supply)
            eval_l0_c = estimate_realized_marginal_animal_value(
                species="COW", day=day, current_animals=our_counts,
                market_inventory=market_inv, empty_pastures=1, town_shops=town_shops,
                opponent_committed_supply=None
            )
            eval_l0_s = estimate_realized_marginal_animal_value(
                species="SHEEP", day=day, current_animals=our_counts,
                market_inventory=market_inv, empty_pastures=1, town_shops=town_shops,
                opponent_committed_supply=None
            )
            eval_l0_g = estimate_realized_marginal_animal_value(
                species="GOOSE", day=day, current_animals=our_counts,
                market_inventory=market_inv, empty_pastures=1, town_shops=town_shops,
                opponent_committed_supply=None
            )

            # Evaluate L1 (with BASE opponent committed supply)
            opp_supply = derive_opponent_committed_livestock_supply(opp_farm, day, scenario="BASE")
            eval_l1_c = estimate_realized_marginal_animal_value(
                species="COW", day=day, current_animals=our_counts,
                market_inventory=market_inv, empty_pastures=1, town_shops=town_shops,
                opponent_committed_supply=opp_supply.get("MILK")
            )
            eval_l1_s = estimate_realized_marginal_animal_value(
                species="SHEEP", day=day, current_animals=our_counts,
                market_inventory=market_inv, empty_pastures=1, town_shops=town_shops,
                opponent_committed_supply=opp_supply.get("WOOL")
            )
            eval_l1_g = estimate_realized_marginal_animal_value(
                species="GOOSE", day=day, current_animals=our_counts,
                market_inventory=market_inv, empty_pastures=1, town_shops=town_shops,
                opponent_committed_supply=opp_supply.get("EGG")
            )

            l0_best_sp = "COW" if eval_l0_c["net_realized_value"] >= eval_l0_s["net_realized_value"] else "SHEEP"
            l1_best_sp = "COW" if eval_l1_c["net_realized_value"] >= eval_l1_s["net_realized_value"] else "SHEEP"

            # Check if species preference flipped
            preference_flipped = (l0_best_sp != l1_best_sp)

            if preference_flipped or (opp_has_livestock and abs(eval_l1_c["net_realized_value"] - eval_l0_c["net_realized_value"]) > 50):
                audit_events.append({
                    "day": day,
                    "hour": hour,
                    "our_counts": dict(our_counts),
                    "opp_counts": dict(opp_counts),
                    "opp_structures": dict(opp_structures),
                    "opp_milk_supply_added": round(sum(opp_supply.get("MILK", {}).values()), 1),
                    "opp_wool_supply_added": round(sum(opp_supply.get("WOOL", {}).values()), 1),
                    "l0_cow_val": eval_l0_c["net_realized_value"],
                    "l0_sheep_val": eval_l0_s["net_realized_value"],
                    "l0_goose_val": eval_l0_g["net_realized_value"],
                    "l0_gap": round(eval_l0_c["net_realized_value"] - eval_l0_s["net_realized_value"], 1),
                    "l0_best": l0_best_sp,
                    "l1_cow_val": eval_l1_c["net_realized_value"],
                    "l1_sheep_val": eval_l1_s["net_realized_value"],
                    "l1_goose_val": eval_l1_g["net_realized_value"],
                    "l1_gap": round(eval_l1_c["net_realized_value"] - eval_l1_s["net_realized_value"], 1),
                    "l1_best": l1_best_sp,
                    "preference_flipped": preference_flipped,
                    "market_inv": market_inv,
                    "town_shops": town_shops,
                    "feed_cost_cow": eval_l0_c["feed_cost"],
                    "feed_cost_sheep": eval_l0_s["feed_cost"],
                })

        # Step environment
        actions = []
        for i, p in enumerate(players):
            act = p(env.state[i].observation)
            actions.append(act)

        env.step(actions)
        done = env.state[0].status != "ACTIVE"
        step_num += 1

    return audit_events


def run_audit():
    print("=== Running Phase 1 Audit: L1 Divergence against full_production_agent ===")
    all_divergences = []
    # Audit across seeds 100, 101, 102, 105, 107
    for s in [100, 101, 102, 105, 107]:
        for seat in [0, 1]:
            events = audit_match(seed=s, seat=seat)
            flipped = [e for e in events if e["preference_flipped"]]
            print(f"Seed {s} Seat {seat}: {len(events)} livestock audit points, {len(flipped)} preference flips")
            for f in flipped:
                f["seed"] = s
                f["seat"] = seat
                all_divergences.append(f)
                print(f"  Day {f['day']}: L0 picked {f['l0_best']} (gap ${f['l0_gap']}), L1 flipped to {f['l1_best']} (gap ${f['l1_gap']}) | Opp animals: {f['opp_counts']} | Opp Milk supply: {f['opp_milk_supply_added']}u")

    out_path = os.path.join(PROJECT_ROOT, "simulations", "experiments", "results", "l1_divergence_audit.json")
    with open(out_path, "w") as fp:
        json.dump(all_divergences, fp, indent=2)
    print(f"\nAudit completed. Saved {len(all_divergences)} flipped decision records to: {out_path}")


if __name__ == "__main__":
    run_audit()
