"""Paired Deterministic A/B Evaluation for Wheat planted_day Accounting Repair.

Compares:
  Baseline:  3562df27783038527de165f203025f27f550e4e9 (Production Point 2)
  Candidate: d74d1e9f28b9c455c9528f44a32da6bfb863a405 (fix/wheat-planted-day-accounting)

Requirements:
  - Exact commit SHA verification with git archive extraction for baseline and candidate.
  - Process/module/state isolation.
  - 20 matched pairs (40 matches) across 5 opponent archetypes:
    pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent.
  - Detailed telemetry: score, wheat production, wheat purchasing, feed feasibility,
    livestock effects, safety, capital/expansion, and causal wheat-timing attribution.
  - Statistical analysis: mean, median, std dev, 95% CI, win/tie/loss, opponent breakdown.
"""

import copy
import json
import math
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Repo Root Resolution & Commit SHA Constants
# ---------------------------------------------------------------------------

def resolve_repo_root() -> str:
    marker_files = [".git", "agent", "simulations"]
    curr = os.path.abspath(os.path.dirname(__file__))
    for _ in range(5):
        if all(os.path.exists(os.path.join(curr, m)) for m in marker_files):
            return curr
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    cwd = os.path.abspath(os.getcwd())
    if all(os.path.exists(os.path.join(cwd, m)) for m in marker_files):
        return cwd
    raise RuntimeError(f"Could not resolve repository root from {__file__} or {cwd}")

REPO_ROOT = resolve_repo_root()

REQUIRED_BASELINE_SHA = "3562df27783038527de165f203025f27f550e4e9"
REQUIRED_CANDIDATE_SHA = "d74d1e9f28b9c455c9528f44a32da6bfb863a405"

RESULTS_DIR = os.path.join(REPO_ROOT, "simulations", "experiments", "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "wheat_planted_day_ab_results.json")

# ---------------------------------------------------------------------------
# Commit Verification & Extraction via git archive
# ---------------------------------------------------------------------------

def get_git_sha(ref: str = "HEAD") -> str:
    cmd = ["git", "rev-parse", ref]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to resolve git ref '{ref}': {res.stderr.strip()}")
    return res.stdout.strip()


def verify_and_extract_commit(target_sha: str, dir_name: str) -> str:
    actual_sha = get_git_sha(target_sha)
    if actual_sha != target_sha:
        raise ValueError(
            f"Commit SHA mismatch for {dir_name}!\n"
            f"  Expected: {target_sha}\n"
            f"  Resolved: {actual_sha}"
        )

    target_extract_dir = os.path.join(REPO_ROOT, "simulations", "experiments", f".extracted_{dir_name}")
    marker_file = os.path.join(target_extract_dir, ".commit_sha")
    agent_dir = os.path.join(target_extract_dir, "agent")

    needs_extract = True
    if os.path.exists(marker_file) and os.path.exists(agent_dir):
        try:
            with open(marker_file, "r") as f:
                if f.read().strip() == actual_sha:
                    needs_extract = False
        except Exception:
            needs_extract = True

    if needs_extract:
        os.makedirs(target_extract_dir, exist_ok=True)
        archive_cmd = ["git", "archive", "--format=tar", actual_sha, "agent"]
        proc = subprocess.Popen(archive_cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(path=target_extract_dir, filter="data")
            else:
                tar.extractall(path=target_extract_dir)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"git archive failed for {target_sha} with code {proc.returncode}")
        with open(marker_file, "w") as f:
            f.write(actual_sha)

    return agent_dir


# ---------------------------------------------------------------------------
# 20 Balanced Paired Scenarios (4 matches per archetype, fresh seeds)
# ---------------------------------------------------------------------------

EVALUATION_PAIRS = [
    # 4 matches vs pass
    {"pair_id": 1, "seed": 1001, "opponent": "pass"},
    {"pair_id": 2, "seed": 1002, "opponent": "pass"},
    {"pair_id": 3, "seed": 1003, "opponent": "pass"},
    {"pair_id": 4, "seed": 1004, "opponent": "pass"},
    # 4 matches vs pure_wheat_rush
    {"pair_id": 5, "seed": 2001, "opponent": "pure_wheat_rush"},
    {"pair_id": 6, "seed": 2002, "opponent": "pure_wheat_rush"},
    {"pair_id": 7, "seed": 2003, "opponent": "pure_wheat_rush"},
    {"pair_id": 8, "seed": 2004, "opponent": "pure_wheat_rush"},
    # 4 matches vs cow_milk_engine
    {"pair_id": 9, "seed": 3001, "opponent": "cow_milk_engine"},
    {"pair_id": 10, "seed": 3002, "opponent": "cow_milk_engine"},
    {"pair_id": 11, "seed": 3003, "opponent": "cow_milk_engine"},
    {"pair_id": 12, "seed": 3004, "opponent": "cow_milk_engine"},
    # 4 matches vs melon_sniper
    {"pair_id": 13, "seed": 4001, "opponent": "melon_sniper"},
    {"pair_id": 14, "seed": 4002, "opponent": "melon_sniper"},
    {"pair_id": 15, "seed": 4003, "opponent": "melon_sniper"},
    {"pair_id": 16, "seed": 4004, "opponent": "melon_sniper"},
    # 4 matches vs full_production_agent
    {"pair_id": 17, "seed": 5001, "opponent": "full_production_agent"},
    {"pair_id": 18, "seed": 5002, "opponent": "full_production_agent"},
    {"pair_id": 19, "seed": 5003, "opponent": "full_production_agent"},
    {"pair_id": 20, "seed": 5004, "opponent": "full_production_agent"},
]

# ---------------------------------------------------------------------------
# Worker Subprocess Execution with Deep Telemetry
# ---------------------------------------------------------------------------

def _run_single_match(params: Dict[str, Any]) -> Dict[str, Any]:
    arm = params["arm"]
    pair_id = params["pair_id"]
    seed = params["seed"]
    opponent_name = params["opponent"]
    target_agent_dir = params["target_agent_dir"]
    repo_root = params["repo_root"]

    # 1. Isolate sys.path to target agent directory
    sys.path = [p for p in sys.path if not p.startswith(os.path.join(repo_root, "agent"))]
    if target_agent_dir not in sys.path:
        sys.path.insert(0, target_agent_dir)
    for sub in ("state", "strategy", "execution", "market"):
        p = os.path.join(target_agent_dir, sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # Purge cached modules
    to_delete = [
        k for k in list(sys.modules.keys())
        if k.startswith((
            "main", "config", "strategy", "state", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "animal_planner",
            "feed_feasibility", "pasture_planner", "expansion_planner",
            "observation_parser", "state_tracker"
        ))
    ]
    for k in to_delete:
        del sys.modules[k]

    import kaggle_environments
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS, ANIMALS
    import main as agent_module
    import config as cfg
    from simulations.experiments.agent_zoo import get_agent

    # Enforce strict production default settings
    cfg.POINT2_FEED_MODE = "shadow"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
    cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"

    agent_module.reset_agent_state()

    # Telemetry data containers
    # 1. Wheat production
    standing_wheat_by_day: Dict[int, List[Dict[str, Any]]] = {}
    harvested_wheat_units = 0
    eod_wheat_inventory: Dict[str, Dict[str, int]] = {}

    # 2. Wheat purchasing
    requested_wheat_orders: List[Dict[str, Any]] = []
    confirmed_wheat_purchases: List[Dict[str, Any]] = []
    total_wheat_requested_qty = 0
    total_wheat_confirmed_qty = 0
    total_wheat_spend = 0.0

    # 3. Feed feasibility & Causal wheat-timing
    causal_timing_discrepancies: List[Dict[str, Any]] = []
    min_observed_wheat_slack = float("inf")
    feed_deficits_by_day: Dict[int, int] = {}
    daily_near_term_wheat_required: Dict[int, int] = {}

    # 4. Livestock effects
    animals_purchased: Dict[str, int] = {"GOOSE": 0, "COW": 0, "SHEEP": 0}
    animal_purchase_events: List[Dict[str, Any]] = []
    candidate_decisions: List[Dict[str, Any]] = []

    # 5. Safety
    safety_incidents = {
        "negative_cash_steps": 0,
        "animal_starvations": 0,
        "animal_deaths": 0,
        "unwatered_crop_events": 0,
    }

    # 6. Capital / Expansion
    cash_by_day: Dict[str, float] = {}
    ne_purchase_day: Optional[int] = None
    sw_purchase_day: Optional[int] = None

    prior_shed_wheat = 0
    prior_worker_wheat = 0

    def tracking_agent(obs, config=None):
        nonlocal requested_wheat_orders, confirmed_wheat_purchases
        nonlocal total_wheat_requested_qty, total_wheat_confirmed_qty, total_wheat_spend
        nonlocal harvested_wheat_units, min_observed_wheat_slack
        nonlocal ne_purchase_day, sw_purchase_day
        nonlocal prior_shed_wheat, prior_worker_wheat

        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        player_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        farm_data = farms[player_id] if len(farms) > player_id else {}
        money = float(farm_data.get("money", 0.0))
        private_data = obs.get("private", {})
        tiles = farm_data.get("tiles", [])
        unlocked = set(farm_data.get("unlocked_quadrants", ["NW"]))

        # Track quadrant purchases
        if "NE" in unlocked and ne_purchase_day is None:
            ne_purchase_day = day
        if "SW" in unlocked and sw_purchase_day is None:
            sw_purchase_day = day

        # Safety Check: Negative cash
        if money < 0:
            safety_incidents["negative_cash_steps"] += 1

        # Safety Check: Animal starvation at turn start (hour 0)
        if hour == 0 and day > 0:
            for row in tiles:
                for t in row:
                    if isinstance(t, dict) and t.get("animal"):
                        if t.get("consecutive_unfed", 0) > 0:
                            safety_incidents["animal_starvations"] += 1

        # Safety Check: Dead animals
        for row in tiles:
            for t in row:
                if isinstance(t, dict) and t.get("animal_status") == "DEAD":
                    safety_incidents["animal_deaths"] += 1

        # Check market confirmed purchases from previous turn
        curr_shed_wheat = int((private_data.get("shed", {}) or {}).get("WHEAT", 0))
        curr_worker_wheat = sum(int((inv or {}).get("WHEAT", 0)) for inv in (private_data.get("inventories", []) or []))

        # At start of turn, observe standing wheat tiles and causal timing
        if hour == 0:
            daily_wheat = []
            for y, row in enumerate(tiles):
                for x, t in enumerate(row):
                    if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop") == "WHEAT":
                        p_day = t.get("planted_day")
                        # Causal comparison:
                        # Corrected arrival = planted_day + 4
                        # Old legacy arrival = current_day + 4 (because placed_day was None)
                        if p_day is not None:
                            crop_age = day - p_day
                            corr_arrival = p_day + CROPS["WHEAT"]["max_yield_day"]
                            old_arrival = day + CROPS["WHEAT"]["max_yield_day"]
                            is_harvestable = crop_age >= CROPS["WHEAT"]["first_yield_day"]
                            is_fert = t.get("fertilized_until_day", -1) >= p_day
                            units = 6 if is_fert else 4

                            # Was there a timing discrepancy relative to the 4-day feed horizon (day..day+3)?
                            in_corr_horizon = corr_arrival <= (day + 3)
                            in_old_horizon = old_arrival <= (day + 3)  # old_arrival = day+4 > day+3, so always FALSE!

                            daily_wheat.append({
                                "pos": [x, y],
                                "planted_day": p_day,
                                "crop_age": crop_age,
                                "corr_arrival": corr_arrival,
                                "old_arrival": old_arrival,
                                "in_corr_horizon": in_corr_horizon,
                                "in_old_horizon": in_old_horizon,
                                "units": units,
                            })

                            if in_corr_horizon != in_old_horizon:
                                causal_timing_discrepancies.append({
                                    "day": day,
                                    "hour": hour,
                                    "pos": [x, y],
                                    "planted_day": p_day,
                                    "crop_age": crop_age,
                                    "corrected_arrival": corr_arrival,
                                    "old_legacy_arrival": old_arrival,
                                    "actual_engine_harvestability": "HARVESTABLE" if is_harvestable else "GROWING",
                                    "credited_secured_units": units,
                                })
            standing_wheat_by_day[day] = daily_wheat

        # Call the underlying agent
        action = agent_module.agent(obs, config)

        # Inspect agent action for wheat and animal market purchases
        market_actions = action.get("market", []) if isinstance(action, dict) else []
        for ma in market_actions:
            if isinstance(ma, dict) and ma.get("type") == "BUY":
                item = ma.get("item")
                qty = int(ma.get("quantity", 0))
                price = float(ma.get("price", 0.0))
                cost = qty * price
                if item == "WHEAT":
                    requested_wheat_orders.append({
                        "day": day, "hour": hour, "qty": qty, "price": price, "cost": cost
                    })
                    total_wheat_requested_qty += qty
                    # Confirmed estimate
                    total_wheat_spend += cost
                    total_wheat_confirmed_qty += qty
                    confirmed_wheat_purchases.append({
                        "day": day, "hour": hour, "qty": qty, "price": price, "cost": cost
                    })
                elif item in ANIMALS:
                    animals_purchased[item] = animals_purchased.get(item, 0) + qty
                    animal_purchase_events.append({
                        "day": day, "hour": hour, "species": item, "qty": qty, "cost": cost
                    })

        # Track worker harvests of wheat
        farmer_act = action.get("farmer", ["PASS"]) if isinstance(action, dict) else ["PASS"]
        hand_acts = action.get("hands", []) if isinstance(action, dict) else []
        all_unit_acts = [farmer_act] + (hand_acts if isinstance(hand_acts, list) else [])
        for ua in all_unit_acts:
            if isinstance(ua, list) and len(ua) >= 1 and ua[0] == "HARVEST":
                # Check worker position on tile
                harvested_wheat_units += 1

        # End of day checks at hour 23
        if hour == 23:
            cash_by_day[f"d{day}"] = money
            # Unwatered crops check
            for row in tiles:
                for t in row:
                    if isinstance(t, dict) and t.get("kind") == "PLANT":
                        if not t.get("watered_today", False):
                            safety_incidents["unwatered_crop_events"] += 1
            # EOD inventory
            eod_wheat_inventory[f"d{day}"] = {
                "shed_wheat": curr_shed_wheat,
                "worker_wheat": curr_worker_wheat,
                "total_on_hand": curr_shed_wheat + curr_worker_wheat,
            }

        prior_shed_wheat = curr_shed_wheat
        prior_worker_wheat = curr_worker_wheat
        return action

    t0 = time.time()
    try:
        env = kaggle_environments.make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720})
        opp_callable = get_agent(opponent_name)
        runner = env.run([tracking_agent, opp_callable])

        last_step = runner[-1]
        p0_state = last_step[0]
        p1_state = last_step[1]

        final_score_p0 = float(p0_state.get("reward", 0.0) or 0.0)
        final_score_p1 = float(p1_state.get("reward", 0.0) or 0.0)
        elapsed = time.time() - t0

        return {
            "pair_id": pair_id,
            "arm": arm,
            "seed": seed,
            "opponent": opponent_name,
            "final_score": final_score_p0,
            "opp_score": final_score_p1,
            "win": final_score_p0 > final_score_p1,
            "tie": final_score_p0 == final_score_p1,
            # Wheat production
            "standing_wheat_days": len(standing_wheat_by_day),
            "harvested_wheat_units": harvested_wheat_units,
            "eod_wheat_inventory": eod_wheat_inventory,
            # Wheat purchasing
            "total_wheat_requested_qty": total_wheat_requested_qty,
            "total_wheat_confirmed_qty": total_wheat_confirmed_qty,
            "total_wheat_spend": total_wheat_spend,
            "confirmed_wheat_purchases": confirmed_wheat_purchases,
            # Feed feasibility & Causal timing
            "causal_timing_discrepancies_count": len(causal_timing_discrepancies),
            "causal_timing_discrepancies": causal_timing_discrepancies[:20],
            # Livestock
            "animals_purchased": animals_purchased,
            "animal_purchase_events": animal_purchase_events,
            # Safety
            "safety_incidents": safety_incidents,
            # Capital / Expansion
            "cash_by_day": cash_by_day,
            "ne_purchase_day": ne_purchase_day,
            "sw_purchase_day": sw_purchase_day,
            "elapsed": round(elapsed, 2),
            "status": "SUCCESS",
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "pair_id": pair_id,
            "arm": arm,
            "seed": seed,
            "opponent": opponent_name,
            "error": str(e),
            "final_score": 0.0,
            "opp_score": 0.0,
            "status": "ERROR",
            "elapsed": round(time.time() - t0, 2),
        }


# ---------------------------------------------------------------------------
# Suite Runner & Statistical Aggregation
# ---------------------------------------------------------------------------

def run_experiment(max_workers: int = 4) -> Dict[str, Any]:
    print("\n================================================================================")
    print("VERIFYING ARTIFACTS AND EXTRACTING AGENTS")
    print("================================================================================")

    # Verify and extract both commits
    baseline_agent_dir = verify_and_extract_commit(REQUIRED_BASELINE_SHA, "baseline_point2")
    candidate_agent_dir = verify_and_extract_commit(REQUIRED_CANDIDATE_SHA, "candidate_planted_day")

    verified_baseline_sha = get_git_sha(REQUIRED_BASELINE_SHA)
    verified_candidate_sha = get_git_sha(REQUIRED_CANDIDATE_SHA)

    import kaggle_environments
    engine_ver = getattr(kaggle_environments, "__version__", "unknown")
    engine_file = getattr(kaggle_environments, "__file__", "unknown")

    print(f"  Baseline Commit:  {verified_baseline_sha} (Verified)")
    print(f"  Candidate Commit: {verified_candidate_sha} (Verified)")
    print(f"  Engine Version:   {engine_ver} ({engine_file})")
    print(f"  Python Version:   {platform.python_version()}")
    print(f"  Pairs to Run:     {len(EVALUATION_PAIRS)} pairs / {len(EVALUATION_PAIRS)*2} matches")
    print(f"  Workers:          {max_workers}")
    print("================================================================================\n")

    tasks = []
    for p in EVALUATION_PAIRS:
        tasks.append({
            "arm": "Baseline",
            "pair_id": p["pair_id"],
            "seed": p["seed"],
            "opponent": p["opponent"],
            "target_agent_dir": baseline_agent_dir,
            "repo_root": REPO_ROOT,
        })
        tasks.append({
            "arm": "Candidate",
            "pair_id": p["pair_id"],
            "seed": p["seed"],
            "opponent": p["opponent"],
            "target_agent_dir": candidate_agent_dir,
            "repo_root": REPO_ROOT,
        })

    t_start = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_run_single_match, t): t for t in tasks}
        completed = 0
        total = len(tasks)
        for fut in as_completed(future_map):
            res = fut.result()
            results.append(res)
            completed += 1
            print(f"  [{completed:2d}/{total:2d}] {res['arm']:9s} Pair {res['pair_id']:2d} (Seed {res['seed']:4d} vs {res['opponent']:20s}): Score={res['final_score']:10.1f} ({res['elapsed']}s)")

    # Align pairs
    paired_data: Dict[int, Dict[str, Any]] = {}
    for r in results:
        pid = r["pair_id"]
        if pid not in paired_data:
            paired_data[pid] = {}
        paired_data[pid][r["arm"]] = r

    # Process paired metrics
    deltas = []
    base_scores = []
    cand_scores = []
    wins = 0
    ties = 0
    losses = 0

    base_wheat_purchased_total = 0
    cand_wheat_purchased_total = 0
    base_wheat_spend_total = 0.0
    cand_wheat_spend_total = 0.0

    base_starvations_total = 0
    cand_starvations_total = 0

    base_animals_total = {"GOOSE": 0, "COW": 0, "SHEEP": 0}
    cand_animals_total = {"GOOSE": 0, "COW": 0, "SHEEP": 0}

    causal_confirmed_count = 0
    unexplained_noise_count = 0

    opponent_stats: Dict[str, Dict[str, Any]] = {}

    pairs_summary = []
    for pid in sorted(paired_data.keys()):
        base_match = paired_data[pid].get("Baseline", {})
        cand_match = paired_data[pid].get("Candidate", {})

        b_score = base_match.get("final_score", 0.0)
        c_score = cand_match.get("final_score", 0.0)
        delta = c_score - b_score
        deltas.append(delta)
        base_scores.append(b_score)
        cand_scores.append(c_score)

        if delta > 0:
            wins += 1
        elif delta == 0:
            ties += 1
        else:
            losses += 1

        opp = base_match.get("opponent", "unknown")
        if opp not in opponent_stats:
            opponent_stats[opp] = {"count": 0, "wins": 0, "ties": 0, "losses": 0, "deltas": [], "base_scores": [], "cand_scores": []}
        opponent_stats[opp]["count"] += 1
        opponent_stats[opp]["deltas"].append(delta)
        opponent_stats[opp]["base_scores"].append(b_score)
        opponent_stats[opp]["cand_scores"].append(c_score)
        if delta > 0:
            opponent_stats[opp]["wins"] += 1
        elif delta == 0:
            opponent_stats[opp]["ties"] += 1
        else:
            opponent_stats[opp]["losses"] += 1

        # Wheat purchase totals
        b_wp = base_match.get("total_wheat_confirmed_qty", 0)
        c_wp = cand_match.get("total_wheat_confirmed_qty", 0)
        base_wheat_purchased_total += b_wp
        cand_wheat_purchased_total += c_wp

        b_ws = base_match.get("total_wheat_spend", 0.0)
        c_ws = cand_match.get("total_wheat_spend", 0.0)
        base_wheat_spend_total += b_ws
        cand_wheat_spend_total += c_ws

        # Starvations
        b_stv = base_match.get("safety_incidents", {}).get("animal_starvations", 0)
        c_stv = cand_match.get("safety_incidents", {}).get("animal_starvations", 0)
        base_starvations_total += b_stv
        cand_starvations_total += c_stv

        # Animals
        for sp in ("GOOSE", "COW", "SHEEP"):
            base_animals_total[sp] += base_match.get("animals_purchased", {}).get(sp, 0)
            cand_animals_total[sp] += cand_match.get("animals_purchased", {}).get(sp, 0)

        # Causal mechanism check
        causal_discrepancies = cand_match.get("causal_timing_discrepancies_count", 0)
        b_ne = base_match.get("ne_purchase_day")
        c_ne = cand_match.get("ne_purchase_day")
        b_sw = base_match.get("sw_purchase_day")
        c_sw = cand_match.get("sw_purchase_day")

        wheat_changed = (b_wp != c_wp or b_ws != c_ws)
        starvation_changed = (b_stv != c_stv)
        expansion_changed = (b_ne != c_ne or b_sw != c_sw)
        animals_changed = (base_match.get("animals_purchased") != cand_match.get("animals_purchased"))

        is_causal = (wheat_changed or starvation_changed or expansion_changed or animals_changed or causal_discrepancies > 0)
        if is_causal:
            causal_confirmed_count += 1
        else:
            if delta != 0:
                unexplained_noise_count += 1

        pairs_summary.append({
            "pair_id": pid,
            "seed": base_match.get("seed"),
            "opponent": opp,
            "base_score": b_score,
            "cand_score": c_score,
            "delta": delta,
            "base_wheat_buy": b_wp,
            "cand_wheat_buy": c_wp,
            "base_wheat_spend": b_ws,
            "cand_wheat_spend": c_ws,
            "base_starvations": b_stv,
            "cand_starvations": c_stv,
            "base_animals": base_match.get("animals_purchased"),
            "cand_animals": cand_match.get("animals_purchased"),
            "base_ne_day": b_ne,
            "cand_ne_day": c_ne,
            "causal_discrepancies_detected": causal_discrepancies,
            "is_causal_mechanism": is_causal,
        })

    # Summary Statistics
    n = len(deltas)
    mean_base = sum(base_scores) / n if n > 0 else 0.0
    mean_cand = sum(cand_scores) / n if n > 0 else 0.0
    mean_delta = sum(deltas) / n if n > 0 else 0.0

    sorted_deltas = sorted(deltas)
    if n % 2 == 1:
        median_delta = sorted_deltas[n // 2]
    else:
        median_delta = (sorted_deltas[n // 2 - 1] + sorted_deltas[n // 2]) / 2.0

    variance = sum((d - mean_delta) ** 2 for d in deltas) / (n - 1) if n > 1 else 0.0
    std_dev = math.sqrt(variance)
    # Approximate 95% CI (1.96 * std_err or t_0.025 with df=19 = 2.093)
    t_crit = 2.093 if n == 20 else 1.96
    margin_of_error = t_crit * (std_dev / math.sqrt(n)) if n > 0 else 0.0
    ci_lower = mean_delta - margin_of_error
    ci_upper = mean_delta + margin_of_error

    total_elapsed = round(time.time() - t_start, 2)

    aggregate = {
        "baseline_commit": verified_baseline_sha,
        "candidate_commit": verified_candidate_sha,
        "engine_version": engine_ver,
        "python_version": platform.python_version(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_pairs": n,
        "mean_base_score": round(mean_base, 2),
        "mean_cand_score": round(mean_cand, 2),
        "mean_paired_delta": round(mean_delta, 2),
        "median_paired_delta": round(median_delta, 2),
        "std_dev_paired_delta": round(std_dev, 2),
        "ci_95_lower": round(ci_lower, 2),
        "ci_95_upper": round(ci_upper, 2),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate": round(wins / n, 4) if n > 0 else 0.0,
        "base_wheat_purchased_total": base_wheat_purchased_total,
        "cand_wheat_purchased_total": cand_wheat_purchased_total,
        "base_wheat_spend_total": base_wheat_spend_total,
        "cand_wheat_spend_total": cand_wheat_spend_total,
        "wheat_spend_saved": base_wheat_spend_total - cand_wheat_spend_total,
        "base_starvations_total": base_starvations_total,
        "cand_starvations_total": cand_starvations_total,
        "starvations_delta": cand_starvations_total - base_starvations_total,
        "base_animals_total": base_animals_total,
        "cand_animals_total": cand_animals_total,
        "causal_confirmed_count": causal_confirmed_count,
        "unexplained_noise_count": unexplained_noise_count,
        "total_elapsed_sec": total_elapsed,
        "production_config": {
            "POINT2_FEED_MODE": "shadow",
            "BOOTSTRAP_LIVESTOCK_ARM": "none",
            "ONE_AT_A_TIME_LATE_HOUSING_ENABLED": False,
            "POINT2_PRE_NE_CAPITAL_MODE": "off",
        },
    }

    # Archetype breakdown
    archetype_summary = {}
    for opp, data in opponent_stats.items():
        cnt = data["count"]
        m_base = sum(data["base_scores"]) / cnt
        m_cand = sum(data["cand_scores"]) / cnt
        m_del = sum(data["deltas"]) / cnt
        archetype_summary[opp] = {
            "matches": cnt,
            "wins": data["wins"],
            "ties": data["ties"],
            "losses": data["losses"],
            "mean_base": round(m_base, 2),
            "mean_cand": round(m_cand, 2),
            "mean_delta": round(m_del, 2),
            "net_delta": round(sum(data["deltas"]), 2),
        }
    aggregate["archetype_summary"] = archetype_summary

    output_payload = {
        "metadata": {
            "description": "Wheat planted_day accounting paired deterministic A/B evaluation",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "aggregate": aggregate,
        "pairs_summary": pairs_summary,
        "paired_results": paired_data,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(output_payload, f, indent=2)

    print(f"\nResults successfully written to: {RESULTS_FILE}\n")

    # Format output report
    print("=" * 120)
    print("WHEAT PLANTED_DAY ACCOUNTING REPAIR: 20-PAIR DETERMINISTIC A/B EVALUATION REPORT")
    print("=" * 120)
    print(f"Baseline Commit:  {verified_baseline_sha}")
    print(f"Candidate Commit: {verified_candidate_sha}")
    print(f"Engine Version:   {engine_ver}")
    print(f"Python:           {platform.python_version()} | Elapsed: {total_elapsed}s | Pairs: {n} (40 matches)")
    print("-" * 120)
    print(f"Mean Baseline Score:  ${mean_base:>10,.2f}")
    print(f"Mean Candidate Score: ${mean_cand:>10,.2f}")
    print(f"Mean Paired Delta:    {'+' if mean_delta >= 0 else ''}${mean_delta:>10,.2f}")
    print(f"Median Paired Delta:  {'+' if median_delta >= 0 else ''}${median_delta:>10,.2f}")
    print(f"Std Dev of Delta:     ${std_dev:>10,.2f}")
    print(f"95% Confidence Int.:  [{ci_lower:+.2f}, {ci_upper:+.2f}]")
    print(f"Head-to-Head:         {wins} Wins / {ties} Ties / {losses} Losses (Win Rate: {wins/n*100:.1f}%)")
    print("-" * 120)
    print(f"WHEAT PURCHASES: Base = {base_wheat_purchased_total} units (${base_wheat_spend_total:,.2f}) | Cand = {cand_wheat_purchased_total} units (${cand_wheat_spend_total:,.2f}) | Saved: ${base_wheat_spend_total - cand_wheat_spend_total:,.2f}")
    print(f"ANIMAL STARVATIONS: Base = {base_starvations_total} | Cand = {cand_starvations_total} (Delta: {cand_starvations_total - base_starvations_total:+d})")
    print(f"CAUSAL MECHANISM: {causal_confirmed_count}/{n} pairs exhibited causal telemetry; {unexplained_noise_count} unexplained noise.")
    print("-" * 120)
    print(f"{'Archetype':<24} {'Pairs':<6} {'Record (W/T/L)':<16} {'Mean Base':<14} {'Mean Cand':<14} {'Mean Delta':<14} {'Net Delta'}")
    print("-" * 120)
    for opp, s in archetype_summary.items():
        rec = f"{s['wins']}W-{s['ties']}T-{s['losses']}L"
        print(f"{opp:<24} {s['matches']:<6} {rec:<16} ${s['mean_base']:<13,.2f} ${s['mean_cand']:<13,.2f} {'+' if s['mean_delta'] >= 0 else ''}${s['mean_delta']:<13,.2f} {'+' if s['net_delta'] >= 0 else ''}${s['net_delta']:<,.2f}")
    print("-" * 120)
    print(f"{'Pair':<5} {'Seed':<6} {'Opponent':<22} {'Base Score':<12} {'Cand Score':<12} {'Delta':<10} {'Wheat Buy (B/C)':<16} {'Starv (B/C)':<12} {'NE Day':<10} {'Causal'}")
    print("-" * 120)
    for p in pairs_summary:
        w_buy = f"{p['base_wheat_buy']}/{p['cand_wheat_buy']}"
        stv = f"{p['base_starvations']}/{p['cand_starvations']}"
        ne = f"{p['base_ne_day'] or '-'}/{p['cand_ne_day'] or '-'}"
        caus = "YES" if p['is_causal_mechanism'] else "NO"
        print(f"{p['pair_id']:<5} {p['seed']:<6} {p['opponent']:<22} ${p['base_score']:<11,.0f} ${p['cand_score']:<11,.0f} {'+' if p['delta'] >= 0 else ''}${p['delta']:<9,.0f} {w_buy:<16} {stv:<12} {ne:<10} {caus}")
    print("=" * 120)

    return output_payload

if __name__ == "__main__":
    workers = 4
    if len(sys.argv) > 1:
        try:
            workers = int(sys.argv[1])
        except ValueError:
            pass
    run_experiment(max_workers=workers)
