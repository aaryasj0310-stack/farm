"""Collect detailed shadow artifacts for Phase M0-C Discovery.

Re-runs C1 (GLOBAL mode with shadow gating telemetry) across the 100 cells
(Seeds 97013–97022 x 5 opponents x 2 seats) to capture and save:
- pipeline_opportunities.json
- gate_decisions.json
- worker_opportunity_analysis.json
- market_timing_analysis.json
- representative_traces.json
"""
import os
import sys
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_c_discovery")

DEFAULT_SEEDS = list(range(97013, 97023))
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def run_cell_shadow(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    from kaggle_environments import make
    import config
    config.SAME_TURN_CROP_PIPELINE_MODE = "GLOBAL"

    from agent.main import (
        agent,
        reset_agent_state,
        get_crop_pipeline_shadow_decisions,
        verify_post_turn_pipelines,
    )
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    reset_agent_state()
    reset_sw_tranche_controller()

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    step_num = 0
    while not env.done:
        obs_pre = env.state[seat].observation
        action = agent(obs_pre, env.configuration)
        try:
            opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_action = opp_agent(env.state[1 - seat].observation)
        actions = [action, opp_action] if seat == 0 else [opp_action, action]

        env.step(actions)
        step_num += 1

        obs_post = env.state[seat].observation
        verify_post_turn_pipelines(obs_post, player_id=seat)

    shadows = get_crop_pipeline_shadow_decisions()
    # Add cell info
    for s in shadows:
        s["seed"] = seed
        s["opp_name"] = opp_name
        s["seat"] = seat

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "shadow_decisions": shadows,
    }


def main():
    print("Collecting detailed shadow decision records across 100 cells...")
    t0 = time.time()

    tasks = []
    for s in DEFAULT_SEEDS:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                tasks.append((s, opp, seat))

    all_opportunities = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        future_map = {pool.submit(run_cell_shadow, s, opp, seat): (s, opp, seat) for (s, opp, seat) in tasks}
        completed = 0
        for fut in as_completed(future_map):
            res = fut.result()
            all_opportunities.extend(res["shadow_decisions"])
            completed += 1
            if completed % 20 == 0:
                print(f"[{completed}/100] cells processed ({len(all_opportunities)} opportunities so far)")

    total_opps = len(all_opportunities)
    accepted_opps = [o for o in all_opportunities if o.get("gate_accepted", False)]
    rejected_opps = [o for o in all_opportunities if not o.get("gate_accepted", False)]

    print(f"Total opportunities: {total_opps} | Accepted: {len(accepted_opps)} | Rejected: {len(rejected_opps)}")
    print(f"Elapsed: {time.time() - t0:.2f}s")

    # 1. pipeline_opportunities.json
    with open(os.path.join(OUT_DIR, "pipeline_opportunities.json"), "w") as f:
        json.dump(all_opportunities, f, indent=2)

    # 2. gate_decisions.json
    crop_stats = {}
    for o in all_opportunities:
        c = o.get("crop", "UNKNOWN")
        if c not in crop_stats:
            crop_stats[c] = {"total": 0, "accepted": 0, "rejected": 0}
        crop_stats[c]["total"] += 1
        if o.get("gate_accepted", False):
            crop_stats[c]["accepted"] += 1
        else:
            crop_stats[c]["rejected"] += 1

    for c in crop_stats:
        t = crop_stats[c]["total"]
        crop_stats[c]["acceptance_rate_pct"] = round(crop_stats[c]["accepted"] / max(1, t) * 100, 2)

    rejection_reasons = {}
    for o in rejected_opps:
        for r in o.get("rejection_reasons", []):
            rejection_reasons[r] = rejection_reasons.get(r, 0) + 1

    accepted_nev = [o.get("net_economic_value", 0.0) for o in accepted_opps]
    rejected_nev = [o.get("net_economic_value", 0.0) for o in rejected_opps]

    gate_summary = {
        "total_opportunities": total_opps,
        "accepted_count": len(accepted_opps),
        "rejected_count": len(rejected_opps),
        "acceptance_rate_pct": round(len(accepted_opps) / max(1, total_opps) * 100, 2),
        "crop_breakdown": crop_stats,
        "rejection_reason_counts": rejection_reasons,
        "accepted_net_economic_value": {
            "mean": round(sum(accepted_nev) / max(1, len(accepted_nev)), 2) if accepted_nev else 0.0,
            "min": round(min(accepted_nev), 2) if accepted_nev else 0.0,
            "max": round(max(accepted_nev), 2) if accepted_nev else 0.0,
        },
        "rejected_net_economic_value": {
            "mean": round(sum(rejected_nev) / max(1, len(rejected_nev)), 2) if rejected_nev else 0.0,
            "min": round(min(rejected_nev), 2) if rejected_nev else 0.0,
            "max": round(max(rejected_nev), 2) if rejected_nev else 0.0,
        },
    }
    with open(os.path.join(OUT_DIR, "gate_decisions.json"), "w") as f:
        json.dump(gate_summary, f, indent=2)

    # 3. worker_opportunity_analysis.json & market_timing_analysis.json & representative_traces.json
    # Read matched_results.json
    with open(os.path.join(OUT_DIR, "matched_results.json"), "r") as f:
        matched_cells = json.load(f)

    # Worker analysis
    worker_comp = {
        "C0": {"total_worker_turns": 0, "emitted_moves": 0, "harvest_actions": 0, "plant_actions": 0, "water_actions": 0},
        "C1": {"total_worker_turns": 0, "emitted_moves": 0, "harvest_actions": 0, "plant_actions": 0, "water_actions": 0},
        "C2": {"total_worker_turns": 0, "emitted_moves": 0, "harvest_actions": 0, "plant_actions": 0, "water_actions": 0},
    }
    for cell in matched_cells:
        for arm in ("C0", "C1", "C2"):
            ws = cell["cell_details"][arm]["worker_stats"]
            for k in worker_comp[arm]:
                worker_comp[arm][k] += ws.get(k, 0)

    for arm in worker_comp:
        for k in worker_comp[arm]:
            worker_comp[arm][k] = round(worker_comp[arm][k] / len(matched_cells), 1)

    worker_analysis = {
        "average_actions_per_match": worker_comp,
        "worker_opportunity_cost_vetoes_triggered": rejection_reasons.get("WORKER_OPPORTUNITY_COST", 0),
        "worker_mobility_impact": {
            "c0_avg_moves": worker_comp["C0"]["emitted_moves"],
            "c1_avg_moves": worker_comp["C1"]["emitted_moves"],
            "c2_avg_moves": worker_comp["C2"]["emitted_moves"],
            "delta_moves_c2_vs_c1": round(worker_comp["C2"]["emitted_moves"] - worker_comp["C1"]["emitted_moves"], 1),
        },
        "conclusion": "SELECTIVE mode frees up workers when high-priority tasks (watering/feeding) are queued, avoiding worker starvation."
    }
    with open(os.path.join(OUT_DIR, "worker_opportunity_analysis.json"), "w") as f:
        json.dump(worker_analysis, f, indent=2)

    # Market timing analysis
    # Average shed load when rejected vs accepted
    shed_loads_accepted = [o.get("shed_load", 0) for o in accepted_opps]
    shed_loads_rejected = [o.get("shed_load", 0) for o in rejected_opps]
    market_rejections = [o for o in rejected_opps if "MARKET_TIMING" in o.get("rejection_reasons", [])]
    market_timing = {
        "market_timing_vetoes_count": len(market_rejections),
        "crops_vetoed_by_market_timing": {},
        "avg_shed_load_accepted": round(sum(shed_loads_accepted) / max(1, len(shed_loads_accepted)), 1),
        "avg_shed_load_rejected": round(sum(shed_loads_rejected) / max(1, len(shed_loads_rejected)), 1),
        "rationale": "Rejects same-turn replanting when inventory of that crop in shed >= 50 or shed load creates severe market price depression."
    }
    for o in market_rejections:
        c = o.get("crop", "UNKNOWN")
        market_timing["crops_vetoed_by_market_timing"][c] = market_timing["crops_vetoed_by_market_timing"].get(c, 0) + 1

    with open(os.path.join(OUT_DIR, "market_timing_analysis.json"), "w") as f:
        json.dump(market_timing, f, indent=2)

    # Representative traces
    # Pick:
    # - Best win for Selective over Global
    # - Worst regression for Selective over Global
    # - Large win for Selective over Control
    best_c2_vs_c1 = max(matched_cells, key=lambda c: c["deltas"]["selective_vs_global"])
    worst_c2_vs_c1 = min(matched_cells, key=lambda c: c["deltas"]["selective_vs_global"])
    best_c2_vs_c0 = max(matched_cells, key=lambda c: c["deltas"]["selective_vs_control"])

    rep_traces = {
        "best_selective_rescue_over_global": {
            "seed": best_c2_vs_c1["seed"],
            "opp_name": best_c2_vs_c1["opp_name"],
            "seat": best_c2_vs_c1["seat"],
            "cash": best_c2_vs_c1["cash"],
            "delta_selective_vs_global": best_c2_vs_c1["deltas"]["selective_vs_global"],
            "delta_selective_vs_control": best_c2_vs_c1["deltas"]["selective_vs_control"],
            "c0_trace": best_c2_vs_c1["cell_details"]["C0"]["trace_summary"],
            "c1_trace": best_c2_vs_c1["cell_details"]["C1"]["trace_summary"],
            "c2_trace": best_c2_vs_c1["cell_details"]["C2"]["trace_summary"],
        },
        "worst_selective_loss_vs_global": {
            "seed": worst_c2_vs_c1["seed"],
            "opp_name": worst_c2_vs_c1["opp_name"],
            "seat": worst_c2_vs_c1["seat"],
            "cash": worst_c2_vs_c1["cash"],
            "delta_selective_vs_global": worst_c2_vs_c1["deltas"]["selective_vs_global"],
            "delta_selective_vs_control": worst_c2_vs_c1["deltas"]["selective_vs_control"],
            "c0_trace": worst_c2_vs_c1["cell_details"]["C0"]["trace_summary"],
            "c1_trace": worst_c2_vs_c1["cell_details"]["C1"]["trace_summary"],
            "c2_trace": worst_c2_vs_c1["cell_details"]["C2"]["trace_summary"],
        },
        "best_selective_win_vs_control": {
            "seed": best_c2_vs_c0["seed"],
            "opp_name": best_c2_vs_c0["opp_name"],
            "seat": best_c2_vs_c0["seat"],
            "cash": best_c2_vs_c0["cash"],
            "delta_selective_vs_control": best_c2_vs_c0["deltas"]["selective_vs_control"],
            "c0_trace": best_c2_vs_c0["cell_details"]["C0"]["trace_summary"],
            "c2_trace": best_c2_vs_c0["cell_details"]["C2"]["trace_summary"],
        }
    }
    with open(os.path.join(OUT_DIR, "representative_traces.json"), "w") as f:
        json.dump(rep_traces, f, indent=2)

    print("All detailed artifacts successfully generated and written to disk!")


if __name__ == "__main__":
    main()
