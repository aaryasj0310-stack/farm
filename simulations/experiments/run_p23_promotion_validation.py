#!/usr/bin/env python3
"""P2.3 Promotion Held-Out Validation Runner.

Validates Pre-P2.3 Production Control (commit 237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e)
against New Promoted Production (P23_MARGINAL_WHEAT_ALLOCATION_ENABLED=True, QUADRANT_HARD_BLOCK={4}).

100 matched cases (50 pairs x 2 seats = 200 live games).
Strictly fresh seed block: 89,001–89,050.
Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
ARMS = ("OldProduction", "PromotedProduction")
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

# Strictly fresh seed block: 89,001+
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 89001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(50)  # 50 pairs x 2 seats = 100 matched cases (200 games)
]


def _git_sha(ref: str) -> str:
    res = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _extract_control_agent(commit_sha: str) -> str:
    out_dir = os.path.join(tempfile.gettempdir(), f"kagg_p23_promo_ctrl_{commit_sha[:8]}")
    if os.path.exists(out_dir):
        try:
            shutil.rmtree(out_dir)
        except Exception:
            pass
    os.makedirs(out_dir, exist_ok=True)
    tar = subprocess.Popen(["git", "archive", commit_sha, "agent"], cwd=ROOT, stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", out_dir], stdin=tar.stdout, check=True)
    tar.wait()
    agent_dir = os.path.join(out_dir, "agent")
    if not os.path.isdir(agent_dir):
        raise RuntimeError(f"Failed to extract agent/ from {commit_sha}")
    return agent_dir


def _snapshot_worktree_agent(temp_dir: str):
    target = os.path.join(temp_dir, "worktree_agent")
    src = os.path.join(ROOT, "agent")
    shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    manifest = []
    for base, _, files in os.walk(target):
        for f in sorted(files):
            if f.endswith(".py"):
                p = os.path.join(base, f)
                manifest.append((os.path.relpath(p, target), os.path.getsize(p)))
    import hashlib
    h = hashlib.sha256(repr(manifest).encode("utf-8")).hexdigest()
    return target, manifest, h


def _configure_arm(cfg, arm: str):
    """Enforce strict 2Q invariants and set P23 flag."""
    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    elif hasattr(cfg, "QUADRANT_HARD_BLOCK"):
        cfg.QUADRANT_HARD_BLOCK = {4}

    # Reset legacy SW switches and prior non-promoted treatments
    for attr, val in (
        ("SW_OWNERSHIP_MODE", "production"),
        ("SW_TIMING_PRIOR_ENABLED", False),
        ("SW_ACTIVATION_MODE", "production"),
        ("STRATEGIC_SW_OWNERSHIP_ENABLED", False),
        ("DYNAMIC_ZONAL_ALLOCATION", False),
        ("DYNAMIC_SW_CROPS_ENABLED", False),
        ("PERSISTENT_WORKER_LOCALITY_ENABLED", False),
        ("SW_CELL_HOUSING_ENABLED", False),
        ("SW_P1_PURCHASE_COMMITTED_HERD_ONLY", False),
        ("SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED", False),
        ("SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED", False),
        ("SW_GENERIC_PLANTING_GATE_ENABLED", False),
        ("P13_TIGHT_SOIL_ENABLED", False),
        ("P13_LIVESTOCK_CAP_ENABLED", False),
        ("P20_SECOND_MELON_TRANCHE_ENABLED", False),
        ("P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED", False),
        ("P22A_DAY28_FEED_HARMONIZATION_ENABLED", False),
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    if hasattr(cfg, "set_p20_second_melon_tranche_enabled"):
        cfg.set_p20_second_melon_tranche_enabled(False)
    if hasattr(cfg, "set_p21_dynamic_strawberry_allocation_enabled"):
        cfg.set_p21_dynamic_strawberry_allocation_enabled(False)
    if hasattr(cfg, "set_p22a_day28_feed_harmonization_enabled"):
        cfg.set_p22a_day28_feed_harmonization_enabled(False)

    # Set P23 switch
    expected_p23 = (arm == "PromotedProduction")
    if hasattr(cfg, "set_p23_marginal_wheat_allocation_enabled"):
        cfg.set_p23_marginal_wheat_allocation_enabled(expected_p23)
    else:
        setattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", expected_p23)

    # Assertions
    assert cfg.QUADRANT_HARD_BLOCK == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    actual_p23 = getattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", False)
    assert actual_p23 == expected_p23, f"{arm}: P23 expected {expected_p23}, got {actual_p23}"


def _verify_manifest(control_dir, worktree_dir):
    for arm, d in (("OldProduction", control_dir), ("PromotedProduction", worktree_dir)):
        for k in list(sys.modules):
            if any(k == m or k.startswith(m + ".") for m in ("config", "main", "macro_planner", "market_brain", "central_planner")):
                del sys.modules[k]
        sys.path.insert(0, d)
        import config as cfg
        _configure_arm(cfg, arm)
        print(f"Verified {arm} config: QUADRANT_HARD_BLOCK={cfg.QUADRANT_HARD_BLOCK}, P23_ENABLED={getattr(cfg, 'P23_MARGINAL_WHEAT_ALLOCATION_ENABLED', False)}", flush=True)


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner"
        )):
            del sys.modules[key]

    try:
        import kaggle_environments
        import main as module
        import config as cfg
        import execution.task_scheduler as ts
        from simulations.experiments.agent_zoo import get_agent

        _configure_arm(cfg, task["arm"])
        module.reset_agent_state()
        ts.reset_daily_log()

        m = {
            "negative_cash_steps": 0, "cash_min": float("inf"),
            "daily_cash": {},
            "unwatered_eod": {"NW": 0, "NE": 0},
            "starvation_animal_days": 0,
            "starvation_animal_hours": 0,
            "wheat_tiles_planted": 0,
            "carrot_tiles_planted": 0,
            "strawberry_tiles_planted": 0,
            "melon_tiles_planted": 0,
            "crop_tiles_planted": defaultdict(int),
            "wheat_fed_units": 0,
            "wheat_buy_units": 0, "wheat_buy_spend": 0.0,
            "wheat_sell_units": 0, "wheat_sell_receipts": 0.0,
            "carrot_sell_units": 0, "carrot_sell_receipts": 0.0,
            "crop_revenue": 0.0, "animal_revenue": 0.0,
            "milk_revenue": 0.0, "wool_revenue": 0.0, "egg_revenue": 0.0,
            "seed_spend": 0.0,
            "p23_yielded_count": 0,
            "p23_terminal_blocked_count": 0,
        }

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            player = int(obs.get("player", task["seat"]))
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}
            money = float(farm.get("money", 0.0))

            if money < 0:
                m["negative_cash_steps"] += 1
            if money < m["cash_min"]:
                m["cash_min"] = money

            for row in farm.get("tiles", []) or []:
                for t in row or []:
                    if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                        if int(t.get("consecutive_unfed", 0) or 0) >= 1:
                            m["starvation_animal_hours"] += 1

            if hour == 23:
                m["daily_cash"][day] = money
                for y, row in enumerate(farm.get("tiles", []) or []):
                    for x, t in enumerate(row or []):
                        if isinstance(t, dict) and t.get("kind") == "PLANT":
                            q = ("N" if y < 5 else "S") + ("W" if x < 5 else "E")
                            if q in m["unwatered_eod"] and not t.get("watered_today", False):
                                m["unwatered_eod"][q] += 1
                        elif isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                            if not t.get("fed_today", False):
                                m["starvation_animal_days"] += 1

            action = module.agent(obs, configuration) or {}

            # Parse actions
            if isinstance(action, dict):
                for u_act in action.get("hands", []) + [action.get("farmer")]:
                    if isinstance(u_act, (list, tuple)) and len(u_act) >= 1:
                        op = u_act[0]
                        if op == "PLANT":
                            c = u_act[1] if len(u_act) >= 2 else ""
                            m["crop_tiles_planted"][c] += 1
                            if c == "WHEAT":
                                m["wheat_tiles_planted"] += 1
                            elif c == "CARROT":
                                m["carrot_tiles_planted"] += 1
                            elif c == "STRAWBERRY":
                                m["strawberry_tiles_planted"] += 1
                            elif c == "MELON":
                                m["melon_tiles_planted"] += 1
                        elif op == "FEED":
                            m["wheat_fed_units"] += 1

                for order in action.get("orders", []) or []:
                    if isinstance(order, (list, tuple)) and len(order) >= 4:
                        side, prod, amt, p = order[0], order[1], order[2], order[3]
                        if side == "BUY":
                            if prod == "WHEAT":
                                m["wheat_buy_units"] += amt
                                m["wheat_buy_spend"] += amt * p
                            elif prod in ("CARROT_SEED", "WHEAT_SEED", "TOMATO_SEED", "STRAWBERRY_SEED", "MELON_SEED"):
                                m["seed_spend"] += amt * p
                        elif side == "SELL":
                            receipt = amt * p
                            if prod == "WHEAT":
                                m["wheat_sell_units"] += amt
                                m["wheat_sell_receipts"] += receipt
                                m["crop_revenue"] += receipt
                            elif prod == "CARROT":
                                m["carrot_sell_units"] += amt
                                m["carrot_sell_receipts"] += receipt
                                m["crop_revenue"] += receipt
                            elif prod in ("TOMATO", "STRAWBERRY", "MELON"):
                                m["crop_revenue"] += receipt
                            elif prod == "MILK":
                                m["milk_revenue"] += receipt
                                m["animal_revenue"] += receipt
                            elif prod == "WOOL":
                                m["wool_revenue"] += receipt
                                m["animal_revenue"] += receipt
                            elif prod in ("EGG", "FEATHER"):
                                m["egg_revenue"] += receipt
                                m["animal_revenue"] += receipt

            return action

        opp = get_agent(task["opponent"])
        agents = [tracking, opp] if task["seat"] == 0 else [opp, tracking]
        env = kaggle_environments.make(
            "kaggriculture",
            configuration={"episodeSteps": 720, "seed": task["seed"]},
        )
        env.reset()
        t0 = time.time()
        env.run(agents)
        wall_time = time.time() - t0

        state = env.state[task["seat"]]
        score = float(state.reward) if state.reward is not None else 0.0
        opp_state = env.state[1 - task["seat"]]
        opp_score = float(opp_state.reward) if opp_state.reward is not None else 0.0

        return {
            "scenario": task["pair_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "seat": task["seat"],
            "arm": task["arm"],
            "score": score,
            "opp_score": opp_score,
            "wall_time": wall_time,
            "negative_cash_steps": m["negative_cash_steps"],
            "cash_min": m["cash_min"] if m["cash_min"] != float("inf") else 0.0,
            "unwatered_eod_nw": m["unwatered_eod"]["NW"],
            "unwatered_eod_ne": m["unwatered_eod"]["NE"],
            "starvation_animal_days": m["starvation_animal_days"],
            "starvation_animal_hours": m["starvation_animal_hours"],
            "wheat_tiles_planted": m["wheat_tiles_planted"],
            "carrot_tiles_planted": m["carrot_tiles_planted"],
            "strawberry_tiles_planted": m["strawberry_tiles_planted"],
            "melon_tiles_planted": m["melon_tiles_planted"],
            "wheat_fed_units": m["wheat_fed_units"],
            "wheat_buy_spend": m["wheat_buy_spend"],
            "wheat_sell_receipts": m["wheat_sell_receipts"],
            "carrot_sell_receipts": m["carrot_sell_receipts"],
            "crop_revenue": m["crop_revenue"],
            "animal_revenue": m["animal_revenue"],
            "milk_revenue": m["milk_revenue"],
            "wool_revenue": m["wool_revenue"],
            "egg_revenue": m["egg_revenue"],
            "seed_spend": m["seed_spend"],
            "error": None,
        }
    except Exception as e:
        return {
            "scenario": task["pair_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "seat": task["seat"],
            "arm": task["arm"],
            "score": 0.0,
            "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="P2.3 Promotion Held-Out Validation")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel worker processes")
    args = parser.parse_args()

    num_workers = args.workers
    print(f"Starting P2.3 Promotion Validation with {num_workers} parallel workers...")
    print(f"Control SHA: {BASELINE_SHA}")
    print(f"Scenarios: {len(SCENARIOS)} pairs (fresh seeds {SCENARIOS[0]['seed']} to {SCENARIOS[-1]['seed']})")

    # 1. Setup agents
    temp_dir = tempfile.mkdtemp(prefix="kagg_p23_promo_ab_")
    control_dir = _extract_control_agent(BASELINE_SHA)
    worktree_dir, manifest, worktree_hash = _snapshot_worktree_agent(temp_dir)
    print(f"Extracted Old Production Control to: {control_dir}")
    print(f"Snapshotted Promoted Production worktree to: {worktree_dir} (hash={worktree_hash[:8]})")

    _verify_manifest(control_dir, worktree_dir)

    # 2. Build tasks
    tasks = []
    for sc in SCENARIOS:
        for seat in (0, 1):
            tasks.append({
                "pair_id": sc["pair_id"],
                "seed": sc["seed"],
                "opponent": sc["opponent"],
                "seat": seat,
                "arm": "OldProduction",
                "agent_dir": control_dir,
            })
            tasks.append({
                "pair_id": sc["pair_id"],
                "seed": sc["seed"],
                "opponent": sc["opponent"],
                "seat": seat,
                "arm": "PromotedProduction",
                "agent_dir": worktree_dir,
            })

    total_games = len(tasks)
    print(f"Built {total_games} total simulation runs (100 matched pairs x 2 arms).")

    # 3. Execute
    results_by_arm = defaultdict(list)
    paired_runs = defaultdict(dict)
    errors = []

    start_time = time.time()
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(_one, t): t for t in tasks}
        completed = 0
        for f in as_completed(futures):
            completed += 1
            res = f.result()
            if res.get("error"):
                errors.append(res)
                print(f"[{completed}/{total_games}] ERROR in {res['arm']} seed {res['seed']}: {res['error']}", flush=True)
            else:
                arm = res["arm"]
                results_by_arm[arm].append(res)
                key = (res["scenario"], res["seed"], res["seat"])
                paired_runs[key][arm] = res
                if completed % 10 == 0 or completed == total_games:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(f"[{completed}/{total_games}] ({rate:.1f} games/s) completed. Arm counts: OldProduction={len(results_by_arm['OldProduction'])}, PromotedProduction={len(results_by_arm['PromotedProduction'])}", flush=True)

    elapsed_total = time.time() - start_time
    print(f"All {completed} games finished in {elapsed_total:.1f}s", flush=True)

    # Statistical Evaluation
    paired_deltas = []
    ctrl_scores, treat_scores = [], []
    ctrl_wheat_planted, treat_wheat_planted = [], []
    ctrl_carrot_planted, treat_carrot_planted = [], []
    ctrl_wheat_fed, treat_wheat_fed = [], []
    ctrl_wheat_bought, treat_wheat_bought = [], []
    ctrl_wheat_sold, treat_wheat_sold = [], []
    ctrl_carrot_sold_rev, treat_carrot_sold_rev = [], []
    ctrl_crop_rev, treat_crop_rev = [], []
    ctrl_animal_rev, treat_animal_rev = [], []
    ctrl_starvation_days, treat_starvation_days = [], []
    ctrl_starvation_hrs, treat_starvation_hrs = [], []
    wins, losses, ties = 0, 0, 0

    for key, arm_dict in sorted(paired_runs.items()):
        if "OldProduction" in arm_dict and "PromotedProduction" in arm_dict:
            c = arm_dict["OldProduction"]
            t = arm_dict["PromotedProduction"]
            sc_c = c["score"]
            sc_t = t["score"]
            delta = sc_t - sc_c
            paired_deltas.append(delta)
            ctrl_scores.append(sc_c)
            treat_scores.append(sc_t)

            ctrl_wheat_planted.append(c["wheat_tiles_planted"])
            treat_wheat_planted.append(t["wheat_tiles_planted"])
            ctrl_carrot_planted.append(c["carrot_tiles_planted"])
            treat_carrot_planted.append(t["carrot_tiles_planted"])

            ctrl_wheat_fed.append(c["wheat_fed_units"])
            treat_wheat_fed.append(t["wheat_fed_units"])
            ctrl_wheat_bought.append(c["wheat_buy_spend"])
            treat_wheat_bought.append(t["wheat_buy_spend"])
            ctrl_wheat_sold.append(c["wheat_sell_receipts"])
            treat_wheat_sold.append(t["wheat_sell_receipts"])

            ctrl_carrot_sold_rev.append(c["carrot_sell_receipts"])
            treat_carrot_sold_rev.append(t["carrot_sell_receipts"])
            ctrl_crop_rev.append(c["crop_revenue"])
            treat_crop_rev.append(t["crop_revenue"])
            ctrl_animal_rev.append(c["animal_revenue"])
            treat_animal_rev.append(t["animal_revenue"])

            ctrl_starvation_days.append(c["starvation_animal_days"])
            treat_starvation_days.append(t["starvation_animal_days"])
            ctrl_starvation_hrs.append(c["starvation_animal_hours"])
            treat_starvation_hrs.append(t["starvation_animal_hours"])

            if delta > 1e-4:
                wins += 1
            elif delta < -1e-4:
                losses += 1
            else:
                ties += 1

    n_pairs = len(paired_deltas)
    mean_ctrl = statistics.mean(ctrl_scores) if ctrl_scores else 0.0
    mean_treat = statistics.mean(treat_scores) if treat_scores else 0.0
    mean_delta = statistics.mean(paired_deltas) if paired_deltas else 0.0
    median_delta = statistics.median(paired_deltas) if paired_deltas else 0.0
    std_delta = statistics.stdev(paired_deltas) if len(paired_deltas) > 1 else 0.0
    se_delta = std_delta / math.sqrt(n_pairs) if n_pairs > 0 else 0.0
    ci_95 = (mean_delta - 1.984 * se_delta, mean_delta + 1.984 * se_delta)
    t_stat = mean_delta / se_delta if se_delta > 0 else 0.0

    # Student's t distribution approximation
    import scipy.stats as st
    try:
        p_val = st.ttest_1samp(paired_deltas, 0.0).pvalue
    except Exception:
        p_val = float("nan")

    print("\n" + "=" * 70)
    print("P2.3 PROMOTION VALIDATION REPORT (HELD-OUT SEEDS 89,001–89,050)")
    print("=" * 70)
    print(f"Matched Pairs Evaluated : {n_pairs}")
    print(f"Old Production Mean     : ${mean_ctrl:,.2f}")
    print(f"Promoted Production Mean: ${mean_treat:,.2f}")
    print(f"Mean Paired Delta       : ${mean_delta:+,.2f}/game")
    print(f"Median Paired Delta     : ${median_delta:+,.2f}/game")
    print(f"95% Confidence Interval : [${ci_95[0]:+,.2f}, ${ci_95[1]:+,.2f}]")
    print(f"t-statistic / p-value   : t = {t_stat:.4f}, p = {p_val:.4e}")
    print(f"Record (Wins/Losses/Ties): {wins}W / {losses}L / {ties}T (Win Rate: {wins/n_pairs*100:.1f}%)")
    print("-" * 70)
    print(f"Wheat Tiles Planted     : Old={statistics.mean(ctrl_wheat_planted):.1f} vs Promoted={statistics.mean(treat_wheat_planted):.1f} (Diff: {statistics.mean(treat_wheat_planted)-statistics.mean(ctrl_wheat_planted):+.1f})")
    print(f"Carrot Tiles Planted    : Old={statistics.mean(ctrl_carrot_planted):.1f} vs Promoted={statistics.mean(treat_carrot_planted):.1f} (Diff: {statistics.mean(treat_carrot_planted)-statistics.mean(ctrl_carrot_planted):+.1f})")
    print(f"Wheat Fed Units         : Old={statistics.mean(ctrl_wheat_fed):.1f} vs Promoted={statistics.mean(treat_wheat_fed):.1f} (Diff: {statistics.mean(treat_wheat_fed)-statistics.mean(ctrl_wheat_fed):+.1f})")
    print(f"Wheat Buy Spend         : Old=${statistics.mean(ctrl_wheat_bought):,.2f} vs Promoted=${statistics.mean(treat_wheat_bought):,.2f}")
    print(f"Carrot Sales Revenue    : Old=${statistics.mean(ctrl_carrot_sold_rev):,.2f} vs Promoted=${statistics.mean(treat_carrot_sold_rev):,.2f} (Diff: ${statistics.mean(treat_carrot_sold_rev)-statistics.mean(ctrl_carrot_sold_rev):+,.2f})")
    print(f"Total Crop Revenue      : Old=${statistics.mean(ctrl_crop_rev):,.2f} vs Promoted=${statistics.mean(treat_crop_rev):,.2f} (Diff: ${statistics.mean(treat_crop_rev)-statistics.mean(ctrl_crop_rev):+,.2f})")
    print(f"Animal Revenue          : Old=${statistics.mean(ctrl_animal_rev):,.2f} vs Promoted=${statistics.mean(treat_animal_rev):,.2f} (Diff: ${statistics.mean(treat_animal_rev)-statistics.mean(ctrl_animal_rev):+,.2f})")
    print(f"Starvation Days (EOD)   : Old={sum(ctrl_starvation_days)} vs Promoted={sum(treat_starvation_days)}")
    print("=" * 70)

    # Save results
    out_dir = os.path.join(ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "p23_promotion_validation.json")
    summary = {
        "baseline_sha": BASELINE_SHA,
        "n_matched_pairs": n_pairs,
        "seed_range": [SCENARIOS[0]["seed"], SCENARIOS[-1]["seed"]],
        "old_production_mean": mean_ctrl,
        "promoted_production_mean": mean_treat,
        "mean_paired_delta": mean_delta,
        "median_paired_delta": median_delta,
        "ci_95": list(ci_95),
        "t_stat": t_stat,
        "p_val": p_val,
        "record": {"wins": wins, "losses": losses, "ties": ties},
        "telemetry": {
            "wheat_planted_old": statistics.mean(ctrl_wheat_planted),
            "wheat_planted_promoted": statistics.mean(treat_wheat_planted),
            "carrot_planted_old": statistics.mean(ctrl_carrot_planted),
            "carrot_planted_promoted": statistics.mean(treat_carrot_planted),
            "wheat_fed_old": statistics.mean(ctrl_wheat_fed),
            "wheat_fed_promoted": statistics.mean(treat_wheat_fed),
            "wheat_bought_spend_old": statistics.mean(ctrl_wheat_bought),
            "wheat_bought_spend_promoted": statistics.mean(treat_wheat_bought),
            "carrot_revenue_old": statistics.mean(ctrl_carrot_sold_rev),
            "carrot_revenue_promoted": statistics.mean(treat_carrot_sold_rev),
            "crop_revenue_old": statistics.mean(ctrl_crop_rev),
            "crop_revenue_promoted": statistics.mean(treat_crop_rev),
            "animal_revenue_old": statistics.mean(ctrl_animal_rev),
            "animal_revenue_promoted": statistics.mean(treat_animal_rev),
            "starvation_days_eod_old": sum(ctrl_starvation_days),
            "starvation_days_eod_promoted": sum(treat_starvation_days),
        },
        "errors": len(errors),
    }

    with open(out_path, "w") as f:
        json.dump({"summary": summary, "pairs": [{
            "pair_key": k,
            "old_score": arm_dict.get("OldProduction", {}).get("score"),
            "promoted_score": arm_dict.get("PromotedProduction", {}).get("score"),
            "delta": arm_dict.get("PromotedProduction", {}).get("score", 0.0) - arm_dict.get("OldProduction", {}).get("score", 0.0),
        } for k, arm_dict in sorted(paired_runs.items())]}, f, indent=2)
    print(f"\nSaved detailed results to: {out_path}")

    # Cleanup temp
    shutil.rmtree(temp_dir, ignore_errors=True)
    shutil.rmtree(control_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
