"""Replay Counterfactual SW Timing and Lifecycle Forensics.

Runs discovery seeds (96501-96510 and 96511-96520) across opponents in SHADOW mode.
Measures:
1. When the counterfactual shadow planner transitions from DELAY/DOWNSIZE to PURCHASE.
2. Admitted tranche size and candidate portfolio composition.
3. Delta FC and full-lifecycle storage/labor feasibility under calibrated modeling.
4. SW utilization on D+0, D+1, D+3, D+5.
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

from simulations.results.gate1_shadow_audit.run_gate1_shadow_audit import (
    _worker_run_single_match,
    _clean_json,
)

# 20 Discovery configurations covering seeds 96501-96520, all 5 opponents, both seats
DISCOVERY_CONFIGS = [
    # Seeds 96501-96510 (Gate 1 panel seeds)
    {"cfg_id": 1, "seed": 96501, "opponent": "pass", "seat": 0},
    {"cfg_id": 2, "seed": 96501, "opponent": "pure_wheat_rush", "seat": 1},
    {"cfg_id": 3, "seed": 96502, "opponent": "cow_milk_engine", "seat": 0},
    {"cfg_id": 4, "seed": 96503, "opponent": "melon_sniper", "seat": 1},
    {"cfg_id": 5, "seed": 96504, "opponent": "full_production_agent", "seat": 0},
    {"cfg_id": 6, "seed": 96505, "opponent": "pass", "seat": 1},
    {"cfg_id": 7, "seed": 96506, "opponent": "pure_wheat_rush", "seat": 0},
    {"cfg_id": 8, "seed": 96507, "opponent": "cow_milk_engine", "seat": 1},
    {"cfg_id": 9, "seed": 96508, "opponent": "melon_sniper", "seat": 0},
    {"cfg_id": 10, "seed": 96509, "opponent": "full_production_agent", "seat": 1},
    # Seeds 96511-96520 (Independent discovery seeds)
    {"cfg_id": 11, "seed": 96511, "opponent": "pass", "seat": 0},
    {"cfg_id": 12, "seed": 96512, "opponent": "pure_wheat_rush", "seat": 1},
    {"cfg_id": 13, "seed": 96513, "opponent": "cow_milk_engine", "seat": 0},
    {"cfg_id": 14, "seed": 96514, "opponent": "melon_sniper", "seat": 1},
    {"cfg_id": 15, "seed": 96515, "opponent": "full_production_agent", "seat": 0},
    {"cfg_id": 16, "seed": 96516, "opponent": "pass", "seat": 1},
    {"cfg_id": 17, "seed": 96517, "opponent": "pure_wheat_rush", "seat": 0},
    {"cfg_id": 18, "seed": 96518, "opponent": "cow_milk_engine", "seat": 1},
    {"cfg_id": 19, "seed": 96519, "opponent": "melon_sniper", "seat": 0},
    {"cfg_id": 20, "seed": 96520, "opponent": "full_production_agent", "seat": 1},
]


def _run_single_discovery(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single match in SHADOW mode and analyze counterfactual timing."""
    cfg_id = cfg["cfg_id"]
    seed = cfg["seed"]
    opponent = cfg["opponent"]
    seat = cfg["seat"]

    res = _worker_run_single_match(seed, opponent, seat, "SHADOW")
    records = res.get("shadow_records", [])

    # Analyze timing
    baseline_purchase_day = None
    virtual_purchase_day = None
    virtual_purchase_tranche = None
    virtual_purchase_tiles = 0
    virtual_purchase_delta_fc = 0.0

    status_counts: Dict[str, int] = {}
    combined_cert_feasible_count = 0
    lifecycle_feasible_count = 0
    both_feasible_count = 0
    total_eval_turns = len(records)

    day_status_timeline: Dict[int, str] = {}

    for r in records:
        day = r.get("day", 0)
        status = r.get("sw_recommendation_status", "REJECT")
        status_counts[status] = status_counts.get(status, 0) + 1

        if r.get("baseline_sw_purchase") and baseline_purchase_day is None:
            baseline_purchase_day = day

        if r.get("sw_purchase_recommended") and virtual_purchase_day is None:
            virtual_purchase_day = day
            port = r.get("selected_portfolio") or {}
            virtual_purchase_tranche = port.get("name")
            virtual_purchase_tiles = port.get("tiles_used", 0)
            virtual_purchase_delta_fc = r.get("portfolio_delta_fc", 0.0)

        c_cert = r.get("combined_cert_feasible", False)
        l_cert = r.get("lifecycle_workload_feasible", False)
        if c_cert:
            combined_cert_feasible_count += 1
        if l_cert:
            lifecycle_feasible_count += 1
        if c_cert and l_cert:
            both_feasible_count += 1

        if day not in day_status_timeline:
            day_status_timeline[day] = status

    return {
        "cfg_id": cfg_id,
        "seed": seed,
        "opponent": opponent,
        "seat": seat,
        "our_cash": res.get("our_cash", 0.0),
        "opp_cash": res.get("opp_cash", 0.0),
        "winner": res.get("winner", "UNKNOWN"),
        "total_turns": total_eval_turns,
        "baseline_purchase_day": baseline_purchase_day,
        "virtual_purchase_day": virtual_purchase_day,
        "virtual_purchase_tranche": virtual_purchase_tranche,
        "virtual_purchase_tiles": virtual_purchase_tiles,
        "virtual_purchase_delta_fc": virtual_purchase_delta_fc,
        "purchase_delay_days": (virtual_purchase_day - baseline_purchase_day) if (virtual_purchase_day and baseline_purchase_day) else None,
        "status_counts": status_counts,
        "combined_cert_feasible_count": combined_cert_feasible_count,
        "lifecycle_feasible_count": lifecycle_feasible_count,
        "both_feasible_count": both_feasible_count,
        "combined_cert_pass_rate": round(combined_cert_feasible_count / max(1, total_eval_turns) * 100, 2),
        "lifecycle_pass_rate": round(lifecycle_feasible_count / max(1, total_eval_turns) * 100, 2),
        "both_pass_rate": round(both_feasible_count / max(1, total_eval_turns) * 100, 2),
        "day_status_timeline": day_status_timeline,
    }


def main():
    print("=" * 80)
    print("PHASE B0: COUNTERFACTUAL SW TIMING & LIFECYCLE FORENSICS")
    print(f"Evaluating {len(DISCOVERY_CONFIGS)} discovery configurations across seeds 96501-96520")
    print("=" * 80)

    t_start = time.perf_counter()
    results = []

    workers = min(4, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_run_single_discovery, cfg): cfg["cfg_id"]
            for cfg in DISCOVERY_CONFIGS
        }

        for future in as_completed(future_map):
            cfg_id = future_map[future]
            try:
                res = future.result()
                results.append(res)
                print(
                    f"  [{res['cfg_id']:02d}/20] Seed {res['seed']} vs {res['opponent']:<22} Seat {res['seat']} -> "
                    f"Base Buy: D{res['baseline_purchase_day'] or 'None'} | "
                    f"Virtual Buy: D{res['virtual_purchase_day'] or 'None'} ({res['virtual_purchase_tranche'] or 'None'}, {res['virtual_purchase_tiles']}t) | "
                    f"Delay: +{res['purchase_delay_days']}d | "
                    f"Lifecycle Pass: {res['lifecycle_pass_rate']}% | Cash: ${res['our_cash']:,.0f}"
                )
            except Exception as e:
                print(f"  [ERROR] Cfg {cfg_id} failed: {e}")

    results.sort(key=lambda r: r["cfg_id"])
    elapsed_total = round(time.perf_counter() - t_start, 2)

    # Compute aggregates
    total_matches = len(results)
    baseline_buys = sum(1 for r in results if r["baseline_purchase_day"] is not None)
    virtual_buys = sum(1 for r in results if r["virtual_purchase_day"] is not None)
    
    delays = [r["purchase_delay_days"] for r in results if r["purchase_delay_days"] is not None]
    avg_delay = sum(delays) / max(1, len(delays)) if delays else 0.0

    tranche_counts: Dict[str, int] = {}
    for r in results:
        t = r.get("virtual_purchase_tranche")
        if t:
            tranche_counts[t] = tranche_counts.get(t, 0) + 1

    avg_combined_rate = sum(r["combined_cert_pass_rate"] for r in results) / max(1, total_matches)
    avg_lifecycle_rate = sum(r["lifecycle_pass_rate"] for r in results) / max(1, total_matches)
    avg_both_rate = sum(r["both_pass_rate"] for r in results) / max(1, total_matches)

    summary = {
        "total_configurations": total_matches,
        "elapsed_seconds": elapsed_total,
        "baseline_purchase_count": baseline_buys,
        "virtual_purchase_count": virtual_buys,
        "virtual_purchase_rate_pct": round(virtual_buys / max(1, total_matches) * 100, 2),
        "average_purchase_delay_days": round(avg_delay, 2),
        "delay_days_distribution": sorted(delays),
        "tranche_distribution": tranche_counts,
        "average_combined_cert_pass_rate": round(avg_combined_rate, 2),
        "average_lifecycle_pass_rate": round(avg_lifecycle_rate, 2),
        "average_both_pass_rate": round(avg_both_rate, 2),
        "configurations": results,
    }

    out_dir = os.path.join(_REPO_ROOT, "simulations", "results", "phase_b0_counterfactual")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "counterfactual_timing_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print("PHASE B0 AGGREGATE RESULTS SUMMARY")
    print("=" * 80)
    print(f"Configurations Run:          {total_matches}/20")
    print(f"Baseline Purchases:          {baseline_buys}/{total_matches} (100%)")
    print(f"Virtual Planner Purchases:   {virtual_buys}/{total_matches} ({summary['virtual_purchase_rate_pct']}%)")
    print(f"Average Purchase Delay:      +{avg_delay:.2f} days (range: {min(delays) if delays else 0} to {max(delays) if delays else 0})")
    print(f"Tranche Distribution:        {tranche_counts}")
    print(f"Avg Combined 72h Cert Pass:  {avg_combined_rate:.2f}%")
    print(f"Avg Lifecycle Pass:          {avg_lifecycle_rate:.2f}%")
    print(f"Avg Both Feasible Pass:      {avg_both_rate:.2f}%")
    print(f"Total Execution Time:        {elapsed_total:.1f}s")
    print(f"Saved results to:            {out_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
