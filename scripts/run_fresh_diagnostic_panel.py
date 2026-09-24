"""Fresh Diagnostic Panel for Calibrated SW-Forward Architecture.

Evaluates 10 fresh, non-protected seeds (96511-96520) across:
- 5 benchmark opponents (pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent)
- Both seats (0 and 1)
- 100 game configurations executed in matched OFF and SHADOW modes (200 match executions total).
- 100% action and final-cash invariance verification.
- Comprehensive SHADOW telemetry capture with calibrated ServiceCertificate and WholeFarmPlanner.
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
_OUTPUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "gate1_calibrated_panel")
_MANIFEST_PATH = os.path.join(_OUTPUT_DIR, "manifest.json")
_RESULTS_PATH = os.path.join(_OUTPUT_DIR, "results.json")
_AGGREGATE_PATH = os.path.join(_OUTPUT_DIR, "aggregate_tables.json")
_TRACES_PATH = os.path.join(_OUTPUT_DIR, "representative_traces.json")

os.makedirs(_OUTPUT_DIR, exist_ok=True)

# Fresh non-protected seeds
FRESH_SEEDS = [96511, 96512, 96513, 96514, 96515, 96516, 96517, 96518, 96519, 96520]
OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]
PROTECTED_RANGE = range(98001, 98051)

for s in FRESH_SEEDS:
    if s in PROTECTED_RANGE:
        raise ValueError(f"CRITICAL: Seed {s} is in protected range 98001-98050!")


def _clean_json(obj: Any) -> Any:
    if isinstance(obj, (set, tuple, list)):
        return [_clean_json(x) for x in obj]
    elif isinstance(obj, dict):
        return {str(k): _clean_json(v) for k, v in obj.items()}
    elif isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    elif hasattr(obj, "__dict__"):
        return _clean_json(obj.__dict__)
    else:
        return str(obj)


def _compute_percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"min": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "mean": 0.0}
    s = sorted(values)
    n = len(s)
    return {
        "min": round(s[0], 3),
        "p25": round(s[int(0.25 * n)], 3),
        "p50": round(s[int(0.50 * n)], 3),
        "p75": round(s[int(0.75 * n)], 3),
        "p90": round(s[min(n - 1, int(0.90 * n))], 3),
        "p95": round(s[min(n - 1, int(0.95 * n))], 3),
        "p99": round(s[min(n - 1, int(0.99 * n))], 3),
        "max": round(s[-1], 3),
        "mean": round(float(sum(s)) / n, 3),
    }


def _worker_run_single_match(
    seed: int,
    opp_name: str,
    seat: int,
    mode: str,
    record_all_turns: bool = False,
) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    from kaggle_environments import make
    import config
    from main import agent, reset_agent_state, get_last_shadow_result
    from simulations.experiments.agent_zoo import get_agent

    config.set_sw_forward_architecture_mode(mode)
    reset_agent_state()

    opp_agent = get_agent(opp_name)

    actions: List[Dict[str, Any]] = []
    shadow_records: List[Dict[str, Any]] = []
    latencies: List[float] = []

    def our_agent_wrapper(obs, conf=None):
        t0 = time.perf_counter()
        act = agent(obs, conf)
        call_dur_ms = (time.perf_counter() - t0) * 1000.0

        actions.append(copy.deepcopy(act))

        if mode == "SHADOW":
            sr = get_last_shadow_result()
            lat = sr.diagnostics.latency_ms if sr else call_dur_ms
            latencies.append(lat)

            if sr is not None:
                try:
                    step = obs.get("step", 0)
                    day = obs.get("day", 0)
                    hour = obs.get("hour", 0)

                    cert_feasible = bool(sr.certificate.feasible) if sr.certificate else True
                    cert_binding_res = str(getattr(sr.certificate, "binding_resource", "NONE")) if sr.certificate else "NONE"
                    cert_min_slack = int(getattr(sr.certificate, "minimum_slack", 0)) if sr.certificate else 0
                    cert_tier = str(getattr(sr.certificate, "guarantee_tier", "UNCERTAIN")) if sr.certificate else "UNCERTAIN"

                    rec = {
                        "step": step,
                        "day": day,
                        "hour": hour,
                        "latency_ms": round(lat, 3),
                        "strategic_state": str(sr.decision.strategic_state),
                        "target_sw_day": sr.decision.target_sw_day,
                        "sw_purchase_recommended": bool(sr.decision.sw_purchase_recommended),
                        "sw_recommendation_status": str(sr.decision.sw_recommendation_status),
                        "baseline_sw_purchase": bool(sr.decision.baseline_sw_purchase),
                        "core_only_cert_feasible": bool(sr.decision.core_only_cert_feasible),
                        "combined_cert_feasible": bool(sr.decision.combined_cert_feasible),
                        "lifecycle_workload_feasible": bool(sr.decision.lifecycle_workload_feasible),
                        "binding_resource": str(sr.decision.binding_resource),
                        "binding_deadline": sr.decision.binding_deadline,
                        "portfolio_delta_fc": round(float(sr.decision.portfolio_delta_fc), 2),
                        "sw_land_cost": round(float(sr.decision.sw_land_cost), 2),
                        "sw_seed_cost": round(float(sr.decision.sw_seed_cost), 2),
                        "sw_incremental_labor_cost": round(float(sr.decision.sw_incremental_labor_cost), 2),
                        "sw_gross_revenue": round(float(sr.decision.sw_gross_revenue), 2),
                        "core_cannibalization_loss": round(float(sr.decision.core_cannibalization_loss), 2),
                        "displaced_core_value": round(float(sr.decision.displaced_core_value), 2),
                        "feed_opportunity_cost": round(float(sr.decision.feed_opportunity_cost), 2),
                        "storage_loss_penalty": round(float(sr.decision.storage_loss_penalty), 2),
                        "projected_terminal_cash_without": round(float(sr.decision.projected_terminal_cash_without), 2),
                        "projected_terminal_cash_with": round(float(sr.decision.projected_terminal_cash_with), 2),
                        "candidates_evaluated_count": sr.decision.candidates_evaluated_count,
                        "candidates_admitted_count": sr.decision.candidates_admitted_count,
                        "candidates_delayed_count": sr.decision.candidates_delayed_count,
                        "candidates_downsized_count": sr.decision.candidates_downsized_count,
                        "candidates_rejected_count": sr.decision.candidates_rejected_count,
                        "economic_uncertainty_flags": list(sr.decision.economic_uncertainty_flags),
                        "event_replan_triggered": bool(sr.diagnostics.event_replan_triggered),
                        "full_lifecycle_peak_shed": sr.diagnostics.full_lifecycle_peak_shed,
                        "full_lifecycle_peak_daily_actions": sr.diagnostics.full_lifecycle_peak_daily_actions,
                        "cert_feasible": cert_feasible,
                        "cert_binding_resource": cert_binding_res,
                        "cert_min_slack": cert_min_slack,
                        "guarantee_tier": cert_tier,
                        "selected_portfolio": _clean_json(sr.decision.selected_portfolio),
                        "disagreements": _clean_json(sr.decision.disagreements_with_baseline),
                    }
                    shadow_records.append(rec)
                except Exception:
                    pass
        return act

    p0 = our_agent_wrapper if seat == 0 else opp_agent
    p1 = our_agent_wrapper if seat == 1 else opp_agent

    env_error: Optional[str] = None
    try:
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
        env.run([p0, p1])
    except Exception as e:
        env_error = str(e)

    steps = getattr(env, "steps", [])
    if steps and len(steps) > 0:
        final_step = steps[-1]
        r0 = float(final_step[0].get("reward") or 0.0)
        r1 = float(final_step[1].get("reward") or 0.0)
        our_cash = r0 if seat == 0 else r1
        opp_cash = r1 if seat == 0 else r0
        winner = "AGENT" if our_cash > opp_cash else ("OPPONENT" if opp_cash > our_cash else "TIE")
    else:
        our_cash = 0.0
        opp_cash = 0.0
        winner = "ERROR"

    reset_agent_state()
    config.set_sw_forward_architecture_mode("OFF")

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "mode": mode,
        "our_cash": our_cash,
        "opp_cash": opp_cash,
        "winner": winner,
        "error": env_error,
        "actions": actions,
        "shadow_records": shadow_records,
        "latencies": latencies,
        "steps_count": len(actions),
    }


def _worker_run_pair(cfg: Dict[str, Any], include_full_trace: bool = False) -> Dict[str, Any]:
    pair_id = cfg["pair_id"]
    seed = cfg["seed"]
    opponent = cfg["opponent"]
    seat = cfg["seat"]

    t_start = time.perf_counter()

    off_res = _worker_run_single_match(seed, opponent, seat, "OFF")
    shadow_res = _worker_run_single_match(seed, opponent, seat, "SHADOW")

    elapsed = round(time.perf_counter() - t_start, 2)

    actions_off = off_res["actions"]
    actions_shadow = shadow_res["actions"]
    cash_off = off_res["our_cash"]
    cash_shadow = shadow_res["our_cash"]

    actions_match = (actions_off == actions_shadow)
    cash_match = (cash_off == cash_shadow)
    error_free = (off_res["error"] is None and shadow_res["error"] is None)
    invariance_passed = bool(actions_match and cash_match and error_free)

    shadow_records = shadow_res["shadow_records"]
    latencies = shadow_res["latencies"]
    lat_stats = _compute_percentiles(latencies)

    first_sw_day: Optional[int] = None
    first_sw_step: Optional[int] = None
    first_baseline_sw_day: Optional[int] = None
    baseline_bought_sw = False

    status_counts = {"PURCHASE": 0, "DELAY": 0, "DOWNSIZE": 0, "REJECT": 0}
    tier_counts = {"CERTIFIED_SAFE": 0, "TIGHT_BUT_SERVICEABLE": 0, "INFEASIBLE": 0, "UNCERTAIN": 0}
    binding_resource_counts: Dict[str, int] = {}
    uncertainty_flag_counts: Dict[str, int] = {}

    core_cert_passes = 0
    combined_cert_passes = 0
    lifecycle_passes = 0

    eval_totals = {
        "evaluated": 0,
        "admitted": 0,
        "delayed": 0,
        "downsized": 0,
        "rejected": 0,
    }

    econ_deltas: List[float] = []
    econ_sw_gross: List[float] = []
    econ_sw_seeds: List[float] = []
    econ_inc_labor: List[float] = []
    econ_cannibalization: List[float] = []
    econ_displaced_val: List[float] = []
    econ_feed_opp: List[float] = []
    econ_storage_pen: List[float] = []

    peak_sheds: List[int] = []
    peak_actions: List[int] = []

    prev_status: str = "REJECT"
    key_events: List[Dict[str, Any]] = []
    daily_telemetry: List[Dict[str, Any]] = []

    for r in shadow_records:
        st = r["sw_recommendation_status"]
        status_counts[st] = status_counts.get(st, 0) + 1
        tier = r.get("guarantee_tier", "UNCERTAIN")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

        bres = r["binding_resource"]
        binding_resource_counts[bres] = binding_resource_counts.get(bres, 0) + 1

        for uf in r["economic_uncertainty_flags"]:
            uncertainty_flag_counts[uf] = uncertainty_flag_counts.get(uf, 0) + 1

        if r["core_only_cert_feasible"]:
            core_cert_passes += 1
        if r["combined_cert_feasible"]:
            combined_cert_passes += 1
        if r["lifecycle_workload_feasible"]:
            lifecycle_passes += 1

        if r["sw_purchase_recommended"] and first_sw_day is None:
            first_sw_day = r["day"]
            first_sw_step = r["step"]

        if r["baseline_sw_purchase"]:
            baseline_bought_sw = True
            if first_baseline_sw_day is None:
                first_baseline_sw_day = r["day"]

        eval_totals["evaluated"] += r["candidates_evaluated_count"]
        eval_totals["admitted"] += r["candidates_admitted_count"]
        eval_totals["delayed"] += r["candidates_delayed_count"]
        eval_totals["downsized"] += r["candidates_downsized_count"]
        eval_totals["rejected"] += r["candidates_rejected_count"]

        if r["portfolio_delta_fc"] != 0.0 or st != "REJECT":
            econ_deltas.append(r["portfolio_delta_fc"])
            econ_sw_gross.append(r["sw_gross_revenue"])
            econ_sw_seeds.append(r["sw_seed_cost"])
            econ_inc_labor.append(r["sw_incremental_labor_cost"])
            econ_cannibalization.append(r["core_cannibalization_loss"])
            econ_displaced_val.append(r["displaced_core_value"])
            econ_feed_opp.append(r["feed_opportunity_cost"])
            econ_storage_pen.append(r["storage_loss_penalty"])

        peak_sheds.append(r["full_lifecycle_peak_shed"])
        peak_actions.append(r["full_lifecycle_peak_daily_actions"])

        if r["hour"] == 0:
            daily_telemetry.append(r)

        if st != prev_status or st in ("PURCHASE", "DOWNSIZE"):
            key_events.append({
                "step": r["step"],
                "day": r["day"],
                "hour": r["hour"],
                "prev_status": prev_status,
                "new_status": st,
                "delta_fc": r["portfolio_delta_fc"],
                "binding_resource": bres,
                "portfolio": r["selected_portfolio"],
            })
            prev_status = st

    n_records = max(1, len(shadow_records))

    pair_result = {
        "pair_id": pair_id,
        "seed": seed,
        "opponent": opponent,
        "seat": seat,
        "elapsed_seconds": elapsed,
        "invariance": {
            "passed": invariance_passed,
            "actions_match": actions_match,
            "cash_match": cash_match,
            "error_free": error_free,
            "cash_off": cash_off,
            "cash_shadow": cash_shadow,
            "opp_cash_off": off_res["opp_cash"],
            "opp_cash_shadow": shadow_res["opp_cash"],
            "winner_off": off_res["winner"],
            "winner_shadow": shadow_res["winner"],
            "off_error": off_res["error"],
            "shadow_error": shadow_res["error"],
            "action_count_off": len(actions_off),
            "action_count_shadow": len(actions_shadow),
        },
        "shadow_summary": {
            "latencies": lat_stats,
            "first_sw_recommended_day": first_sw_day,
            "first_sw_recommended_step": first_sw_step,
            "sw_ever_recommended": first_sw_day is not None,
            "first_baseline_sw_day": first_baseline_sw_day,
            "baseline_bought_sw": baseline_bought_sw,
            "status_counts": status_counts,
            "tier_counts": tier_counts,
            "candidate_eval_totals": eval_totals,
            "core_cert_pass_rate": round(core_cert_passes / n_records, 4),
            "combined_cert_pass_rate": round(combined_cert_passes / n_records, 4),
            "lifecycle_pass_rate": round(lifecycle_passes / n_records, 4),
            "binding_resource_counts": binding_resource_counts,
            "uncertainty_flag_counts": uncertainty_flag_counts,
            "mean_delta_fc": round(float(sum(econ_deltas) / len(econ_deltas)), 2) if econ_deltas else 0.0,
            "max_delta_fc": round(max(econ_deltas), 2) if econ_deltas else 0.0,
            "mean_sw_gross": round(float(sum(econ_sw_gross) / len(econ_sw_gross)), 2) if econ_sw_gross else 0.0,
            "mean_sw_seeds": round(float(sum(econ_sw_seeds) / len(econ_sw_seeds)), 2) if econ_sw_seeds else 0.0,
            "mean_inc_labor": round(float(sum(econ_inc_labor) / len(econ_inc_labor)), 2) if econ_inc_labor else 0.0,
            "mean_cannibalization": round(float(sum(econ_cannibalization) / len(econ_cannibalization)), 2) if econ_cannibalization else 0.0,
            "mean_displaced_val": round(float(sum(econ_displaced_val) / len(econ_displaced_val)), 2) if econ_displaced_val else 0.0,
            "mean_feed_opp": round(float(sum(econ_feed_opp) / len(econ_feed_opp)), 2) if econ_feed_opp else 0.0,
            "mean_storage_pen": round(float(sum(econ_storage_pen) / len(econ_storage_pen)), 2) if econ_storage_pen else 0.0,
            "max_peak_shed": max(peak_sheds) if peak_sheds else 0,
            "max_peak_actions": max(peak_actions) if peak_actions else 0,
        },
        "daily_telemetry": daily_telemetry,
        "key_events": key_events,
    }

    if include_full_trace:
        pair_result["full_step_records"] = shadow_records

    return pair_result


def build_manifest() -> Dict[str, Any]:
    configs = []
    pair_id = 0
    for seed in FRESH_SEEDS:
        for opp in OPPONENTS:
            for seat in SEATS:
                configs.append({
                    "pair_id": pair_id,
                    "seed": seed,
                    "opponent": opp,
                    "seat": seat,
                })
                pair_id += 1

    manifest = {
        "panel_name": "Kaggriculture Calibrated Diagnostic Panel (100 Configurations)",
        "evaluated_branch": "experiment/sw-forward-architecture-phase-a",
        "engine_name": "kaggriculture",
        "engine_version": "1.32.7",
        "python_version": "3.12.10",
        "default_architecture_mode": "OFF",
        "evaluation_modes": ["OFF", "SHADOW"],
        "total_pairs": len(configs),
        "total_matches": len(configs) * 2,
        "episode_steps": 720,
        "seeds": FRESH_SEEDS,
        "seed_provenance": "10 fresh non-protected seeds (96511-96520) verified unreferenced and unexecuted",
        "protected_seeds_quarantined": "98001-98050 (strictly untouched)",
        "opponents": OPPONENTS,
        "seats": SEATS,
        "configurations": configs,
    }
    with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def main():
    print("=" * 80)
    print("RUNNING FRESH CALIBRATED DIAGNOSTIC PANEL (100 CONFIGURATIONS)")
    print("=" * 80)

    manifest = build_manifest()
    configs = manifest["configurations"]
    total_configs = len(configs)
    trace_pair_ids = {0, 3, 14, 27, 38, 41, 52, 65, 76, 89}

    workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"Executing {total_configs} pairs ({total_configs * 2} matches) with {workers} workers...")

    tasks = [(cfg, cfg["pair_id"] in trace_pair_ids) for cfg in configs]
    t_start = time.perf_counter()
    results: List[Dict[str, Any]] = []
    completed_count = 0

    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_worker_run_pair, cfg, inc_trace): cfg["pair_id"]
            for cfg, inc_trace in tasks
        }

        for future in as_completed(future_map):
            pair_id = future_map[future]
            try:
                res = future.result()
                results.append(res)
                completed_count += 1
                inv_sym = "PASS" if res["invariance"]["passed"] else "FAIL"
                sm = res["shadow_summary"]
                print(
                    f"[{completed_count:3d}/{total_configs}] Pair {res['pair_id']:02d} "
                    f"(Seed {res['seed']}, Opp: {res['opponent']:20s}, S{res['seat']}): "
                    f"Inv={inv_sym} | CorePass={sm['core_cert_pass_rate']*100:.1f}% | "
                    f"CombPass={sm['combined_cert_pass_rate']*100:.1f}% | "
                    f"Lat_p50={sm['latencies']['p50']:.1f}ms | T={res['elapsed_seconds']}s",
                    flush=True
                )
            except Exception as exc:
                print(f"ERROR executing pair {pair_id}: {exc}", flush=True)
                raise exc

    results.sort(key=lambda r: r["pair_id"])
    total_elapsed = round(time.perf_counter() - t_start, 2)

    # Save traces
    rep_traces = {}
    for r in results:
        if "full_step_records" in r:
            rep_traces[f"pair_{r['pair_id']}_{r['opponent']}_s{r['seat']}_seed{r['seed']}"] = {
                "pair_id": r["pair_id"],
                "seed": r["seed"],
                "opponent": r["opponent"],
                "seat": r["seat"],
                "invariance": r["invariance"],
                "shadow_summary": r["shadow_summary"],
                "full_step_records": r.pop("full_step_records"),
            }
    with open(_TRACES_PATH, "w", encoding="utf-8") as f:
        json.dump(rep_traces, f, indent=2)

    # Save results
    with open(_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Aggregates
    passed_invariance = sum(1 for r in results if r["invariance"]["passed"])
    all_lat_p50 = [r["shadow_summary"]["latencies"]["p50"] for r in results]
    all_lat_p95 = [r["shadow_summary"]["latencies"]["p95"] for r in results]
    all_lat_max = [r["shadow_summary"]["latencies"]["max"] for r in results]

    tot_status = {"PURCHASE": 0, "DELAY": 0, "DOWNSIZE": 0, "REJECT": 0}
    tot_tiers = {"CERTIFIED_SAFE": 0, "TIGHT_BUT_SERVICEABLE": 0, "INFEASIBLE": 0, "UNCERTAIN": 0}
    tot_bindings: Dict[str, int] = {}
    tot_uncertainty: Dict[str, int] = {}

    for r in results:
        sm = r["shadow_summary"]
        for k, v in sm["status_counts"].items():
            tot_status[k] += v
        for k, v in sm.get("tier_counts", {}).items():
            tot_tiers[k] += v
        for k, v in sm["binding_resource_counts"].items():
            tot_bindings[k] = tot_bindings.get(k, 0) + v
        for k, v in sm["uncertainty_flag_counts"].items():
            tot_uncertainty[k] = tot_uncertainty.get(k, 0) + v

    mean_core_pass = round(sum(r["shadow_summary"]["core_cert_pass_rate"] for r in results) / total_configs, 4)
    mean_comb_pass = round(sum(r["shadow_summary"]["combined_cert_pass_rate"] for r in results) / total_configs, 4)
    mean_lc_pass = round(sum(r["shadow_summary"]["lifecycle_pass_rate"] for r in results) / total_configs, 4)

    aggregate_tables = {
        "provenance": {
            "panel_name": manifest["panel_name"],
            "evaluated_branch": manifest["evaluated_branch"],
            "seeds": manifest["seeds"],
            "total_pairs": total_configs,
            "total_matches": total_configs * 2,
            "elapsed_seconds": total_elapsed,
        },
        "invariance": {
            "total_pairs": total_configs,
            "passed_invariance": passed_invariance,
            "invariance_pct": round(passed_invariance / total_configs * 100.0, 2),
            "latency_p50": _compute_percentiles(all_lat_p50),
            "latency_p95": _compute_percentiles(all_lat_p95),
            "latency_max": _compute_percentiles(all_lat_max),
        },
        "feasibility": {
            "mean_core_cert_pass_rate": mean_core_pass,
            "mean_combined_cert_pass_rate": mean_comb_pass,
            "mean_lifecycle_pass_rate": mean_lc_pass,
            "status_distribution": tot_status,
            "tier_distribution": tot_tiers,
            "binding_resources": tot_bindings,
            "uncertainty_flags": tot_uncertainty,
        }
    }

    with open(_AGGREGATE_PATH, "w", encoding="utf-8") as f:
        json.dump(aggregate_tables, f, indent=2)

    print("\n" + "=" * 80)
    print("FRESH CALIBRATED DIAGNOSTIC PANEL SUMMARY VERDICT")
    print("=" * 80)
    print(f"Action & Cash Invariance:    {passed_invariance}/{total_configs} ({passed_invariance/total_configs*100:.1f}%)")
    print(f"Mean Core Cert Pass Rate:    {mean_core_pass*100:.2f}% (Gate 1 uncalibrated was: 3.77%)")
    print(f"Mean Combined Pass Rate:     {mean_comb_pass*100:.2f}%")
    print(f"Mean Lifecycle Pass Rate:    {mean_lc_pass*100:.2f}%")
    print(f"Safety Tiers (All Turns):    {tot_tiers}")
    print(f"Latency P50 Mean:            {aggregate_tables['invariance']['latency_p50']['mean']:.2f}ms")
    print(f"Total Elapsed Time:          {total_elapsed}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
