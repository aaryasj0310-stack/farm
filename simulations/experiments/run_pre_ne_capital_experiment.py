"""Point-2 Pre-NE Capital Admission Policy Experiment (200 Held-Out Seeds / 800 Matches).

Evaluates whether preserving early NE capital recovers the ~$12.3k gap between
the shadow control and live livestock architectures while retaining safe Point-2 mechanics.

Arms:
  Arm A (Shadow Control):
    feed_mode="shadow", boot_arm="none", late_cont=False, pre_ne_mode="off"
  Arm B (Current Rejected Live Baseline):
    feed_mode="live", boot_arm="ArmE", late_cont=True, pre_ne_mode="off"
  Arm C (NE-first Live):
    feed_mode="live", boot_arm="ArmE", late_cont=True, pre_ne_mode="ne_first"
  Arm D (NE-escrow Live):
    feed_mode="live", boot_arm="ArmE", late_cont=True, pre_ne_mode="ne_escrow"

Populations:
  Deterministic held-out set of 200 seeds (40 pass, 40 pure_wheat_rush,
  40 cow_milk_engine, 40 melon_sniper, 40 full_production_agent).
  Loaded from simulations/experiments/results/heldout_200_seeds_manifest.json.
  Total matches: 200 seeds * 4 arms = 800 matches.
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
    ROOT_DIR, "simulations", "experiments", "results", "pre_ne_capital_experiment_results.json"
)
PARTIAL_RESULTS_PATH = os.path.join(
    ROOT_DIR, "simulations", "experiments", "results", "pre_ne_capital_experiment_partial.json"
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
    pre_ne_mode: str,
) -> Dict[str, Any]:
    import config as cfg
    cfg.POINT2_FEED_MODE = feed_mode
    cfg.BOOTSTRAP_LIVESTOCK_ARM = boot_arm
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = late_cont
    cfg.POINT2_PRE_NE_CAPITAL_MODE = pre_ne_mode

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
            setattr(sys.modules[mod_name], "POINT2_PRE_NE_CAPITAL_MODE", pre_ne_mode)

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
    day0_animal_spend = 0.0
    day0_animals_bought = 0
    day0_structures_queued = 0

    min_wheat_slack = 999999

    animals_bought_pre_d12 = 0
    animals_bought_d12 = 0
    animals_bought_d13 = 0
    animals_bought_d14 = 0
    animals_bought_post_d14 = 0
    animals_bought_while_ne_locked = 0

    pre_ne_deferred_count = 0

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

        # Checkpoints: Day 0, 1, 3, 5, 10, 12, 13, 14, 15, 20
        if hour == 0 and day in (0, 1, 3, 5, 10, 12, 13, 14, 15, 20):
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

        # Check animal loss
        if step > 24 and total_owned_herd < prev_total_owned:
            delta_loss = prev_total_owned - total_owned_herd
            starvations_or_deaths += delta_loss
        prev_total_owned = total_owned_herd

        # Run agent decisions
        try:
            act0 = _agent_decision(obs0)
        except Exception as e:
            act0 = []

        try:
            act1 = opp_callable(obs1)
        except Exception as e:
            act1 = []

        # Audit actions
        ne_locked_curr = ("NE" not in unlocked_quads)

        # Worker actions for BUILD PASTURE
        worker_pos_map = {"farmer": tuple(farm0.get("farmer", (-1, -1)))}
        for h_idx, h_pos in enumerate(farm0.get("hands", [])):
            worker_pos_map[f"hand_{h_idx}"] = tuple(h_pos)

        worker_list = []
        if isinstance(act0, dict):
            worker_list.append(("farmer", act0.get("farmer", [])))
            for h_idx, h in enumerate(act0.get("hands", [])):
                worker_list.append((f"hand_{h_idx}", h))
        elif isinstance(act0, list):
            worker_list.append(("farmer", act0))

        for w_name, w_act in worker_list:
            if isinstance(w_act, (list, tuple)) and len(w_act) > 0:
                op = w_act[0]
                if op in ("BUILD_PASTURE", "BUILD"):
                    bpos = (
                        tuple(w_act[1])
                        if len(w_act) > 1 and isinstance(w_act[1], (list, tuple))
                        else worker_pos_map.get(w_name)
                    )
                    if day == 0:
                        day0_structures_queued += 1
                    if day >= 12:
                        if day > 14:
                            continuation_builds_initiated_post_d14 += 1
                        else:
                            continuation_pasture_requests += 1
                            active_target_tile = bpos
                            target_became_physical = False
                            target_animal_placed = False

        # Market orders
        orders = []
        if isinstance(act0, dict):
            orders = act0.get("market", [])
        elif isinstance(act0, list):
            orders = [a for a in act0 if isinstance(a, (list, tuple)) and len(a) > 0 and str(a[0]).startswith("BUY")]

        market_prices = (
            obs0.get("market", {}).get("prices", {})
            if isinstance(obs0.get("market"), dict)
            else {}
        )

        for action in orders:
            if isinstance(action, (list, tuple)) and len(action) > 0:
                op = action[0]
                if op == "BUY_ANIMAL":
                    sp = action[1] if len(action) > 1 else "COW"
                    cnt = int(action[2]) if len(action) > 2 else 1
                    cost = float(ANIMALS.get(sp, {}).get("cost", 400.0)) * cnt
                    animal_spend += cost
                    if day == 0:
                        day0_animal_spend += cost
                        day0_animals_bought += cnt
                    if ne_locked_curr:
                        animals_bought_while_ne_locked += cnt

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

                    if day >= 12:
                        if physical_pastures <= placed_herd:
                            speculative_animal_purchases += cnt
                            purchases_into_uncompleted_pasture += cnt
                        else:
                            continuation_animal_purchases += cnt

                    animal_buy_events.append({"day": day, "hour": hour, "species": sp, "cost": cost, "count": cnt})

                elif op in ("BUY_PRODUCT", "BUY") and len(action) > 1 and action[1] == "WHEAT":
                    qty = int(action[2]) if len(action) > 2 else 1
                    wheat_bought_units += qty
                    wheat_spend += qty * 28.0

                elif op == "SELL":
                    item = action[1]
                    qty = int(action[2]) if len(action) > 2 else 1
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
                sp = o[1]
                cost = float(ANIMALS.get(sp, {}).get("cost", 400.0))
                if money0 < cost:
                    c2c_dependency_violations += 1

        priv_shed_wheat = int(obs0.get("private", {}).get("shed", {}).get("WHEAT", 0)) if "private" in obs0 else 0
        rem_feed_days = min(4, max(0, 28 - day))
        req_wheat_buf = (placed_herd + owned_unplaced_herd) * rem_feed_days
        allowed_wheat_sale = max(0, priv_shed_wheat - req_wheat_buf)
        for o in orders:
            if isinstance(o, (list, tuple)) and len(o) >= 3 and o[0] in ("SELL", "SELL_PRODUCT") and o[1] == "WHEAT":
                qty = int(o[2])
                if qty > allowed_wheat_sale:
                    wheat_sale_reservation_violations += 1

        if _STATE.get("livestock_fallback_triggered", False):
            unsafe_livestock_fallback_events += 1

        # In-flight continuation telemetry
        mem_curr = _STATE
        if mem_curr.get("late_continuation_in_flight", False):
            max_simultaneous_in_flight = max(max_simultaneous_in_flight, 1)

        # Pre-NE deferred candidates count
        if "pre_ne_capital" in _STATE:
            pne = _STATE.get("pre_ne_capital", {})
            if isinstance(pne, dict):
                cands = pne.get("candidates", [])
                pre_ne_deferred_count = sum(1 for c in cands if not c.get("admitted", True))

        env.step([act0, act1])
        step += 1

    # End-of-game extraction
    final_farm0 = env.state[0].observation.get("farms", [{}])[0]
    final_score = float(final_farm0.get("money", 0.0))
    final_opp_score = float(env.state[1].observation.get("farms", [{}])[0].get("money", 0.0))

    final_pastures = 0
    final_placed_animals = 0
    for r, row in enumerate(final_farm0.get("tiles", [])):
        for c, t in enumerate(row):
            if isinstance(t, dict):
                if t.get("kind") == "PASTURE" or t.get("structure") == "PASTURE":
                    final_pastures += 1
                if t.get("animal") is not None or t.get("is_animal"):
                    final_placed_animals += 1

    unused_pastures = max(0, final_pastures - final_placed_animals)
    final_unplaced = 0
    if "private" in env.state[0].observation:
        priv_end = env.state[0].observation["private"]
        if "shed" in priv_end and isinstance(priv_end["shed"], dict):
            for sp in ("COW", "SHEEP", "GOOSE"):
                final_unplaced += int(priv_end["shed"].get(sp, 0))
    stranded_animals = final_unplaced

    ne_unlock_day = (ne_unlock_step[0] + ne_unlock_step[1] / 24.0) if ne_unlock_step is not None else None
    sw_unlock_day = (sw_unlock_step[0] + sw_unlock_step[1] / 24.0) if sw_unlock_step is not None else None

    return {
        "seed": seed,
        "opponent": opponent_name,
        "arm": arm_name,
        "feed_mode": feed_mode,
        "boot_arm": boot_arm,
        "late_cont": late_cont,
        "pre_ne_mode": pre_ne_mode,
        "final_score": round(final_score, 2),
        "opponent_score": round(final_opp_score, 2),
        "win": final_score > final_opp_score,
        "tie": final_score == final_opp_score,
        "loss": final_score < final_opp_score,
        "cash_checkpoints": cash_checkpoints,
        "day0_cash_deployment": day0_cash_deployment,
        "day0_animal_spend": day0_animal_spend,
        "day0_animals_bought": day0_animals_bought,
        "day0_structures_queued": day0_structures_queued,
        "animals_bought_while_ne_locked": animals_bought_while_ne_locked,
        "pre_ne_deferred_count": pre_ne_deferred_count,
        "animal_spend": round(animal_spend, 2),
        "wheat_bought_units": wheat_bought_units,
        "wheat_spend": round(wheat_spend, 2),
        "max_placed_herd": max_placed_herd,
        "max_total_owned_herd": max_total_owned_herd,
        "final_placed_herd": final_placed_animals,
        "final_pastures": final_pastures,
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
        "ne_unlock_day": ne_unlock_day,
        "sw_unlock_step": sw_unlock_step,
        "sw_unlock_day": sw_unlock_day,
        "min_cash": round(min_cash, 2),
        "negative_cash_events": negative_cash_events,
        "starvations_or_deaths": starvations_or_deaths,
        "escapes": escapes,
        "feed_shortage_deaths": feed_shortage_deaths,
        "c2c_dependency_violations": c2c_dependency_violations,
        "wheat_sale_reservation_violations": wheat_sale_reservation_violations,
        "unsafe_livestock_fallback_events": unsafe_livestock_fallback_events,
    }


def run_seed_quad_job(item: Dict[str, Any]) -> Dict[str, Any]:
    seed = item["seed"]
    opp = item["opponent"]
    idx = item.get("index", -1)

    t0 = time.time()
    # 1. Arm A: Shadow Control
    res_a = run_match_single_arm(
        seed=seed,
        opponent_name=opp,
        arm_name="ArmA",
        feed_mode="shadow",
        boot_arm="none",
        late_cont=False,
        pre_ne_mode="off",
    )

    # 2. Arm B: Current Rejected Live Baseline (3C + Late1, pre-NE off)
    res_b = run_match_single_arm(
        seed=seed,
        opponent_name=opp,
        arm_name="ArmB",
        feed_mode="live",
        boot_arm="ArmE",
        late_cont=True,
        pre_ne_mode="off",
    )

    # 3. Arm C: NE-first Live (3C + Late1, pre-NE ne_first)
    res_c = run_match_single_arm(
        seed=seed,
        opponent_name=opp,
        arm_name="ArmC",
        feed_mode="live",
        boot_arm="ArmE",
        late_cont=True,
        pre_ne_mode="ne_first",
    )

    # 4. Arm D: NE-escrow Live (3C + Late1, pre-NE ne_escrow)
    res_d = run_match_single_arm(
        seed=seed,
        opponent_name=opp,
        arm_name="ArmD",
        feed_mode="live",
        boot_arm="ArmE",
        late_cont=True,
        pre_ne_mode="ne_escrow",
    )
    elapsed = round(time.time() - t0, 2)

    delta_b_minus_a = round(res_b["final_score"] - res_a["final_score"], 2)
    delta_c_minus_a = round(res_c["final_score"] - res_a["final_score"], 2)
    delta_d_minus_a = round(res_d["final_score"] - res_a["final_score"], 2)
    delta_c_minus_b = round(res_c["final_score"] - res_b["final_score"], 2)
    delta_d_minus_b = round(res_d["final_score"] - res_b["final_score"], 2)

    return {
        "index": idx,
        "seed": seed,
        "opponent": opp,
        "elapsed_sec": elapsed,
        "arm_a": res_a,
        "arm_b": res_b,
        "arm_c": res_c,
        "arm_d": res_d,
        "delta_b_minus_a": delta_b_minus_a,
        "delta_c_minus_a": delta_c_minus_a,
        "delta_d_minus_a": delta_d_minus_a,
        "delta_c_minus_b": delta_c_minus_b,
        "delta_d_minus_b": delta_d_minus_b,
    }


def main():
    print("================================================================================", flush=True)
    print(" POINT-2 PRE-NE CAPITAL ADMISSION EXPERIMENT (200 SEEDS / 800 MATCHES)", flush=True)
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
            for i, res in enumerate(pool.imap_unordered(run_seed_quad_job, pending_items), 1):
                results_list.append(res)
                total_done = len(results_list)
                a_val = res["arm_a"]["final_score"]
                b_val = res["arm_b"]["final_score"]
                c_val = res["arm_c"]["final_score"]
                d_val = res["arm_d"]["final_score"]
                print(
                    f"[{total_done:03d}/200] Seed {res['seed']} vs {res['opponent']:<21} | "
                    f"A: ${a_val:,.0f} | B: ${b_val:,.0f} | "
                    f"C: ${c_val:,.0f} (vs B: {res['delta_c_minus_b']:+,.0f}) | "
                    f"D: ${d_val:,.0f} (vs B: {res['delta_d_minus_b']:+,.0f}) | {res['elapsed_sec']:.1f}s",
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
        "total_matches": len(results_list) * 4,
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

    print(f"\nCompleted {len(results_list)*4} matches in {total_wall_time:.1f}s.", flush=True)
    print(f"Saved raw experiment results to: {RESULTS_PATH}", flush=True)


if __name__ == "__main__":
    main()
