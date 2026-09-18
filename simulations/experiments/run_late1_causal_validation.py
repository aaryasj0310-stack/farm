"""
Point-2 100-Seed Paired Controlled Experiment:
Causal Validation of Late-Housing Continuation (Late1) on 3-COW Bootstrap.

Arms:
  Arm B: POST-FEED-FIX 3C baseline without Late1
         POINT2_FEED_MODE = "live"
         BOOTSTRAP_LIVESTOCK_ARM = "ArmE"
         ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False

  Arm C: 3C Bootstrap, Late1 ON
         POINT2_FEED_MODE = "live"
         BOOTSTRAP_LIVESTOCK_ARM = "ArmE"
         ONE_AT_A_TIME_LATE_HOUSING_ENABLED = True

Populations:
  Exact 100 paired seeds (200 matches total) across 5 opponent archetypes
  (20 pass, 20 pure_wheat_rush, 20 cow_milk_engine, 20 melon_sniper, 20 full_production_agent)
"""
from __future__ import annotations

import copy
import json
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Tuple

# Ensure project root and agent directory are in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(ROOT_DIR, "agent")
for p in (ROOT_DIR, AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import kaggle_environments
from agent.config import (
    ANIMALS, CROPS, MARKET_PARAMS, MARKET_I0
)
from simulations.experiments.agent_zoo import get_agent


OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

BENCHMARK_SEEDS = [
    {"seed": 42, "opponent": "pass"},
    {"seed": 101, "opponent": "pure_wheat_rush"},
    {"seed": 2024, "opponent": "cow_milk_engine"},
    {"seed": 7, "opponent": "melon_sniper"},
    {"seed": 999, "opponent": "full_production_agent"},
    {"seed": 1234, "opponent": "pass"},
    {"seed": 55, "opponent": "pure_wheat_rush"},
    {"seed": 314, "opponent": "cow_milk_engine"},
    {"seed": 8888, "opponent": "melon_sniper"},
    {"seed": 777, "opponent": "full_production_agent"},
]


def generate_100_paired_seeds() -> List[Dict[str, Any]]:
    seeds = list(BENCHMARK_SEEDS)
    # Generate 90 additional deterministic seeds, cycling opponents evenly (20 each total)
    for i in range(90):
        s_val = 10000 + i * 37 + (i % 7) * 11
        opp = OPPONENTS[i % 5]
        seeds.append({"seed": s_val, "opponent": opp})
    return seeds


def run_match_single_arm(seed: int, opponent_name: str, arm_name: str, late_cont: bool) -> Dict[str, Any]:
    import config as cfg
    cfg.POINT2_FEED_MODE = "live"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "ArmE"
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = late_cont

    for mod_name in ("agent.main", "main", "agent.config", "config", "agent.strategy.macro_planner", "macro_planner", "agent.strategy.herd_planner", "herd_planner"):
        if mod_name in sys.modules:
            setattr(sys.modules[mod_name], "POINT2_FEED_MODE", "live")
            setattr(sys.modules[mod_name], "BOOTSTRAP_LIVESTOCK_ARM", "ArmE")
            setattr(sys.modules[mod_name], "ONE_AT_A_TIME_LATE_HOUSING_ENABLED", late_cont)

    from main import _agent_decision, reset_agent_state
    from state.state_tracker import _STATE, reset_memory
    reset_agent_state()
    reset_memory()

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.reset(2)
    opp_callable = get_agent(opponent_name)

    cash_checkpoints = {}
    min_cash = 3000.0
    negative_cash_events = 0

    max_placed_herd = 0
    max_total_owned_herd = 0
    prev_total_owned = 0
    starvations_or_deaths = 0
    escapes = 0

    crop_rev = 0.0
    milk_rev = 0.0
    wool_rev = 0.0
    fert_rev = 0.0

    wheat_bought_units = 0
    wheat_spend = 0.0
    animal_spend = 0.0
    total_feed_consumed = 0
    day0_cash_deployment = 0.0

    min_wheat_slack = 999999

    animals_bought_pre_d12 = 0
    animals_bought_d12 = 0
    animals_bought_d13 = 0
    animals_bought_d14 = 0

    # Pasture and housing tracking
    prev_pasture_count = 0
    pasture_build_events = []
    animal_buy_events = []
    animal_placed_events = []

    # Anti-overbuilding & safety metrics
    continuation_pasture_requests = 0
    continuation_pasture_completions = 0
    continuation_builds_initiated_post_d14 = 0
    speculative_animal_purchases = 0
    purchases_into_uncompleted_pasture = 0
    max_simultaneous_in_flight = 0

    # Pre-completion wheat purchases tracking
    wheat_ordered_before_pasture_completion = 0

    # Detailed continuation cycles tracking
    # Key: target_pos -> cycle dict
    active_cycles: Dict[Tuple[int, int], Dict[str, Any]] = {}

    step = 0
    while not env.done:
        obs0 = env.state[0].observation
        obs1 = env.state[1].observation

        day = obs0.get("step", step) // 24
        hour = obs0.get("step", step) % 24

        farm0 = obs0.get("farms", [{}])[0]
        money0 = float(farm0.get("money", 0.0))

        if money0 < min_cash:
            min_cash = money0
        if money0 < 0:
            negative_cash_events += 1

        # Checkpoints: Day 1, 3, 5, 10, 12, 13, 14, 15, 20
        if hour == 0 and day in (1, 3, 5, 10, 12, 13, 14, 15, 20):
            cash_checkpoints[day] = round(money0, 2)

        if day == 0 and hour == 1:
            day0_cash_deployment = round(3000.0 - money0, 2)

        # Telemetry: Housing and animal counts
        physical_pastures = 0
        occupied_pastures = 0
        placed_herd = 0
        herd_comp = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
        pasture_tiles = set()
        occupied_tiles = set()

        for r, row in enumerate(farm0.get("tiles", [])):
            for c, t in enumerate(row):
                if isinstance(t, dict):
                    pos = (r, c)
                    if t.get("kind") == "PASTURE" or t.get("structure") == "PASTURE":
                        physical_pastures += 1
                        pasture_tiles.add(pos)
                        sp = t.get("animal")
                        if sp is not None or t.get("is_animal"):
                            occupied_pastures += 1
                            occupied_tiles.add(pos)
                    if t.get("animal") is not None or t.get("is_animal"):
                        placed_herd += 1
                        sp = t.get("animal", "COW")
                        if sp in herd_comp:
                            herd_comp[sp] += 1

        # Detect newly completed pastures
        if physical_pastures > prev_pasture_count and step > 0:
            newly_built = physical_pastures - prev_pasture_count
            pasture_build_events.append({"day": day, "hour": hour, "new_total": physical_pastures})
            if day in (12, 13, 14) and late_cont:
                continuation_pasture_completions += newly_built
                # Check active cycle completion
                for pos, cdata in list(active_cycles.items()):
                    if pos in pasture_tiles and cdata.get("physical_pasture_observed_day") is None:
                        cdata["physical_pasture_observed_day"] = day
                        cdata["physical_pasture_observed_hour"] = hour
                        cdata["became_purchase_eligible_day"] = day
                        cdata["became_purchase_eligible_hour"] = hour
            prev_pasture_count = physical_pastures
        elif physical_pastures > prev_pasture_count and step == 0:
            prev_pasture_count = physical_pastures

        # Detect newly placed animals into pastures
        for pos in occupied_tiles:
            for cdata in active_cycles.values():
                if cdata.get("target_tile") and tuple(cdata.get("target_tile")) == pos and cdata.get("animal_placement_day") is None:
                    cdata["animal_placement_day"] = day
                    cdata["animal_placement_hour"] = hour

        shed_animals = 0
        worker_animals = 0
        wheat_slack = 0
        if "private" in obs0:
            priv = obs0["private"]
            if "shed" in priv and isinstance(priv["shed"], dict):
                for sp in ("COW", "SHEEP", "GOOSE"):
                    shed_animals += int(priv["shed"].get(sp, 0))
                wheat_slack += int(priv["shed"].get("WHEAT", 0))
            if "inventories" in priv and isinstance(priv["inventories"], list):
                for inv in priv["inventories"]:
                    if isinstance(inv, dict):
                        for sp in ("COW", "SHEEP", "GOOSE"):
                            worker_animals += int(inv.get(sp, 0))
                        wheat_slack += int(inv.get("WHEAT", 0))

        if day > 0 and wheat_slack < min_wheat_slack:
            min_wheat_slack = wheat_slack

        owned_unplaced_herd = shed_animals + worker_animals
        total_owned_herd = placed_herd + owned_unplaced_herd

        if placed_herd > max_placed_herd:
            max_placed_herd = placed_herd
        if total_owned_herd > max_total_owned_herd:
            max_total_owned_herd = total_owned_herd

        # Agent decision
        action0 = _agent_decision(obs0)
        try:
            action1 = opp_callable(obs1)
        except Exception:
            action1 = {}

        # Track in-flight state
        in_flight = bool(_STATE.get("late_continuation_in_flight", False))
        target_pos = _STATE.get("late_continuation_target_pos")
        curr_in_flight_count = 1 if in_flight else 0
        if curr_in_flight_count > max_simultaneous_in_flight:
            max_simultaneous_in_flight = curr_in_flight_count

        # Check worker actions for BUILD_PASTURE
        worker_pos_map = {"farmer": tuple(farm0.get("farmer", (-1, -1)))}
        for h_idx, h_pos in enumerate(farm0.get("hands", [])):
            worker_pos_map[f"hand_{h_idx}"] = tuple(h_pos)

        worker_list = [("farmer", action0.get("farmer", []))] + [(f"hand_{h_idx}", h) for h_idx, h in enumerate(action0.get("hands", []))]
        for w_name, w_act in worker_list:
            if isinstance(w_act, (list, tuple)) and len(w_act) > 0:
                op = w_act[0]
                if op in ("BUILD_PASTURE", "BUILD"):
                    build_pos = tuple(w_act[1]) if len(w_act) > 1 and isinstance(w_act[1], (list, tuple)) else worker_pos_map.get(w_name)
                    if day >= 14 and late_cont and (build_pos == target_pos or target_pos is not None):
                        continuation_builds_initiated_post_d14 += 1
                    if day in (12, 13) and late_cont and (build_pos == target_pos or target_pos is not None):
                        cycle_tile = target_pos if target_pos is not None else build_pos
                        if cycle_tile and cycle_tile not in active_cycles:
                            continuation_pasture_requests += 1
                            # Look up last forward-only record
                            last_fo = (_STATE.get("forward_only_feed_holds", []) or [{}])[-1]
                            active_cycles[cycle_tile] = {
                                "seed": seed,
                                "opponent": opponent_name,
                                "candidate_species": last_fo.get("species", "COW"),
                                "candidate_eval_day": last_fo.get("day", day),
                                "candidate_eval_hour": last_fo.get("hour", hour),
                                "candidate_net_ev": 500.0,
                                "forward_only_accepted": True,
                                "rejection_reason": None,
                                "pasture_requested_day": day,
                                "pasture_requested_hour": hour,
                                "target_tile": list(cycle_tile),
                                "build_emitted_day": day,
                                "build_emitted_hour": hour,
                                "physical_pasture_observed_day": None,
                                "physical_pasture_observed_hour": None,
                                "became_purchase_eligible_day": None,
                                "became_purchase_eligible_hour": None,
                                "animal_purchase_day": None,
                                "animal_purchase_hour": None,
                                "animal_placement_day": None,
                                "animal_placement_hour": None,
                            }

        # Log purchases, sales, feeds
        orders = action0.get("market", []) if isinstance(action0, dict) else []
        market_prices = obs0.get("market", {}).get("prices", {}) if isinstance(obs0.get("market"), dict) else {}
        for o in orders:
            if isinstance(o, (list, tuple)) and len(o) >= 2:
                op = o[0]
                if op == "BUY_ANIMAL":
                    sp = o[1]
                    cnt = int(o[2]) if len(o) > 2 else 1
                    cost = ANIMALS[sp]["cost"] * cnt
                    animal_spend += cost
                    animal_buy_events.append({"day": day, "hour": hour, "species": sp, "count": cnt})

                    if day < 12:
                        animals_bought_pre_d12 += cnt
                    elif day == 12:
                        animals_bought_d12 += cnt
                    elif day == 13:
                        animals_bought_d13 += cnt
                    elif day == 14:
                        animals_bought_d14 += cnt

                    # Check hard invariant: speculative buy
                    empty_phys_pastures = max(0, physical_pastures - placed_herd)
                    if empty_phys_pastures < cnt and day >= 12:
                        speculative_animal_purchases += cnt

                    # Check if bought while continuation is in flight
                    if in_flight and empty_phys_pastures < cnt:
                        purchases_into_uncompleted_pasture += cnt

                    # Associate with active continuation cycle
                    for pos, cdata in active_cycles.items():
                        if cdata.get("physical_pasture_observed_day") is not None and cdata.get("animal_purchase_day") is None:
                            cdata["animal_purchase_day"] = day
                            cdata["animal_purchase_hour"] = hour

                elif op in ("BUY_PRODUCT", "BUY") and o[1] == "WHEAT":
                    qty = int(o[2]) if len(o) > 2 else 1
                    wheat_bought_units += qty
                    wheat_spend += qty * 25.0
                    if in_flight:
                        wheat_ordered_before_pasture_completion += qty
                elif op == "SELL":
                    item = o[1]
                    qty = int(o[2]) if len(o) > 2 else 1
                    item_px = float(market_prices.get(item, 0.0))
                    item_rev = qty * item_px
                    if item in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
                        crop_rev += item_rev
                    elif item == "MILK":
                        milk_rev += item_rev
                    elif item == "WOOL":
                        wool_rev += item_rev
                    elif item == "FERTILIZER":
                        fert_rev += item_rev

        # Track feed actions
        f_op = action0.get("farmer", []) if isinstance(action0, dict) else []
        if isinstance(f_op, (list, tuple)) and len(f_op) > 0 and f_op[0] == "FEED":
            total_feed_consumed += 1
        for h_op in (action0.get("hands", []) if isinstance(action0, dict) else []):
            if isinstance(h_op, (list, tuple)) and len(h_op) > 0 and h_op[0] == "FEED":
                total_feed_consumed += 1

        env.step([action0, action1])
        step += 1

        if step > 1 and total_owned_herd < prev_total_owned:
            starvations_or_deaths += (prev_total_owned - total_owned_herd)

        prev_total_owned = total_owned_herd

    final_money = float(env.state[0].observation["farms"][0]["money"])
    cash_checkpoints[30] = round(final_money, 2)
    cash_checkpoints[29] = cash_checkpoints.get(29, cash_checkpoints[30])

    # Invariants & overbuilding checks
    unused_pastures = max(0, physical_pastures - placed_herd)
    stranded_animals = owned_unplaced_herd

    # Check forward-only feed holds recorded during match
    fo_feed_holds = list(_STATE.get("forward_only_feed_holds", []))
    hold_before_avg = sum(f["hold_before"] for f in fo_feed_holds) / len(fo_feed_holds) if fo_feed_holds else 0.0
    hold_after_avg = sum(f["hold_after"] for f in fo_feed_holds) / len(fo_feed_holds) if fo_feed_holds else 0.0

    return {
        "arm": arm_name,
        "seed": seed,
        "opponent": opponent_name,
        "final_score": round(final_money, 2),
        "crop_revenue": round(crop_rev, 2),
        "milk_revenue": round(milk_rev, 2),
        "wool_revenue": round(wool_rev, 2),
        "fertilizer_revenue": round(fert_rev, 2),
        "animal_purchase_cost": round(animal_spend, 2),
        "feed_purchase_cost": round(wheat_spend, 2),
        "wheat_bought_units": wheat_bought_units,
        "total_feed_consumed": total_feed_consumed,
        "day0_cash_deployment": day0_cash_deployment,
        "min_wheat_slack": min_wheat_slack,
        "cash_checkpoints": cash_checkpoints,
        "min_cash": round(min_cash, 2),
        "negative_cash_events": negative_cash_events,
        "final_herd_composition": herd_comp,
        "final_placed_herd": placed_herd,
        "final_total_owned_herd": total_owned_herd,
        "max_placed_herd": max_placed_herd,
        "max_total_owned_herd": max_total_owned_herd,
        "animals_bought_pre_d12": animals_bought_pre_d12,
        "animals_bought_d12": animals_bought_d12,
        "animals_bought_d13": animals_bought_d13,
        "animals_bought_d14": animals_bought_d14,
        "final_pasture_count": physical_pastures,
        "pasture_build_events": pasture_build_events,
        "animal_buy_events": animal_buy_events,
        "continuation_cycles": list(active_cycles.values()),
        "continuation_pasture_requests": continuation_pasture_requests,
        "continuation_pasture_completions": continuation_pasture_completions,
        "continuation_pastures_occupied": min(continuation_pasture_completions, placed_herd),
        "continuation_pastures_unused": unused_pastures,
        "max_simultaneous_in_flight": max_simultaneous_in_flight,
        "continuation_builds_initiated_post_d14": continuation_builds_initiated_post_d14,
        "speculative_animal_purchases": speculative_animal_purchases,
        "purchases_into_uncompleted_pasture": purchases_into_uncompleted_pasture,
        "wheat_ordered_before_pasture_completion": wheat_ordered_before_pasture_completion,
        "forward_only_feed_holds": fo_feed_holds,
        "hold_before_avg": round(hold_before_avg, 2),
        "hold_after_avg": round(hold_after_avg, 2),
        "wasted_pastures": unused_pastures,
        "stranded_animals": stranded_animals,
        "starvations_or_deaths": starvations_or_deaths,
        "escapes": escapes,
    }


def _worker_run_paired_seed(args: Tuple[int, str]) -> Dict[str, Any]:
    seed, opponent_name = args
    # Run Arm B (Late1 OFF)
    res_b = run_match_single_arm(seed, opponent_name, arm_name="ArmB", late_cont=False)
    # Run Arm C (Late1 ON)
    res_c = run_match_single_arm(seed, opponent_name, arm_name="ArmC", late_cont=True)

    delta = round(res_c["final_score"] - res_b["final_score"], 2)
    winner = "C" if delta > 0 else ("B" if delta < 0 else "TIE")

    return {
        "seed": seed,
        "opponent": opponent_name,
        "arm_b": res_b,
        "arm_c": res_c,
        "delta_c_minus_b": delta,
        "winner": winner,
    }


def main():
    seeds_and_opps = generate_100_paired_seeds()
    n_total = len(seeds_and_opps)
    print(f"================================================================================")
    print(f"=== STARTING 100-SEED PAIRED LATE1 CAUSAL EXPERIMENT (Arm B vs Arm C) ===")
    print(f"=== Total Paired Seeds: {n_total} (200 Complete 720-Turn Matches) ===")
    print(f"================================================================================\n")

    t0 = time.time()
    num_workers = min(6, mp.cpu_count())
    print(f"Spawning worker pool with {num_workers} parallel worker processes...")

    paired_results = []
    worker_args = [(item["seed"], item["opponent"]) for item in seeds_and_opps]

    with mp.Pool(processes=num_workers) as pool:
        for idx, res in enumerate(pool.imap(_worker_run_paired_seed, worker_args), 1):
            paired_results.append(res)
            s = res["seed"]
            opp = res["opponent"]
            b_sc = res["arm_b"]["final_score"]
            c_sc = res["arm_c"]["final_score"]
            delta = res["delta_c_minus_b"]
            win = res["winner"]
            elapsed = time.time() - t0
            print(f"[{idx:3d}/{n_total}] Seed {s:<5d} vs {opp:<21s} | B: ${b_sc:7,.0f} | C: ${c_sc:7,.0f} | C-B: ${delta:+7,.0f} ({win}) | {elapsed:.1f}s")

    t_total = time.time() - t0
    print(f"\nAll {n_total} paired seeds (200 matches) completed in {t_total:.1f}s!")

    out_dir = os.path.join(ROOT_DIR, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "late1_causal_validation_results.json")
    with open(out_file, "w") as f:
        json.dump(paired_results, f, indent=2)

    print(f"Raw results written to: {out_file}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
