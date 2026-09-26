"""Phase M0-K-R1: Evidence Reconciliation & Telemetry Audit Script.

Performs:
1. Raw artifact immutability verification (SHA256 check).
2. Authoritative re-computation of descriptive and clustered statistics from paired_results.json.
3. Storage discard and spot-value aggregation reconciliation.
4. Telemetry diagnosis:
   - Explains why rescue_units_sold was negative (-13,024) in the whole-step calculation.
   - Explains why rescue_revenue ($941,919) was a whole-step cash delta rather than rescue revenue.
   - Explains the market order cap metric and gate_8 evaluation.
5. Validation replay on consumed development seed 97013 demonstrating authoritative
   market-execution-boundary instrumentation.
6. Emits structured comparison and validation deliverables to simulations/results/phase_m0_k_r1_validation/.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
CONF_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_k_confirmation")
REP_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_k_reproduction")
REL_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_k_release")
R1_VAL_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_k_r1_validation")
os.makedirs(R1_VAL_DIR, exist_ok=True)

# Expected canonical raw hashes recorded at the start of R1
RAW_HASHES = {
    os.path.join(REP_DIR, "c0_results.json"): "3faf066160269ba3b1233c6ddefcdea8c1b203da15227a355e5015c60efc54a9",
    os.path.join(REP_DIR, "clustered_statistics.json"): "42e274df2b80f87917d1c97e844047456e99b1ba69d34948bf7503657fcff5db",
    os.path.join(REP_DIR, "feed_safety.json"): "483eedd9a2560ff4de418cebfdc560a1ade908f6b2385783d6d138d725ce0236",
    os.path.join(REP_DIR, "manifest.json"): "bbbc0a23a30c78ad16850d36868e6b6792a01d104fe8e710e45e2a95a80e1960",
    os.path.join(REP_DIR, "market_arbitration.json"): "e33412cdeb997566261a08f2e53f4fe96d9becc693965b8a0db0dd30f8fe5470",
    os.path.join(REP_DIR, "paired_results.json"): "87f469c80f217f5504a1983ddbd66b9581be30b06d7d21d50a65a42c71a4036a",
    os.path.join(REP_DIR, "rescue_execution.json"): "5a0aec32e098122e6380418a6508f4122a6aada566129e2c7b08a0bb397a1ffb",
    os.path.join(REP_DIR, "rescue_results.json"): "2881c4a113c6134c5ba863e7b13f1047b96535e975b08f489846bc98fc90af2e",
    os.path.join(REP_DIR, "source_hashes.json"): "e77008a3ea8483c6f78646870a1c78264d3308425017254ffb798f5feeaa524e",
    os.path.join(REP_DIR, "storage_accounting.json"): "553b7d6852802ff3fc832d012589caa354dc8857aee768347df2e178c049ca92",
    os.path.join(CONF_DIR, "aggregate_statistics.json"): "716322fb82c68d4e30efd850ef375ede183635357a6a77f6dc1815092a0a1015",
    os.path.join(CONF_DIR, "animal_safety.json"): "483eedd9a2560ff4de418cebfdc560a1ade908f6b2385783d6d138d725ce0236",
    os.path.join(CONF_DIR, "clustered_statistics.json"): "fb6d86546a7ccbfca96710286ea8745d3692b655d2e2aac0eefd77ebb66a7c3d",
    os.path.join(CONF_DIR, "downside_forensics.json"): "e71d81a4e288277cc95a7700b193114130bbc2b28e4f8c30e02b008d5b33cf1c",
    os.path.join(CONF_DIR, "frozen_candidate_hashes.json"): "e48e9f5b97f187e03d70602094a99f7ac8ed10825245ecf55f553ad903cca787",
    os.path.join(CONF_DIR, "manifest.json"): "21f8ca3f10165f8106c5209bc224fdc090f9e88866bbc78ba6c97645d8a6f36e",
    os.path.join(CONF_DIR, "market_safety.json"): "8cd2356f27ccef998494f748f58f9c25a3fdafcffb180ad9f2732c4d18413df5",
    os.path.join(CONF_DIR, "opponent_breakdown.json"): "19cf0b4059d5ccc0d4cf5b97440ae228cc39e2a4419ebdc92cd25011f7504ddc",
    os.path.join(CONF_DIR, "paired_results.json"): "6863e9ef6c3595d9f677f5ca0de52289e1c2a22aae7a2b28d9ff51d66eb333ae",
    os.path.join(CONF_DIR, "seat_breakdown.json"): "498e7e9522b89c94e3af23aa4773f2567cb7c8db76aae2ce50724a0be2d03d7f",
    os.path.join(CONF_DIR, "storage_comparison.json"): "7941b6fcc86882e243006c4eee0d9a5b38c2f2190b7180d64d9dd4818f0f61aa",
}


def audit_raw_immutability() -> Dict[str, Any]:
    """Verify that all raw experimental artifacts remain bit-for-bit identical."""
    mismatches = []
    verified = []
    for path, expected_hash in RAW_HASHES.items():
        if not os.path.exists(path):
            mismatches.append({"path": path, "status": "FILE_NOT_FOUND"})
            continue
        with open(path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        if actual_hash != expected_hash:
            mismatches.append({"path": path, "expected": expected_hash, "actual": actual_hash})
        else:
            verified.append({"path": path, "hash": actual_hash})
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "verified_count": len(verified),
        "mismatches": mismatches,
    }


def recompute_confirmation_statistics() -> Dict[str, Any]:
    """Recompute all statistics directly from raw paired_results.json."""
    pairs_path = os.path.join(CONF_DIR, "paired_results.json")
    with open(pairs_path, "r", encoding="utf-8") as f:
        pairs = json.load(f)

    assert len(pairs) == 200, f"Expected 200 pairs, found {len(pairs)}"

    c0_cash = np.array([p["c0_cash"] for p in pairs], dtype=float)
    c2_cash = np.array([p["c2_cash"] for p in pairs], dtype=float)
    deltas = np.array([p["delta_cash"] for p in pairs], dtype=float)

    # Descriptive statistics
    stats = {
        "c0": {
            "mean": float(np.mean(c0_cash)),
            "std": float(np.std(c0_cash, ddof=1)),
            "median": float(np.median(c0_cash)),
            "p10": float(np.percentile(c0_cash, 10)),
            "p25": float(np.percentile(c0_cash, 25)),
            "p50": float(np.percentile(c0_cash, 50)),
            "p75": float(np.percentile(c0_cash, 75)),
            "p90": float(np.percentile(c0_cash, 90)),
        },
        "c2": {
            "mean": float(np.mean(c2_cash)),
            "std": float(np.std(c2_cash, ddof=1)),
            "median": float(np.median(c2_cash)),
            "p10": float(np.percentile(c2_cash, 10)),
            "p25": float(np.percentile(c2_cash, 25)),
            "p50": float(np.percentile(c2_cash, 50)),
            "p75": float(np.percentile(c2_cash, 75)),
            "p90": float(np.percentile(c2_cash, 90)),
        },
        "delta": {
            "mean": float(np.mean(deltas)),
            "std": float(np.std(deltas, ddof=1)),
            "median": float(np.median(deltas)),
            "p10": float(np.percentile(deltas, 10)),
            "p25": float(np.percentile(deltas, 25)),
            "p50": float(np.percentile(deltas, 50)),
            "p75": float(np.percentile(deltas, 75)),
            "p90": float(np.percentile(deltas, 90)),
        },
        "record": {
            "wins": int(np.sum(deltas > 0.01)),
            "ties": int(np.sum(np.abs(deltas) <= 0.01)),
            "losses": int(np.sum(deltas < -0.01)),
            "win_rate_pct": float(np.sum(deltas > 0.01) / len(pairs) * 100.0),
        },
    }

    # Seed-clustered statistics
    seed_clusters: Dict[int, List[float]] = {}
    for p in pairs:
        seed_clusters.setdefault(p["seed"], []).append(p["delta_cash"])

    cluster_means = {s: float(np.mean(v)) for s, v in seed_clusters.items()}
    cluster_means_arr = np.array(list(cluster_means.values()), dtype=float)
    k = len(cluster_means_arr)
    grand_mean = float(np.mean(cluster_means_arr))
    se_clustered = float(np.std(cluster_means_arr, ddof=1) / math.sqrt(k))
    t_crit = 2.093024  # df = 19, 95% two-tailed
    ci_95 = [grand_mean - t_crit * se_clustered, grand_mean + t_crit * se_clustered]

    stats["clustered"] = {
        "k_clusters": k,
        "df": k - 1,
        "grand_mean": grand_mean,
        "se_clustered": se_clustered,
        "t_crit": t_crit,
        "ci_95": ci_95,
        "positive_clusters": int(np.sum(cluster_means_arr > 0)),
        "cluster_means": cluster_means,
    }

    # Storage and discard aggregation
    c0_discard = sum(p["c0_discarded"] for p in pairs)
    c2_discard = sum(p["c2_discarded"] for p in pairs)
    c0_spot_lost = sum(p["c0_spot_lost"] for p in pairs)
    c2_spot_lost = sum(p["c2_spot_lost"] for p in pairs)
    spot_preserved = sum(p["spot_val_preserved"] for p in pairs)

    stats["storage"] = {
        "c0_discarded_units": c0_discard,
        "c2_discarded_units": c2_discard,
        "units_saved": c0_discard - c2_discard,
        "discard_reduction_pct": (c0_discard - c2_discard) / c0_discard * 100.0,
        "c0_spot_value_lost": c0_spot_lost,
        "c2_spot_value_lost": c2_spot_lost,
        "spot_value_preserved": spot_preserved,
    }

    # Flawed telemetry fields recorded in historical archive
    stats["flawed_historical_telemetry"] = {
        "raw_sum_rescue_orders": sum(p["rescue_orders"] for p in pairs),
        "raw_sum_rescue_executed": sum(p["rescue_executed"] for p in pairs),
        "raw_sum_rescue_units": sum(p["rescue_units"] for p in pairs),
        "raw_sum_rescue_revenue": sum(p["rescue_revenue"] for p in pairs),
        "flaw_explanation_units": (
            "Computed via (shed_wheat_pre - shed_wheat_post) over step Hour 23->0. "
            "Engine _drop_inventories_to_shed deposits workers' wheat into shed at midnight rollover, "
            "making shed_wheat_post > shed_wheat_pre, yielding -13,024. Inverting sign to +13,024 is invalid."
        ),
        "flaw_explanation_revenue": (
            "Computed via (money_post - money_pre) over step Hour 23->0. "
            "Measures total step cash delta across all sales and purchases, not rescue wheat revenue alone."
        ),
        "flaw_explanation_cap_blocked": (
            "market_safety.json reported orders_blocked_by_10_cap = (emitted - executed) = 1,067. "
            "In kaggriculture, unexecuted orders are not blocked by the cap; controller only emits if len(market)<10."
        ),
    }

    return stats


def run_r1_validation_replay(seed: int = 97013) -> Dict[str, Any]:
    """Run an instrumented match on consumed dev seed 97013 to demonstrate market execution boundary hooks."""
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, os.path.join(_REPO_ROOT, "agent")] + [
        os.path.join(_REPO_ROOT, "agent", s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
    from agent.main import agent, reset_agent_state
    import config
    from execution.midnight_storage_controller import reset_midnight_storage_telemetry
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    config.set_midnight_storage_dump_mode("RESCUE")
    reset_agent_state()
    reset_midnight_storage_telemetry()
    reset_sw_tranche_controller()

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent("pass")

    orig_interpreter = env.interpreter
    turn_diagnostics = []

    def instrumented_interpreter(state, env_inst):
        s0 = state[0]
        act0 = s0.action if isinstance(s0.action, dict) else {}
        mkt0 = act0.get("market", [])
        obs0 = s0.observation
        day, hour = obs0.day, obs0.hour

        shed = obs0.private.shed
        carried = sum(sum(inv.values()) for inv in obs0.private.inventories)
        proj_load = sum(shed.values()) + carried

        is_rescue_step = (hour == 23 and day < 29 and proj_load > 98)
        rescue_order_idx = None
        if is_rescue_step and len(mkt0) > 0:
            last_ord = mkt0[-1]
            if last_ord[0] == "SELL" and last_ord[1] == "WHEAT":
                rescue_order_idx = len(mkt0) - 1

        orig_commit = kengine._commit_unit
        committed_units_p0 = []

        def tracked_commit(op, item, price, farm, private, market, shed_capacity=100):
            res = orig_commit(op, item, price, farm, private, market, shed_capacity)
            if res and farm is state[0].observation.farms[0]:
                committed_units_p0.append({"op": op, "item": item, "price": price})
            return res

        kengine._commit_unit = tracked_commit
        money_pre = state[0].observation.farms[0]["money"]
        shed_wheat_pre = obs0.private.shed.get("WHEAT", 0)

        try:
            ret_state = orig_interpreter(state, env_inst)
        finally:
            kengine._commit_unit = orig_commit

        if is_rescue_step:
            money_post = state[0].observation.farms[0]["money"]
            shed_wheat_post = state[0].observation.private.shed.get("WHEAT", 0)

            # Flawed metrics (the ones M0-K script recorded)
            flawed_wheat_sold = shed_wheat_pre - shed_wheat_post
            flawed_cash_delta = money_post - money_pre

            # Authoritative rescue execution:
            wheat_sales = [u for u in committed_units_p0 if u["op"] == "SELL" and u["item"] == "WHEAT"]
            exact_wheat_units = len(wheat_sales)
            exact_wheat_revenue = sum(u["price"] for u in wheat_sales)
            rescue_req = mkt0[rescue_order_idx][2] if rescue_order_idx is not None else 0

            turn_diagnostics.append({
                "day": day,
                "hour": hour,
                "projected_load": proj_load,
                "shed_wheat_pre": shed_wheat_pre,
                "shed_wheat_post": shed_wheat_post,
                "rescue_order_emitted": (rescue_order_idx is not None),
                "rescue_order_requested": rescue_req,
                "flawed_step_wheat_sold": flawed_wheat_sold,
                "flawed_step_cash_delta": flawed_cash_delta,
                "authoritative_turn_wheat_units_sold": exact_wheat_units,
                "authoritative_turn_wheat_revenue": exact_wheat_revenue,
                "all_committed_units_on_turn": committed_units_p0,
            })
        return ret_state

    env.interpreter = instrumented_interpreter
    try:
        while not env.done:
            obs = env.state[0].observation
            act = agent(obs, env.configuration)
            try:
                opp_act = opp_agent(env.state[1].observation, env.configuration)
            except TypeError:
                opp_act = opp_agent(env.state[1].observation)
            env.step([act, opp_act])
    finally:
        env.interpreter = orig_interpreter

    final_cash = float(env.state[0].observation.farms[0]["money"])
    return {
        "seed": seed,
        "final_cash": final_cash,
        "rescue_steps": turn_diagnostics,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-K-R1 Evidence Reconciliation")
    args = parser.parse_args()

    print("=== Phase M0-K-R1: Evidence Reconciliation & Telemetry Audit ===")

    # 1. Audit raw file immutability
    print("\n1. Verifying raw archive SHA256 immutability...")
    immutability = audit_raw_immutability()
    print(f"Status: {immutability['status']} ({immutability['verified_count']} files verified)")
    if immutability["mismatches"]:
        print("WARNING: Mismatches detected:", immutability["mismatches"])

    # 2. Recompute authoritative statistics
    print("\n2. Recomputing authoritative statistics from raw paired_results.json...")
    recomputed = recompute_confirmation_statistics()

    print("\n--- Desired vs Recomputed Statistics ---")
    c0 = recomputed["c0"]
    c2 = recomputed["c2"]
    d = recomputed["delta"]
    cl = recomputed["clustered"]
    st = recomputed["storage"]

    print(f"C0 Cash:    Mean=${c0['mean']:,.2f}, Std=${c0['std']:,.2f}, Median=${c0['median']:,.2f}")
    print(f"C2 Cash:    Mean=${c2['mean']:,.2f}, Std=${c2['std']:,.2f}, Median=${c2['median']:,.2f}")
    print(f"Delta Cash: Mean=${d['mean']:+,.2f}, Std=${d['std']:,.2f}, Median=${d['median']:+,.2f}")
    print(f"Record:     {recomputed['record']['wins']}W / {recomputed['record']['ties']}T / {recomputed['record']['losses']}L ({recomputed['record']['win_rate_pct']:.1f}%)")
    print(f"95% CI:     [${cl['ci_95'][0]:+,.2f}, ${cl['ci_95'][1]:+,.2f}] (df={cl['df']}, SE=${cl['se_clustered']:.2f})")
    print(f"Clusters:   {cl['positive_clusters']} / {cl['k_clusters']} positive")
    print(f"Discards:   C0={st['c0_discarded_units']} -> C2={st['c2_discarded_units']} (-{st['discard_reduction_pct']:.2f}%)")
    print(f"Spot Preserved: ${st['spot_value_preserved']:,.2f} (C0 Lost: ${st['c0_spot_value_lost']:,.2f}, C2 Lost: ${st['c2_spot_value_lost']:,.2f})")

    # 3. Flawed telemetry breakdown
    fl = recomputed["flawed_historical_telemetry"]
    print("\n--- Flawed Historical Telemetry Diagnosis ---")
    print(f"Archived rescue_units_sold: {fl['raw_sum_rescue_units']}")
    print(f"Archived rescue_revenue:    ${fl['raw_sum_rescue_revenue']:,.2f}")
    print(f"Reason for negative units:  {fl['flaw_explanation_units']}")
    print(f"Reason for flawed revenue:  {fl['flaw_explanation_revenue']}")
    print(f"Reason for cap blocked:     {fl['flaw_explanation_cap_blocked']}")

    # 4. Run R1 validation replay on dev seed 97013
    print("\n3. Running R1 validation replay on consumed development seed 97013...")
    val_replay = run_r1_validation_replay(seed=97013)
    print(f"Match completed successfully. Final Cash: ${val_replay['final_cash']:,.2f}")
    print(f"Total rescue steps observed: {len(val_replay['rescue_steps'])}")
    for step in val_replay["rescue_steps"]:
        print(
            f"Day {step['day']:02d} H{step['hour']:02d} | ProjLoad: {step['projected_load']} | "
            f"Req: {step['rescue_order_requested']} | "
            f"Flawed Units: {step['flawed_step_wheat_sold']} | "
            f"Exact Units Sold: {step['authoritative_turn_wheat_units_sold']} | "
            f"Exact Wheat Rev: ${step['authoritative_turn_wheat_revenue']:,.2f} | "
            f"Flawed Step Cash: ${step['flawed_step_cash_delta']:,.2f}"
        )

    # 5. Save reconciliation report to R1 validation directory
    r1_summary = {
        "immutability_audit": immutability,
        "recomputed_statistics": recomputed,
        "validation_replay_seed_97013": val_replay,
        "metric_comparison_table": {
            "candidate_frozen_sha": {
                "reported_in_m0_k": "0a23f938b1d9bf5443a5ee9048a127ee7dcb46a9",
                "corrected_actual_git": "0a23f93eaad59dad71723ff989d44fb9e132ca76",
                "status": "CORRECTED",
            },
            "c0_median_cash": {
                "reported_in_m0_k": 103450.0,
                "corrected_actual_git": 102212.0,
                "status": "CORRECTED",
            },
            "c2_median_cash": {
                "reported_in_m0_k": 108126.5,
                "corrected_actual_git": 107423.5,
                "status": "CORRECTED",
            },
            "paired_median_gain": {
                "reported_in_m0_k": 5361.0,
                "corrected_actual_git": 5361.0,
                "status": "VERIFIED_ACCURATE",
            },
            "c0_std_cash": {
                "reported_in_m0_k": 24089.47,
                "corrected_actual_git": 8958.89,
                "status": "CORRECTED",
            },
            "c2_std_cash": {
                "reported_in_m0_k": 24196.48,
                "corrected_actual_git": 8668.26,
                "status": "CORRECTED",
            },
            "spot_value_preserved": {
                "reported_in_m0_k": 832052.0,
                "archived_storage_comparison": 1398785.0,
                "status": "CORRECTED_TO_ARCHIVE",
            },
            "c0_spot_value_lost": {
                "reported_in_m0_k": 888272.0,
                "archived_storage_comparison": 1480845.0,
                "status": "CORRECTED_TO_ARCHIVE",
            },
            "c2_spot_value_lost": {
                "reported_in_m0_k": 56220.0,
                "archived_storage_comparison": 82060.0,
                "status": "CORRECTED_TO_ARCHIVE",
            },
            "rescue_units_sold": {
                "reported_in_m0_k": 13024,
                "archived_raw": -13024,
                "status": "LABELED_UNVERIFIED_AND_FLAWED",
            },
            "rescue_revenue": {
                "reported_in_m0_k": 941919.0,
                "archived_raw": 941919.0,
                "status": "LABELED_UNVERIFIED_STEP_CASH_DELTA",
            },
            "orders_blocked_by_10_cap": {
                "reported_in_m0_k": 0,
                "archived_market_safety": 1067,
                "status": "CORRECTED_METHODOLOGY_EXPLAINED",
            },
        },
    }

    out_file = os.path.join(R1_VAL_DIR, "reconciliation_summary.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(r1_summary, f, indent=2)

    print(f"\nR1 Evidence Reconciliation complete. Deliverables written to: {out_file}")


if __name__ == "__main__":
    main()
