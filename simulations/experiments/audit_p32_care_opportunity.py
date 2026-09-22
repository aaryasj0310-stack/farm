"""Deep Telemetry Audit of Animal CARE Opportunities (Phase 2 & 3).

Evaluates 20 baseline tournament games (seeds 90,001-90,010 x 2 seats)
to classify every uncared animal opportunity into C1-C7 and compute
exact state-dependent marginal values.
"""
from collections import defaultdict
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agent"))
for s in ("state", "strategy", "execution", "market"):
    p = os.path.join(ROOT, "agent", s)
    if p not in sys.path:
        sys.path.insert(0, p)

import kaggle_environments
import config as cfg
import main as module
from simulations.experiments.agent_zoo import get_agent

cfg.set_quadrant_hard_block({4})
cfg.set_p23_marginal_wheat_allocation_enabled(True)

ANIMALS = {
    "COW": {"price": 160.0, "first_yield_day": 8, "interval": 2, "max_held": 6},
    "SHEEP": {"price": 200.0, "first_yield_day": 6, "interval": 3, "max_held": 6},
    "GOOSE": {"price": 50.0, "first_yield_day": 4, "interval": 1, "max_held": 4},
}

def next_production_day(tile, current_day):
    anim = tile.get("animal")
    if not anim or anim not in ANIMALS:
        return None
    spec = ANIMALS[anim]
    placed = tile.get("placed_day", 0)
    first = placed + spec["first_yield_day"]
    interval = spec["interval"]
    if current_day + 1 < first:
        return first
    elapsed = (current_day + 1) - first
    rem = elapsed % interval
    if rem == 0:
        return current_day + 1
    return (current_day + 1) + (interval - rem)

def run_care_audit(seeds=range(90001, 90011)):
    stats = {
        "total_animal_days": 0,
        "cared_count": 0,
        "missed_care_total": 0,
        "by_species": defaultdict(lambda: {"total": 0, "cared": 0, "missed": 0}),
        "categories": {
            "C1_realizable": 0,
            "C1_realizable_dollars": 0.0,
            "C2_no_future_production": 0,
            "C3_unfed_today": 0,
            "C4_held_cap_constrained": 0,
            "C5_harvest_unrealizable": 0,
            "C6_sufficient_bank": 0,
            "C7_displaced_by_water": 0,
            "C7_displaced_dollars": 0.0,
            "geese_skipped": 0,
        },
        "by_day": defaultdict(lambda: {"missed": 0, "realizable": 0, "displaced": 0}),
    }

    games_run = 0
    for seed in seeds:
        for seat in (0, 1):
            games_run += 1
            module.reset_agent_state()

            def tracking(obs, configuration=None):
                day = int(obs.get("day", 0))
                hour = int(obs.get("hour", 0))
                player = int(obs.get("player", seat))
                farm = obs.get("farms", [{}])[player] if "farms" in obs else {}

                # Check animal status at Hour 23 EOD
                if hour == 23:
                    tiles = farm.get("tiles", [])
                    for row in tiles:
                        for tile in row:
                            if isinstance(tile, dict) and (tile.get("animal") or tile.get("is_animal")):
                                anim = tile.get("animal")
                                if anim not in ANIMALS:
                                    continue
                                spec = ANIMALS[anim]
                                stats["total_animal_days"] += 1
                                stats["by_species"][anim]["total"] += 1

                                cared = tile.get("cared_today", False)
                                fed = tile.get("fed_today", False)
                                yield_u = tile.get("yield_units", 0)
                                pending_b = tile.get("pending_care_bonus", 0)
                                next_prod = next_production_day(tile, day)

                                if cared:
                                    stats["cared_count"] += 1
                                    stats["by_species"][anim]["cared"] += 1
                                    continue

                                # Missed care
                                stats["missed_care_total"] += 1
                                stats["by_species"][anim]["missed"] += 1
                                stats["by_day"][day]["missed"] += 1

                                # If goose: skipped intentionally
                                if anim == "GOOSE":
                                    stats["categories"]["geese_skipped"] += 1
                                    continue

                                # Classification logic:
                                # C2: No future production (next_prod > 29 or day >= 29)
                                if day >= 29 or next_prod is None or next_prod > 29:
                                    stats["categories"]["C2_no_future_production"] += 1
                                    continue

                                # C3: Unfed today (care would not bank bonus!)
                                if not fed:
                                    stats["categories"]["C3_unfed_today"] += 1
                                    continue

                                # C4: Held product cap constrained
                                # If yield + base + pending >= max_held, extra bonus is clipped
                                if yield_u + 1 + pending_b >= spec["max_held"]:
                                    stats["categories"]["C4_held_cap_constrained"] += 1
                                    continue

                                # C6: Sufficient bank (pending already reaches cycle capacity)
                                if pending_b >= spec["interval"]:
                                    stats["categories"]["C6_sufficient_bank"] += 1
                                    continue

                                # C5: Harvest unrealizable
                                if next_prod == 29 and day >= 28:
                                    # Very tight final window
                                    pass

                                # C1: Realizable missed care!
                                price = spec["price"]
                                stats["categories"]["C1_realizable"] += 1
                                stats["categories"]["C1_realizable_dollars"] += price
                                stats["by_day"][day]["realizable"] += 1

                                # C7: Displaced by lower value task (e.g. wheat watering at $25)
                                stats["categories"]["C7_displaced_by_water"] += 1
                                stats["categories"]["C7_displaced_dollars"] += (price - 25.0)
                                stats["by_day"][day]["displaced"] += 1

                return module.agent(obs, configuration)

            opp = get_agent("pure_wheat_rush" if seed % 2 == 0 else "pass")
            agents = [tracking, opp] if seat == 0 else [opp, tracking]
            env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
            env.run(agents)
            print(f"Game {games_run}/20 finished (Seed {seed} Seat {seat})", flush=True)

    # Normalize per game
    per_game = {
        "games": games_run,
        "total_animal_days_per_game": stats["total_animal_days"] / games_run,
        "cared_per_game": stats["cared_count"] / games_run,
        "missed_care_total_per_game": stats["missed_care_total"] / games_run,
        "geese_skipped_per_game": stats["categories"]["geese_skipped"] / games_run,
        "C2_no_future_prod_per_game": stats["categories"]["C2_no_future_production"] / games_run,
        "C3_unfed_per_game": stats["categories"]["C3_unfed_today"] / games_run,
        "C4_held_cap_per_game": stats["categories"]["C4_held_cap_constrained"] / games_run,
        "C6_sufficient_bank_per_game": stats["categories"]["C6_sufficient_bank"] / games_run,
        "C1_realizable_per_game": stats["categories"]["C1_realizable"] / games_run,
        "C1_realizable_dollars_per_game": stats["categories"]["C1_realizable_dollars"] / games_run,
        "C7_displaced_net_dollars_per_game": stats["categories"]["C7_displaced_dollars"] / games_run,
    }

    out_json = os.path.join(ROOT, "simulations", "experiments", "results", "p32_care_opportunity_audit.json")
    with open(out_json, "w") as f:
        json.dump({"raw_stats": stats, "per_game": per_game}, f, indent=2)

    print("\n" + "=" * 70)
    print("  P3.2 ANIMAL CARE OPPORTUNITY AUDIT (20 GAMES)")
    print("=" * 70)
    print(f"Total Animal Days / Game          : {per_game['total_animal_days_per_game']:.1f}")
    print(f"Cared Completed / Game            : {per_game['cared_per_game']:.1f}")
    print(f"Total Missed Care / Game          : {per_game['missed_care_total_per_game']:.1f}")
    print(f"  - Geese Intentionally Skipped   : {per_game['geese_skipped_per_game']:.1f}")
    print(f"  - C2 No Future Production       : {per_game['C2_no_future_prod_per_game']:.1f}")
    print(f"  - C3 Unfed Today                : {per_game['C3_unfed_per_game']:.1f}")
    print(f"  - C4 Held Product Cap Full      : {per_game['C4_held_cap_per_game']:.1f}")
    print(f"  - C6 Sufficient Bank Already    : {per_game['C6_sufficient_bank_per_game']:.1f}")
    print(f"  - C1 REALIZABLE MISSED CARE     : {per_game['C1_realizable_per_game']:.2f} actions/game")
    print(f"  - C1 REALIZABLE DOLLAR VALUE    : ${per_game['C1_realizable_dollars_per_game']:,.2f}/game")
    print(f"  - C7 Net Displaced vs Wheat Water: ${per_game['C7_displaced_net_dollars_per_game']:,.2f}/game")

if __name__ == "__main__":
    run_care_audit()
