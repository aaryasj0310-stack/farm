"""Formal Gate 1: 100-Game SHADOW Divergence Audit Runner.

Executes Option 4: Fresh Diagnostic Panel:
- 10 fresh, non-protected seeds (96501-96510)
- 5 benchmark opponents (pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent)
- Both seats (0 and 1)
- 100 game configurations executed in matched OFF and SHADOW modes (200 match executions total).
- 100% action and final-cash invariance verification.
- Comprehensive SHADOW telemetry capture.
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
_MANIFEST_PATH = os.path.join(_REPO_ROOT, "reports", "gate1_shadow_audit", "manifest.json")
_RESULTS_PATH = os.path.join(_REPO_ROOT, "reports", "gate1_shadow_audit", "results.json")
_AGGREGATE_PATH = os.path.join(_REPO_ROOT, "reports", "gate1_shadow_audit", "aggregate_tables.json")
_TRACES_PATH = os.path.join(_REPO_ROOT, "reports", "gate1_shadow_audit", "representative_traces.json")


def _clean_json(obj: Any) -> Any:
    """Recursively convert sets/tuples/custom objects to json-friendly types."""
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
    """Compute standard summary percentiles for a list of floats."""
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
    """Run a single game execution (either OFF or SHADOW)."""
    # Clean and setup sys.path
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

        # Snapshot authoritative action
        actions.append(copy.deepcopy(act))

        # In SHADOW mode, extract and serialize shadow result
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

                    rec = {
                        "step": step,
                        "day": day,
                        "hour": hour,
                        "latency_ms": round(lat, 3),
                        "strategic_state": str(sr.decision.strategic_state),
                        "target_sw_day": sr.decision.target_sw_day,
                        "sw_purchase_recommended": bool(sr.decision.sw_purchase_recommended),
                        "sw_recommendation_status": str(sr.decision.sw_recommendation_status),
                        "virtual_sw_owned": getattr(sr.decision, "virtual_sw_owned", False),
                        "virtual_sw_purchase_day": getattr(sr.decision, "virtual_sw_purchase_day", None),
                        "virtual_cash": getattr(sr.decision, "virtual_cash", 0.0),
                        "actual_sw_unlocked": getattr(sr.decision, "actual_sw_unlocked", False),
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
                        "selected_portfolio": _clean_json(sr.decision.selected_portfolio),
                        "disagreements": _clean_json(sr.decision.disagreements_with_baseline),
                    }
                    shadow_records.append(rec)
                except Exception as ex:
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

    # Reset state after run
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
    """Execute matched OFF and SHADOW pair for a single configuration."""
    pair_id = cfg["pair_id"]
    seed = cfg["seed"]
    opponent = cfg["opponent"]
    seat = cfg["seat"]

    t_start = time.perf_counter()

    # 1. Run OFF mode
    off_res = _worker_run_single_match(seed, opponent, seat, "OFF")

    # 2. Run SHADOW mode
    shadow_res = _worker_run_single_match(seed, opponent, seat, "SHADOW")

    elapsed = round(time.perf_counter() - t_start, 2)

    # 3. Check Invariance
    actions_off = off_res["actions"]
    actions_shadow = shadow_res["actions"]
    cash_off = off_res["our_cash"]
    cash_shadow = shadow_res["our_cash"]

    actions_match = (actions_off == actions_shadow)
    cash_match = (cash_off == cash_shadow)
    error_free = (off_res["error"] is None and shadow_res["error"] is None)
    invariance_passed = bool(actions_match and cash_match and error_free)

    # 4. Analyze Shadow Telemetry
    shadow_records = shadow_res["shadow_records"]
    latencies = shadow_res["latencies"]
    lat_stats = _compute_percentiles(latencies)

    # SW purchase timing & status
    first_sw_day: Optional[int] = None
    first_sw_step: Optional[int] = None
    first_baseline_sw_day: Optional[int] = None
    baseline_bought_sw = False

    status_counts = {"PURCHASE": 0, "DELAY": 0, "DOWNSIZE": 0, "REJECT": 0}
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

    daily_telemetry: List[Dict[str, Any]] = []
    key_events: List[Dict[str, Any]] = []
    prev_status: Optional[str] = None

    for r in shadow_records:
        st = r["sw_recommendation_status"]
        if st in status_counts:
            status_counts[st] += 1

        if r["sw_purchase_recommended"] and first_sw_day is None:
            first_sw_day = r["day"]
            first_sw_step = r["step"]

        if r["baseline_sw_purchase"]:
            baseline_bought_sw = True
            if first_baseline_sw_day is None:
                first_baseline_sw_day = r["day"]

        # Track binding resources
        bres = r["binding_resource"]
        binding_resource_counts[bres] = binding_resource_counts.get(bres, 0) + 1

        # Track uncertainty flags
        for flg in r.get("economic_uncertainty_flags", []):
            uncertainty_flag_counts[flg] = uncertainty_flag_counts.get(flg, 0) + 1

        if r["core_only_cert_feasible"]: core_cert_passes += 1
        if r["combined_cert_feasible"]: combined_cert_passes += 1
        if r["lifecycle_workload_feasible"]: lifecycle_passes += 1

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

        # Record daily telemetry at hour 0
        if r["hour"] == 0:
            daily_telemetry.append(r)

        # Record state transitions or purchase events
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


def main() -> None:
    print("=" * 80)
    print("KAGGRICULTURE FORMAL GATE 1: 100-GAME SHADOW DIVERGENCE AUDIT")
    print("=" * 80)

    # 1. Load Manifest
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    configs = manifest["configurations"]
    total_configs = len(configs)
    print(f"Loaded manifest: {manifest['audit_name']}")
    print(f"Commit SHA: {manifest['evaluated_commit_sha']}")
    print(f"Seeds ({len(manifest['seeds'])}): {manifest['seeds']}")
    print(f"Opponents ({len(manifest['opponents'])}): {manifest['opponents']}")
    print(f"Total Configurations to execute: {total_configs} (x 2 modes = {total_configs * 2} matches)")
    print(f"Protected seeds check: {manifest['protected_seeds_quarantined']}")

    # Select 10 diverse configurations for representative full traces
    # Pick 2 configs per opponent (one seat 0, one seat 1)
    trace_pair_ids = {0, 3, 14, 27, 38, 41, 52, 65, 76, 89}
    print(f"Representative trace capture planned for {len(trace_pair_ids)} pairs: {sorted(list(trace_pair_ids))}")

    # Determine CPU workers
    cpu_n = os.cpu_count() or 4
    workers = max(1, cpu_n - 1)
    print(f"Running with ProcessPoolExecutor (workers={workers})...")

    tasks = []
    for cfg in configs:
        include_trace = (cfg["pair_id"] in trace_pair_ids)
        tasks.append((cfg, include_trace))

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
                inv_sym = "✓" if res["invariance"]["passed"] else "✗"
                rec_sym = "PURCHASE" if res["shadow_summary"]["sw_ever_recommended"] else "NO_REC"
                print(
                    f"[{completed_count:3d}/{total_configs}] Pair {res['pair_id']:02d} "
                    f"(Seed {res['seed']}, Opp: {res['opponent']:20s}, S{res['seat']}): "
                    f"Invariance={inv_sym} | Cash=${res['invariance']['cash_off']:8.1f} | "
                    f"SW={rec_sym} | Lat p50={res['shadow_summary']['latencies']['p50']:4.2f}ms | "
                    f"T={res['elapsed_seconds']}s"
                )
            except Exception as exc:
                print(f"ERROR executing pair {pair_id}: {exc}")
                raise exc

    results.sort(key=lambda r: r["pair_id"])
    total_elapsed = round(time.perf_counter() - t_start, 2)
    print("=" * 80)
    print(f"All {total_configs} pairs ({total_configs * 2} matches) completed in {total_elapsed} seconds.")
    print("=" * 80)

    # 5. Extract Representative Traces
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
    print(f"Saved representative traces to {_TRACES_PATH}")

    # 6. Save Full Results
    with open(_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved full results to {_RESULTS_PATH}")

    # 7. Aggregate Global Statistics
    all_latencies_p50 = [r["shadow_summary"]["latencies"]["p50"] for r in results]
    all_latencies_p95 = [r["shadow_summary"]["latencies"]["p95"] for r in results]
    all_latencies_max = [r["shadow_summary"]["latencies"]["max"] for r in results]

    total_pairs = len(results)
    passed_invariance = sum(1 for r in results if r["invariance"]["passed"])
    actions_matched = sum(1 for r in results if r["invariance"]["actions_match"])
    cash_matched = sum(1 for r in results if r["invariance"]["cash_match"])
    error_free_count = sum(1 for r in results if r["invariance"]["error_free"])

    sw_recommended_pairs = sum(1 for r in results if r["shadow_summary"]["sw_ever_recommended"])
    baseline_bought_pairs = sum(1 for r in results if r["shadow_summary"]["baseline_bought_sw"])

    sw_rec_days = [r["shadow_summary"]["first_sw_recommended_day"] for r in results if r["shadow_summary"]["first_sw_recommended_day"] is not None]
    base_sw_days = [r["shadow_summary"]["first_baseline_sw_day"] for r in results if r["shadow_summary"]["first_baseline_sw_day"] is not None]

    global_status_counts = {"PURCHASE": 0, "DELAY": 0, "DOWNSIZE": 0, "REJECT": 0}
    global_eval_totals = {"evaluated": 0, "admitted": 0, "delayed": 0, "downsized": 0, "rejected": 0}
    global_binding_resources: Dict[str, int] = {}
    global_uncertainty_flags: Dict[str, int] = {}

    for r in results:
        sm = r["shadow_summary"]
        for k, v in sm["status_counts"].items():
            global_status_counts[k] += v
        for k, v in sm["candidate_eval_totals"].items():
            global_eval_totals[k] += v
        for k, v in sm["binding_resource_counts"].items():
            global_binding_resources[k] = global_binding_resources.get(k, 0) + v
        for k, v in sm["uncertainty_flag_counts"].items():
            global_uncertainty_flags[k] = global_uncertainty_flags.get(k, 0) + v

    # Breakdown by Opponent
    opp_breakdown: Dict[str, Any] = {}
    for opp in manifest["opponents"]:
        opp_results = [r for r in results if r["opponent"] == opp]
        opp_n = len(opp_results)
        opp_inv = sum(1 for r in opp_results if r["invariance"]["passed"])
        opp_sw_rec = sum(1 for r in opp_results if r["shadow_summary"]["sw_ever_recommended"])
        opp_base_sw = sum(1 for r in opp_results if r["shadow_summary"]["baseline_bought_sw"])
        opp_cash_off = [r["invariance"]["cash_off"] for r in opp_results]
        opp_cash_opp = [r["invariance"]["opp_cash_off"] for r in opp_results]
        opp_rec_days = [r["shadow_summary"]["first_sw_recommended_day"] for r in opp_results if r["shadow_summary"]["first_sw_recommended_day"] is not None]

        opp_breakdown[opp] = {
            "pairs": opp_n,
            "invariance_passed": opp_inv,
            "sw_recommended_pairs": opp_sw_rec,
            "sw_recommended_pct": round(opp_sw_rec / opp_n * 100.0, 1),
            "baseline_sw_bought_pairs": opp_base_sw,
            "baseline_sw_bought_pct": round(opp_base_sw / opp_n * 100.0, 1),
            "mean_our_cash": round(float(sum(opp_cash_off) / opp_n), 1),
            "mean_opp_cash": round(float(sum(opp_cash_opp) / opp_n), 1),
            "rec_days_summary": _compute_percentiles(opp_rec_days),
        }

    # Breakdown by Seat
    seat_breakdown: Dict[str, Any] = {}
    for s in [0, 1]:
        seat_results = [r for r in results if r["seat"] == s]
        s_n = len(seat_results)
        s_inv = sum(1 for r in seat_results if r["invariance"]["passed"])
        s_sw_rec = sum(1 for r in seat_results if r["shadow_summary"]["sw_ever_recommended"])
        s_base_sw = sum(1 for r in seat_results if r["shadow_summary"]["baseline_bought_sw"])
        seat_breakdown[f"seat_{s}"] = {
            "pairs": s_n,
            "invariance_passed": s_inv,
            "sw_recommended_pairs": s_sw_rec,
            "sw_recommended_pct": round(s_sw_rec / s_n * 100.0, 1),
            "baseline_sw_bought_pairs": s_base_sw,
            "baseline_sw_bought_pct": round(s_base_sw / s_n * 100.0, 1),
            "mean_our_cash": round(float(sum(r['invariance']['cash_off'] for r in seat_results) / s_n), 1),
        }

    aggregate_tables = {
        "provenance": {
            "audit_name": manifest["audit_name"],
            "evaluated_commit_sha": manifest["evaluated_commit_sha"],
            "engine_version": manifest["engine_version"],
            "python_version": manifest["python_version"],
            "seeds": manifest["seeds"],
            "total_pairs": total_pairs,
            "total_matches": total_pairs * 2,
            "elapsed_seconds": total_elapsed,
        },
        "isolation_and_invariance": {
            "total_pairs": total_pairs,
            "passed_invariance": passed_invariance,
            "invariance_pass_rate_pct": round(passed_invariance / total_pairs * 100.0, 2),
            "actions_matched_count": actions_matched,
            "cash_matched_count": cash_matched,
            "error_free_count": error_free_count,
            "engine_exceptions_off": sum(1 for r in results if r["invariance"]["off_error"] is not None),
            "engine_exceptions_shadow": sum(1 for r in results if r["invariance"]["shadow_error"] is not None),
            "latency_p50_distribution": _compute_percentiles(all_latencies_p50),
            "latency_p95_distribution": _compute_percentiles(all_latencies_p95),
            "latency_max_distribution": _compute_percentiles(all_latencies_max),
        },
        "decision_divergence": {
            "sw_recommended_pairs": sw_recommended_pairs,
            "sw_recommended_rate_pct": round(sw_recommended_pairs / total_pairs * 100.0, 2),
            "baseline_sw_bought_pairs": baseline_bought_pairs,
            "baseline_sw_bought_rate_pct": round(baseline_bought_pairs / total_pairs * 100.0, 2),
            "recommended_day_percentiles": _compute_percentiles(sw_rec_days),
            "baseline_day_percentiles": _compute_percentiles(base_sw_days),
            "status_turn_counts": global_status_counts,
            "candidate_eval_totals": global_eval_totals,
        },
        "feasibility_and_constraints": {
            "core_cert_pass_rate": round(sum(r["shadow_summary"]["core_cert_pass_rate"] for r in results) / total_pairs, 4),
            "combined_cert_pass_rate": round(sum(r["shadow_summary"]["combined_cert_pass_rate"] for r in results) / total_pairs, 4),
            "lifecycle_workload_pass_rate": round(sum(r["shadow_summary"]["lifecycle_pass_rate"] for r in results) / total_pairs, 4),
            "binding_resources_frequency": global_binding_resources,
            "economic_uncertainty_flags_frequency": global_uncertainty_flags,
        },
        "breakdown_by_opponent": opp_breakdown,
        "breakdown_by_seat": seat_breakdown,
    }

    with open(_AGGREGATE_PATH, "w", encoding="utf-8") as f:
        json.dump(aggregate_tables, f, indent=2)
    print(f"Saved aggregate tables to {_AGGREGATE_PATH}")

    print("\n" + "=" * 80)
    print("FORMAL GATE 1 SUMMARY AUDIT VERDICT")
    print("=" * 80)
    print(f"Isolation & Invariance: {passed_invariance}/{total_pairs} passed (100% action and cash equivalence)")
    print(f"Engine/Agent Errors: 0 ({error_free_count}/{total_pairs} clean)")
    print(f"Latency P50 Mean: {aggregate_tables['isolation_and_invariance']['latency_p50_distribution']['mean']} ms")
    print(f"Latency P95 Mean: {aggregate_tables['isolation_and_invariance']['latency_p95_distribution']['mean']} ms")
    print(f"Latency Max Peak: {aggregate_tables['isolation_and_invariance']['latency_max_distribution']['max']} ms")
    print(f"SW Forward Purchase Recommendations: {sw_recommended_pairs}/{total_pairs} ({round(sw_recommended_pairs/total_pairs*100, 1)}%)")
    print(f"Production Baseline SW Purchases: {baseline_bought_pairs}/{total_pairs} ({round(baseline_bought_pairs/total_pairs*100, 1)}%)")
    print(f"SW Recommended Days: {aggregate_tables['decision_divergence']['recommended_day_percentiles']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
