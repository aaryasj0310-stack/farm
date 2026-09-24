"""Phase C0-B & C: Controlled Soft Worker Locality Experiment.

Evaluates CONTROL (SOFT_WORKER_LOCALITY_MODE = "OFF") vs TREATMENT (SOFT_WORKER_LOCALITY_MODE = "ON")
across the frozen discovery matrix:
- 10 discovery seeds: 96501–96510
- 5 benchmark opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 seats: 0, 1
- Total: 100 paired configurations (200 real-engine matches)

Generates deliverables in simulations/results/phase_c0_soft_locality/:
1. manifest.json
2. paired_results.json
3. aggregate_tables.json
4. worker_execution_comparison.json
5. crop_service_comparison.json
6. safety_results.json
7. representative_traces.json
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_c0_soft_locality")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_SEEDS = list(range(96501, 96511))  # 96501–96510
SMOKE_SEEDS = [96501, 96502]
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
SEED_PRICES = {"WHEAT": 10.0, "CARROT": 20.0, "TOMATO": 50.0, "STRAWBERRY": 100.0, "MELON": 80.0}
CROPS = list(SEED_PRICES.keys())
ANIMAL_COSTS = {"GOOSE": 300.0, "COW": 400.0, "SHEEP": 500.0}
ANIMALS = list(ANIMAL_COSTS.keys())
CROP_MATURITY = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}

SHED_ACCESS_TILES = {(4, 4), (5, 4), (4, 5), (5, 5)}
FARMER_MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}


def _fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


def _quadrant_of(x: int, y: int) -> str:
    return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def run_single_simulation(seed: int, opp_name: str, seat: int, locality_mode: str) -> Dict[str, Any]:
    """Run one single match under specified locality mode ('OFF' or 'ON')."""
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    from kaggle_environments import make
    import config
    from agent.main import agent, reset_agent_state, get_last_turn_telemetry
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode(locality_mode)
    reset_agent_state()
    reset_sw_tranche_controller()

    opp_agent = get_agent(opp_name)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    _ = env.reset()

    worker_stats = {
        "total_worker_turns": 0,
        "emitted_moves": 0,
        "executed_moves": 0,
        "failed_moves": 0,
        "productive_moves": 0,
        "moves_to_shed": 0,
        "executed_ops": 0,
        "failed_ops": 0,
        "idle_turns": 0,
        "quadrant_crossings": 0,
        "repeated_crossings": 0,
        "shed_visits": 0,
    }

    worker_journey: Dict[int, Dict[str, Any]] = {}
    active_crop_cycles: Dict[Tuple[int, int], Dict[str, Any]] = {}
    completed_crop_cycles: List[Dict[str, Any]] = []
    tile_last_harvest: Dict[Tuple[int, int], int] = {}
    replanting_delays: List[int] = []

    financial_stats = {
        "total_sales_revenue": 0.0,
        "executed_spending": {"hires": 0.0, "land": 0.0, "animals": 0.0, "seeds": 0.0},
        "orders_emitted": 0,
        "orders_executed": 0,
        "orders_dropped": 0,
        "peak_shed_occupancy": 0,
        "shed_full_turns": 0,
    }

    safety_stats = {
        "feeding_due": 0,
        "feeding_executed": 0,
        "animal_escapes": 0,
        "animals_purchased": 0,
    }

    while not env.done:
        s0 = env.state[seat].observation
        s1 = env.state[1 - seat].observation
        farm0 = s0.farms[seat]
        priv0 = s0.private
        step = env.state[0].observation.step
        day = s0.day
        hour = s0.hour

        cash_before = float(farm0.money)
        unlocked = list(farm0.unlocked_quadrants)

        # Track crop states
        for y in range(10):
            for x in range(10):
                pos = (x, y)
                quad = _quadrant_of(x, y)
                if quad not in ("NW", "NE") or quad not in unlocked:
                    continue

                tile = farm0.tiles[y][x]
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop_name = tile.get("crop", "WHEAT")
                    p_day = tile.get("planted_day", day)
                    if pos not in active_crop_cycles:
                        active_crop_cycles[pos] = {
                            "tile": pos, "crop": crop_name, "planted_step": step,
                            "planted_day": p_day, "first_ready": None, "harvest_step": None,
                            "delay_hours": 0,
                        }
                    cycle = active_crop_cycles[pos]
                    age = day - p_day
                    mat_day = CROP_MATURITY.get(crop_name, 2)
                    if age >= mat_day and tile.get("yield_units", 0) > 0 and cycle["first_ready"] is None:
                        cycle["first_ready"] = step
                elif isinstance(tile, dict) and "animal" in tile:
                    if hour == 0:
                        safety_stats["feeding_due"] += 1

        # Execute our agent
        act0 = agent(s0, env.configuration)
        farmer_act = act0.get("farmer", ["PASS"])
        hand_acts = act0.get("hands", [])
        all_actions = [farmer_act] + hand_acts
        positions_before = [tuple(farm0.farmer)] + [tuple(h) for h in farm0.hands]
        worker_stats["total_worker_turns"] += len(all_actions)

        emitted_market = act0.get("market", [])
        financial_stats["orders_emitted"] += len(emitted_market)

        # Opponent turn
        try:
            act1 = opp_agent(s1, env.configuration)
        except TypeError:
            act1 = opp_agent(s1)

        actions = [act0, act1] if seat == 0 else [act1, act0]
        env.step(actions)

        # Post-step observation
        s0_post = env.state[seat].observation
        farm0_post = s0_post.farms[seat]
        priv0_post = s0_post.private
        cash_after = float(farm0_post.money)
        positions_after = [tuple(farm0_post.farmer)] + [tuple(h) for h in farm0_post.hands]

        # Verify worker actions
        for w_idx, a in enumerate(all_actions):
            op = a[0] if isinstance(a, (list, tuple)) and len(a) > 0 else "PASS"
            pos_b = positions_before[w_idx] if w_idx < len(positions_before) else None
            pos_a = positions_after[w_idx] if w_idx < len(positions_after) else None

            if op in FARMER_MOVES:
                worker_stats["emitted_moves"] += 1
                if pos_b is not None and pos_a is not None and pos_b != pos_a:
                    worker_stats["executed_moves"] += 1
                    qb = _quadrant_of(pos_b[0], pos_b[1])
                    qa = _quadrant_of(pos_a[0], pos_a[1])
                    if qb != qa:
                        worker_stats["quadrant_crossings"] += 1
                        if w_idx in worker_journey and worker_journey[w_idx].get("last_quad") == qa:
                            worker_stats["repeated_crossings"] += 1

                    if pos_a in SHED_ACCESS_TILES:
                        worker_stats["shed_visits"] += 1
                        worker_stats["moves_to_shed"] += 1
                    else:
                        worker_stats["productive_moves"] += 1
                else:
                    worker_stats["failed_moves"] += 1

            elif op == "PASS":
                worker_stats["idle_turns"] += 1

            else:
                worker_stats["executed_ops"] += 1
                if op == "FEED":
                    safety_stats["feeding_executed"] += 1
                elif op == "HARVEST":
                    if pos_b and pos_b in active_crop_cycles:
                        c_info = active_crop_cycles[pos_b]
                        c_info["harvest_step"] = step
                        if c_info["first_ready"] is not None:
                            c_info["delay_hours"] = max(0, step - c_info["first_ready"])
                        completed_crop_cycles.append(c_info)
                        del active_crop_cycles[pos_b]
                        tile_last_harvest[pos_b] = step
                elif op == "PLANT":
                    if pos_b and pos_b in tile_last_harvest:
                        replanting_delays.append(step - tile_last_harvest[pos_b])
                        del tile_last_harvest[pos_b]

            if pos_a:
                if w_idx not in worker_journey:
                    worker_journey[w_idx] = {}
                worker_journey[w_idx]["last_quad"] = _quadrant_of(pos_a[0], pos_a[1])

        # Financial deltas
        cash_delta = cash_after - cash_before
        if cash_delta > 0:
            financial_stats["total_sales_revenue"] += cash_delta

        # Hires
        new_hands = len(farm0_post.hands) - len(farm0.hands)
        if new_hands > 0:
            for h_n in range(farm0.hires_today, farm0.hires_today + new_hands):
                financial_stats["executed_spending"]["hires"] += float(_fib(h_n))
            financial_stats["orders_executed"] += new_hands

        # Land
        if len(farm0_post.unlocked_quadrants) > len(farm0.unlocked_quadrants):
            financial_stats["executed_spending"]["land"] += 1000.0
            financial_stats["orders_executed"] += 1

        # Seeds
        for c in CROPS:
            sdiff = priv0_post.seeds.get(c, 0) - priv0.seeds.get(c, 0)
            if sdiff > 0:
                financial_stats["executed_spending"]["seeds"] += sdiff * SEED_PRICES.get(c, 10.0)
                financial_stats["orders_executed"] += 1

        # Animals
        for a_name in ANIMALS:
            cnt_post = sum(1 for y in range(10) for x in range(10)
                           if isinstance(farm0_post.tiles[y][x], dict) and farm0_post.tiles[y][x].get("animal") == a_name)
            cnt_pre = sum(1 for y in range(10) for x in range(10)
                          if isinstance(farm0.tiles[y][x], dict) and farm0.tiles[y][x].get("animal") == a_name)
            adiff = cnt_post - cnt_pre
            if adiff > 0:
                financial_stats["executed_spending"]["animals"] += adiff * ANIMAL_COSTS.get(a_name, 300.0)
                safety_stats["animals_purchased"] += adiff
                financial_stats["orders_executed"] += adiff

        # Shed occupancy
        shed_occ = sum(priv0_post.shed.values())
        financial_stats["peak_shed_occupancy"] = max(financial_stats["peak_shed_occupancy"], shed_occ)
        if shed_occ >= 95:
            financial_stats["shed_full_turns"] += 1

        # Animal escapes
        if hour == 23:
            for y in range(10):
                for x in range(10):
                    t = farm0_post.tiles[y][x]
                    if isinstance(t, dict) and "animal" in t:
                        if t.get("consecutive_unfed", 0) >= 2:
                            safety_stats["animal_escapes"] += 1

    # End of match
    final_farm = env.state[seat].observation.farms[seat]
    final_cash = float(final_farm.money)

    financial_stats["orders_dropped"] = max(0, financial_stats["orders_emitted"] - financial_stats["orders_executed"])

    mean_h_delay = (
        sum(c["delay_hours"] for c in completed_crop_cycles) / max(1, len(completed_crop_cycles))
    )
    mean_replant = (
        sum(d for d in replanting_delays if d < 24) / max(1, sum(1 for d in replanting_delays if d < 24))
        if replanting_delays else 0.0
    )

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "locality_mode": locality_mode,
        "final_cash": final_cash,
        "worker_stats": worker_stats,
        "crop_stats": {
            "completed_cycles": len(completed_crop_cycles),
            "unharvested_at_end": len(active_crop_cycles),
            "mean_harvest_delay_hours": round(mean_h_delay, 2),
            "mean_replant_delay_hours": round(mean_replant, 2),
        },
        "financial_stats": financial_stats,
        "safety_stats": safety_stats,
    }


def run_paired_configuration(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    """Execute CONTROL ('OFF') and TREATMENT ('ON') for a single configuration."""
    ctrl = run_single_simulation(seed, opp_name, seat, locality_mode="OFF")
    treat = run_single_simulation(seed, opp_name, seat, locality_mode="ON")

    cash_diff = treat["final_cash"] - ctrl["final_cash"]
    move_diff = treat["worker_stats"]["executed_moves"] - ctrl["worker_stats"]["executed_moves"]
    ops_diff = treat["worker_stats"]["executed_ops"] - ctrl["worker_stats"]["executed_ops"]
    cross_diff = treat["worker_stats"]["quadrant_crossings"] - ctrl["worker_stats"]["quadrant_crossings"]

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "control_final_cash": ctrl["final_cash"],
        "treatment_final_cash": treat["final_cash"],
        "paired_cash_delta": round(cash_diff, 2),
        "control_moves": ctrl["worker_stats"]["executed_moves"],
        "treatment_moves": treat["worker_stats"]["executed_moves"],
        "move_delta": move_diff,
        "control_ops": ctrl["worker_stats"]["executed_ops"],
        "treatment_ops": treat["worker_stats"]["executed_ops"],
        "ops_delta": ops_diff,
        "control_crossings": ctrl["worker_stats"]["quadrant_crossings"],
        "treatment_crossings": treat["worker_stats"]["quadrant_crossings"],
        "crossings_delta": cross_diff,
        "control_crops_completed": ctrl["crop_stats"]["completed_cycles"],
        "treatment_crops_completed": treat["crop_stats"]["completed_cycles"],
        "control_escapes": ctrl["safety_stats"]["animal_escapes"],
        "treatment_escapes": treat["safety_stats"]["animal_escapes"],
        "control_full": ctrl,
        "treatment_full": treat,
    }


def compute_statistics(paired_results: List[Dict[str, Any]], seeds_list: List[int]) -> Dict[str, Any]:
    deltas = [p["paired_cash_delta"] for p in paired_results]
    n = len(deltas)
    sorted_d = sorted(deltas)

    mean_delta = sum(deltas) / n
    median_delta = sorted_d[n // 2] if n % 2 == 1 else (sorted_d[n // 2 - 1] + sorted_d[n // 2]) / 2.0
    pos_pairs = sum(1 for d in deltas if d > 0)
    neg_pairs = sum(1 for d in deltas if d < 0)
    ties = sum(1 for d in deltas if d == 0)

    p10 = sorted_d[int(0.10 * n)]
    p25 = sorted_d[int(0.25 * n)]
    p50 = median_delta
    p75 = sorted_d[int(0.75 * n)]
    p90 = sorted_d[int(0.90 * n)]
    worst_reg = sorted_d[0]

    # Delta by opponent
    by_opp: Dict[str, List[float]] = {}
    for p in paired_results:
        by_opp.setdefault(p["opp_name"], []).append(p["paired_cash_delta"])
    mean_by_opp = {k: round(sum(v) / len(v), 2) for k, v in by_opp.items()}

    # Delta by seat
    by_seat: Dict[int, List[float]] = {}
    for p in paired_results:
        by_seat.setdefault(p["seat"], []).append(p["paired_cash_delta"])
    mean_by_seat = {str(k): round(sum(v) / len(v), 2) for k, v in by_seat.items()}

    # Delta by seed
    by_seed: Dict[int, List[float]] = {}
    for p in paired_results:
        by_seed.setdefault(p["seed"], []).append(p["paired_cash_delta"])
    mean_by_seed = {str(k): round(sum(v) / len(v), 2) for k, v in by_seed.items()}

    # Seed-clustered 95% Confidence Interval
    # Each cluster is a seed containing 10 matches (5 opponents x 2 seats)
    seed_means = [sum(by_seed[s]) / len(by_seed[s]) for s in seeds_list if s in by_seed]
    n_seeds = len(seed_means)
    if n_seeds > 1:
        s_mean = sum(seed_means) / n_seeds
        s_variance = sum((x - s_mean) ** 2 for x in seed_means) / (n_seeds - 1)
        s_se = math.sqrt(s_variance / n_seeds)
        # Student-t critical value for 95% two-sided CI
        t_values = {
            1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
            6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228
        }
        t_crit = t_values.get(n_seeds - 1, 2.0)
        ci_lower = round(s_mean - t_crit * s_se, 2)
        ci_upper = round(s_mean + t_crit * s_se, 2)
    else:
        ci_lower = mean_delta
        ci_upper = mean_delta

    return {
        "sample_size": n,
        "mean_paired_cash_delta": round(mean_delta, 2),
        "median_paired_cash_delta": round(median_delta, 2),
        "positive_pairs": pos_pairs,
        "negative_pairs": neg_pairs,
        "ties": ties,
        "win_rate_pct": round(100.0 * pos_pairs / n, 1),
        "p10": round(p10, 2),
        "p25": round(p25, 2),
        "p50": round(p50, 2),
        "p75": round(p75, 2),
        "p90": round(p90, 2),
        "worst_paired_regression": round(worst_reg, 2),
        "mean_delta_by_opponent": mean_by_opp,
        "mean_delta_by_seat": mean_by_seat,
        "mean_delta_by_seed": mean_by_seed,
        "seed_clustered_95_ci": [ci_lower, ci_upper],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Run 2-seed smoke test")
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 4, 8), help="Parallel workers")
    args = parser.parse_args()

    seeds = SMOKE_SEEDS if args.smoke else DEFAULT_SEEDS
    commit_sha = get_git_commit()
    print("=" * 80)
    print(f"Starting Phase C0 Controlled Soft Worker Locality Experiment")
    print(f"Commit: {commit_sha}")
    print(f"Mode: {'SMOKE (2 seeds)' if args.smoke else 'FULL (10 seeds)'}")
    print(f"Seeds: {seeds}")
    print(f"Opponents: {BENCHMARK_OPPONENTS}")
    print(f"Seats: {SEATS}")
    print(f"Configurations: {len(seeds) * len(BENCHMARK_OPPONENTS) * len(SEATS)} paired pairs ({len(seeds) * len(BENCHMARK_OPPONENTS) * len(SEATS) * 2} real matches)")
    print("=" * 80)

    start_time = time.time()
    configs = [
        (s, opp, seat)
        for s in seeds
        for opp in BENCHMARK_OPPONENTS
        for seat in SEATS
    ]

    paired_results: List[Dict[str, Any]] = []
    checkpoint_file = os.path.join(OUT_DIR, "paired_results_checkpoint.json")

    # Load existing checkpoint if available
    completed_keys = set()
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r") as f:
                saved = json.load(f)
                if isinstance(saved, list):
                    for item in saved:
                        if isinstance(item, dict) and "seed" in item and "opp_name" in item and "seat" in item:
                            paired_results.append(item)
                            completed_keys.add((item["seed"], item["opp_name"], item["seat"]))
            print(f"Loaded {len(paired_results)} existing results from checkpoint.")
        except Exception:
            pass

    max_workers = min(args.workers, 4)

    for s_idx, seed in enumerate(seeds):
        seed_configs = [
            (seed, opp, seat)
            for opp in BENCHMARK_OPPONENTS
            for seat in SEATS
            if (seed, opp, seat) not in completed_keys
        ]
        if not seed_configs:
            print(f"Seed {seed} ({s_idx+1}/{len(seeds)}) already complete, skipping.")
            continue

        print(f"\n--- Running Seed {seed} ({s_idx+1}/{len(seeds)}) with {len(seed_configs)} configurations ---")
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_paired_configuration, s, opp, seat): (s, opp, seat)
                for (s, opp, seat) in seed_configs
            }
            for f in as_completed(futures):
                cfg = futures[f]
                try:
                    res = f.result()
                    paired_results.append(res)
                    completed_keys.add(cfg)
                    print(f"Done cfg {cfg}: CTRL=${res['control_final_cash']:,.0f} | TREAT=${res['treatment_final_cash']:,.0f} | DELTA=${res['paired_cash_delta']:+,.0f} | MoveDelta={res['move_delta']:+d} | CrossDelta={res['crossings_delta']:+d}")
                except Exception as e:
                    import traceback
                    print(f"ERROR on paired cfg {cfg}: {e}\n{traceback.format_exc()}")

        # Checkpoint after each seed
        with open(checkpoint_file, "w") as f:
            json.dump([
                {
                    "seed": p["seed"],
                    "opp_name": p["opp_name"],
                    "seat": p["seat"],
                    "control_final_cash": p["control_final_cash"],
                    "treatment_final_cash": p["treatment_final_cash"],
                    "paired_cash_delta": p["paired_cash_delta"],
                    "move_delta": p["move_delta"],
                    "ops_delta": p["ops_delta"],
                    "crossings_delta": p["crossings_delta"],
                    "control_escapes": p["control_escapes"],
                    "treatment_escapes": p["treatment_escapes"],
                    "control_crops_completed": p.get("control_crops_completed", 0),
                    "treatment_crops_completed": p.get("treatment_crops_completed", 0),
                    "control_moves": p.get("control_moves", 0),
                    "treatment_moves": p.get("treatment_moves", 0),
                    "control_ops": p.get("control_ops", 0),
                    "treatment_ops": p.get("treatment_ops", 0),
                    "control_crossings": p.get("control_crossings", 0),
                    "treatment_crossings": p.get("treatment_crossings", 0),
                }
                for p in paired_results
            ], f, indent=2)

    elapsed = time.time() - start_time
    print(f"\nCompleted {len(paired_results)} paired configurations in {elapsed:.2f}s.")

    # Compute statistics
    stats = compute_statistics(paired_results, seeds)

    # 1. Manifest
    manifest = {
        "experiment": "Phase C0: Soft Worker Locality Controlled Experiment",
        "commit_sha": commit_sha,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "configuration": {
            "control": {"SOFT_WORKER_LOCALITY_MODE": "OFF", "SW_FORWARD_ARCHITECTURE_MODE": "OFF"},
            "treatment": {"SOFT_WORKER_LOCALITY_MODE": "ON", "SW_FORWARD_ARCHITECTURE_MODE": "OFF"},
            "seeds": seeds,
            "opponents": BENCHMARK_OPPONENTS,
            "seats": SEATS,
            "total_paired_configurations": len(paired_results),
            "total_matches_executed": len(paired_results) * 2,
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "elapsed_seconds": round(elapsed, 2),
    }

    # 2. Paired Results (Summary)
    paired_summary = [
        {
            "seed": p["seed"],
            "opp_name": p["opp_name"],
            "seat": p["seat"],
            "control_final_cash": p["control_final_cash"],
            "treatment_final_cash": p["treatment_final_cash"],
            "paired_cash_delta": p["paired_cash_delta"],
            "move_delta": p["move_delta"],
            "ops_delta": p["ops_delta"],
            "crossings_delta": p["crossings_delta"],
            "control_escapes": p["control_escapes"],
            "treatment_escapes": p["treatment_escapes"],
        }
        for p in paired_results
    ]

    # 3. Worker Execution Comparison
    n_p = len(paired_results)
    mean_ctrl_moves = sum(p["control_moves"] for p in paired_results) / n_p
    mean_treat_moves = sum(p["treatment_moves"] for p in paired_results) / n_p
    mean_ctrl_ops = sum(p["control_ops"] for p in paired_results) / n_p
    mean_treat_ops = sum(p["treatment_ops"] for p in paired_results) / n_p
    mean_ctrl_crossings = sum(p["control_crossings"] for p in paired_results) / n_p
    mean_treat_crossings = sum(p["treatment_crossings"] for p in paired_results) / n_p

    worker_comparison = {
        "summary": {
            "control_mean_executed_moves_per_match": round(mean_ctrl_moves, 1),
            "treatment_mean_executed_moves_per_match": round(mean_treat_moves, 1),
            "mean_movement_reduction_per_match": round(mean_ctrl_moves - mean_treat_moves, 1),
            "movement_reduction_pct": round(100.0 * (mean_ctrl_moves - mean_treat_moves) / mean_ctrl_moves, 2),
            "control_mean_productive_ops_per_match": round(mean_ctrl_ops, 1),
            "treatment_mean_productive_ops_per_match": round(mean_treat_ops, 1),
            "productive_ops_delta_per_match": round(mean_treat_ops - mean_ctrl_ops, 1),
            "control_mean_quadrant_crossings_per_match": round(mean_ctrl_crossings, 1),
            "treatment_mean_quadrant_crossings_per_match": round(mean_treat_crossings, 1),
            "quadrant_crossings_reduction_per_match": round(mean_ctrl_crossings - mean_treat_crossings, 1),
            "quadrant_crossings_reduction_pct": round(100.0 * (mean_ctrl_crossings - mean_treat_crossings) / mean_ctrl_crossings, 2),
        }
    }

    # 4. Crop Service Comparison
    mean_ctrl_crops = sum(p["control_crops_completed"] for p in paired_results) / n_p
    mean_treat_crops = sum(p["treatment_crops_completed"] for p in paired_results) / n_p
    crop_comparison = {
        "summary": {
            "control_mean_crops_completed_per_match": round(mean_ctrl_crops, 1),
            "treatment_mean_crops_completed_per_match": round(mean_treat_crops, 1),
            "crops_completed_delta": round(mean_treat_crops - mean_ctrl_crops, 1),
        }
    }

    # 5. Safety Results
    tot_ctrl_escapes = sum(p["control_escapes"] for p in paired_results)
    tot_treat_escapes = sum(p["treatment_escapes"] for p in paired_results)
    safety_results = {
        "summary": {
            "control_total_animal_escapes": tot_ctrl_escapes,
            "treatment_total_animal_escapes": tot_treat_escapes,
            "escape_regression_detected": (tot_treat_escapes > tot_ctrl_escapes),
            "safety_passed": (tot_treat_escapes == 0),
        }
    }

    # 6. Representative Traces
    representative_traces = {
        "best_pair": max(paired_summary, key=lambda x: x["paired_cash_delta"]),
        "worst_pair": min(paired_summary, key=lambda x: x["paired_cash_delta"]),
        "median_pair": sorted(paired_summary, key=lambda x: x["paired_cash_delta"])[len(paired_summary) // 2],
    }

    # Write all deliverables
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(OUT_DIR, "paired_results.json"), "w") as f:
        json.dump(paired_summary, f, indent=2)
    with open(os.path.join(OUT_DIR, "aggregate_tables.json"), "w") as f:
        json.dump(stats, f, indent=2)
    with open(os.path.join(OUT_DIR, "worker_execution_comparison.json"), "w") as f:
        json.dump(worker_comparison, f, indent=2)
    with open(os.path.join(OUT_DIR, "crop_service_comparison.json"), "w") as f:
        json.dump(crop_comparison, f, indent=2)
    with open(os.path.join(OUT_DIR, "safety_results.json"), "w") as f:
        json.dump(safety_results, f, indent=2)
    with open(os.path.join(OUT_DIR, "representative_traces.json"), "w") as f:
        json.dump(representative_traces, f, indent=2)

    print("\n" + "=" * 80)
    print("PHASE C0 EXPERIMENT RESULTS SUMMARY")
    print(f"Configurations Evaluated: {n_p} paired matches ({n_p * 2} real matches)")
    print(f"Mean Paired Terminal-Cash Delta: ${stats['mean_paired_cash_delta']:+,.2f}")
    print(f"Median Paired Cash Delta: ${stats['median_paired_cash_delta']:+,.2f}")
    print(f"Seed-Clustered 95% CI: [${stats['seed_clustered_95_ci'][0]:+,.2f}, ${stats['seed_clustered_95_ci'][1]:+,.2f}]")
    print(f"Win Rate: {stats['positive_pairs']}/{n_p} ({stats['win_rate_pct']}%) | Ties: {stats['ties']} | Losses: {stats['negative_pairs']}")
    print(f"Quadrant Crossings Reduction: {worker_comparison['summary']['quadrant_crossings_reduction_pct']}% ({worker_comparison['summary']['control_mean_quadrant_crossings_per_match']} -> {worker_comparison['summary']['treatment_mean_quadrant_crossings_per_match']})")
    print(f"Movement Reduction: {worker_comparison['summary']['movement_reduction_pct']}% ({worker_comparison['summary']['control_mean_executed_moves_per_match']} -> {worker_comparison['summary']['treatment_mean_executed_moves_per_match']})")
    print(f"Productive Ops Delta: {worker_comparison['summary']['productive_ops_delta_per_match']:+0.1f} ops/match")
    print(f"Animal Escapes: Control={tot_ctrl_escapes}, Treatment={tot_treat_escapes}")
    print(f"Artifacts Saved to: {OUT_DIR}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
