"""Rigorous L0 vs L2 (Guarded Commitment Awareness) Paired Tournament.

Compares:
  L0:  Production baseline (unconstrained livestock valuation).
  L2A: Guarded commitment awareness with conservative 5% relative gap threshold.
  L2B: Guarded commitment awareness with medium 15% relative gap threshold.
  L2C: Guarded commitment awareness with permissive 30% relative gap threshold.

Opponents:
  - full_production_agent (balanced mixed strategy)
  - cow_milk_engine (livestock-heavy opponent producing lots of Milk)
  - melon_sniper (crop-heavy, dump-heavy)

All runs isolate the livestock valuation mechanism with:
  - SW disabled (ArmA)
  - OPPONENT_INTELLIGENCE_MODE = "O0_SHADOW" (no behavioral prediction)

Measures:
  - Paired Delta our score (L2 - L0)
  - Paired Delta opponent score (L2 - L0)
  - Paired Delta score margin (L2 margin - L0 margin)
  - 95% paired bootstrap CI
  - Paired W/T/L (Win: L2 > L0, Tie: L2 == L0, Loss: L2 < L0)
  - Animal purchases by species (COW, SHEEP, GOOSE)
  - Switches triggered, baseline gaps at switch, and guard-blocked switches
"""

import os
import sys
import time
import json
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Any, Tuple, Optional
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)


def compute_bootstrap_ci(
    data: List[float],
    num_resamples: int = 10000,
    ci: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float]:
    """Compute bootstrap percentile confidence interval on the mean of paired deltas."""
    if len(data) == 0:
        return 0.0, 0.0
    rng = np.random.RandomState(seed)
    arr = np.array(data, dtype=float)
    n = len(arr)
    indices = rng.randint(0, n, size=(num_resamples, n))
    resampled_means = np.mean(arr[indices], axis=1)
    lower = float(np.percentile(resampled_means, (1.0 - ci) / 2.0 * 100.0))
    upper = float(np.percentile(resampled_means, (1.0 + ci) / 2.0 * 100.0))
    return lower, upper


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = payload["mode"]          # "L0", "L2A", "L2B", "L2C"
    seed = payload["seed"]
    opponent_name = payload["opponent_name"]
    seat = payload["seat"]          # 0 (our agent is P0) or 1 (our agent is P1)

    # Clean module cache for deterministic clean state
    to_delete = [k for k in list(sys.modules.keys()) if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'marginal_livestock_valuator',
        'herd_planner'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    import execution.task_scheduler as task_scheduler
    from strategy.macro_planner import clear_livestock_decision_logs, get_livestock_decision_logs
    from simulations.experiments.agent_zoo import get_agent

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    task_scheduler.reset_worker_locality()
    clear_livestock_decision_logs()

    # Base configuration: O0_SHADOW (no behavioral prediction), ArmA (no SW)
    config.set_sw_experiment_arm("ArmA")
    config.set_opponent_intelligence_mode("O0_SHADOW")
    config.set_livestock_valuation_mode(mode)

    opp_callable = get_agent(opponent_name)

    # Seat allocation
    if seat == 0:
        players = [agent_module.agent, opp_callable]
        our_idx = 0
        opp_idx = 1
    else:
        players = [opp_callable, agent_module.agent]
        our_idx = 1
        opp_idx = 0

    env = make("kaggriculture", configuration={"randomSeed": seed}, debug=False)
    steps = env.run(players)

    our_score = float(steps[-1][our_idx]["reward"] or 0.0)
    opp_score = float(steps[-1][opp_idx]["reward"] or 0.0)
    we_won_opp = (our_score > opp_score)
    is_tie_opp = (our_score == opp_score)

    # Telemetry extraction: purchases, timing, animals, feed
    animal_purchases = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    purchase_days = []
    wheat_bought = 0

    for step_data in steps:
        action = step_data[our_idx].get("action")
        if not action or not isinstance(action, dict):
            continue
        market_orders = action.get("market", [])
        obs = step_data[our_idx].get("observation", {})
        day = obs.get("day", 0)

        for order in market_orders:
            if not isinstance(order, (list, tuple)) or len(order) < 2:
                continue
            if order[0] == "BUY_ANIMAL":
                sp = str(order[1]).upper()
                if sp in animal_purchases:
                    animal_purchases[sp] += 1
                    purchase_days.append(day)
            elif order[0] == "BUY_PRODUCT" and order[1] == "WHEAT":
                qty = order[2] if len(order) > 2 else 1
                wheat_bought += qty

    # Final farm animal counts
    final_obs = steps[-1][our_idx].get("observation", {})
    farms = final_obs.get("farms", [])
    our_farm = farms[our_idx] if len(farms) > our_idx else {}
    tiles = our_farm.get("tiles", [])

    final_animals = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    if isinstance(tiles, list):
        for row in tiles:
            if isinstance(row, list):
                for t in row:
                    if isinstance(t, dict) and "animal" in t:
                        sp = str(t["animal"]).upper()
                        if sp in final_animals:
                            final_animals[sp] += 1

    first_purchase_day = min(purchase_days) if purchase_days else None
    last_purchase_day = max(purchase_days) if purchase_days else None

    # Extract guard telemetry
    logs = get_livestock_decision_logs()
    switches = []
    guard_blocks = []
    for rec in logs:
        gdiag = rec.get("guard_diag")
        if not gdiag:
            continue
        if gdiag.get("switched") and rec.get("selected_species") is not None:
            switches.append({
                "day": rec.get("day"),
                "hour": rec.get("hour"),
                "baseline_best": gdiag.get("baseline_best"),
                "switched_to": rec.get("selected_species"),
                "relative_gap": gdiag.get("relative_gap"),
                "baseline_gap": gdiag.get("baseline_gap"),
                "guard_threshold": gdiag.get("guard_threshold"),
            })
        elif gdiag.get("blocked_by_guard"):
            guard_blocks.append({
                "day": rec.get("day"),
                "hour": rec.get("hour"),
                "baseline_best": gdiag.get("baseline_best"),
                "stress_best": gdiag.get("stress_best"),
                "relative_gap": gdiag.get("relative_gap"),
                "baseline_gap": gdiag.get("baseline_gap"),
                "guard_threshold": gdiag.get("guard_threshold"),
            })

    return {
        "mode": mode,
        "seed": seed,
        "opponent_name": opponent_name,
        "seat": seat,
        "our_score": our_score,
        "opp_score": opp_score,
        "margin": our_score - opp_score,
        "we_won_opp": we_won_opp,
        "is_tie_opp": is_tie_opp,
        "animal_purchases": animal_purchases,
        "final_animals": final_animals,
        "purchase_days": purchase_days,
        "first_purchase_day": first_purchase_day,
        "last_purchase_day": last_purchase_day,
        "wheat_bought": wheat_bought,
        "switches_triggered": len(switches),
        "switches": switches,
        "guard_blocks_count": len(guard_blocks),
        "guard_blocks": guard_blocks,
    }


def run_l2_tournament(
    seeds: List[int],
    modes: List[str] = ["L0", "L2A", "L2B", "L2C"],
    opponents: List[str] = ["full_production_agent", "cow_milk_engine", "melon_sniper"],
    max_workers: int = 8,
    output_filename: str = "l2_tournament_report.json",
) -> Dict[str, Any]:
    print(f"=== Starting Guarded Livestock (L2 vs L0) Tournament ===")
    print(f"Modes: {modes}")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Opponents: {opponents} | Seat-swapped: Yes")

    tasks = []
    for opp in opponents:
        for s in seeds:
            for seat in (0, 1):
                for m in modes:
                    tasks.append({"mode": m, "seed": s, "opponent_name": opp, "seat": seat})

    total_matches = len(tasks)
    print(f"Total matches to execute: {total_matches}")

    results_map: Dict[Tuple[str, int, int, str], Dict[str, Any]] = {}
    start_time = time.time()
    completed = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_match, t): t for t in tasks}
        for fut in as_completed(futures):
            res = fut.result()
            completed += 1
            key = (res["opponent_name"], res["seed"], res["seat"], res["mode"])
            results_map[key] = res
            if completed % 20 == 0 or completed == total_matches:
                elapsed = time.time() - start_time
                print(f"[{completed}/{total_matches}] matches completed ({elapsed:.1f}s)")

    # Analysis: Compare each L2 variant directly against L0 on identical match (opp, seed, seat)
    test_modes = [m for m in modes if m != "L0"]
    report_by_mode: Dict[str, Any] = {}

    for t_mode in test_modes:
        mode_records_all_opps = []
        opp_breakdown = {}

        for opp in opponents:
            opp_pairs = []
            for s in seeds:
                for seat in (0, 1):
                    r_l0 = results_map.get((opp, s, seat, "L0"))
                    r_test = results_map.get((opp, s, seat, t_mode))
                    if r_l0 and r_test:
                        d_our = r_test["our_score"] - r_l0["our_score"]
                        d_opp = r_test["opp_score"] - r_l0["opp_score"]
                        d_margin = r_test["margin"] - r_l0["margin"]
                        win_vs_l0 = 1 if d_our > 0 else 0
                        tie_vs_l0 = 1 if d_our == 0 else 0
                        loss_vs_l0 = 1 if d_our < 0 else 0

                        pair_info = {
                            "seed": s,
                            "seat": seat,
                            "l0_score": r_l0["our_score"],
                            "test_score": r_test["our_score"],
                            "l0_opp_score": r_l0["opp_score"],
                            "test_opp_score": r_test["opp_score"],
                            "l0_margin": r_l0["margin"],
                            "test_margin": r_test["margin"],
                            "delta_our": d_our,
                            "delta_opp": d_opp,
                            "delta_margin": d_margin,
                            "win_vs_l0": win_vs_l0,
                            "tie_vs_l0": tie_vs_l0,
                            "loss_vs_l0": loss_vs_l0,
                            "l0_purchases": r_l0["animal_purchases"],
                            "test_purchases": r_test["animal_purchases"],
                            "switches_triggered": r_test["switches_triggered"],
                            "switches": r_test["switches"],
                            "guard_blocks_count": r_test["guard_blocks_count"],
                            "guard_blocks": r_test["guard_blocks"],
                        }
                        opp_pairs.append(pair_info)
                        mode_records_all_opps.append(pair_info)

            # Summarize this opponent
            n = len(opp_pairs)
            delta_our_list = [p["delta_our"] for p in opp_pairs]
            delta_opp_list = [p["delta_opp"] for p in opp_pairs]
            delta_margin_list = [p["delta_margin"] for p in opp_pairs]
            l0_scores = [p["l0_score"] for p in opp_pairs]
            test_scores = [p["test_score"] for p in opp_pairs]

            w = sum(p["win_vs_l0"] for p in opp_pairs)
            t = sum(p["tie_vs_l0"] for p in opp_pairs)
            l = sum(p["loss_vs_l0"] for p in opp_pairs)

            mean_d_our = float(np.mean(delta_our_list)) if n > 0 else 0.0
            mean_d_opp = float(np.mean(delta_opp_list)) if n > 0 else 0.0
            mean_d_margin = float(np.mean(delta_margin_list)) if n > 0 else 0.0
            ci_lower, ci_upper = compute_bootstrap_ci(delta_our_list)
            m_ci_lower, m_ci_upper = compute_bootstrap_ci(delta_margin_list)

            cow_l0 = np.mean([p["l0_purchases"]["COW"] for p in opp_pairs])
            sheep_l0 = np.mean([p["l0_purchases"]["SHEEP"] for p in opp_pairs])
            cow_test = np.mean([p["test_purchases"]["COW"] for p in opp_pairs])
            sheep_test = np.mean([p["test_purchases"]["SHEEP"] for p in opp_pairs])

            tot_switches = sum(p["switches_triggered"] for p in opp_pairs)
            tot_blocks = sum(p["guard_blocks_count"] for p in opp_pairs)

            opp_breakdown[opp] = {
                "n_matches": n,
                "mean_l0_score": float(np.mean(l0_scores)),
                "mean_test_score": float(np.mean(test_scores)),
                "mean_delta_our": mean_d_our,
                "mean_delta_opp": mean_d_opp,
                "mean_delta_margin": mean_d_margin,
                "bootstrap_ci_95_our": [ci_lower, ci_upper],
                "bootstrap_ci_95_margin": [m_ci_lower, m_ci_upper],
                "paired_wtl_vs_l0": {"W": w, "T": t, "L": l, "win_rate": (w / n) if n > 0 else 0.0},
                "mean_cow_l0": cow_l0,
                "mean_cow_test": cow_test,
                "mean_sheep_l0": sheep_l0,
                "mean_sheep_test": sheep_test,
                "switches_triggered": tot_switches,
                "guard_blocks": tot_blocks,
                "pairs": opp_pairs,
            }

        # Overall across all opponents
        n_all = len(mode_records_all_opps)
        all_d_our = [p["delta_our"] for p in mode_records_all_opps]
        all_d_opp = [p["delta_opp"] for p in mode_records_all_opps]
        all_d_margin = [p["delta_margin"] for p in mode_records_all_opps]
        all_w = sum(p["win_vs_l0"] for p in mode_records_all_opps)
        all_t = sum(p["tie_vs_l0"] for p in mode_records_all_opps)
        all_l = sum(p["loss_vs_l0"] for p in mode_records_all_opps)
        all_ci_lower, all_ci_upper = compute_bootstrap_ci(all_d_our)
        all_m_ci_lower, all_m_ci_upper = compute_bootstrap_ci(all_d_margin)

        all_switches = sum(p["switches_triggered"] for p in mode_records_all_opps)
        all_blocks = sum(p["guard_blocks_count"] for p in mode_records_all_opps)

        # Collect detailed switches
        detailed_switches = []
        for p in mode_records_all_opps:
            for sw in p["switches"]:
                detailed_switches.append({
                    "seed": p["seed"],
                    "seat": p["seat"],
                    **sw
                })

        report_by_mode[t_mode] = {
            "n_matches": n_all,
            "overall_mean_l0_score": float(np.mean([p["l0_score"] for p in mode_records_all_opps])),
            "overall_mean_test_score": float(np.mean([p["test_score"] for p in mode_records_all_opps])),
            "overall_mean_delta_our": float(np.mean(all_d_our)),
            "overall_mean_delta_opp": float(np.mean(all_d_opp)),
            "overall_mean_delta_margin": float(np.mean(all_d_margin)),
            "overall_bootstrap_ci_95_our": [all_ci_lower, all_ci_upper],
            "overall_bootstrap_ci_95_margin": [all_m_ci_lower, all_m_ci_upper],
            "overall_paired_wtl_vs_l0": {
                "W": all_w, "T": all_t, "L": all_l,
                "win_rate": (all_w / n_all) if n_all > 0 else 0.0
            },
            "total_switches_triggered": all_switches,
            "total_guard_blocks": all_blocks,
            "detailed_switches": detailed_switches,
            "by_opponent": opp_breakdown,
        }

    # Print summary tables
    print("\n" + "=" * 80)
    print("                      L2 GUARD COMPARISON TO L0 BASELINE")
    print("=" * 80)
    print(f"{'Mode':<6} | {'Guard':<6} | {'Delta Score':<14} | {'95% CI (Our)':<22} | {'Delta Margin':<14} | {'Paired W/T/L':<14} | {'Switches':<8}")
    print("-" * 92)

    for m in test_modes:
        rep = report_by_mode[m]
        guard_pct = "5%" if m == "L2A" else ("15%" if m == "L2B" else "30%")
        ci = rep["overall_bootstrap_ci_95_our"]
        ci_str = f"[{ci[0]:+7.1f}, {ci[1]:+7.1f}]"
        wtl = rep["overall_paired_wtl_vs_l0"]
        wtl_str = f"{wtl['W']}W / {wtl['T']}T / {wtl['L']}L"
        d_score = f"{rep['overall_mean_delta_our']:+8.1f}"
        d_margin = f"{rep['overall_mean_delta_margin']:+8.1f}"
        sw = f"{rep['total_switches_triggered']} (bl:{rep['total_guard_blocks']})"
        print(f"{m:<6} | {guard_pct:<6} | {d_score:<14} | {ci_str:<22} | {d_margin:<14} | {wtl_str:<14} | {sw:<8}")

    print("\n" + "-" * 80)
    print("                  BREAKDOWN BY OPPONENT PROFILE")
    print("-" * 80)
    for m in test_modes:
        rep = report_by_mode[m]
        print(f"\n--- Mode {m} ---")
        print(f"{'Opponent':<24} | {'Delta Score':<12} | {'Delta Margin':<12} | {'Paired W/T/L':<12} | {'Cows (L0->L2)':<16} | {'Sheep (L0->L2)':<16}")
        for opp, o_rep in rep["by_opponent"].items():
            wtl = o_rep["paired_wtl_vs_l0"]
            wtl_str = f"{wtl['W']}W/{wtl['T']}T/{wtl['L']}L"
            cows = f"{o_rep['mean_cow_l0']:.1f} -> {o_rep['mean_cow_test']:.1f}"
            sheep = f"{o_rep['mean_sheep_l0']:.1f} -> {o_rep['mean_sheep_test']:.1f}"
            print(f"{opp:<24} | {o_rep['mean_delta_our']:+9.1f}  | {o_rep['mean_delta_margin']:+9.1f}  | {wtl_str:<12} | {cows:<16} | {sheep:<16}")

    # Switch details
    print("\n" + "-" * 80)
    print("                      DETAILED SWITCH AUDIT")
    print("-" * 80)
    for m in test_modes:
        rep = report_by_mode[m]
        sws = rep["detailed_switches"]
        print(f"\nMode {m}: {len(sws)} total switches")
        if sws:
            for s in sws[:10]:  # print up to 10
                print(f"  Seed {s['seed']} Seat {s['seat']} Day {s['day']} Hour {s['hour']}: {s['baseline_best']} -> {s['switched_to']} (gap={s['relative_gap']*100:.1f}%, thresh={s['guard_threshold']*100:.0f}%)")
            if len(sws) > 10:
                print(f"  ... and {len(sws) - 10} more switches")

    # Save output
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, output_filename)
    with open(out_file, "w", encoding="utf-8") as f:
        # Convert pairs to summary only to keep JSON clean and lightweight
        save_rep = {}
        for m, d in report_by_mode.items():
            save_rep[m] = {k: v for k, v in d.items() if k != "by_opponent"}
            save_rep[m]["by_opponent"] = {}
            for opp, o_data in d["by_opponent"].items():
                save_rep[m]["by_opponent"][opp] = {k: v for k, v in o_data.items() if k != "pairs"}
        json.dump(save_rep, f, indent=2)
    print(f"\nFull report saved to {out_file}")

    return report_by_mode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run L2 Guarded Livestock Tournament")
    parser.add_argument("--seeds", type=int, default=10, help="Number of seeds to run (default: 10)")
    parser.add_argument("--start_seed", type=int, default=42, help="Starting seed (default: 42)")
    parser.add_argument("--modes", nargs="+", default=["L0", "L2A", "L2B", "L2C"], help="Modes to run")
    parser.add_argument("--workers", type=int, default=8, help="Process pool workers")
    parser.add_argument("--output", type=str, default="l2_tournament_report.json", help="Output JSON filename")
    args = parser.parse_args()

    seed_list = list(range(args.start_seed, args.start_seed + args.seeds))
    run_l2_tournament(seeds=seed_list, modes=args.modes, max_workers=args.workers, output_filename=args.output)
