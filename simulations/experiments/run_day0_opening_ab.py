"""Paired A/B Experiment: Day-0 Opening Commitment Idempotence Repair.

Compares:
  Arm A: Baseline (Commit a74d63f7ea7ad4fbed2a714f1376a36d03a0db70 — without Day-0 opening idempotence)
  Arm B: Candidate (Repaired commit — with Day-0 opening commitment idempotence & physical capacity bounding)

Across paired scenarios with matched seeds and opponent archetypes.

Telemetry Tracked:
  - Requested seed orders on Day 0 (MELON, WHEAT, and total requested spend)
  - Engine-confirmed seed purchases on Day 0 (from EOD inventory + EOD plantings, and confirmed spend)
  - Successful plantings by Day 0 EOD
  - NW empty/fallow tile usage at Day 0 EOD
  - Cash at end of Day 0 through Day 6
  - Safety incidents: unwatered crops at EOD0, animal starvations, animal deaths, negative cash steps
  - Final scores and win/loss/tie outcomes at Day 30
"""

import os
import sys
import json
import time
import tarfile
import subprocess
import traceback
from typing import Dict, Any, List
from concurrent.futures import ProcessPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Dynamic Repository & Commit Verification
# ---------------------------------------------------------------------------

def resolve_repo_root() -> str:
    """Dynamically resolve repository root without hardcoded paths."""
    curr = os.path.abspath(os.path.dirname(__file__))
    while curr and os.path.splitdrive(curr)[1] != "\\":
        if os.path.exists(os.path.join(curr, ".git")):
            return curr
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


REPO_ROOT = resolve_repo_root()
REQUIRED_BASELINE_SHA = "a74d63f7ea7ad4fbed2a714f1376a36d03a0db70"


def get_git_sha(ref: str) -> str:
    """Return the full 40-char commit SHA for a ref, or raise if invalid."""
    cmd = ["git", "rev-parse", ref]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def verify_and_extract_baseline(baseline_sha: str) -> str:
    """Verify baseline SHA against git and extract clean baseline agent via git archive."""
    actual_sha = get_git_sha(baseline_sha)
    if not actual_sha.startswith(baseline_sha):
        raise ValueError(f"Baseline SHA mismatch! Expected {baseline_sha}, got {actual_sha}")

    baseline_dir = os.path.join(REPO_ROOT, "simulations", "baselines", f"baseline_{actual_sha[:7]}")
    baseline_agent_dir = os.path.join(baseline_dir, "agent")
    marker_file = os.path.join(baseline_dir, ".extracted_sha")

    needs_extract = True
    if os.path.exists(marker_file) and os.path.exists(os.path.join(baseline_agent_dir, "main.py")):
        try:
            with open(marker_file, "r") as f:
                if f.read().strip() == actual_sha:
                    needs_extract = False
        except Exception:
            needs_extract = True

    if needs_extract:
        os.makedirs(baseline_dir, exist_ok=True)
        archive_cmd = ["git", "archive", "--format=tar", actual_sha, "agent"]
        proc = subprocess.Popen(archive_cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(path=baseline_dir, filter="data")
            else:
                tar.extractall(path=baseline_dir)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"git archive failed with returncode {proc.returncode}")
        with open(marker_file, "w") as f:
            f.write(actual_sha)

    return baseline_agent_dir


# Original 10 evaluation pairs
ORIGINAL_10_PAIRS = [
    {"pair_id": 1, "seed": 42, "opponent": "pass"},
    {"pair_id": 2, "seed": 1234, "opponent": "pass"},
    {"pair_id": 3, "seed": 101, "opponent": "pure_wheat_rush"},
    {"pair_id": 4, "seed": 55, "opponent": "pure_wheat_rush"},
    {"pair_id": 5, "seed": 2024, "opponent": "cow_milk_engine"},
    {"pair_id": 6, "seed": 314, "opponent": "cow_milk_engine"},
    {"pair_id": 7, "seed": 7, "opponent": "melon_sniper"},
    {"pair_id": 8, "seed": 8888, "opponent": "melon_sniper"},
    {"pair_id": 9, "seed": 999, "opponent": "full_production_agent"},
    {"pair_id": 10, "seed": 777, "opponent": "full_production_agent"},
]

# Expanded balanced evaluation set (30 pairs across 5 opponent archetypes with diverse fresh seeds)
EXPANDED_PAIRS = [
    # 6 matches vs pass
    {"pair_id": 1, "seed": 42, "opponent": "pass"},
    {"pair_id": 2, "seed": 1234, "opponent": "pass"},
    {"pair_id": 3, "seed": 2026, "opponent": "pass"},
    {"pair_id": 4, "seed": 4040, "opponent": "pass"},
    {"pair_id": 5, "seed": 5151, "opponent": "pass"},
    {"pair_id": 6, "seed": 6262, "opponent": "pass"},
    # 6 matches vs pure_wheat_rush
    {"pair_id": 7, "seed": 101, "opponent": "pure_wheat_rush"},
    {"pair_id": 8, "seed": 55, "opponent": "pure_wheat_rush"},
    {"pair_id": 9, "seed": 303, "opponent": "pure_wheat_rush"},
    {"pair_id": 10, "seed": 707, "opponent": "pure_wheat_rush"},
    {"pair_id": 11, "seed": 1111, "opponent": "pure_wheat_rush"},
    {"pair_id": 12, "seed": 1515, "opponent": "pure_wheat_rush"},
    # 6 matches vs cow_milk_engine
    {"pair_id": 13, "seed": 2024, "opponent": "cow_milk_engine"},
    {"pair_id": 14, "seed": 314, "opponent": "cow_milk_engine"},
    {"pair_id": 15, "seed": 2718, "opponent": "cow_milk_engine"},
    {"pair_id": 16, "seed": 3141, "opponent": "cow_milk_engine"},
    {"pair_id": 17, "seed": 4444, "opponent": "cow_milk_engine"},
    {"pair_id": 18, "seed": 5555, "opponent": "cow_milk_engine"},
    # 6 matches vs melon_sniper
    {"pair_id": 19, "seed": 7, "opponent": "melon_sniper"},
    {"pair_id": 20, "seed": 8888, "opponent": "melon_sniper"},
    {"pair_id": 21, "seed": 9191, "opponent": "melon_sniper"},
    {"pair_id": 22, "seed": 1313, "opponent": "melon_sniper"},
    {"pair_id": 23, "seed": 2424, "opponent": "melon_sniper"},
    {"pair_id": 24, "seed": 3535, "opponent": "melon_sniper"},
    # 6 matches vs full_production_agent
    {"pair_id": 25, "seed": 999, "opponent": "full_production_agent"},
    {"pair_id": 26, "seed": 777, "opponent": "full_production_agent"},
    {"pair_id": 27, "seed": 888, "opponent": "full_production_agent"},
    {"pair_id": 28, "seed": 1212, "opponent": "full_production_agent"},
    {"pair_id": 29, "seed": 3434, "opponent": "full_production_agent"},
    {"pair_id": 30, "seed": 5656, "opponent": "full_production_agent"},
]


# ---------------------------------------------------------------------------
# Isolated Match Runner
# ---------------------------------------------------------------------------

def _run_single_match(task: Dict[str, Any]) -> Dict[str, Any]:
    arm = task["arm"]
    pair_id = task["pair_id"]
    seed = task["seed"]
    opponent_name = task["opponent"]
    target_agent_dir = task["target_agent_dir"]
    repo_root = task["repo_root"]

    # Strict isolation of sys.path
    clean_sys_path = [p for p in sys.path if "agent" not in p.lower() and ".worktrees" not in p.lower()]
    sys.path = [target_agent_dir] + [
        os.path.join(target_agent_dir, sub) for sub in ("state", "strategy", "execution", "market")
    ] + [repo_root] + clean_sys_path

    # Clean local module caches to prevent state leakage
    to_delete = [
        k for k in list(sys.modules.keys())
        if any(k.startswith(p) for p in (
            "main", "config", "strategy", "state", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "animal_planner",
            "pasture_planner", "expansion_planner", "observation_parser", "state_tracker"
        ))
    ]
    for k in to_delete:
        del sys.modules[k]

    import kaggle_environments
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
    import main as agent_module
    import config as cfg
    from simulations.experiments.agent_zoo import get_agent

    # Enforce strict production default settings
    cfg.POINT2_FEED_MODE = "shadow"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
    cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"

    agent_module.reset_agent_state()

    # Telemetry storage
    day0_seed_orders: List[Dict[str, Any]] = []
    requested_melon = 0
    requested_wheat = 0
    requested_spend = 0.0

    confirmed_melon = 0
    confirmed_wheat = 0
    confirmed_spend = 0.0

    cash_by_day: Dict[str, float] = {}
    safety_incidents = {
        "negative_cash_steps": 0,
        "animal_starvations": 0,
        "animal_deaths": 0,
        "unwatered_crops_eod0": 0,
    }

    day0_eod_tiles = {
        "planted_melon": 0,
        "planted_wheat": 0,
        "total_planted": 0,
        "empty_nw_tiles": 0,
        "pasture_tiles": 0,
        "coop_tiles": 0,
        "eod_inventory_melon": 0,
        "eod_inventory_wheat": 0,
    }

    def tracking_agent(obs, config=None):
        nonlocal requested_melon, requested_wheat, requested_spend
        nonlocal confirmed_melon, confirmed_wheat, confirmed_spend
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        player_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        farm_data = farms[player_id] if len(farms) > player_id else {}
        money = float(farm_data.get("money", 0.0))
        private_data = obs.get("private", {})

        # Safety Check: Negative cash
        if money < 0:
            safety_incidents["negative_cash_steps"] += 1

        # Safety Check: Animal starvation at turn start
        if hour == 0 and day > 0:
            for row in farm_data.get("tiles", []):
                for t in row:
                    if isinstance(t, dict) and t.get("animal"):
                        if t.get("consecutive_unfed", 0) > 0:
                            safety_incidents["animal_starvations"] += 1

        # Safety Check: Dead animals
        for row in farm_data.get("tiles", []):
            for t in row:
                if isinstance(t, dict) and t.get("animal_status") == "DEAD":
                    safety_incidents["animal_deaths"] += 1

        # At Day 1 Hour 0: Observe engine-confirmed state from Day 0
        if day == 1 and hour == 0:
            seeds = private_data.get("seeds", {})
            eod_inv_melon = int(seeds.get("MELON", 0))
            eod_inv_wheat = int(seeds.get("WHEAT", 0))
            day0_eod_tiles["eod_inventory_melon"] = eod_inv_melon
            day0_eod_tiles["eod_inventory_wheat"] = eod_inv_wheat

            # Confirmed purchases: crops planted + remaining unplanted seeds in inventory
            confirmed_melon = day0_eod_tiles["planted_melon"] + eod_inv_melon
            confirmed_wheat = day0_eod_tiles["planted_wheat"] + eod_inv_wheat
            confirmed_spend = (
                confirmed_melon * CROPS.get("MELON", {}).get("seed", 80.0) +
                confirmed_wheat * CROPS.get("WHEAT", {}).get("seed", 10.0)
            )

        # Invoke agent
        action = agent_module.agent(obs, config) or {}

        # Track Day 0 requested market orders
        if day == 0:
            for order in action.get("market", []):
                if isinstance(order, (list, tuple)) and len(order) >= 3 and order[0] == "BUY_SEED":
                    crop = order[1]
                    qty = int(order[2])
                    unit_cost = CROPS.get(crop, {}).get("seed", 0.0)
                    cost = qty * unit_cost
                    day0_seed_orders.append({
                        "hour": hour,
                        "crop": crop,
                        "qty": qty,
                        "unit_cost": unit_cost,
                        "cost": cost,
                    })
                    if crop == "MELON":
                        requested_melon += qty
                    elif crop == "WHEAT":
                        requested_wheat += qty
                    requested_spend += cost

        # Track Day 0 EOD tile status at hour 23
        if day == 0 and hour == 23:
            tiles = farm_data.get("tiles", [])
            for y in range(5):
                for x in range(5):
                    if (x, y) == (4, 4):
                        continue
                    t = tiles[y][x] if y < len(tiles) and x < len(tiles[y]) else None
                    if t is None or (isinstance(t, dict) and t.get("kind") == "EMPTY"):
                        day0_eod_tiles["empty_nw_tiles"] += 1
                    elif isinstance(t, dict):
                        kind = t.get("kind")
                        if kind == "PLANT":
                            day0_eod_tiles["total_planted"] += 1
                            c = t.get("crop")
                            if c == "MELON":
                                day0_eod_tiles["planted_melon"] += 1
                            elif c == "WHEAT":
                                day0_eod_tiles["planted_wheat"] += 1
                            if not t.get("watered_today", False):
                                safety_incidents["unwatered_crops_eod0"] += 1
                        elif kind == "PASTURE":
                            day0_eod_tiles["pasture_tiles"] += 1
                        elif kind == "COOP":
                            day0_eod_tiles["coop_tiles"] += 1

        # Track cash balance at EOD for Days 0 through 6
        if hour == 23 and day <= 6:
            cash_by_day[f"d{day}"] = money

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

        # Fallback for confirmed calculation if episode finished early
        if confirmed_melon == 0 and confirmed_wheat == 0 and (day0_eod_tiles["planted_melon"] > 0 or day0_eod_tiles["planted_wheat"] > 0):
            confirmed_melon = day0_eod_tiles["planted_melon"] + day0_eod_tiles["eod_inventory_melon"]
            confirmed_wheat = day0_eod_tiles["planted_wheat"] + day0_eod_tiles["eod_inventory_wheat"]
            confirmed_spend = (
                confirmed_melon * CROPS.get("MELON", {}).get("seed", 80.0) +
                confirmed_wheat * CROPS.get("WHEAT", {}).get("seed", 10.0)
            )

        return {
            "pair_id": pair_id,
            "arm": arm,
            "seed": seed,
            "opponent": opponent_name,
            "final_score": final_score_p0,
            "opp_score": final_score_p1,
            "win": final_score_p0 > final_score_p1,
            "tie": final_score_p0 == final_score_p1,
            # Requested orders telemetry
            "day0_requested_melon": requested_melon,
            "day0_requested_wheat": requested_wheat,
            "day0_requested_total_seeds": requested_melon + requested_wheat,
            "day0_requested_seed_spend": requested_spend,
            "day0_seed_orders": day0_seed_orders,
            # Engine-confirmed purchase telemetry
            "day0_confirmed_melon": confirmed_melon,
            "day0_confirmed_wheat": confirmed_wheat,
            "day0_confirmed_total_seeds": confirmed_melon + confirmed_wheat,
            "day0_confirmed_seed_spend": confirmed_spend,
            # EOD0 state
            "day0_eod_tiles": day0_eod_tiles,
            "cash_by_day": cash_by_day,
            "safety_incidents": safety_incidents,
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
# Paired Suite Execution & Metrics
# ---------------------------------------------------------------------------

def run_experiment_suite(pairs: List[Dict[str, Any]], suite_name: str = "10_pair", max_workers: int = 4) -> Dict[str, Any]:
    # 1. Verify exact commit SHAs
    baseline_agent_dir = verify_and_extract_baseline(REQUIRED_BASELINE_SHA)
    verified_baseline_sha = get_git_sha(REQUIRED_BASELINE_SHA)
    verified_candidate_sha = get_git_sha("HEAD")

    # 2. Record engine environment metadata
    import kaggle_environments
    engine_ver = getattr(kaggle_environments, "__version__", "unknown")
    engine_file = getattr(kaggle_environments, "__file__", "unknown")

    candidate_agent_dir = os.path.join(REPO_ROOT, "agent")

    tasks = []
    for p in pairs:
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

    print(f"\n================================================================================")
    print(f"Starting A/B Replay Experiment: {suite_name.upper()} ({len(pairs)} pairs / {len(tasks)} matches)")
    print(f"  Baseline Commit:  {verified_baseline_sha} (Verified)")
    print(f"  Candidate Commit: {verified_candidate_sha} (Verified)")
    print(f"  Engine Version:   {engine_ver} ({engine_file})")
    print(f"  Workers:          {max_workers}")
    print(f"================================================================================\n")

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
            print(f"  [{completed:2d}/{total:2d}] {res['arm']:9s} Pair {res['pair_id']:2d} (Seed {res['seed']:5d} vs {res['opponent']:20s}): Score={res['final_score']:10.1f} ({res['elapsed']}s)")

    # Align pairs
    paired_data = {}
    for r in results:
        pid = r["pair_id"]
        if pid not in paired_data:
            paired_data[pid] = {}
        paired_data[pid][r["arm"]] = r

    pairs_summary = []
    for p in pairs:
        pid = p["pair_id"]
        base = paired_data[pid].get("Baseline", {})
        cand = paired_data[pid].get("Candidate", {})

        score_delta = cand.get("final_score", 0.0) - base.get("final_score", 0.0)
        req_melon_delta = cand.get("day0_requested_melon", 0) - base.get("day0_requested_melon", 0)
        req_wheat_delta = cand.get("day0_requested_wheat", 0) - base.get("day0_requested_wheat", 0)
        req_spend_delta = cand.get("day0_requested_seed_spend", 0.0) - base.get("day0_requested_seed_spend", 0.0)

        conf_melon_delta = cand.get("day0_confirmed_melon", 0) - base.get("day0_confirmed_melon", 0)
        conf_wheat_delta = cand.get("day0_confirmed_wheat", 0) - base.get("day0_confirmed_wheat", 0)
        conf_spend_delta = cand.get("day0_confirmed_seed_spend", 0.0) - base.get("day0_confirmed_seed_spend", 0.0)

        empty_delta = cand.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0) - base.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0)

        pairs_summary.append({
            "pair_id": pid,
            "seed": p["seed"],
            "opponent": p["opponent"],
            "base_score": base.get("final_score", 0.0),
            "cand_score": cand.get("final_score", 0.0),
            "score_delta": score_delta,
            # Requested metrics
            "base_requested_melon": base.get("day0_requested_melon", 0),
            "cand_requested_melon": cand.get("day0_requested_melon", 0),
            "base_requested_wheat": base.get("day0_requested_wheat", 0),
            "cand_requested_wheat": cand.get("day0_requested_wheat", 0),
            "base_requested_spend": base.get("day0_requested_seed_spend", 0.0),
            "cand_requested_spend": cand.get("day0_requested_seed_spend", 0.0),
            # Confirmed metrics
            "base_confirmed_melon": base.get("day0_confirmed_melon", 0),
            "cand_confirmed_melon": cand.get("day0_confirmed_melon", 0),
            "base_confirmed_wheat": base.get("day0_confirmed_wheat", 0),
            "cand_confirmed_wheat": cand.get("day0_confirmed_wheat", 0),
            "base_confirmed_spend": base.get("day0_confirmed_seed_spend", 0.0),
            "cand_confirmed_spend": cand.get("day0_confirmed_seed_spend", 0.0),
            # EOD0 tiles & cash
            "base_eod_planted": base.get("day0_eod_tiles", {}).get("total_planted", 0),
            "cand_eod_planted": cand.get("day0_eod_tiles", {}).get("total_planted", 0),
            "base_eod_empty": base.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0),
            "cand_eod_empty": cand.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0),
            "empty_delta": empty_delta,
            "base_cash_d0": base.get("cash_by_day", {}).get("d0", 0.0),
            "cand_cash_d0": cand.get("cash_by_day", {}).get("d0", 0.0),
            "base_cash_d1": base.get("cash_by_day", {}).get("d1", 0.0),
            "cand_cash_d1": cand.get("cash_by_day", {}).get("d1", 0.0),
            "base_cash_d6": base.get("cash_by_day", {}).get("d6", 0.0),
            "cand_cash_d6": cand.get("cash_by_day", {}).get("d6", 0.0),
            # Safety
            "base_safety": base.get("safety_incidents", {}),
            "cand_safety": cand.get("safety_incidents", {}),
        })

    pairs_summary.sort(key=lambda x: x["pair_id"])

    # Aggregate summaries
    n = len(pairs_summary)
    mean_base_score = sum(p["base_score"] for p in pairs_summary) / n
    mean_cand_score = sum(p["cand_score"] for p in pairs_summary) / n
    mean_score_delta = sum(p["score_delta"] for p in pairs_summary) / n
    wins = sum(1 for p in pairs_summary if p["score_delta"] > 0)
    ties = sum(1 for p in pairs_summary if p["score_delta"] == 0)
    losses = sum(1 for p in pairs_summary if p["score_delta"] < 0)

    total_base_req_melon = sum(p["base_requested_melon"] for p in pairs_summary)
    total_cand_req_melon = sum(p["cand_requested_melon"] for p in pairs_summary)
    total_base_conf_melon = sum(p["base_confirmed_melon"] for p in pairs_summary)
    total_cand_conf_melon = sum(p["cand_confirmed_melon"] for p in pairs_summary)

    total_base_req_wheat = sum(p["base_requested_wheat"] for p in pairs_summary)
    total_cand_req_wheat = sum(p["cand_requested_wheat"] for p in pairs_summary)
    total_base_conf_wheat = sum(p["base_confirmed_wheat"] for p in pairs_summary)
    total_cand_conf_wheat = sum(p["cand_confirmed_wheat"] for p in pairs_summary)

    total_base_req_spend = sum(p["base_requested_spend"] for p in pairs_summary)
    total_cand_req_spend = sum(p["cand_requested_spend"] for p in pairs_summary)
    total_base_conf_spend = sum(p["base_confirmed_spend"] for p in pairs_summary)
    total_cand_conf_spend = sum(p["cand_confirmed_spend"] for p in pairs_summary)

    # Total safety incidents across all matches
    base_safety_totals = {
        "negative_cash_steps": sum(p["base_safety"].get("negative_cash_steps", 0) for p in pairs_summary),
        "animal_starvations": sum(p["base_safety"].get("animal_starvations", 0) for p in pairs_summary),
        "animal_deaths": sum(p["base_safety"].get("animal_deaths", 0) for p in pairs_summary),
        "unwatered_crops_eod0": sum(p["base_safety"].get("unwatered_crops_eod0", 0) for p in pairs_summary),
    }
    cand_safety_totals = {
        "negative_cash_steps": sum(p["cand_safety"].get("negative_cash_steps", 0) for p in pairs_summary),
        "animal_starvations": sum(p["cand_safety"].get("animal_starvations", 0) for p in pairs_summary),
        "animal_deaths": sum(p["cand_safety"].get("animal_deaths", 0) for p in pairs_summary),
        "unwatered_crops_eod0": sum(p["cand_safety"].get("unwatered_crops_eod0", 0) for p in pairs_summary),
    }

    aggregate = {
        "suite_name": suite_name,
        "total_pairs": n,
        "mean_base_score": round(mean_base_score, 2),
        "mean_cand_score": round(mean_cand_score, 2),
        "mean_score_delta": round(mean_score_delta, 2),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        # Requested seed metrics
        "total_base_requested_melon": total_base_req_melon,
        "total_cand_requested_melon": total_cand_req_melon,
        "total_base_requested_wheat": total_base_req_wheat,
        "total_cand_requested_wheat": total_cand_req_wheat,
        "total_base_requested_spend": total_base_req_spend,
        "total_cand_requested_spend": total_cand_req_spend,
        "redundant_requested_melon_orders_eliminated": total_base_req_melon - total_cand_req_melon,
        "redundant_requested_spend_eliminated": total_base_req_spend - total_cand_req_spend,
        # Confirmed seed metrics
        "total_base_confirmed_melon": total_base_conf_melon,
        "total_cand_confirmed_melon": total_cand_conf_melon,
        "total_base_confirmed_wheat": total_base_conf_wheat,
        "total_cand_confirmed_wheat": total_cand_conf_wheat,
        "total_base_confirmed_spend": total_base_conf_spend,
        "total_cand_confirmed_spend": total_cand_conf_spend,
        "redundant_confirmed_melon_eliminated": total_base_conf_melon - total_cand_conf_melon,
        "redundant_confirmed_spend_eliminated": total_base_conf_spend - total_cand_conf_spend,
        # Safety totals
        "baseline_safety_incidents": base_safety_totals,
        "candidate_safety_incidents": cand_safety_totals,
        "total_elapsed_sec": round(time.time() - t_start, 2),
    }

    metadata = {
        "experiment_name": "day0_opening_commitment_idempotence_ab",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "baseline_sha": verified_baseline_sha,
        "candidate_sha": verified_candidate_sha,
        "engine_version": engine_ver,
        "engine_file": engine_file,
        "production_config": {
            "POINT2_FEED_MODE": "shadow",
            "BOOTSTRAP_LIVESTOCK_ARM": "none",
            "ONE_AT_A_TIME_LATE_HOUSING_ENABLED": False,
            "POINT2_PRE_NE_CAPITAL_MODE": "off",
        },
    }

    full_output = {
        "metadata": metadata,
        "aggregate": aggregate,
        "pairs_summary": pairs_summary,
        "raw_results": results,
    }

    return full_output


def print_report(data: Dict[str, Any]):
    meta = data["metadata"]
    agg = data["aggregate"]
    pairs = data["pairs_summary"]

    print("\n" + "=" * 120)
    print(f"DAY-0 OPENING COMMITMENT IDEMPOTENCE REPAIR: {agg['suite_name'].upper()} REPORT")
    print("=" * 120)
    print(f"Baseline Commit:  {meta['baseline_sha']}")
    print(f"Candidate Commit: {meta['candidate_sha']}")
    print(f"Engine:           {meta['engine_version']} ({meta['engine_file']})")
    print(f"Pairs Evaluated:  {agg['total_pairs']} | Elapsed: {agg['total_elapsed_sec']}s")
    print("-" * 120)
    print(f"Mean Baseline Score:  ${agg['mean_base_score']:10,.2f}")
    print(f"Mean Candidate Score: ${agg['mean_cand_score']:10,.2f}")
    print(f"Mean Score Delta:     {'+' if agg['mean_score_delta'] >= 0 else ''}${agg['mean_score_delta']:10,.2f}")
    print(f"Head-to-Head:         {agg['wins']} Wins / {agg['ties']} Ties / {agg['losses']} Losses")
    print("-" * 120)
    print(f"REQUESTED SEEDS: Base={agg['total_base_requested_melon']}M/{agg['total_base_requested_wheat']}W (${agg['total_base_requested_spend']:,.0f}) | Cand={agg['total_cand_requested_melon']}M/{agg['total_cand_requested_wheat']}W (${agg['total_cand_requested_spend']:,.0f}) | Orders Saved: {agg['redundant_requested_melon_orders_eliminated']} Melons (${agg['redundant_requested_spend_eliminated']:,.0f})")
    print(f"CONFIRMED SEEDS: Base={agg['total_base_confirmed_melon']}M/{agg['total_base_confirmed_wheat']}W (${agg['total_base_confirmed_spend']:,.0f}) | Cand={agg['total_cand_confirmed_melon']}M/{agg['total_cand_confirmed_wheat']}W (${agg['total_cand_confirmed_spend']:,.0f}) | Purchases Saved: {agg['redundant_confirmed_melon_eliminated']} Melons (${agg['redundant_confirmed_spend_eliminated']:,.0f})")
    print("-" * 120)
    print("SAFETY INCIDENTS (Baseline vs Candidate):")
    b_safe = agg["baseline_safety_incidents"]
    c_safe = agg["candidate_safety_incidents"]
    print(f"  Unwatered Crops (EOD0): {b_safe['unwatered_crops_eod0']} vs {c_safe['unwatered_crops_eod0']}")
    print(f"  Animal Starvations:     {b_safe['animal_starvations']} vs {c_safe['animal_starvations']}")
    print(f"  Animal Deaths:          {b_safe['animal_deaths']} vs {c_safe['animal_deaths']}")
    print(f"  Negative Cash Steps:    {b_safe['negative_cash_steps']} vs {c_safe['negative_cash_steps']}")
    print("-" * 120)

    header = f"{'Pair':<5}{'Seed':<7}{'Opponent':<22}{'Base Score':<13}{'Cand Score':<13}{'Delta':<10}{'Req (B/C)':<14}{'Conf (B/C)':<14}{'NW Empty':<10}{'D0 Cash (B/C)':<14}"
    print(header)
    print("-" * 120)

    for p in pairs:
        delta_str = f"{'+' if p['score_delta'] >= 0 else ''}{p['score_delta']:,.0f}"
        req_bc = f"{p['base_requested_melon']}M / {p['cand_requested_melon']}M"
        conf_bc = f"{p['base_confirmed_melon']}M / {p['cand_confirmed_melon']}M"
        nw_empty = f"{p['base_eod_empty']} -> {p['cand_eod_empty']}"
        cash_bc = f"${p['base_cash_d0']:.0f}/${p['cand_cash_d0']:.0f}"
        print(f"{p['pair_id']:<5}{p['seed']:<7}{p['opponent']:<22}${p['base_score']:<12,.0f}${p['cand_score']:<12,.0f}{delta_str:<10}{req_bc:<14}{conf_bc:<14}{nw_empty:<10}{cash_bc:<14}")

    print("=" * 120 + "\n")


def run_original_10_pairs(max_workers: int = 4) -> Dict[str, Any]:
    """Run corrected 10-pair evaluation and save to separate file."""
    data = run_experiment_suite(ORIGINAL_10_PAIRS, suite_name="10_pair", max_workers=max_workers)
    out_path = os.path.join(REPO_ROOT, "simulations", "experiments", "results", "day0_opening_ab_corrected_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Corrected 10-pair results written to: {out_path}")
    print_report(data)
    return data


def run_expanded_pairs(max_workers: int = 4) -> Dict[str, Any]:
    """Run expanded 30-pair evaluation with balanced opponents and fresh seeds."""
    data = run_experiment_suite(EXPANDED_PAIRS, suite_name="expanded_30_pair", max_workers=max_workers)
    out_path = os.path.join(REPO_ROOT, "simulations", "experiments", "results", "day0_opening_ab_expanded_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Expanded 30-pair results written to: {out_path}")
    print_report(data)
    return data


if __name__ == "__main__":
    workers = min(4, os.cpu_count() or 4)
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "10_pair":
        run_original_10_pairs(max_workers=workers)
    elif mode == "expanded":
        run_expanded_pairs(max_workers=workers)
    else:
        run_original_10_pairs(max_workers=workers)
        run_expanded_pairs(max_workers=workers)
