"""Comprehensive Deep-Dive Audit of the Arm A Production Baseline (NW + NE).

Audits 15 representative seeds (100 to 114) turn-by-turn to measure:
1. Worker Efficiency (moves/op, travel distance, idle causes, NW vs NE time, cross-quadrant transit, shed trips, task latency).
2. Crop Utilization (NW vs NE, empty tile-days, planting delays, harvest latency, watering hours, value per tile-day, value per action).
3. Livestock Utilization (housing occupancy, animal output/op, feed timing, care rate, fertilizer collection rate, shed distance).
4. Labor Allocation & Hourly Capacity (morning crunch vs midday surplus, chore collisions).
5. Density & Spatial Agglomeration (distance to shed, clustering efficiency).
6. Marginal Economic Returns.
"""

import os
import sys
import json
import time
import math
from typing import Dict, Any, List, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")


def _run_audit_match(seed: int) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'sw_cell_allocator'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    from observation_parser import parse_observation
    import execution.task_scheduler as task_scheduler

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    task_scheduler.reset_worker_locality()

    # Enforce production baseline
    config.set_sw_experiment_arm("ArmA")

    # Tracking Structures
    SHED_TILES = {(4, 4), (5, 4), (4, 5), (5, 5)}

    # Worker metrics
    worker_turns_in_quad = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    moves_by_quad = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    prod_by_quad = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    total_travel_distance = 0
    total_actions_available = 0
    total_actions_used = 0
    total_idle_passes = 0
    idle_by_hour = [0] * 24
    used_by_hour = [0] * 24
    avail_by_hour = [0] * 24

    cross_nw_ne_field_transits = 0
    last_field_quad = {}
    prev_positions = {}

    shed_visits_total = 0
    shed_visits_zero_op = 0

    # Operational breakdown
    ops_breakdown = {
        "WATER": 0, "PLANT": 0, "HARVEST_CROP": 0, "HARVEST_ANIMAL": 0,
        "FEED": 0, "CARE": 0, "COLLECT_FERTILIZER": 0,
        "BUILD_PASTURE": 0, "BUILD_COOP": 0, "DIG": 0, "PICKUP": 0, "DROP": 0, "PASS": 0, "MOVE": 0
    }

    # Crop metrics
    nw_empty_tile_hours = 0
    ne_empty_tile_hours = 0
    nw_weed_tile_hours = 0
    ne_weed_tile_hours = 0
    nw_crop_tile_hours = 0
    ne_crop_tile_hours = 0

    crop_harvest_latency_hours = []  # hours ripe before harvested
    crop_planted_counts = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}
    crop_harvested_units = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}
    crop_revenue_est = {"WHEAT": 0.0, "CARROT": 0.0, "TOMATO": 0.0, "STRAWBERRY": 0.0, "MELON": 0.0}
    crop_ops_count = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}
    watering_by_hour = [0] * 24

    # Livestock metrics
    animal_counts_by_quad = {"NW": {"COW": 0, "SHEEP": 0, "GOOSE": 0}, "NE": {"COW": 0, "SHEEP": 0, "GOOSE": 0}}
    pastures_by_quad = {"NW": 0, "NE": 0}
    coops_by_quad = {"NW": 0, "NE": 0}
    pasture_occupied_hours = 0
    pasture_empty_hours = 0
    coop_occupied_hours = 0
    coop_empty_hours = 0

    feed_actions_early = 0  # < hour 14
    feed_actions_late = 0   # >= hour 14
    care_actions_completed = 0
    fertilizer_available_eod = 0
    fertilizer_collected_total = 0
    animal_harvest_latency_hours = []
    feed_pickup_distances = []
    livestock_chores_local = 0
    livestock_chores_cross = 0

    # Tracking per-tile state across turns
    tile_ripe_step = {}  # pos -> step when it became ripe
    animal_ripe_step = {} # pos -> step when yield_units reached max_held

    def tracking_agent(obs, configuration=None):
        nonlocal total_travel_distance, total_actions_available, total_actions_used, total_idle_passes
        nonlocal cross_nw_ne_field_transits, shed_visits_total, shed_visits_zero_op
        nonlocal nw_empty_tile_hours, ne_empty_tile_hours, nw_weed_tile_hours, ne_weed_tile_hours
        nonlocal nw_crop_tile_hours, ne_crop_tile_hours
        nonlocal pasture_occupied_hours, pasture_empty_hours, coop_occupied_hours, coop_empty_hours
        nonlocal feed_actions_early, feed_actions_late, care_actions_completed
        nonlocal fertilizer_available_eod, fertilizer_collected_total
        nonlocal livestock_chores_local, livestock_chores_cross

        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)

        # Clear worker positions at midnight
        if hour == 0:
            prev_positions.clear()
            last_field_quad.clear()

        parsed = parse_observation(obs)
        if parsed is None:
            return agent_module.agent(obs, configuration)

        farm = parsed["farm"]
        all_units = [farm.farmer] + farm.hands
        n_units = len(all_units)

        total_actions_available += n_units
        avail_by_hour[hour] += n_units

        # Tile accounting (NW and NE)
        for t in farm.iter_tiles():
            q = farm.quadrant_of(t.pos)
            if q not in ("NW", "NE"):
                continue

            if t.kind == "EMPTY":
                if q == "NW": nw_empty_tile_hours += 1
                elif q == "NE": ne_empty_tile_hours += 1
            elif t.kind == "WEED":
                if q == "NW": nw_weed_tile_hours += 1
                elif q == "NE": ne_weed_tile_hours += 1
            elif getattr(t, "is_plant", False) or getattr(t, "crop", None):
                if q == "NW": nw_crop_tile_hours += 1
                elif q == "NE": ne_crop_tile_hours += 1

                # Track ripe duration
                if t.yield_units > 0:
                    if t.pos not in tile_ripe_step:
                        tile_ripe_step[t.pos] = step
            elif getattr(t, "is_animal", False):
                if getattr(t, "yield_units", 0) >= config.ANIMALS.get(getattr(t, "animal", ""), {}).get("max_held", 4):
                    if t.pos not in animal_ripe_step:
                        animal_ripe_step[t.pos] = step

            if t.kind == "PASTURE":
                if getattr(t, "is_animal", False):
                    pasture_occupied_hours += 1
                else:
                    pasture_empty_hours += 1
            elif t.kind == "COOP":
                if getattr(t, "is_animal", False):
                    coop_occupied_hours += 1
                else:
                    coop_empty_hours += 1

            # End of day fertilizer audit
            if hour == 23 and getattr(t, "is_animal", False):
                if getattr(t, "fertilizer_available", False):
                    fertilizer_available_eod += 1

        # Call agent
        action = agent_module.agent(obs, configuration)

        farmer_act = action.get("farmer", ["PASS"])
        hands_act = action.get("hands", [])
        all_actions = [farmer_act] + hands_act

        for u_idx, act in enumerate(all_actions):
            if not act:
                act = ["PASS"]
            op = act[0]
            upos = all_units[u_idx] if u_idx < len(all_units) else (4, 4)
            uq = farm.quadrant_of(upos)
            worker_turns_in_quad[uq] = worker_turns_in_quad.get(uq, 0) + 1

            # Distance tracking
            prev = prev_positions.get(u_idx, upos)
            dist = abs(upos[0] - prev[0]) + abs(upos[1] - prev[1])
            prev_positions[u_idx] = upos
            total_travel_distance += dist

            # Shed visit tracking
            if upos in SHED_TILES:
                shed_visits_total += 1
                if op in ("PASS", "NORTH", "SOUTH", "EAST", "WEST"):
                    shed_visits_zero_op += 1

            # Field traversal tracking (NW field vs NE field)
            if upos not in SHED_TILES:
                last_q = last_field_quad.get(u_idx)
                if last_q in ("NW", "NE") and uq in ("NW", "NE") and last_q != uq:
                    cross_nw_ne_field_transits += 1
                last_field_quad[u_idx] = uq

            # Action classification
            if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                moves_by_quad[uq] = moves_by_quad.get(uq, 0) + 1
                ops_breakdown["MOVE"] += 1
                total_actions_used += 1
                used_by_hour[hour] += 1
            elif op == "PASS":
                total_idle_passes += 1
                idle_by_hour[hour] += 1
                ops_breakdown["PASS"] += 1
            else:
                prod_by_quad[uq] = prod_by_quad.get(uq, 0) + 1
                total_actions_used += 1
                used_by_hour[hour] += 1

                # Semantic action tracking
                if op == "WATER":
                    ops_breakdown["WATER"] += 1
                    watering_by_hour[hour] += 1
                    t = farm.tile_at(upos)
                    if t and t.crop:
                        crop_ops_count[t.crop] = crop_ops_count.get(t.crop, 0) + 1
                elif op == "PLANT":
                    ops_breakdown["PLANT"] += 1
                    c_name = act[1] if len(act) > 1 else ""
                    if c_name in crop_planted_counts:
                        crop_planted_counts[c_name] += 1
                        crop_ops_count[c_name] = crop_ops_count.get(c_name, 0) + 1
                elif op == "HARVEST":
                    t = farm.tile_at(upos)
                    if t and (getattr(t, "is_animal", False) or getattr(t, "animal", None)):
                        ops_breakdown["HARVEST_ANIMAL"] += 1
                        if upos in animal_ripe_step:
                            animal_harvest_latency_hours.append(step - animal_ripe_step[upos])
                            del animal_ripe_step[upos]
                    else:
                        ops_breakdown["HARVEST_CROP"] += 1
                        if t and t.crop:
                            c_name = t.crop
                            units = getattr(t, "yield_units", 0)
                            base_p = config.MARKET_PARAMS.get(c_name, {}).get("base", 0)
                            crop_harvested_units[c_name] = crop_harvested_units.get(c_name, 0) + units
                            crop_revenue_est[c_name] = crop_revenue_est.get(c_name, 0.0) + (units * base_p)
                            crop_ops_count[c_name] = crop_ops_count.get(c_name, 0) + 1
                        if upos in tile_ripe_step:
                            crop_harvest_latency_hours.append(step - tile_ripe_step[upos])
                            del tile_ripe_step[upos]
                elif op == "FEED":
                    ops_breakdown["FEED"] += 1
                    if hour < 14: feed_actions_early += 1
                    else: feed_actions_late += 1
                    # Track chore locality
                    worker_home = uq
                    if worker_home in ("NW", "NE"):
                        livestock_chores_local += 1
                    else:
                        livestock_chores_cross += 1
                elif op == "CARE":
                    ops_breakdown["CARE"] += 1
                    care_actions_completed += 1
                elif op == "COLLECT_FERTILIZER":
                    ops_breakdown["COLLECT_FERTILIZER"] += 1
                    fertilizer_collected_total += 1
                elif op == "BUILD_PASTURE":
                    ops_breakdown["BUILD_PASTURE"] += 1
                elif op == "BUILD_COOP":
                    ops_breakdown["BUILD_COOP"] += 1
                elif op == "DIG":
                    ops_breakdown["DIG"] += 1
                elif op == "PICKUP":
                    ops_breakdown["PICKUP"] += 1
                elif op == "DROP":
                    ops_breakdown["DROP"] += 1

        return action

    # Run match
    env = make("kaggriculture", configuration={"randomSeed": seed}, debug=True)
    steps = env.run([tracking_agent, "random"])
    final_score = steps[-1][0]["reward"] or 0.0

    # Final farm audit
    final_obs = parse_observation(steps[-1][0]["observation"])
    end_farm = final_obs["farm"] if final_obs else None
    if end_farm:
        for t in end_farm.iter_tiles():
            q = end_farm.quadrant_of(t.pos)
            if q in ("NW", "NE"):
                if getattr(t, "is_animal", False):
                    a = getattr(t, "animal", "")
                    if a in animal_counts_by_quad[q]:
                        animal_counts_by_quad[q][a] += 1
                if getattr(t, "kind", "") == "PASTURE":
                    pastures_by_quad[q] += 1
                elif getattr(t, "kind", "") == "COOP":
                    coops_by_quad[q] += 1

    total_productive = sum(prod_by_quad.values())
    total_moves = sum(moves_by_quad.values())

    return {
        "seed": seed,
        "final_score": final_score,
        "total_actions_available": total_actions_available,
        "total_actions_used": total_actions_used,
        "total_idle_passes": total_idle_passes,
        "idle_rate": total_idle_passes / max(1, total_actions_available),
        "total_travel_distance": total_travel_distance,
        "total_moves": total_moves,
        "total_productive": total_productive,
        "move_ratio_overall": total_moves / max(1, total_productive),
        "travel_per_productive_op": total_travel_distance / max(1, total_productive),
        "worker_turns_in_quad": worker_turns_in_quad,
        "moves_by_quad": moves_by_quad,
        "prod_by_quad": prod_by_quad,
        "cross_nw_ne_field_transits": cross_nw_ne_field_transits,
        "shed_visits_total": shed_visits_total,
        "shed_visits_zero_op": shed_visits_zero_op,
        "ops_breakdown": ops_breakdown,
        "idle_by_hour": idle_by_hour,
        "used_by_hour": used_by_hour,
        "avail_by_hour": avail_by_hour,
        "watering_by_hour": watering_by_hour,
        # Crop metrics
        "nw_empty_tile_days": nw_empty_tile_hours / 24.0,
        "ne_empty_tile_days": ne_empty_tile_hours / 24.0,
        "nw_weed_tile_days": nw_weed_tile_hours / 24.0,
        "ne_weed_tile_days": ne_weed_tile_hours / 24.0,
        "nw_crop_tile_days": nw_crop_tile_hours / 24.0,
        "ne_crop_tile_days": ne_crop_tile_hours / 24.0,
        "crop_harvest_latency_mean": float(np.mean(crop_harvest_latency_hours)) if crop_harvest_latency_hours else 0.0,
        "crop_planted_counts": crop_planted_counts,
        "crop_harvested_units": crop_harvested_units,
        "crop_revenue_est": crop_revenue_est,
        "crop_ops_count": crop_ops_count,
        # Livestock metrics
        "animal_counts_by_quad": animal_counts_by_quad,
        "pastures_by_quad": pastures_by_quad,
        "coops_by_quad": coops_by_quad,
        "pasture_occupied_days": pasture_occupied_hours / 24.0,
        "pasture_empty_days": pasture_empty_hours / 24.0,
        "coop_occupied_days": coop_occupied_hours / 24.0,
        "coop_empty_days": coop_empty_hours / 24.0,
        "feed_actions_early": feed_actions_early,
        "feed_actions_late": feed_actions_late,
        "care_actions_completed": care_actions_completed,
        "fertilizer_available_eod": fertilizer_available_eod,
        "fertilizer_collected_total": fertilizer_collected_total,
        "animal_harvest_latency_mean": float(np.mean(animal_harvest_latency_hours)) if animal_harvest_latency_hours else 0.0,
        "livestock_chores_local": livestock_chores_local,
        "livestock_chores_cross": livestock_chores_cross,
    }


def run_audit(seeds: List[int] = list(range(100, 115)), max_workers: int = 4, output_path: str = None) -> Dict[str, Any]:
    print(f"================================================================")
    print(f"PRODUCTION BASELINE (ARM A) DEEP-DIVE EFFICIENCY AUDIT")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Workers: {max_workers}")
    print(f"================================================================")

    results = []
    start_time = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_audit_match, s): s for s in seeds}
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                r = fut.result()
                results.append(r)
                elapsed = time.time() - start_time
                print(f"[{len(results):02d}/{len(seeds):02d}] Seed {r['seed']} Score=${r['final_score']:,.0f} | Moves/Op={r['move_ratio_overall']:.2f} | Idle={r['idle_rate']*100:.1f}% [{elapsed:.1f}s]")
            except Exception as e:
                print(f"ERROR on seed {s}: {e}")
                import traceback
                traceback.print_exc()

    results.sort(key=lambda x: x["seed"])

    # Aggregate Metrics
    n = len(results)
    scores = [r["final_score"] for r in results]
    move_ratios = [r["move_ratio_overall"] for r in results]
    travel_per_op = [r["travel_per_productive_op"] for r in results]
    idle_rates = [r["idle_rate"] * 100.0 for r in results]
    cross_transits = [r["cross_nw_ne_field_transits"] for r in results]
    shed_visits = [r["shed_visits_total"] for r in results]
    zero_op_shed = [r["shed_visits_zero_op"] for r in results]

    nw_empty_days = [r["nw_empty_tile_days"] for r in results]
    ne_empty_days = [r["ne_empty_tile_days"] for r in results]
    crop_latencies = [r["crop_harvest_latency_mean"] for r in results]
    anim_latencies = [r["animal_harvest_latency_mean"] for r in results]
    uncollected_fert = [r["fertilizer_available_eod"] for r in results]
    collected_fert = [r["fertilizer_collected_total"] for r in results]

    # Ops sum
    total_ops = {}
    for r in results:
        for k, v in r["ops_breakdown"].items():
            total_ops[k] = total_ops.get(k, 0) + v
    avg_ops = {k: v / n for k, v in total_ops.items()}

    # Hourly labor profile
    avg_avail_by_hour = [sum(r["avail_by_hour"][h] for r in results) / n for h in range(24)]
    avg_used_by_hour = [sum(r["used_by_hour"][h] for r in results) / n for h in range(24)]
    avg_idle_by_hour = [sum(r["idle_by_hour"][h] for r in results) / n for h in range(24)]
    avg_watering_by_hour = [sum(r["watering_by_hour"][h] for r in results) / n for h in range(24)]

    # Crop economics
    crop_names = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
    crop_summary = {}
    for c in crop_names:
        planted = sum(r["crop_planted_counts"].get(c, 0) for r in results) / n
        harvested = sum(r["crop_harvested_units"].get(c, 0) for r in results) / n
        rev = sum(r["crop_revenue_est"].get(c, 0.0) for r in results) / n
        ops = sum(r["crop_ops_count"].get(c, 0) for r in results) / n
        crop_summary[c] = {
            "avg_planted_tiles": planted,
            "avg_harvested_units": harvested,
            "avg_revenue": rev,
            "avg_ops": ops,
            "revenue_per_op": rev / max(1, ops),
            "revenue_per_plant": rev / max(1, planted),
        }

    # Animals
    avg_cows_nw = sum(r["animal_counts_by_quad"]["NW"]["COW"] for r in results) / n
    avg_sheep_nw = sum(r["animal_counts_by_quad"]["NW"]["SHEEP"] for r in results) / n
    avg_cows_ne = sum(r["animal_counts_by_quad"]["NE"]["COW"] for r in results) / n
    avg_sheep_ne = sum(r["animal_counts_by_quad"]["NE"]["SHEEP"] for r in results) / n

    audit_report = {
        "n_seeds": n,
        "score_mean": float(np.mean(scores)),
        "score_median": float(np.median(scores)),
        "score_min": float(np.min(scores)),
        "score_max": float(np.max(scores)),
        "worker_efficiency": {
            "moves_per_productive_op_mean": float(np.mean(move_ratios)),
            "travel_dist_per_productive_op_mean": float(np.mean(travel_per_op)),
            "idle_rate_mean_pct": float(np.mean(idle_rates)),
            "cross_nw_ne_field_transits_mean": float(np.mean(cross_transits)),
            "shed_visits_mean": float(np.mean(shed_visits)),
            "shed_visits_zero_op_mean": float(np.mean(zero_op_shed)),
            "shed_zero_op_pct": float(np.mean(zero_op_shed)) / max(1, float(np.mean(shed_visits))),
            "actions_breakdown_per_game": avg_ops,
            "hourly_avail": avg_avail_by_hour,
            "hourly_used": avg_used_by_hour,
            "hourly_idle": avg_idle_by_hour,
            "hourly_watering": avg_watering_by_hour,
        },
        "crop_utilization": {
            "nw_empty_tile_days_mean": float(np.mean(nw_empty_days)),
            "ne_empty_tile_days_mean": float(np.mean(ne_empty_days)),
            "crop_harvest_latency_mean_hours": float(np.mean(crop_latencies)),
            "crop_economics_by_species": crop_summary,
        },
        "livestock_utilization": {
            "nw_cows_mean": avg_cows_nw,
            "nw_sheep_mean": avg_sheep_nw,
            "ne_cows_mean": avg_cows_ne,
            "ne_sheep_mean": avg_sheep_ne,
            "total_animals_mean": avg_cows_nw + avg_sheep_nw + avg_cows_ne + avg_sheep_ne,
            "animal_harvest_latency_mean_hours": float(np.mean(anim_latencies)),
            "fertilizer_collected_mean": float(np.mean(collected_fert)),
            "fertilizer_lost_eod_mean": float(np.mean(uncollected_fert)),
            "fertilizer_collection_efficiency_pct": float(np.mean(collected_fert)) / max(1, float(np.mean(collected_fert)) + float(np.mean(uncollected_fert))) * 100.0,
            "feed_early_mean": float(np.mean([r["feed_actions_early"] for r in results])),
            "feed_late_mean": float(np.mean([r["feed_actions_late"] for r in results])),
            "care_actions_mean": float(np.mean([r["care_actions_completed"] for r in results])),
        },
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(audit_report, f, indent=2)
        print(f"\nSaved audit report to {output_path}")

    # Print summary
    print("\n================================================================")
    print("PRODUCTION BASELINE (ARM A) EFFICIENCY AUDIT SUMMARY")
    print("================================================================")
    print(f"Mean Score:               ${audit_report['score_mean']:,.1f} (Median: ${audit_report['score_median']:,.1f})")
    print(f"Moves / Productive Op:    {audit_report['worker_efficiency']['moves_per_productive_op_mean']:.2f}")
    print(f"Travel / Productive Op:   {audit_report['worker_efficiency']['travel_dist_per_productive_op_mean']:.2f} tiles")
    print(f"Worker Idle Rate:         {audit_report['worker_efficiency']['idle_rate_mean_pct']:.1f}% ({audit_report['worker_efficiency']['actions_breakdown_per_game'].get('PASS', 0):.1f} turns/game)")
    print(f"Cross NW<->NE Transits:   {audit_report['worker_efficiency']['cross_nw_ne_field_transits_mean']:.1f} field transits/game")
    print(f"Shed Visits Total:        {audit_report['worker_efficiency']['shed_visits_mean']:.1f} (Zero-Op Shed Steps: {audit_report['worker_efficiency']['shed_visits_zero_op_mean']:.1f}, {audit_report['worker_efficiency']['shed_zero_op_pct']*100:.1f}%)")
    print(f"\n--- Crop Utilization ---")
    print(f"NW Empty Tile-Days:       {audit_report['crop_utilization']['nw_empty_tile_days_mean']:.1f} tile-days ({audit_report['crop_utilization']['nw_empty_tile_days_mean']/30:.2f} tiles permanently empty)")
    print(f"NE Empty Tile-Days:       {audit_report['crop_utilization']['ne_empty_tile_days_mean']:.1f} tile-days ({audit_report['crop_utilization']['ne_empty_tile_days_mean']/30:.2f} tiles permanently empty)")
    print(f"Crop Harvest Latency:     {audit_report['crop_utilization']['crop_harvest_latency_mean_hours']:.1f} hours ripe before harvest")
    for c, info in audit_report['crop_utilization']['crop_economics_by_species'].items():
        print(f"  {c:<10}: Planted={info['avg_planted_tiles']:.1f} | Rev=${info['avg_revenue']:,.0f} | Ops={info['avg_ops']:.1f} | $/Op=${info['revenue_per_op']:.1f}")
    print(f"\n--- Livestock Utilization ---")
    print(f"Total Animals:            {audit_report['livestock_utilization']['total_animals_mean']:.1f} (NW: {avg_cows_nw:.1f}C/{avg_sheep_nw:.1f}S, NE: {avg_cows_ne:.1f}C/{avg_sheep_ne:.1f}S)")
    print(f"Animal Harvest Latency:   {audit_report['livestock_utilization']['animal_harvest_latency_mean_hours']:.1f} hours max-held before milking/shearing")
    print(f"Fertilizer Collection:    {audit_report['livestock_utilization']['fertilizer_collection_efficiency_pct']:.1f}% collected ({audit_report['livestock_utilization']['fertilizer_lost_eod_mean']:.1f} lost/game = ${audit_report['livestock_utilization']['fertilizer_lost_eod_mean']*100:,.0f} left on table)")
    print(f"Feed Timing:              {audit_report['livestock_utilization']['feed_early_mean']:.1f} early vs {audit_report['livestock_utilization']['feed_late_mean']:.1f} late")

    return audit_report


if __name__ == "__main__":
    seeds = list(range(100, 115))
    run_audit(seeds=seeds, max_workers=4, output_path="simulations/experiments/results/arm_a_audit_report.json")
