"""Phase M0-A: Same-Turn Crop Pipeline Discovery Experiment Runner.

Evaluates CONTROL (SAME_TURN_CROP_PIPELINE_MODE = "OFF") vs TREATMENT (SAME_TURN_CROP_PIPELINE_MODE = "ON")
across the frozen discovery matrix:
- 10 discovery seeds: 96501–96510
- 5 benchmark opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 seats: 0, 1
- Total: 100 paired configurations (200 real-engine matches)

Production defaults strictly maintained:
SW_FORWARD_ARCHITECTURE_MODE = "OFF"
SOFT_WORKER_LOCALITY_MODE = "OFF"

Outputs deliverables into:
simulations/results/phase_m0_a_discovery/
    manifest.json
    paired_results.json
    aggregate_tables.json
    pipeline_telemetry.json
    crop_cycle_comparison.json
    safety_comparison.json
    losing_pair_forensics.json
    representative_traces.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
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
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_a_discovery")
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


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _quadrant_of(x: int, y: int) -> str:
    return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def run_single_simulation(seed: int, opp_name: str, seat: int, pipeline_mode: str) -> Dict[str, Any]:
    """Run one single match under specified pipeline mode ('OFF' or 'ON')."""
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    from kaggle_environments import make
    import config
    from agent.main import agent, reset_agent_state, get_crop_pipeline_telemetry, verify_post_turn_pipelines
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode("OFF")
    config.set_same_turn_crop_pipeline_mode(pipeline_mode)
    try:
        import agent.config as ac
        ac.set_sw_forward_architecture_mode("OFF")
        ac.set_soft_worker_locality_mode("OFF")
        ac.set_same_turn_crop_pipeline_mode(pipeline_mode)
    except Exception:
        pass
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
        "shed_visits": 0,
    }

    active_crop_cycles: Dict[Tuple[int, int], Dict[str, Any]] = {}
    completed_crop_cycles: List[Dict[str, Any]] = []
    tile_last_harvest: Dict[Tuple[int, int], int] = {}
    replanting_delays: List[int] = []
    tile_empty_turns: int = 0

    financial_stats = {
        "total_sales_revenue": 0.0,
        "product_sales_units": {p: 0 for p in PRODUCTS},
        "executed_spending": {
            "hires": 0.0,
            "land": 0.0,
            "animals": 0.0,
            "seeds": 0.0,
        },
        "orders_emitted": 0,
        "orders_executed": 0,
        "peak_shed_occupancy": 0,
        "shed_full_turns": 0,
    }

    safety_stats = {
        "feeding_due": 0,
        "feeding_executed": 0,
        "animal_escapes": 0,
        "consecutive_unfed_max": 0,
    }

    step_traces: List[Dict[str, Any]] = []

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

        # Track active crop states & empty tiles
        for y in range(10):
            for x in range(10):
                pos = (x, y)
                quad = _quadrant_of(x, y)
                if quad not in ("NW", "NE") or quad not in unlocked:
                    continue
                tile = farm0.tiles[y][x]
                if tile is None:
                    tile_empty_turns += 1
                elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop_name = tile.get("crop", "WHEAT")
                    p_day = tile.get("planted_day", day)
                    if pos not in active_crop_cycles:
                        active_crop_cycles[pos] = {
                            "tile": pos,
                            "crop": crop_name,
                            "planted_step": step,
                            "planted_day": p_day,
                            "first_ready": None,
                            "harvest_step": None,
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

        step_traces.append({
            "step": step,
            "day": day,
            "hour": hour,
            "positions": positions_before,
            "actions": [list(a) if isinstance(a, (list, tuple)) else [a] for a in all_actions],
            "money": cash_before,
        })

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

        # Verify pipeline post-step
        verify_post_turn_pipelines(s0_post, seat)

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
                    if pos_a in SHED_ACCESS_TILES:
                        worker_stats["shed_visits"] += 1
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

        # Financial tracking
        cash_delta = cash_after - cash_before
        if cash_delta > 0:
            financial_stats["total_sales_revenue"] += cash_delta
            for prod in PRODUCTS:
                cnt_pre = priv0.shed.get(prod, 0) + sum((inv or {}).get(prod, 0) for inv in priv0.inventories)
                cnt_post = priv0_post.shed.get(prod, 0) + sum((inv or {}).get(prod, 0) for inv in priv0_post.inventories)
                if cnt_pre > cnt_post:
                    financial_stats["product_sales_units"][prod] += (cnt_pre - cnt_post)

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
                financial_stats["orders_executed"] += adiff

        # Shed occupancy
        shed_occ = sum(priv0_post.shed.values())
        financial_stats["peak_shed_occupancy"] = max(financial_stats["peak_shed_occupancy"], shed_occ)
        if shed_occ >= 95:
            financial_stats["shed_full_turns"] += 1

        # Animal escapes & unfed check
        for y in range(10):
            for x in range(10):
                t = farm0_post.tiles[y][x]
                if isinstance(t, dict) and "animal" in t:
                    unfed = t.get("consecutive_unfed", 0)
                    safety_stats["consecutive_unfed_max"] = max(safety_stats["consecutive_unfed_max"], unfed)
                    if hour == 23 and unfed >= 2:
                        safety_stats["animal_escapes"] += 1

    # End of match
    final_farm = env.state[seat].observation.farms[seat]
    final_cash = float(final_farm.money)

    mean_h_delay = (
        sum(c["delay_hours"] for c in completed_crop_cycles) / max(1, len(completed_crop_cycles))
    )
    mean_replant = (
        sum(d for d in replanting_delays if d < 24) / max(1, sum(1 for d in replanting_delays if d < 24))
        if replanting_delays else 0.0
    )

    crop_yield_by_type = {}
    for c in completed_crop_cycles:
        cr = c["crop"]
        crop_yield_by_type[cr] = crop_yield_by_type.get(cr, 0) + 1

    # Pipeline telemetry
    pipelines = get_crop_pipeline_telemetry()
    successful_p = [p for p in pipelines if p.get("pipeline_success")]

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "pipeline_mode": pipeline_mode,
        "final_cash": final_cash,
        "worker_stats": worker_stats,
        "crop_stats": {
            "completed_cycles": len(completed_crop_cycles),
            "completed_cycles_by_type": crop_yield_by_type,
            "mean_harvest_delay_hours": round(mean_h_delay, 2),
            "mean_replant_delay_hours": round(mean_replant, 2),
            "empty_tile_turns": tile_empty_turns,
        },
        "financial_stats": financial_stats,
        "safety_stats": safety_stats,
        "pipeline_stats": {
            "pipelines_attempted": len(pipelines),
            "pipelines_successful": len(successful_p),
            "events": pipelines,
        },
        "step_traces": step_traces,
    }


def find_first_causal_divergence(ctrl_traces: List[Dict[str, Any]], treat_traces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    min_len = min(len(ctrl_traces), len(treat_traces))
    for i in range(min_len):
        c_step = ctrl_traces[i]
        t_step = treat_traces[i]
        if c_step["actions"] != t_step["actions"]:
            diff_w = None
            diff_c = None
            diff_t = None
            for w in range(max(len(c_step["actions"]), len(t_step["actions"]))):
                ca = c_step["actions"][w] if w < len(c_step["actions"]) else ["NONE"]
                ta = t_step["actions"][w] if w < len(t_step["actions"]) else ["NONE"]
                if ca != ta:
                    diff_w = w
                    diff_c = ca
                    diff_t = ta
                    break
            return {
                "first_divergent_step": c_step["step"],
                "day": c_step["day"],
                "hour": c_step["hour"],
                "worker_index": diff_w,
                "control_action": diff_c,
                "treatment_action": diff_t,
                "control_money": c_step["money"],
                "treatment_money": t_step["money"],
            }
    return None


def run_paired_configuration(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    ctrl = run_single_simulation(seed, opp_name, seat, pipeline_mode="OFF")
    treat = run_single_simulation(seed, opp_name, seat, pipeline_mode="ON")

    cash_diff = treat["final_cash"] - ctrl["final_cash"]
    move_diff = treat["worker_stats"]["executed_moves"] - ctrl["worker_stats"]["executed_moves"]
    ops_diff = treat["worker_stats"]["executed_ops"] - ctrl["worker_stats"]["executed_ops"]
    cross_diff = treat["worker_stats"]["quadrant_crossings"] - ctrl["worker_stats"]["quadrant_crossings"]
    crop_diff = treat["crop_stats"]["completed_cycles"] - ctrl["crop_stats"]["completed_cycles"]
    h_delay_diff = treat["crop_stats"]["mean_harvest_delay_hours"] - ctrl["crop_stats"]["mean_harvest_delay_hours"]
    replant_diff = treat["crop_stats"]["mean_replant_delay_hours"] - ctrl["crop_stats"]["mean_replant_delay_hours"]
    empty_diff = treat["crop_stats"]["empty_tile_turns"] - ctrl["crop_stats"]["empty_tile_turns"]

    div_info = find_first_causal_divergence(ctrl["step_traces"], treat["step_traces"])

    del ctrl["step_traces"]
    del treat["step_traces"]

    treat_p_stats = treat["pipeline_stats"]
    p_events = treat_p_stats["events"]

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "control_final_cash": ctrl["final_cash"],
        "treatment_final_cash": treat["final_cash"],
        "paired_cash_delta": round(cash_diff, 2),
        "pipelines_attempted": treat_p_stats["pipelines_attempted"],
        "pipelines_successful": treat_p_stats["pipelines_successful"],
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
        "crop_delta": crop_diff,
        "harvest_delay_delta": round(h_delay_diff, 2),
        "replant_delay_delta": round(replant_diff, 2),
        "empty_tile_turns_delta": empty_diff,
        "control_escapes": ctrl["safety_stats"]["animal_escapes"],
        "treatment_escapes": treat["safety_stats"]["animal_escapes"],
        "control_max_unfed": ctrl["safety_stats"]["consecutive_unfed_max"],
        "treatment_max_unfed": treat["safety_stats"]["consecutive_unfed_max"],
        "control_shed_full": ctrl["financial_stats"]["shed_full_turns"],
        "treatment_shed_full": treat["financial_stats"]["shed_full_turns"],
        "pipeline_events": p_events,
        "first_divergence": div_info,
        "ctrl_full": ctrl,
        "treat_full": treat,
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
    best_gain = sorted_d[-1]

    by_opp: Dict[str, List[float]] = {}
    for p in paired_results:
        by_opp.setdefault(p["opp_name"], []).append(p["paired_cash_delta"])
    mean_by_opp = {k: round(sum(v) / len(v), 2) for k, v in by_opp.items()}

    by_seat: Dict[int, List[float]] = {}
    for p in paired_results:
        by_seat.setdefault(p["seat"], []).append(p["paired_cash_delta"])
    mean_by_seat = {str(k): round(sum(v) / len(v), 2) for k, v in by_seat.items()}

    by_seed: Dict[int, List[float]] = {}
    for p in paired_results:
        by_seed.setdefault(p["seed"], []).append(p["paired_cash_delta"])
    mean_by_seed = {str(k): round(sum(v) / len(v), 2) for k, v in by_seed.items()}

    seed_means = [sum(by_seed[s]) / len(by_seed[s]) for s in seeds_list if s in by_seed]
    n_seeds = len(seed_means)
    if n_seeds > 1:
        s_mean = sum(seed_means) / n_seeds
        s_variance = sum((x - s_mean) ** 2 for x in seed_means) / (n_seeds - 1)
        s_se = math.sqrt(s_variance / n_seeds)
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
        "control_mean_cash": round(sum(p["control_final_cash"] for p in paired_results) / n, 2),
        "treatment_mean_cash": round(sum(p["treatment_final_cash"] for p in paired_results) / n, 2),
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
        "best_paired_gain": round(best_gain, 2),
        "worst_paired_regression": round(worst_reg, 2),
        "mean_delta_by_opponent": mean_by_opp,
        "mean_delta_by_seat": mean_by_seat,
        "mean_delta_by_seed": mean_by_seed,
        "seed_clustered_95_ci": [ci_lower, ci_upper],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Run 2-seed smoke test")
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 4, 4), help="Parallel workers")
    args = parser.parse_args()

    seeds = SMOKE_SEEDS if args.smoke else DEFAULT_SEEDS
    max_workers = args.workers
    commit_sha = get_git_commit()

    print(f"Starting Phase M0-A Crop Pipeline Experiment", flush=True)
    print(f"Commit HEAD: {commit_sha}", flush=True)
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Workers: {max_workers}", flush=True)

    # Compute source hashes
    critical_files = [
        os.path.join(_REPO_ROOT, "agent", "config.py"),
        os.path.join(_REPO_ROOT, "agent", "main.py"),
        os.path.join(_REPO_ROOT, "agent", "execution", "task_scheduler.py"),
        os.path.join(_REPO_ROOT, "agent", "execution", "crop_pipeline_controller.py"),
    ]
    source_hashes = {}
    for fp in critical_files:
        if os.path.exists(fp):
            source_hashes[os.path.relpath(fp, _REPO_ROOT).replace("\\", "/")] = compute_sha256(fp)

    start_time = time.time()
    paired_results: List[Dict[str, Any]] = []

    for s_idx, seed in enumerate(seeds):
        seed_configs = [
            (seed, opp, seat)
            for opp in BENCHMARK_OPPONENTS
            for seat in SEATS
        ]
        print(f"\n--- Running Seed {seed} ({s_idx + 1}/{len(seeds)}) with {len(seed_configs)} configurations ---", flush=True)
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
                    print(f"Done cfg {cfg}: CTRL=${res['control_final_cash']:,.0f} | TREAT=${res['treatment_final_cash']:,.0f} | DELTA=${res['paired_cash_delta']:+,.0f} | Pipelines={res['pipelines_successful']}/{res['pipelines_attempted']}", flush=True)
                except Exception as e:
                    import traceback
                    print(f"ERROR on paired cfg {cfg}: {e}\n{traceback.format_exc()}", flush=True)

    elapsed = time.time() - start_time
    print(f"\nCompleted {len(paired_results)} paired configurations in {elapsed:.2f}s.", flush=True)

    # 1. Manifest
    manifest = {
        "phase": "Phase M0-A: Engine Mechanics Exploitation — Same-Turn Crop Pipeline",
        "commit_sha": commit_sha,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "configuration": {
            "control": {
                "SAME_TURN_CROP_PIPELINE_MODE": "OFF",
                "SOFT_WORKER_LOCALITY_MODE": "OFF",
                "SW_FORWARD_ARCHITECTURE_MODE": "OFF",
            },
            "treatment": {
                "SAME_TURN_CROP_PIPELINE_MODE": "ON",
                "SOFT_WORKER_LOCALITY_MODE": "OFF",
                "SW_FORWARD_ARCHITECTURE_MODE": "OFF",
            },
            "seeds": seeds,
            "opponents": BENCHMARK_OPPONENTS,
            "seats": SEATS,
            "total_paired_configurations": len(paired_results),
            "total_matches_executed": len(paired_results) * 2,
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "source_hashes": source_hashes,
        },
        "elapsed_seconds": round(elapsed, 2),
    }

    # 2. Paired results (clean)
    paired_clean = [
        {
            "seed": p["seed"],
            "opp_name": p["opp_name"],
            "seat": p["seat"],
            "control_final_cash": p["control_final_cash"],
            "treatment_final_cash": p["treatment_final_cash"],
            "paired_cash_delta": p["paired_cash_delta"],
            "pipelines_attempted": p["pipelines_attempted"],
            "pipelines_successful": p["pipelines_successful"],
            "move_delta": p["move_delta"],
            "ops_delta": p["ops_delta"],
            "crossings_delta": p["crossings_delta"],
            "crop_delta": p["crop_delta"],
            "harvest_delay_delta": p["harvest_delay_delta"],
            "replant_delay_delta": p["replant_delay_delta"],
            "empty_tile_turns_delta": p["empty_tile_turns_delta"],
        }
        for p in paired_results
    ]

    # 3. Aggregate tables
    stats = compute_statistics(paired_results, seeds)

    # 4. Pipeline Telemetry
    all_pipeline_events = []
    for p in paired_results:
        for ev in p.get("pipeline_events", []):
            ev_copy = dict(ev)
            ev_copy["seed"] = p["seed"]
            ev_copy["opp_name"] = p["opp_name"]
            ev_copy["seat"] = p["seat"]
            all_pipeline_events.append(ev_copy)

    pipeline_telemetry = {
        "total_attempted": sum(p["pipelines_attempted"] for p in paired_results),
        "total_successful": sum(p["pipelines_successful"] for p in paired_results),
        "mean_successful_per_match": round(sum(p["pipelines_successful"] for p in paired_results) / max(1, len(paired_results)), 2),
        "events": all_pipeline_events[:500],  # sample up to 500
    }

    # 5. Crop cycle comparison
    n_p = max(1, len(paired_results))
    crop_comp = {
        "mean_crops_completed_ctrl": round(sum(p["ctrl_full"]["crop_stats"]["completed_cycles"] for p in paired_results) / n_p, 2),
        "mean_crops_completed_treat": round(sum(p["treat_full"]["crop_stats"]["completed_cycles"] for p in paired_results) / n_p, 2),
        "mean_crops_completed_delta": round(sum(p["crop_delta"] for p in paired_results) / n_p, 2),
        "mean_harvest_delay_hours_ctrl": round(sum(p["ctrl_full"]["crop_stats"]["mean_harvest_delay_hours"] for p in paired_results) / n_p, 2),
        "mean_harvest_delay_hours_treat": round(sum(p["treat_full"]["crop_stats"]["mean_harvest_delay_hours"] for p in paired_results) / n_p, 2),
        "mean_harvest_delay_delta": round(sum(p["harvest_delay_delta"] for p in paired_results) / n_p, 2),
        "mean_replant_delay_hours_ctrl": round(sum(p["ctrl_full"]["crop_stats"]["mean_replant_delay_hours"] for p in paired_results) / n_p, 2),
        "mean_replant_delay_hours_treat": round(sum(p["treat_full"]["crop_stats"]["mean_replant_delay_hours"] for p in paired_results) / n_p, 2),
        "mean_replant_delay_delta": round(sum(p["replant_delay_delta"] for p in paired_results) / n_p, 2),
        "mean_empty_tile_turns_ctrl": round(sum(p["ctrl_full"]["crop_stats"]["empty_tile_turns"] for p in paired_results) / n_p, 1),
        "mean_empty_tile_turns_treat": round(sum(p["treat_full"]["crop_stats"]["empty_tile_turns"] for p in paired_results) / n_p, 1),
        "mean_empty_tile_turns_delta": round(sum(p["empty_tile_turns_delta"] for p in paired_results) / n_p, 1),
    }

    # 6. Safety comparison
    safety_comp = {
        "control_total_escapes": sum(p["control_escapes"] for p in paired_results),
        "treatment_total_escapes": sum(p["treatment_escapes"] for p in paired_results),
        "control_max_consecutive_unfed": max(p["control_max_unfed"] for p in paired_results),
        "treatment_max_consecutive_unfed": max(p["treatment_max_unfed"] for p in paired_results),
        "control_shed_full_turns": sum(p["control_shed_full"] for p in paired_results),
        "treatment_shed_full_turns": sum(p["treatment_shed_full"] for p in paired_results),
    }

    # 7. Losing Pair Forensics (regressions > $2,000)
    losing_regressions = [p for p in paired_results if p["paired_cash_delta"] < -2000]
    losing_forensics = [
        {
            "seed": p["seed"],
            "opp_name": p["opp_name"],
            "seat": p["seat"],
            "control_cash": p["control_final_cash"],
            "treatment_cash": p["treatment_final_cash"],
            "paired_delta": p["paired_cash_delta"],
            "pipelines_successful": p["pipelines_successful"],
            "first_divergence": p["first_divergence"],
        }
        for p in sorted(losing_regressions, key=lambda x: x["paired_cash_delta"])
    ]

    # 8. Representative traces
    rep_traces = {
        "best_pair": max(paired_clean, key=lambda x: x["paired_cash_delta"]),
        "worst_pair": min(paired_clean, key=lambda x: x["paired_cash_delta"]),
        "median_pair": sorted(paired_clean, key=lambda x: x["paired_cash_delta"])[len(paired_clean) // 2],
    }

    # Write all output files
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(OUT_DIR, "paired_results.json"), "w") as f:
        json.dump(paired_clean, f, indent=2)
    with open(os.path.join(OUT_DIR, "aggregate_tables.json"), "w") as f:
        json.dump(stats, f, indent=2)
    with open(os.path.join(OUT_DIR, "pipeline_telemetry.json"), "w") as f:
        json.dump(pipeline_telemetry, f, indent=2)
    with open(os.path.join(OUT_DIR, "crop_cycle_comparison.json"), "w") as f:
        json.dump(crop_comp, f, indent=2)
    with open(os.path.join(OUT_DIR, "safety_comparison.json"), "w") as f:
        json.dump(safety_comp, f, indent=2)
    with open(os.path.join(OUT_DIR, "losing_pair_forensics.json"), "w") as f:
        json.dump(losing_forensics, f, indent=2)
    with open(os.path.join(OUT_DIR, "representative_traces.json"), "w") as f:
        json.dump(rep_traces, f, indent=2)

    print("\n" + "=" * 80)
    print("PHASE M0-A DISCOVERY EXPERIMENT RESULTS SUMMARY")
    print(f"Configurations: {len(paired_results)} pairs ({len(paired_results) * 2} real matches)")
    print(f"Control Mean Cash:   ${stats['control_mean_cash']:,.2f}")
    print(f"Treatment Mean Cash: ${stats['treatment_mean_cash']:,.2f}")
    print(f"Mean Paired Delta:   ${stats['mean_paired_cash_delta']:+,.2f}")
    print(f"Median Paired Delta: ${stats['median_paired_cash_delta']:+,.2f}")
    print(f"Seed-Clustered 95% CI: [${stats['seed_clustered_95_ci'][0]:+,.2f}, ${stats['seed_clustered_95_ci'][1]:+,.2f}]")
    print(f"Win Rate: {stats['positive_pairs']}/{len(paired_results)} ({stats['win_rate_pct']}%) | Ties: {stats['ties']} | Losses: {stats['negative_pairs']}")
    print(f"Successful Pipelines Total: {pipeline_telemetry['total_successful']} (mean {pipeline_telemetry['mean_successful_per_match']} / match)")
    print(f"Replant Delay Delta: {crop_comp['mean_replant_delay_delta']:+0.2f} hours")
    print(f"Completed Crop Cycles Delta: {crop_comp['mean_crops_completed_delta']:+0.2f}")
    print(f"Empty Tile Turns Delta: {crop_comp['mean_empty_tile_turns_delta']:+0.1f}")
    print(f"Animal Escapes: Control={safety_comp['control_total_escapes']}, Treatment={safety_comp['treatment_total_escapes']}")
    print(f"Artifacts saved to: {OUT_DIR}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
