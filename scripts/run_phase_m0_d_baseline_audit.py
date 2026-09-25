"""Phase M0-D: Baseline Authoritative Midnight Storage & Discard Audit.

Evaluates CONTROL (all experimental flags OFF) across:
Consumed seeds 96501–96510 x 5 opponents x 2 seats = 100 real-engine matches.

Authoritative Measurements:
- Exact carried units across workers immediately before _drop_inventories_to_shed
- Exact deposited units entering shed
- Exact discarded units destroyed by the engine
- Discarded units by product
- Spot market value lost from discard
- Conservation law verification: carried == deposited + discarded

Deliverables saved to simulations/results/phase_m0_d_engine_audit/:
- baseline_overflow_audit.json
- decision_gate_a.json
"""

import copy
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_d_engine_audit")
os.makedirs(OUT_DIR, exist_ok=True)

AUDIT_SEEDS = list(range(96501, 96511))  # 96501–96510
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]

# Base prices for valuation if spot market pricing is unavailable
PRODUCT_BASE_PRICES = {
    "WHEAT": 25.0,
    "CARROT": 35.0,
    "TOMATO": 60.0,
    "STRAWBERRY": 120.0,
    "MELON": 250.0,
    "EGG": 50.0,
    "MILK": 160.0,
    "WOOL": 200.0,
    "FERTILIZER": 100.0,
}


def compute_unified_percentiles(vals: List[float]) -> Dict[str, float]:
    if not vals:
        return {"mean": 0.0, "std": 0.0, "median": 0.0, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    arr = np.array(vals, dtype=float)
    med = float(np.median(arr))
    p50 = float(np.percentile(arr, 50))
    assert math.isclose(med, p50, rel_tol=1e-7)
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        "median": med,
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "p50": p50,
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
    }


def run_single_audit_match(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
    from agent.main import agent, reset_agent_state
    import config
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_midnight_storage_dump_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"

    reset_agent_state()
    reset_sw_tranche_controller()

    daily_events: List[Dict[str, Any]] = []
    call_count = [0]
    orig_drop = kengine._drop_inventories_to_shed

    def instrumented_drop(private, capacity):
        p_id = call_count[0] % 2
        day = call_count[0] // 2
        call_count[0] += 1

        if p_id == seat:
            carried = {}
            for inv in private["inventories"]:
                for k, v in inv.items():
                    if v > 0:
                        carried[k] = carried.get(k, 0) + v
            shed_pre = dict(private["shed"])
            orig_drop(private, capacity)
            shed_post = dict(private["shed"])

            dep = {}
            for k in set(shed_pre.keys()).union(shed_post.keys()):
                d = shed_post.get(k, 0) - shed_pre.get(k, 0)
                if d > 0:
                    dep[k] = d

            disc = {}
            for k, v in carried.items():
                diff = v - dep.get(k, 0)
                if diff > 0:
                    disc[k] = diff

            # Conservation check
            c_tot = sum(carried.values())
            d_tot = sum(dep.values())
            x_tot = sum(disc.values())
            assert c_tot == d_tot + x_tot, f"Conservation violation: {c_tot} != {d_tot} + {x_tot}"

            daily_events.append({
                "day": day,
                "carried": carried,
                "shed_pre": shed_pre,
                "shed_post": shed_post,
                "deposited": dep,
                "discarded": disc,
                "carried_total": c_tot,
                "deposited_total": d_tot,
                "discarded_total": x_tot,
            })
        else:
            orig_drop(private, capacity)

    kengine._drop_inventories_to_shed = instrumented_drop

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    storage_stats = {
        "peak_shed_occupancy": 0,
        "shed_turns_ge_90": 0,
        "shed_turns_ge_95": 0,
        "shed_turns_at_capacity": 0,
    }

    step_num = 0
    try:
        while not env.done:
            obs_pre = env.state[seat].observation
            priv_pre = obs_pre.private
            shed_items = sum(priv_pre.shed.values()) if hasattr(priv_pre, "shed") else 0

            if shed_items > storage_stats["peak_shed_occupancy"]:
                storage_stats["peak_shed_occupancy"] = shed_items
            if shed_items >= 90:
                storage_stats["shed_turns_ge_90"] += 1
            if shed_items >= 95:
                storage_stats["shed_turns_ge_95"] += 1
            if shed_items >= 100:
                storage_stats["shed_turns_at_capacity"] += 1

            action = agent(obs_pre, env.configuration)
            try:
                opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
            except TypeError:
                opp_action = opp_agent(env.state[1 - seat].observation)

            actions = [action, opp_action] if seat == 0 else [opp_action, action]
            env.step(actions)
            step_num += 1
    finally:
        kengine._drop_inventories_to_shed = orig_drop

    final_reward = env.steps[-1][seat].reward or 0.0
    final_cash = float(final_reward)

    tot_carried = sum(e["carried_total"] for e in daily_events)
    tot_deposited = sum(e["deposited_total"] for e in daily_events)
    tot_discarded = sum(e["discarded_total"] for e in daily_events)
    assert tot_carried == tot_deposited + tot_discarded

    discarded_by_item: Dict[str, int] = {}
    spot_value_lost = 0.0
    for e in daily_events:
        for k, v in e["discarded"].items():
            discarded_by_item[k] = discarded_by_item.get(k, 0) + v
            spot_value_lost += v * PRODUCT_BASE_PRICES.get(k, 25.0)

    overflow_days = [e["day"] for e in daily_events if e["discarded_total"] > 0]

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "final_cash": final_cash,
        "total_carried_units": tot_carried,
        "total_deposited_units": tot_deposited,
        "total_discarded_units": tot_discarded,
        "discarded_by_item": discarded_by_item,
        "spot_value_lost": spot_value_lost,
        "overflow_days_count": len(overflow_days),
        "overflow_days": overflow_days,
        "storage_stats": storage_stats,
        "conservation_verified": True,
    }


def run_all_audit_matches(max_workers: int = 8) -> List[Dict[str, Any]]:
    tasks = []
    for seed in AUDIT_SEEDS:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                tasks.append((seed, opp, seat))

    print(f"Starting Phase M0-D Baseline Audit: {len(tasks)} matches on {max_workers} workers...")
    t0 = time.time()
    results = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_single_audit_match, s, o, seat): (s, o, seat)
            for s, o, seat in tasks
        }
        done_cnt = 0
        for fut in as_completed(future_map):
            meta = future_map[fut]
            try:
                res = fut.result()
                results.append(res)
                done_cnt += 1
                if done_cnt % 10 == 0 or done_cnt == len(tasks):
                    print(f"[{done_cnt}/{len(tasks)}] Done {meta} -> cash=${res['final_cash']:,.2f}, discarded={res['total_discarded_units']} units (${res['spot_value_lost']:,.2f})")
            except Exception as e:
                print(f"ERROR in {meta}: {e}")
                raise e

    elapsed = time.time() - t0
    print(f"All {len(results)} matches completed in {elapsed:.1f}s.")
    return results


def analyze_baseline_audit(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    cash_vals = [r["final_cash"] for r in results]
    discard_units = [r["total_discarded_units"] for r in results]
    carried_units = [r["total_carried_units"] for r in results]
    deposited_units = [r["total_deposited_units"] for r in results]
    spot_values = [r["spot_value_lost"] for r in results]
    overflow_days = [r["overflow_days_count"] for r in results]
    peak_sheds = [r["storage_stats"]["peak_shed_occupancy"] for r in results]

    agg_item_discards: Dict[str, int] = {}
    for r in results:
        for k, v in r["discarded_by_item"].items():
            agg_item_discards[k] = agg_item_discards.get(k, 0) + v

    # Seed-clustered cash and discard stats
    by_seed: Dict[int, List[Dict[str, Any]]] = {}
    for r in results:
        by_seed.setdefault(r["seed"], []).append(r)

    seed_cash_means = [float(np.mean([m["final_cash"] for m in by_seed[s]])) for s in sorted(by_seed.keys())]
    seed_discard_means = [float(np.mean([m["total_discarded_units"] for m in by_seed[s]])) for s in sorted(by_seed.keys())]
    seed_value_means = [float(np.mean([m["spot_value_lost"] for m in by_seed[s]])) for s in sorted(by_seed.keys())]

    k = len(seed_cash_means)
    assert k == 10
    # Clustered 95% CI using t-distribution (df = 9, t_crit = 2.262)
    t_crit = 2.262
    mean_cash = float(np.mean(seed_cash_means))
    se_cash = float(np.std(seed_cash_means, ddof=1) / math.sqrt(k))
    ci_cash = [mean_cash - t_crit * se_cash, mean_cash + t_crit * se_cash]

    mean_discard = float(np.mean(seed_discard_means))
    se_discard = float(np.std(seed_discard_means, ddof=1) / math.sqrt(k))
    ci_discard = [mean_discard - t_crit * se_discard, mean_discard + t_crit * se_discard]

    mean_value = float(np.mean(seed_value_means))
    se_value = float(np.std(seed_value_means, ddof=1) / math.sqrt(k))
    ci_value = [mean_value - t_crit * se_value, mean_value + t_crit * se_value]

    summary = {
        "match_count": len(results),
        "seeds": AUDIT_SEEDS,
        "cash_stats": compute_unified_percentiles(cash_vals),
        "discard_units_stats": compute_unified_percentiles(discard_units),
        "carried_units_stats": compute_unified_percentiles(carried_units),
        "deposited_units_stats": compute_unified_percentiles(deposited_units),
        "spot_value_lost_stats": compute_unified_percentiles(spot_values),
        "overflow_days_stats": compute_unified_percentiles(overflow_days),
        "peak_shed_stats": compute_unified_percentiles(peak_sheds),
        "aggregate_item_discards": agg_item_discards,
        "seed_clustered": {
            "k_clusters": k,
            "cash": {"mean": mean_cash, "se": se_cash, "ci95": ci_cash},
            "discard_units": {"mean": mean_discard, "se": se_discard, "ci95": ci_discard},
            "spot_value_lost": {"mean": mean_value, "se": se_value, "ci95": ci_value},
        },
    }

    # Decision Gate A evaluation:
    # Does true discard > 0 and is it economically meaningful?
    has_meaningful_discard = mean_discard > 1.0 or mean_value > 50.0
    gate_a = {
        "gate_name": "DECISION_GATE_A",
        "question": "Does the Kaggriculture engine genuinely discard worker inventory at midnight when shed capacity is exceeded, and is the loss economically meaningful?",
        "passed": bool(has_meaningful_discard),
        "mean_discard_units_per_match": mean_discard,
        "ci95_discard_units": ci_discard,
        "mean_spot_value_lost_per_match": mean_value,
        "ci95_spot_value_lost": ci_value,
        "matches_with_discard_gt_0": sum(1 for d in discard_units if d > 0),
        "percent_matches_with_discard": float(sum(1 for d in discard_units if d > 0)) / len(results) * 100.0,
        "verdict": "PROCEED TO RESCUE" if has_meaningful_discard else "STOP - DISCARD NEGLIGIBLE",
        "rationale": (
            f"True engine discard observed: mean {mean_discard:.2f} units/match (${mean_value:,.2f}/match lost). "
            f"{sum(1 for d in discard_units if d > 0)}/{len(results)} matches suffered discard. "
            "Engine midnight overflow is active, destructive, and economically meaningful."
            if has_meaningful_discard else
            "True engine discard is near zero. End-of-day rescue is unnecessary."
        ),
    }

    return {"summary": summary, "decision_gate_a": gate_a, "matches": results}


def main():
    results = run_all_audit_matches(max_workers=8)
    analysis = analyze_baseline_audit(results)

    audit_path = os.path.join(OUT_DIR, "baseline_overflow_audit.json")
    with open(audit_path, "w") as fp:
        json.dump(analysis, fp, indent=2)
    print(f"Saved baseline audit to {audit_path}")

    gate_path = os.path.join(OUT_DIR, "decision_gate_a.json")
    with open(gate_path, "w") as fp:
        json.dump(analysis["decision_gate_a"], fp, indent=2)
    print(f"Saved Decision Gate A to {gate_path}")

    print("\n=== DECISION GATE A SUMMARY ===")
    print(f"Verdict: {analysis['decision_gate_a']['verdict']}")
    print(f"Mean discard units: {analysis['decision_gate_a']['mean_discard_units_per_match']:.2f}")
    print(f"Mean spot value lost: ${analysis['decision_gate_a']['mean_spot_value_lost_per_match']:,.2f}")
    print(f"Matches with discard: {analysis['decision_gate_a']['matches_with_discard_gt_0']}/{len(results)} ({analysis['decision_gate_a']['percent_matches_with_discard']:.1f}%)")
    print(f"Rationale: {analysis['decision_gate_a']['rationale']}")


if __name__ == "__main__":
    main()
