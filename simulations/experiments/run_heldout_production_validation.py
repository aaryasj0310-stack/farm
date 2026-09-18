"""
Point-2 200-Seed Out-of-Sample Production-Bundle Validation Experiment.

Arms:
  Arm S (Control): Production shadow baseline
    POINT2_FEED_MODE = "shadow"
    BOOTSTRAP_LIVESTOCK_ARM = "none"
    ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False

  Arm C (3C Bundle): Live 3-COW bootstrap + Late1 continuation
    POINT2_FEED_MODE = "live"
    BOOTSTRAP_LIVESTOCK_ARM = "ArmE"
    ONE_AT_A_TIME_LATE_HOUSING_ENABLED = True

  Arm D (2C1S Bundle): Live 2-COW + 1-SHEEP bootstrap + Late1 continuation
    POINT2_FEED_MODE = "live"
    BOOTSTRAP_LIVESTOCK_ARM = "ArmC"
    ONE_AT_A_TIME_LATE_HOUSING_ENABLED = True

Populations:
  Deterministic held-out set of 200 seeds (40 pass, 40 pure_wheat_rush,
  40 cow_milk_engine, 40 melon_sniper, 40 full_production_agent).
  Loaded directly from simulations/experiments/results/heldout_200_seeds_manifest.json.
  Total matches: 200 * 3 = 600 matches.
"""
from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(ROOT_DIR, "agent")
for p in (ROOT_DIR, AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import kaggle_environments
from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS, CROPS, MARKET_PARAMS, MARKET_I0
)
from simulations.experiments.agent_zoo import get_agent


MANIFEST_PATH = os.path.join(
    ROOT_DIR, "simulations", "experiments", "results", "heldout_200_seeds_manifest.json"
)
RESULTS_PATH = os.path.join(
    ROOT_DIR, "simulations", "experiments", "results", "heldout_production_validation_results.json"
)
PARTIAL_RESULTS_PATH = os.path.join(
    ROOT_DIR, "simulations", "experiments", "results", "heldout_production_validation_partial.json"
)


def load_manifest() -> Tuple[List[Dict[str, Any]], str]:
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    manifest = json.loads(content)
    return manifest, sha256


def run_match_single_arm(
    seed: int,
    opponent_name: str,
    arm_name: str,
    feed_mode: str,
    boot_arm: str,
    late_cont: bool,
) -> Dict[str, Any]:
    import config as cfg
    cfg.POINT2_FEED_MODE = feed_mode
    cfg.BOOTSTRAP_LIVESTOCK_ARM = boot_arm
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = late_cont

    for mod_name in (
        "agent.main", "main", "agent.config", "config",
        "agent.strategy.macro_planner", "macro_planner",
        "agent.strategy.herd_planner", "herd_planner",
        "agent.strategy.feed_feasibility", "feed_feasibility",
        "agent.market.order_builder", "order_builder",
    ):
        if mod_name in sys.modules:
            setattr(sys.modules[mod_name], "POINT2_FEED_MODE", feed_mode)
            setattr(sys.modules[mod_name], "BOOTSTRAP_LIVESTOCK_ARM", boot_arm)
            setattr(sys.modules[mod_name], "ONE_AT_A_TIME_LATE_HOUSING_ENABLED", late_cont)

    from main import _agent_decision, reset_agent_state
    from state.state_tracker import _STATE, reset_memory
    reset_agent_state()
    reset_memory()

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.reset(2)
    opp_callable = get_agent(opponent_name)

    cash_checkpoints: Dict[int, float] = {}
    min_cash = 3000.0
    negative_cash_events = 0

    max_placed_herd = 0
    max_total_owned_herd = 0
    prev_total_owned = 0
    starvations_or_deaths = 0
    escapes = 0
    feed_shortage_deaths = 0
    c2c_dependency_violations = 0
    wheat_sale_reservation_violations = 0
    unsafe_livestock_fallback_events = 0

    crop_rev = 0.0
    milk_rev = 0.0
    wool_rev = 0.0
    fert_rev = 0.0
    wheat_sold_rev = 0.0

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
    animals_bought_post_d14 = 0

    # Pasture and housing tracking
    prev_pasture_count = 0
    pasture_build_events = []
    animal_buy_events = []
    animal_placed_events = []

    # Late-housing continuation metrics
    continuation_pasture_requests = 0
    continuation_pasture_completions = 0
    continuation_animal_purchases = 0
    continuation_builds_initiated_post_d14 = 0
    speculative_animal_purchases = 0
    purchases_into_uncompleted_pasture = 0
    max_simultaneous_in_flight = 0

    # Land unlock tracking
    ne_unlock_step: Optional[Tuple[int, int]] = None
    sw_unlock_step: Optional[Tuple[int, int]] = None

    # Track target position for continuation
    active_target_tile: Optional[Tuple[int, int]] = None
    target_became_physical = False
    target_animal_placed = False

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

        # Check land unlocks
        unlocked_quads = farm0.get("unlocked_quadrants", ["NW"]) or ["NW"]
        if "NE" in unlocked_quads and ne_unlock_step is None:
            ne_unlock_step = (day, hour)
        if "SW" in unlocked_quads and sw_unlock_step is None:
            sw_unlock_step = (day, hour)

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

        for r, row in enumerate(farm0.get("tiles", [])):
            for c, t in enumerate(row):
                if isinstance(t, dict):
                    pos = (r, c)
                    is_past = (t.get("kind") == "PASTURE" or t.get("structure") == "PASTURE")
                    has_anim = (t.get("animal") is not None or t.get("is_animal"))
                    if is_past:
                        physical_pastures += 1
                        if has_anim:
                            occupied_pastures += 1
                    if has_anim:
                        placed_herd += 1
                        sp = t.get("animal", "COW")
                        if sp in herd_comp:
                            herd_comp[sp] += 1

        # Check active target tile status
        if active_target_tile is not None:
            tr, tc = active_target_tile
            tiles_grid = farm0.get("tiles", [])
            if 0 <= tr < len(tiles_grid) and 0 <= tc < len(tiles_grid[tr]):
                tile_obj = tiles_grid[tr][tc]
                if isinstance(tile_obj, dict):
                    if (tile_obj.get("kind") == "PASTURE" or tile_obj.get("structure") == "PASTURE"):
                        if not target_became_physical:
                            target_became_physical = True
                            continuation_pasture_completions += 1
                    if (tile_obj.get("animal") is not None or tile_obj.get("is_animal")):
                        if not target_animal_placed:
                            target_animal_placed = True

        # Detect newly completed pastures overall
        if physical_pastures > prev_pasture_count and step > 0:
            pasture_build_events.append({"day": day, "hour": hour, "new_total": physical_pastures})
            prev_pasture_count = physical_pastures
        elif physical_pastures > prev_pasture_count and step == 0:
            prev_pasture_count = physical_pastures

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

        worker_list = [("farmer", action0.get("farmer", []))] + [
            (f"hand_{h_idx}", h) for h_idx, h in enumerate(action0.get("hands", []))
        ]
        for w_name, w_act in worker_list:
            if isinstance(w_act, (list, tuple)) and len(w_act) > 0:
                op = w_act[0]
                if op in ("BUILD_PASTURE", "BUILD"):
                    build_pos = (
                        tuple(w_act[1])
                        if len(w_act) > 1 and isinstance(w_act[1], (list, tuple))
                        else worker_pos_map.get(w_name)
                    )
                    if day >= 14 and late_cont and (build_pos == target_pos or target_pos is not None):
                        continuation_builds_initiated_post_d14 += 1
                    if day in (12, 13) and late_cont and (build_pos == target_pos or target_pos is not None):
                        if active_target_tile is None:
                            active_target_tile = target_pos if target_pos is not None else build_pos
                            continuation_pasture_requests += 1

        # Log purchases, sales, feeds
        orders = action0.get("market", []) if isinstance(action0, dict) else []
        market_prices = (
            obs0.get("market", {}).get("prices", {})
            if isinstance(obs0.get("market"), dict)
            else {}
        )
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
                    else:
                        animals_bought_post_d14 += cnt

                    # Check hard invariant: speculative buy without physical housing
                    empty_phys_pastures = max(0, physical_pastures - placed_herd)
                    if empty_phys_pastures < cnt and day >= 12:
                        speculative_animal_purchases += cnt

                    # Check if bought while continuation is in flight
                    if in_flight and empty_phys_pastures < cnt:
                        purchases_into_uncompleted_pasture += cnt

                    if day in (12, 13, 14) and late_cont:
                        continuation_animal_purchases += cnt

                elif op in ("BUY_PRODUCT", "BUY") and o[1] == "WHEAT":
                    qty = int(o[2]) if len(o) > 2 else 1
                    wheat_bought_units += qty
                    wheat_spend += qty * 25.0
                elif op == "SELL":
                    item = o[1]
                    qty = int(o[2]) if len(o) > 2 else 1
                    item_px = float(market_prices.get(item, 0.0))
                    item_rev = qty * item_px
                    if item in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
                        crop_rev += item_rev
                        if item == "WHEAT":
                            wheat_sold_rev += item_rev
                    elif item == "MILK":
                        milk_rev += item_rev
                    elif item == "WOOL":
                        wool_rev += item_rev
                    elif item == "FERTILIZER":
                        fert_rev += item_rev

        # Safety checking on emitted orders
        for o in orders:
            if isinstance(o, (list, tuple)) and len(o) >= 2 and o[0] == "BUY_ANIMAL":
                cost = ANIMALS.get(o[1], {}).get("cost", 400.0)
                if money0 < cost:
                    c2c_dependency_violations += 1

        priv_shed_wheat = (
            int(obs0.get("private", {}).get("shed", {}).get("WHEAT", 0))
            if "private" in obs0
            else 0
        )
        rem_feed_days = min(4, max(0, 28 - day))
        req_wheat_buf = (placed_herd + owned_unplaced_herd) * rem_feed_days
        allowed_wheat_sale = max(0, priv_shed_wheat - req_wheat_buf)
        for o in orders:
            if isinstance(o, (list, tuple)) and len(o) >= 3 and o[0] == "SELL" and o[1] == "WHEAT":
                qty = int(o[2])
                if qty > allowed_wheat_sale:
                    wheat_sale_reservation_violations += 1

        if _STATE.get("livestock_fallback_triggered", False):
            unsafe_livestock_fallback_events += 1

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
            loss = prev_total_owned - total_owned_herd
            starvations_or_deaths += loss
            escapes += loss
            feed_shortage_deaths += loss

        prev_total_owned = total_owned_herd

    final_money = float(env.state[0].observation["farms"][0]["money"])
    cash_checkpoints[30] = round(final_money, 2)
    cash_checkpoints[29] = cash_checkpoints.get(29, cash_checkpoints[30])

    unused_pastures = max(0, physical_pastures - placed_herd)
    stranded_animals = owned_unplaced_herd
    net_livestock_profit = round(milk_rev + wool_rev + fert_rev - animal_spend - wheat_spend, 2)

    day0_events = [e for e in animal_buy_events if e["day"] == 0]
    day0_admitted_count = sum(e["count"] for e in day0_events)
    day0_admitted_comp: Dict[str, int] = {}
    for e in day0_events:
        day0_admitted_comp[e["species"]] = day0_admitted_comp.get(e["species"], 0) + e["count"]

    return {
        "arm": arm_name,
        "seed": seed,
        "opponent": opponent_name,
        "final_score": round(final_money, 2),
        "crop_revenue": round(crop_rev, 2),
        "wheat_sold_revenue": round(wheat_sold_rev, 2),
        "milk_revenue": round(milk_rev, 2),
        "wool_revenue": round(wool_rev, 2),
        "fertilizer_revenue": round(fert_rev, 2),
        "animal_purchase_cost": round(animal_spend, 2),
        "feed_purchase_cost": round(wheat_spend, 2),
        "net_livestock_profit": net_livestock_profit,
        "wheat_bought_units": wheat_bought_units,
        "total_feed_consumed": total_feed_consumed,
        "day0_cash_deployment": day0_cash_deployment,
        "cash_checkpoints": cash_checkpoints,
        "day0_admitted_count": day0_admitted_count,
        "day0_admitted_composition": day0_admitted_comp,
        "final_herd_composition": herd_comp,
        "max_placed_herd": max_placed_herd,
        "max_total_owned_herd": max_total_owned_herd,
        "final_placed_herd": placed_herd,
        "final_total_owned_herd": total_owned_herd,
        "final_pasture_count": physical_pastures,
        "pasture_build_events": pasture_build_events,
        "animal_buy_events": animal_buy_events,
        "animals_bought_pre_d12": animals_bought_pre_d12,
        "animals_bought_d12": animals_bought_d12,
        "animals_bought_d13": animals_bought_d13,
        "animals_bought_d14": animals_bought_d14,
        "animals_bought_post_d14": animals_bought_post_d14,
        "continuation_pasture_requests": continuation_pasture_requests,
        "continuation_pasture_completions": continuation_pasture_completions,
        "continuation_animal_purchases": continuation_animal_purchases,
        "continuation_builds_initiated_post_d14": continuation_builds_initiated_post_d14,
        "speculative_animal_purchases": speculative_animal_purchases,
        "purchases_into_uncompleted_pasture": purchases_into_uncompleted_pasture,
        "max_simultaneous_in_flight": max_simultaneous_in_flight,
        "unused_pastures": unused_pastures,
        "stranded_animals": stranded_animals,
        "min_wheat_slack": min_wheat_slack,
        "ne_unlock_step": ne_unlock_step,
        "sw_unlock_step": sw_unlock_step,
        "min_cash": round(min_cash, 2),
        "negative_cash_events": negative_cash_events,
        "starvations_or_deaths": starvations_or_deaths,
        "escapes": escapes,
        "feed_shortage_deaths": feed_shortage_deaths,
        "c2c_dependency_violations": c2c_dependency_violations,
        "wheat_sale_reservation_violations": wheat_sale_reservation_violations,
        "unsafe_livestock_fallback_events": unsafe_livestock_fallback_events,
    }


def run_seed_triplet_job(item: Dict[str, Any]) -> Dict[str, Any]:
    seed = item["seed"]
    opp = item["opponent"]
    idx = item.get("index", -1)

    t0 = time.time()
    # 1. Arm S: Shadow Control
    res_s = run_match_single_arm(
        seed=seed,
        opponent_name=opp,
        arm_name="ArmS",
        feed_mode="shadow",
        boot_arm="none",
        late_cont=False,
    )

    # 2. Arm C: Full Live 3-COW Bundle
    res_c = run_match_single_arm(
        seed=seed,
        opponent_name=opp,
        arm_name="ArmC",
        feed_mode="live",
        boot_arm="ArmE",
        late_cont=True,
    )

    # 3. Arm D: Full Live 2C1S Bundle
    res_d = run_match_single_arm(
        seed=seed,
        opponent_name=opp,
        arm_name="ArmD",
        feed_mode="live",
        boot_arm="ArmC",
        late_cont=True,
    )
    elapsed = round(time.time() - t0, 2)

    delta_c_minus_s = round(res_c["final_score"] - res_s["final_score"], 2)
    delta_d_minus_s = round(res_d["final_score"] - res_s["final_score"], 2)
    delta_d_minus_c = round(res_d["final_score"] - res_c["final_score"], 2)

    return {
        "index": idx,
        "seed": seed,
        "opponent": opp,
        "elapsed_sec": elapsed,
        "arm_s": res_s,
        "arm_c": res_c,
        "arm_d": res_d,
        "delta_c_minus_s": delta_c_minus_s,
        "delta_d_minus_s": delta_d_minus_s,
        "delta_d_minus_c": delta_d_minus_c,
    }


def main():
    print("================================================================================", flush=True)
    print(" POINT-2 HELD-OUT OUT-OF-SAMPLE PRODUCTION-BUNDLE VALIDATION (200 SEEDS / 600 MATCHES)", flush=True)
    print("================================================================================", flush=True)

    manifest, sha256 = load_manifest()
    print(f"Loaded held-out manifest: {len(manifest)} seeds", flush=True)
    print(f"Manifest SHA256: {sha256}", flush=True)

    completed_results: Dict[int, Dict[str, Any]] = {}
    if os.path.exists(PARTIAL_RESULTS_PATH):
        try:
            with open(PARTIAL_RESULTS_PATH, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                if saved_data.get("manifest_sha256") == sha256:
                    for r in saved_data.get("results", []):
                        completed_results[r["seed"]] = r
                    print(f"Resuming from partial results: {len(completed_results)} already completed.", flush=True)
        except Exception as e:
            print(f"Warning: could not load partial results: {e}", flush=True)

    pending_items = [item for item in manifest if item["seed"] not in completed_results]
    print(f"Remaining seeds to evaluate: {len(pending_items)}", flush=True)

    num_workers = max(1, min(7, mp.cpu_count() - 1))
    print(f"Executing across {num_workers} parallel workers...", flush=True)

    start_time = time.time()
    results_list = list(completed_results.values())

    if pending_items:
        with mp.Pool(processes=num_workers) as pool:
            for i, res in enumerate(pool.imap_unordered(run_seed_triplet_job, pending_items), 1):
                results_list.append(res)
                total_done = len(results_list)
                s_val = res["arm_s"]["final_score"]
                c_val = res["arm_c"]["final_score"]
                d_val = res["arm_d"]["final_score"]
                print(
                    f"[{total_done:03d}/200] Seed {res['seed']} vs {res['opponent']:<21} | "
                    f"S: ${s_val:,.0f} | C: ${c_val:,.0f} (Δ {res['delta_c_minus_s']:+,.0f}) | "
                    f"D: ${d_val:,.0f} (Δ {res['delta_d_minus_s']:+,.0f}) | {res['elapsed_sec']:.1f}s",
                    flush=True
                )

                # Incremental checkpoint save every 5 completed
                if total_done % 5 == 0 or total_done == len(manifest):
                    sorted_curr = sorted(results_list, key=lambda x: x["index"])
                    with open(PARTIAL_RESULTS_PATH, "w", encoding="utf-8") as f:
                        json.dump({
                            "manifest_sha256": sha256,
                            "completed_count": len(sorted_curr),
                            "results": sorted_curr,
                        }, f)

    total_wall_time = time.time() - start_time
    results_list.sort(key=lambda x: x["index"])

    payload = {
        "manifest_sha256": sha256,
        "total_seeds": len(results_list),
        "total_matches": len(results_list) * 3,
        "total_wall_clock_sec": round(total_wall_time, 2),
        "results": results_list,
    }

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # Clean up partial results file if complete
    if len(results_list) == len(manifest) and os.path.exists(PARTIAL_RESULTS_PATH):
        try:
            os.remove(PARTIAL_RESULTS_PATH)
        except Exception:
            pass

    print(f"\nCompleted {len(results_list)*3} matches in {total_wall_time:.1f}s.", flush=True)
    print(f"Saved raw validation results to: {RESULTS_PATH}", flush=True)


if __name__ == "__main__":
    main()
