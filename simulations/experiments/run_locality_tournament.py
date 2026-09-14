"""Persistent Worker Locality & SW Production Cell Benchmark Tournament (Arms A, B-P, C-Cell).

Evaluates:
  1. Arm B-P vs Arm A: Does persistent worker locality with hysteresis recover
     lost performance and reduce NE <-> SW switching overhead?
  2. Arm C-Cell vs Arm B-P: Does a controlled mixed SW production cell (siting
     at most one already-justified large livestock pasture in SW) recover displaced
     NW+NE core farm labor and improve net farm profit?

Arms:
  - Arm A: Fresh Production Control (Current strategy with SW expansion disabled/frozen)
  - Arm B-P: Working SW + Persistent Worker Locality with Hysteresis (Livestock 100% Core)
  - Arm C-Cell: Exactly Arm B-P + Controlled Mixed SW Production Cell (Spatial Allocation Only)

Metrics Collected:
  - Locality Metrics:
      * Same-quadrant retention rate (% turns worker retained previous turn's home quadrant)
      * Home quadrant reassignments per worker-day
      * Total NE <-> SW home quadrant changes
      * Total physical NE <-> SW traversals (shed transit excluded)
      * Moves per productive action ratio (overall, and SW)
      * Temporary cross-zone spillovers count
      * Emergency survival preemptions count
  - Semantic Operations by Quadrant x Category:
      * Quadrants: NW, NE, SW, SE
      * Categories: crop, livestock, housing, logistics, maintenance, other
      * Core productive actions: NW + NE (verifying zero degradation to core farm)
  - Primary Production Value by Source Quadrant:
      * Estimated value of all crops and livestock products harvested in NW, NE, SW, SE
  - Treatment Exposure Metrics (Arm C-Cell):
      * sw_cell_eligible, day_first_eligible
      * sw_pasture_reserved, sw_pasture_built, day_built
      * sw_pasture_occupied, day_occupied, occupying_species
      * occupied_pasture_days, empty_sw_pasture_days
      * future_pasture_opportunities_after_sw
  - Safety:
      * Max consecutive unfed days seen, animals with >=2 unfed days (must be 0)
  - Economics & Statistical Rigor:
      * Final score / coins
      * Paired score differences: (C-Cell - B-P), (B-P - A), (C-Cell - A)
      * Bootstrap 95% CI on paired deltas, paired t-test, Wilcoxon signed-rank test
      * Win / tie / loss counts, trimmed mean (10%).
"""

import os
import sys
import json
import time
import math
import copy
import argparse
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from scipy import stats

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")


def compute_bootstrap_ci(
    deltas: List[float],
    n_boot: int = 10000,
    alpha: float = 0.05,
    seed: int = 42,
) -> Tuple[float, float]:
    """Compute bootstrap percentile confidence interval on the mean of paired deltas."""
    if len(deltas) <= 1:
        val = float(np.mean(deltas)) if deltas else 0.0
        return val, val
    rng = np.random.RandomState(seed)
    arr = np.array(deltas, dtype=float)
    boot_means = [float(np.mean(rng.choice(arr, size=len(arr), replace=True))) for _ in range(n_boot)]
    lower = float(np.percentile(boot_means, 100 * (alpha / 2)))
    upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    return lower, upper


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    arm = payload["arm"]
    seed = payload["seed"]
    opp_name = payload.get("opponent", "random")

    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'land_serviceability_model',
        'marginal_livestock_valuator', 'sw_cell_allocator'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    from observation_parser import parse_observation
    import execution.task_scheduler as task_scheduler
    import strategy.sw_cell_allocator as sw_cell_allocator

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    if hasattr(agent_module, "reset_daily_telemetry"):
        agent_module.reset_daily_telemetry()
    elif hasattr(agent_module, "reset_daily_log"):
        agent_module.reset_daily_log()

    task_scheduler.reset_worker_locality()
    sw_cell_allocator.reset_sw_cell_telemetry()

    # Configure Arm
    config.set_sw_experiment_arm(arm)

    # SW Purchase Telemetry
    sw_purchased = False
    sw_purchase_day = None
    sw_purchase_hour = None
    sw_purchase_step = None

    # SW Occupancy & Tile-Hour Tracking
    sw_productive_actions = 0
    sw_movement_actions = 0
    sw_planted_unwatered_hours = 0
    sw_ripe_unharvested_hours = 0

    # Animal Safety Telemetry
    max_consecutive_unfed_seen = 0
    animals_consec_ge_2 = 0
    escaped_animals = 0
    feed_actions_completed_late = 0

    # Labor Telemetry by Quadrant
    quad_moves = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    quad_productive = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}

    # Primary Production Value by Source Quadrant (crops + livestock output + fertilizer)
    estimated_prod_val = {"NW": 0.0, "NE": 0.0, "SW": 0.0, "SE": 0.0}

    # SW Cell Treatment Exposure Telemetry
    sw_pasture_built = False
    day_built = None
    sw_pasture_occupied = False
    day_occupied = None
    occupying_species = None
    occupied_pasture_days = 0
    empty_sw_pasture_days = 0
    total_pastures_at_day_built = 0

    last_money = 3000.0

    def tracking_agent(obs, configuration=None):
        nonlocal sw_purchased, sw_purchase_day, sw_purchase_hour, sw_purchase_step
        nonlocal sw_productive_actions, sw_movement_actions, sw_planted_unwatered_hours
        nonlocal sw_ripe_unharvested_hours
        nonlocal max_consecutive_unfed_seen, animals_consec_ge_2, escaped_animals, feed_actions_completed_late
        nonlocal quad_moves, quad_productive, estimated_prod_val, last_money
        nonlocal sw_pasture_built, day_built, sw_pasture_occupied, day_occupied, occupying_species
        nonlocal occupied_pasture_days, empty_sw_pasture_days, total_pastures_at_day_built

        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)

        parsed = parse_observation(obs)
        farm = parsed["farm"] if parsed else None

        # Call agent to get actions
        action = agent_module.agent(obs, configuration)
        if farm is None:
            return action

        last_money = farm.money

        # Track worker locations and actions
        all_unit_positions = [farm.farmer] + farm.hands
        farmer_act = action.get("farmer", ["PASS"])
        hands_act = action.get("hands", [])
        all_actions = [farmer_act] + hands_act

        for u_idx, act in enumerate(all_actions):
            if not act:
                continue
            act_type = act[0]
            upos = all_unit_positions[u_idx] if u_idx < len(all_unit_positions) else (4, 4)
            uq = farm.quadrant_of(upos)

            if act_type in ("NORTH", "SOUTH", "EAST", "WEST"):
                quad_moves[uq] = quad_moves.get(uq, 0) + 1
                if uq == "SW":
                    sw_movement_actions += 1
            elif act_type not in ("PASS",):
                quad_productive[uq] = quad_productive.get(uq, 0) + 1
                if uq == "SW":
                    sw_productive_actions += 1

                # Record primary production value when harvest / collect actions take place
                if act_type == "HARVEST":
                    tile = farm.tile_at(upos)
                    if tile:
                        if getattr(tile, "is_plant", False) or getattr(tile, "crop", None):
                            c_name = getattr(tile, "crop", "")
                            units = getattr(tile, "yield_units", 0)
                            base_p = config.MARKET_PARAMS.get(c_name, {}).get("base", 0)
                            if units > 0:
                                estimated_prod_val[uq] = estimated_prod_val.get(uq, 0.0) + (units * base_p)
                        elif getattr(tile, "is_animal", False) or getattr(tile, "animal", None):
                            a_name = getattr(tile, "animal", "")
                            prod_item = config.ANIMALS.get(a_name, {}).get("product", "")
                            units = getattr(tile, "yield_units", 0)
                            base_p = config.MARKET_PARAMS.get(prod_item, {}).get("base", 0)
                            if units > 0:
                                estimated_prod_val[uq] = estimated_prod_val.get(uq, 0.0) + (units * base_p)
                elif act_type == "COLLECT_FERTILIZER":
                    tile = farm.tile_at(upos)
                    if tile and getattr(tile, "is_animal", False) and getattr(tile, "fertilizer_available", False):
                        base_p = config.MARKET_PARAMS.get("FERTILIZER", {}).get("base", 100)
                        estimated_prod_val[uq] = estimated_prod_val.get(uq, 0.0) + base_p

            if act_type == "FEED" and hour >= 14:
                feed_actions_completed_late += 1

        # Check animal safety & SW crops
        for t in farm.iter_tiles():
            if t.is_animal:
                consec = t.consecutive_unfed
                if consec > max_consecutive_unfed_seen:
                    max_consecutive_unfed_seen = consec
                if consec >= 2:
                    animals_consec_ge_2 += 1

            if farm.quadrant_of(t.pos) == "SW" and t.pos != (4, 5):
                is_plant = getattr(t, "is_plant", False) or t.crop is not None
                if is_plant:
                    if hour == 23 and not t.watered_today:
                        sw_planted_unwatered_hours += 1
                    if t.yield_units > 0:
                        sw_ripe_unharvested_hours += 1

        # SW purchase event detection
        if "SW" in farm.unlocked and not sw_purchased:
            sw_purchased = True
            sw_purchase_day = day
            sw_purchase_hour = hour
            sw_purchase_step = step

        # SW Cell pasture construction & occupancy detection
        sw_pastures = [
            t for t in farm.iter_tiles()
            if farm.quadrant_of(t.pos) == "SW" and (
                getattr(t, "kind", None) == "PASTURE" or
                (getattr(t, "is_animal", False) and config.ANIMALS.get(getattr(t, "animal", ""), {}).get("structure") == "PASTURE")
            )
        ]
        if sw_pastures and not sw_pasture_built:
            sw_pasture_built = True
            day_built = day
            total_pastures_at_day_built = sum(
                1 for t in farm.iter_tiles()
                if getattr(t, "kind", None) == "PASTURE" or
                (getattr(t, "is_animal", False) and config.ANIMALS.get(getattr(t, "animal", ""), {}).get("structure") == "PASTURE")
            )

        sw_occupied = [t for t in sw_pastures if getattr(t, "is_animal", False)]
        if sw_occupied and not sw_pasture_occupied:
            sw_pasture_occupied = True
            day_occupied = day
            occupying_species = getattr(sw_occupied[0], "animal", None)

        if hour == 23:
            if sw_occupied:
                occupied_pasture_days += 1
            elif sw_pastures:
                empty_sw_pasture_days += 1

        return action

    # Run game in kaggle_environments
    env = make("kaggriculture", configuration={"randomSeed": seed}, debug=False)
    env_agents = [tracking_agent, opp_name] if payload.get("agent_index", 0) == 0 else [opp_name, tracking_agent]
    steps = env.run(env_agents)

    p_idx = payload.get("agent_index", 0)
    final_reward = steps[-1][p_idx]["reward"] or 0.0
    opp_reward = steps[-1][1 - p_idx]["reward"] or 0.0

    # Extract locality telemetry
    loc_telem = task_scheduler.get_locality_telemetry()
    loc_summary = loc_telem.get("summary", {})
    daily_log = loc_telem.get("daily_log", {})

    retention_vals = [d_info.get("same_home_retention_pct", 1.0) * 100.0 for d_info in daily_log.values()]
    retention_rate = float(np.mean(retention_vals)) if retention_vals else 100.0
    switches_vals = [d_info.get("within_day_home_changes_per_worker", 0.0) for d_info in daily_log.values()]
    switches_per_worker_day = float(np.mean(switches_vals)) if switches_vals else 0.0
    time_in_home_vals = [d_info.get("pct_time_in_home_quadrant", 1.0) * 100.0 for d_info in daily_log.values()]
    time_in_home_pct = float(np.mean(time_in_home_vals)) if time_in_home_vals else 100.0

    # Extract semantic operation counts by quadrant and category
    quad_ops_by_type = {
        q: {"crop": 0, "livestock": 0, "housing": 0, "logistics": 0, "maintenance": 0, "other": 0}
        for q in ("NW", "NE", "SW", "SE")
    }
    for d_info in daily_log.values():
        d_q_ops = d_info.get("ops_by_quad_and_type", {})
        for q, cats in d_q_ops.items():
            for cat, count in cats.items():
                if q in quad_ops_by_type and cat in quad_ops_by_type[q]:
                    quad_ops_by_type[q][cat] += count

    total_moves = sum(quad_moves.values())
    total_productive = sum(quad_productive.values())
    move_ratio_overall = total_moves / max(1, total_productive)
    move_ratio_sw = quad_moves.get("SW", 0) / max(1, quad_productive.get("SW", 0))

    # Cell treatment diagnostics from sw_cell_allocator
    cell_telem = sw_cell_allocator.get_sw_cell_telemetry()
    sw_cell_eligible = cell_telem.get("eligible", False)
    day_first_eligible = cell_telem.get("day_first_eligible")
    sw_pasture_reserved = cell_telem.get("reserved", False) or sw_pasture_built

    # Future pasture opportunities after SW pasture built
    last_parsed = parse_observation(steps[-1][p_idx]["observation"])
    if last_parsed and last_parsed.get("farm") and sw_pasture_built:
        end_farm = last_parsed["farm"]
        final_total_pastures = sum(
            1 for t in end_farm.iter_tiles()
            if getattr(t, "kind", None) == "PASTURE" or
            (getattr(t, "is_animal", False) and config.ANIMALS.get(getattr(t, "animal", ""), {}).get("structure") == "PASTURE")
        )
        future_pastures_after_sw = max(0, final_total_pastures - total_pastures_at_day_built)
    else:
        future_pastures_after_sw = 0

    return {
        "arm": arm,
        "seed": seed,
        "final_reward": final_reward,
        "opp_reward": opp_reward,
        "win": final_reward > opp_reward,
        "tie": final_reward == opp_reward,
        "sw_purchased": sw_purchased,
        "sw_purchase_day": sw_purchase_day,
        "sw_purchase_hour": sw_purchase_hour,
        "sw_purchase_step": sw_purchase_step,
        # Locality metrics
        "retention_rate": retention_rate,
        "switches_per_worker_day": switches_per_worker_day,
        "time_in_home_pct": time_in_home_pct,
        "total_within_day_reassignments": loc_summary.get("total_within_day_reassignments", 0),
        "total_ne_sw_home_changes": loc_summary.get("total_ne_sw_home_changes", 0),
        "total_physical_ne_sw_traversals": loc_summary.get("total_physical_ne_sw_traversals", 0),
        "total_temporary_spillovers": loc_summary.get("total_temporary_spillovers", 0),
        "total_emergency_preemptions": loc_summary.get("total_emergency_preemptions", 0),
        # Action & Move counts
        "quad_moves": quad_moves,
        "quad_productive": quad_productive,
        "quad_ops_by_type": quad_ops_by_type,
        "estimated_production_value": estimated_prod_val,
        "move_ratio_overall": move_ratio_overall,
        "move_ratio_sw": move_ratio_sw,
        "sw_productive_actions": sw_productive_actions,
        "sw_movement_actions": sw_movement_actions,
        "sw_planted_unwatered_hours": sw_planted_unwatered_hours,
        "sw_ripe_unharvested_hours": sw_ripe_unharvested_hours,
        # Treatment-exposure metrics (Arm C-Cell)
        "sw_cell_eligible": sw_cell_eligible,
        "day_first_eligible": day_first_eligible,
        "sw_pasture_reserved": sw_pasture_reserved,
        "sw_pasture_built": sw_pasture_built,
        "day_built": day_built,
        "sw_pasture_occupied": sw_pasture_occupied,
        "day_occupied": day_occupied,
        "occupying_species": occupying_species,
        "occupied_pasture_days": occupied_pasture_days,
        "empty_sw_pasture_days": empty_sw_pasture_days,
        "future_pasture_opportunities_after_sw": future_pastures_after_sw,
        # Safety metrics
        "max_consecutive_unfed_seen": max_consecutive_unfed_seen,
        "animals_consec_ge_2": animals_consec_ge_2,
        "escaped_animals": escaped_animals,
        "feed_actions_completed_late": feed_actions_completed_late,
    }


def run_tournament(
    arms: List[str] = ("ArmA", "ArmB-P", "ArmC-Cell"),
    seeds: List[int] = list(range(100, 130)),
    max_workers: int = 4,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    print(f"================================================================")
    print(f"KAGGRICULTURE ARM C-CELL BENCHMARK TOURNAMENT")
    print(f"Arms: {arms}")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]})")
    print(f"Total Matches: {len(arms) * len(seeds)}")
    print(f"Workers: {max_workers}")
    print(f"================================================================")

    payloads = []
    for seed in seeds:
        for arm in arms:
            payloads.append({
                "arm": arm,
                "seed": seed,
                "opponent": "random",
                "agent_index": 0,
            })

    results_by_arm: Dict[str, List[Dict[str, Any]]] = {arm: [] for arm in arms}
    start_time = time.time()
    completed = 0
    total = len(payloads)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_match, p): p for p in payloads}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                res = fut.result()
                results_by_arm[res["arm"]].append(res)
                completed += 1
                elapsed = time.time() - start_time
                print(f"[{completed:03d}/{total:03d}] Finished {res['arm']:<9} seed={res['seed']} score={res['final_reward']:>9,.1f} (SW Pasture Built={res['sw_pasture_built']}, Occ={res['occupying_species']}) [{elapsed:.1f}s]")
            except Exception as e:
                print(f"ERROR on {p['arm']} seed={p['seed']}: {e}")
                import traceback
                traceback.print_exc()

    # Sort each arm by seed
    for arm in arms:
        results_by_arm[arm].sort(key=lambda x: x["seed"])

    # Aggregate & Statistical Analysis
    analysis = analyze_results(results_by_arm, arms, seeds)

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump({
                "arms": arms,
                "seeds": seeds,
                "analysis": analysis,
                "raw_results": results_by_arm,
            }, f, indent=2)
        print(f"\nSaved tournament results to {output_path}")

    return analysis


def analyze_results(results_by_arm: Dict[str, List[Dict[str, Any]]], arms: List[str], seeds: List[int]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}

    for arm in arms:
        res_list = results_by_arm[arm]
        scores = [r["final_reward"] for r in res_list]
        retentions = [r["retention_rate"] for r in res_list]
        switches = [r["switches_per_worker_day"] for r in res_list]
        ne_sw_changes = [r["total_ne_sw_home_changes"] for r in res_list]
        ne_sw_traversals = [r["total_physical_ne_sw_traversals"] for r in res_list]
        spillovers = [r["total_temporary_spillovers"] for r in res_list]
        moves_ratio = [r["move_ratio_overall"] for r in res_list]
        sw_moves_ratio = [r["move_ratio_sw"] for r in res_list]
        nw_prod = [r["quad_productive"].get("NW", 0) for r in res_list]
        ne_prod = [r["quad_productive"].get("NE", 0) for r in res_list]
        sw_prod = [r["quad_productive"].get("SW", 0) for r in res_list]
        core_prod = [nw + ne for nw, ne in zip(nw_prod, ne_prod)]

        # Semantic ops by quadrant and type
        nw_live = [r.get("quad_ops_by_type", {}).get("NW", {}).get("livestock", 0) for r in res_list]
        ne_live = [r.get("quad_ops_by_type", {}).get("NE", {}).get("livestock", 0) for r in res_list]
        sw_live = [r.get("quad_ops_by_type", {}).get("SW", {}).get("livestock", 0) for r in res_list]
        core_live = [nw + ne for nw, ne in zip(nw_live, ne_live)]

        nw_crops = [r.get("quad_ops_by_type", {}).get("NW", {}).get("crop", 0) for r in res_list]
        ne_crops = [r.get("quad_ops_by_type", {}).get("NE", {}).get("crop", 0) for r in res_list]
        sw_crops = [r.get("quad_ops_by_type", {}).get("SW", {}).get("crop", 0) for r in res_list]

        # Estimated Production Value
        nw_val = [r.get("estimated_production_value", {}).get("NW", 0.0) for r in res_list]
        ne_val = [r.get("estimated_production_value", {}).get("NE", 0.0) for r in res_list]
        sw_val = [r.get("estimated_production_value", {}).get("SW", 0.0) for r in res_list]
        core_val = [nw + ne for nw, ne in zip(nw_val, ne_val)]
        tot_val = [nw + ne + sw for nw, ne, sw in zip(nw_val, ne_val, sw_val)]

        # Treatment Exposure
        sw_eligible_count = sum(1 for r in res_list if r.get("sw_cell_eligible"))
        sw_built_count = sum(1 for r in res_list if r.get("sw_pasture_built"))
        sw_occ_count = sum(1 for r in res_list if r.get("sw_pasture_occupied"))
        built_days = [r["day_built"] for r in res_list if r.get("day_built") is not None]
        occ_days = [r["day_occupied"] for r in res_list if r.get("day_occupied") is not None]
        occ_pasture_days = [r.get("occupied_pasture_days", 0) for r in res_list]
        empty_pasture_days = [r.get("empty_sw_pasture_days", 0) for r in res_list]

        species_dist: Dict[str, int] = {}
        for r in res_list:
            sp = r.get("occupying_species")
            if sp:
                species_dist[sp] = species_dist.get(sp, 0) + 1

        max_unfed = [r["max_consecutive_unfed_seen"] for r in res_list]
        unfed_ge_2 = [r["animals_consec_ge_2"] for r in res_list]
        sw_bought = sum(1 for r in res_list if r["sw_purchased"])

        summary[arm] = {
            "n": len(scores),
            "score_mean": float(np.mean(scores)) if scores else 0.0,
            "score_std": float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0,
            "score_median": float(np.median(scores)) if scores else 0.0,
            "score_trimmed_mean": float(stats.trim_mean(scores, 0.1)) if scores else 0.0,
            "score_min": float(np.min(scores)) if scores else 0.0,
            "score_max": float(np.max(scores)) if scores else 0.0,
            "sw_purchase_count": sw_bought,
            "sw_purchase_rate": sw_bought / max(1, len(scores)),
            # Locality
            "retention_rate_mean": float(np.mean(retentions)) if retentions else 0.0,
            "switches_per_worker_day_mean": float(np.mean(switches)) if switches else 0.0,
            "ne_sw_home_changes_mean": float(np.mean(ne_sw_changes)) if ne_sw_changes else 0.0,
            "ne_sw_traversals_mean": float(np.mean(ne_sw_traversals)) if ne_sw_traversals else 0.0,
            "temporary_spillovers_mean": float(np.mean(spillovers)) if spillovers else 0.0,
            "move_ratio_mean": float(np.mean(moves_ratio)) if moves_ratio else 0.0,
            "sw_move_ratio_mean": float(np.mean(sw_moves_ratio)) if sw_moves_ratio else 0.0,
            # Core & SW Production Labor
            "core_productive_mean": float(np.mean(core_prod)) if core_prod else 0.0,
            "nw_productive_mean": float(np.mean(nw_prod)) if nw_prod else 0.0,
            "ne_productive_mean": float(np.mean(ne_prod)) if ne_prod else 0.0,
            "sw_productive_mean": float(np.mean(sw_prod)) if sw_prod else 0.0,
            "core_livestock_ops_mean": float(np.mean(core_live)) if core_live else 0.0,
            "sw_livestock_ops_mean": float(np.mean(sw_live)) if sw_live else 0.0,
            "core_crop_ops_mean": float(np.mean([nw + ne for nw, ne in zip(nw_crops, ne_crops)])) if nw_crops else 0.0,
            "sw_crop_ops_mean": float(np.mean(sw_crops)) if sw_crops else 0.0,
            # Primary Production Value
            "core_production_value_mean": float(np.mean(core_val)) if core_val else 0.0,
            "sw_production_value_mean": float(np.mean(sw_val)) if sw_val else 0.0,
            "total_production_value_mean": float(np.mean(tot_val)) if tot_val else 0.0,
            # Treatment Exposure (Arm C-Cell)
            "sw_cell_eligible_rate": sw_eligible_count / max(1, len(scores)),
            "sw_pasture_built_rate": sw_built_count / max(1, len(scores)),
            "sw_pasture_occupied_rate": sw_occ_count / max(1, len(scores)),
            "day_built_mean": float(np.mean(built_days)) if built_days else None,
            "day_occupied_mean": float(np.mean(occ_days)) if occ_days else None,
            "species_distribution": species_dist,
            "occupied_pasture_days_mean": float(np.mean(occ_pasture_days)) if occ_pasture_days else 0.0,
            "empty_sw_pasture_days_mean": float(np.mean(empty_pasture_days)) if empty_pasture_days else 0.0,
            # Safety
            "max_consecutive_unfed_seen": int(max(max_unfed)) if max_unfed else 0,
            "total_unfed_ge_2": int(sum(unfed_ge_2)) if unfed_ge_2 else 0,
        }

    # Paired comparisons
    comparisons = {}
    pair_keys = [("ArmC-Cell", "ArmB-P"), ("ArmB-P", "ArmA"), ("ArmC-Cell", "ArmA")]
    for arm_t, arm_c in pair_keys:
        if arm_t in results_by_arm and arm_c in results_by_arm:
            list_t = results_by_arm[arm_t]
            list_c = results_by_arm[arm_c]
            map_c = {r["seed"]: r for r in list_c}
            deltas = []
            core_prod_deltas = []
            core_live_deltas = []
            sw_prod_deltas = []
            sw_live_deltas = []
            traversal_deltas = []
            move_ratio_deltas = []
            core_val_deltas = []
            sw_val_deltas = []

            for rt in list_t:
                s = rt["seed"]
                if s in map_c:
                    rc = map_c[s]
                    d_score = rt["final_reward"] - rc["final_reward"]
                    deltas.append(d_score)

                    core_t = rt["quad_productive"].get("NW", 0) + rt["quad_productive"].get("NE", 0)
                    core_c = rc["quad_productive"].get("NW", 0) + rc["quad_productive"].get("NE", 0)
                    core_prod_deltas.append(core_t - core_c)

                    clive_t = rt.get("quad_ops_by_type", {}).get("NW", {}).get("livestock", 0) + rt.get("quad_ops_by_type", {}).get("NE", {}).get("livestock", 0)
                    clive_c = rc.get("quad_ops_by_type", {}).get("NW", {}).get("livestock", 0) + rc.get("quad_ops_by_type", {}).get("NE", {}).get("livestock", 0)
                    core_live_deltas.append(clive_t - clive_c)

                    sw_p_t = rt["quad_productive"].get("SW", 0)
                    sw_p_c = rc["quad_productive"].get("SW", 0)
                    sw_prod_deltas.append(sw_p_t - sw_p_c)

                    sw_l_t = rt.get("quad_ops_by_type", {}).get("SW", {}).get("livestock", 0)
                    sw_l_c = rc.get("quad_ops_by_type", {}).get("SW", {}).get("livestock", 0)
                    sw_live_deltas.append(sw_l_t - sw_l_c)

                    trav_t = rt.get("total_physical_ne_sw_traversals", 0)
                    trav_c = rc.get("total_physical_ne_sw_traversals", 0)
                    traversal_deltas.append(trav_t - trav_c)

                    move_ratio_deltas.append(rt["move_ratio_overall"] - rc["move_ratio_overall"])

                    cval_t = rt.get("estimated_production_value", {}).get("NW", 0.0) + rt.get("estimated_production_value", {}).get("NE", 0.0)
                    cval_c = rc.get("estimated_production_value", {}).get("NW", 0.0) + rc.get("estimated_production_value", {}).get("NE", 0.0)
                    core_val_deltas.append(cval_t - cval_c)

                    swval_t = rt.get("estimated_production_value", {}).get("SW", 0.0)
                    swval_c = rc.get("estimated_production_value", {}).get("SW", 0.0)
                    sw_val_deltas.append(swval_t - swval_c)

            n_pairs = len(deltas)
            if n_pairs > 1:
                t_stat, p_val = stats.ttest_rel(
                    [rt["final_reward"] for rt in list_t if rt["seed"] in map_c],
                    [map_c[rt["seed"]]["final_reward"] for rt in list_t if rt["seed"] in map_c],
                )
                try:
                    w_res = stats.wilcoxon(deltas)
                    w_pval = float(w_res.pvalue)
                except Exception:
                    w_pval = 1.0
                win_count = sum(1 for d in deltas if d > 0)
                tie_count = sum(1 for d in deltas if d == 0)
                loss_count = sum(1 for d in deltas if d < 0)
                win_rate = win_count / max(1, n_pairs - tie_count)
                ci_lower, ci_upper = compute_bootstrap_ci(deltas)
                trimmed_mean = float(stats.trim_mean(deltas, 0.1))
            else:
                t_stat, p_val, w_pval, win_rate = 0.0, 1.0, 1.0, 0.0
                win_count, tie_count, loss_count = 0, 0, 0
                ci_lower, ci_upper = 0.0, 0.0
                trimmed_mean = 0.0

            comparisons[f"{arm_t}_vs_{arm_c}"] = {
                "n_pairs": n_pairs,
                "delta_mean": float(np.mean(deltas)) if deltas else 0.0,
                "delta_trimmed_mean": trimmed_mean,
                "delta_median": float(np.median(deltas)) if deltas else 0.0,
                "delta_std": float(np.std(deltas, ddof=1)) if len(deltas) > 1 else 0.0,
                "delta_ci_95": [ci_lower, ci_upper],
                "delta_min": float(np.min(deltas)) if deltas else 0.0,
                "delta_max": float(np.max(deltas)) if deltas else 0.0,
                "win_count": win_count,
                "tie_count": tie_count,
                "loss_count": loss_count,
                "win_rate": float(win_rate),
                "paired_t_stat": float(t_stat),
                "paired_t_pval": float(p_val),
                "wilcoxon_pval": float(w_pval),
                # Semantic Labor deltas
                "core_prod_delta_mean": float(np.mean(core_prod_deltas)) if core_prod_deltas else 0.0,
                "core_live_delta_mean": float(np.mean(core_live_deltas)) if core_live_deltas else 0.0,
                "sw_prod_delta_mean": float(np.mean(sw_prod_deltas)) if sw_prod_deltas else 0.0,
                "sw_live_delta_mean": float(np.mean(sw_live_deltas)) if sw_live_deltas else 0.0,
                "physical_traversals_delta_mean": float(np.mean(traversal_deltas)) if traversal_deltas else 0.0,
                "move_ratio_delta_mean": float(np.mean(move_ratio_deltas)) if move_ratio_deltas else 0.0,
                "core_val_delta_mean": float(np.mean(core_val_deltas)) if core_val_deltas else 0.0,
                "sw_val_delta_mean": float(np.mean(sw_val_deltas)) if sw_val_deltas else 0.0,
            }

    print("\n================================================================")
    print("TOURNAMENT SUMMARY TABLE")
    print("================================================================")
    print(f"{'Arm':<10} | {'Score Mean':>11} | {'Retention':>10} | {'Sw/Day':>8} | {'NE<->SW':>8} | {'Core Prod':>10} | {'SW Prod':>8} | {'Core Val':>10} | {'SW Val':>9}")
    print("-" * 95)
    for arm in arms:
        s = summary[arm]
        print(f"{arm:<10} | {s['score_mean']:>11,.1f} | {s['retention_rate_mean']:>9.1f}% | {s['switches_per_worker_day_mean']:>8.2f} | {s['ne_sw_home_changes_mean']:>8.1f} | {s['core_productive_mean']:>10.1f} | {s['sw_productive_mean']:>8.1f} | ${s['core_production_value_mean']:>9,.0f} | ${s['sw_production_value_mean']:>8,.0f}")

    print("\n================================================================")
    print("PAIRED COMPARISONS")
    print("================================================================")
    for pair_name, c in comparisons.items():
        print(f"--- {pair_name} ---")
        ci = c["delta_ci_95"]
        print(f"  Delta Mean:     ${c['delta_mean']:+,.2f} [95% CI: ${ci[0]:+,.2f} .. ${ci[1]:+,.2f}]")
        print(f"  Trimmed Mean:   ${c['delta_trimmed_mean']:+,.2f} (Median: ${c['delta_median']:+,.2f})")
        print(f"  Win Rate:       {c['win_rate']*100:.1f}% ({c['win_count']}W / {c['tie_count']}T / {c['loss_count']}L, n={c['n_pairs']})")
        print(f"  Paired t-test:  p = {c['paired_t_pval']:.4f} (t = {c['paired_t_stat']:.3f})")
        print(f"  Wilcoxon p-val: p = {c['wilcoxon_pval']:.4f}")
        print(f"  Core NW+NE Δ:   {c['core_prod_delta_mean']:+.1f} actions (Livestock: {c['core_live_delta_mean']:+.1f})")
        print(f"  SW Productive Δ:{c['sw_prod_delta_mean']:+.1f} actions (Livestock: {c['sw_live_delta_mean']:+.1f})")
        print(f"  Phys Traversals:{c['physical_traversals_delta_mean']:+.1f}")
        print(f"  Production Val: Core Δ=${c['core_val_delta_mean']:+,.1f}, SW Δ=${c['sw_val_delta_mean']:+,.1f}")

    return {
        "arm_summaries": summary,
        "comparisons": comparisons,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kaggriculture Benchmark Tournament")
    parser.add_argument("--arms", type=str, default="ArmA,ArmB-P,ArmC-Cell", help="Comma-separated arms")
    parser.add_argument("--seeds", type=int, default=30, help="Number of seeds to run")
    parser.add_argument("--start-seed", type=int, default=100, help="Starting seed")
    parser.add_argument("--workers", type=int, default=4, help="Parallel worker processes")
    parser.add_argument("--output", type=str, default="simulations/experiments/results/cell_tournament_results.json")
    args = parser.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    run_tournament(arms=arms, seeds=seeds, max_workers=args.workers, output_path=args.output)
