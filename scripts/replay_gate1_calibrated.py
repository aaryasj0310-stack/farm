"""Replay Gate 1 Representative Configurations with Calibrated Service Certificate.

Evaluates the 10 representative Gate 1 configurations (covering all 5 opponents and both seats across seeds 96501-96509)
using the calibrated WholeFarmPlanner and ServiceCertificate.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _AGENT_DIR)
for sub in ["state", "strategy", "execution", "market", "economy"]:
    p = os.path.join(_AGENT_DIR, sub)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

from scripts.run_gate1_shadow_audit import _worker_run_pair

REPRESENTATIVE_PAIRS = [
    {"pair_id": 0, "seed": 96501, "opponent": "pass", "seat": 0},
    {"pair_id": 3, "seed": 96501, "opponent": "pure_wheat_rush", "seat": 1},
    {"pair_id": 14, "seed": 96502, "opponent": "cow_milk_engine", "seat": 0},
    {"pair_id": 27, "seed": 96503, "opponent": "melon_sniper", "seat": 1},
    {"pair_id": 38, "seed": 96504, "opponent": "full_production_agent", "seat": 0},
    {"pair_id": 41, "seed": 96505, "opponent": "pass", "seat": 1},
    {"pair_id": 52, "seed": 96506, "opponent": "pure_wheat_rush", "seat": 0},
    {"pair_id": 65, "seed": 96507, "opponent": "cow_milk_engine", "seat": 1},
    {"pair_id": 76, "seed": 96508, "opponent": "melon_sniper", "seat": 0},
    {"pair_id": 89, "seed": 96509, "opponent": "full_production_agent", "seat": 1},
]


def main():
    print("=" * 80)
    print("REPLAYING 10 REPRESENTATIVE GATE 1 CONFIGURATIONS THROUGH CALIBRATED PLANNER")
    print("=" * 80)

    t_start = time.perf_counter()
    pair_results = []

    # Run sequentially or with small pool
    workers = min(4, os.cpu_count() or 4)
    print(f"Executing {len(REPRESENTATIVE_PAIRS)} pairs with {workers} workers...")

    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_worker_run_pair, cfg, True): cfg["pair_id"]
            for cfg in REPRESENTATIVE_PAIRS
        }

        for future in as_completed(future_map):
            pair_id = future_map[future]
            try:
                res = future.result()
                pair_results.append(res)
                inv_sym = "PASS" if res["invariance"]["passed"] else "FAIL"
                ss = res["shadow_summary"]
                print(f"[Done] Pair {res['pair_id']:02d} (seed {res['seed']}, opp {res['opponent']:<22}, seat {res['seat']}): "
                      f"Invariance={inv_sym} | "
                      f"CoreCertPass={ss['core_cert_pass_rate']*100:.1f}% | "
                      f"CombinedPass={ss['combined_cert_pass_rate']*100:.1f}% | "
                      f"SW_Ever_Rec={ss['sw_ever_recommended']} (Day {ss['first_sw_recommended_day']}) | "
                      f"Base_SW={ss['baseline_bought_sw']} | "
                      f"P50Lat={ss['latencies']['p50']:.2f}ms | {res['elapsed_seconds']}s")
            except Exception as e:
                print(f"Error in pair {pair_id}: {e}")
                raise e

    total_time = round(time.perf_counter() - t_start, 1)
    pair_results.sort(key=lambda x: x["pair_id"])

    # Aggregate summaries
    total_pairs = len(pair_results)
    inv_pass = sum(1 for r in pair_results if r["invariance"]["passed"])
    mean_core_pass = sum(r["shadow_summary"]["core_cert_pass_rate"] for r in pair_results) / total_pairs
    mean_comb_pass = sum(r["shadow_summary"]["combined_cert_pass_rate"] for r in pair_results) / total_pairs
    pairs_sw_rec = sum(1 for r in pair_results if r["shadow_summary"]["sw_ever_recommended"])
    pairs_base_sw = sum(1 for r in pair_results if r["shadow_summary"]["baseline_bought_sw"])

    tot_status = {"PURCHASE": 0, "DELAY": 0, "DOWNSIZE": 0, "REJECT": 0}
    tot_bindings: Dict[str, int] = {}

    for r in pair_results:
        for k, v in r["shadow_summary"]["status_counts"].items():
            tot_status[k] = tot_status.get(k, 0) + v
        for k, v in r["shadow_summary"]["binding_resource_counts"].items():
            tot_bindings[k] = tot_bindings.get(k, 0) + v

    print("\n" + "=" * 80)
    print("CALIBRATION REPLAY SUMMARY (10 REPRESENTATIVE GATE 1 CONFIGURATIONS)")
    print("=" * 80)
    print(f"Total Configurations:        {total_pairs} (20 match executions)")
    print(f"Total Elapsed Time:          {total_time}s")
    print(f"Action & Cash Invariance:    {inv_pass}/{total_pairs} ({inv_pass/total_pairs*100:.1f}%)")
    print(f"Mean Core Cert Pass Rate:    {mean_core_pass*100:.2f}%  (Gate 1 uncalibrated was: 3.77%)")
    print(f"Mean Combined Pass Rate:     {mean_comb_pass*100:.2f}%")
    print(f"SW Recommended Configurations: {pairs_sw_rec}/{total_pairs} ({pairs_sw_rec/total_pairs*100:.1f}%) (Gate 1 uncalibrated was: 0/10)")
    print(f"Baseline Bought SW:          {pairs_base_sw}/{total_pairs} ({pairs_base_sw/total_pairs*100:.1f}%)")
    print(f"SW Recommendation Statuses:  {tot_status}")
    print(f"Binding Resources:           {tot_bindings}")
    print("=" * 80)

    # Save output json
    out_path = os.path.join(_REPO_ROOT, "simulations", "results", "gate1_shadow_audit", "replay_calibrated_results.json")
    with open(out_path, "w") as f:
        json.dump({
            "summary": {
                "total_pairs": total_pairs,
                "invariance_passed": inv_pass,
                "mean_core_cert_pass_rate": mean_core_pass,
                "mean_combined_cert_pass_rate": mean_comb_pass,
                "pairs_sw_recommended": pairs_sw_rec,
                "pairs_baseline_sw": pairs_base_sw,
                "status_distribution": tot_status,
                "binding_distribution": tot_bindings,
                "elapsed_sec": total_time,
            },
            "pairs": [
                {
                    "pair_id": r["pair_id"],
                    "seed": r["seed"],
                    "opponent": r["opponent"],
                    "seat": r["seat"],
                    "invariance": r["invariance"]["passed"],
                    "core_cert_pass_rate": r["shadow_summary"]["core_cert_pass_rate"],
                    "combined_cert_pass_rate": r["shadow_summary"]["combined_cert_pass_rate"],
                    "sw_ever_recommended": r["shadow_summary"]["sw_ever_recommended"],
                    "first_sw_day": r["shadow_summary"]["first_sw_recommended_day"],
                    "baseline_bought_sw": r["shadow_summary"]["baseline_bought_sw"],
                    "status_counts": r["shadow_summary"]["status_counts"],
                    "binding_counts": r["shadow_summary"]["binding_resource_counts"],
                    "elapsed_sec": r["elapsed_seconds"],
                }
                for r in pair_results
            ],
        }, f, indent=2)
    print(f"Saved replay results to {out_path}")


if __name__ == "__main__":
    main()
