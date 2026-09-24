"""Forensic Analysis: Service Certificate vs. Real Production Baseline Execution.

Compares turn-by-turn predictions of core_only_cert_feasible against the actual
downstream ground-truth execution of the production baseline:
- Tracks plant watering (missed watering, decay, death)
- Tracks animal feeding (fed status by H23, starvation, health)
- Tracks crop harvest latency (harvested on time vs decayed)
- Tracks worker action utilization (chores vs idle passes vs travel)
- Evaluates TP, FP, TN, FN classifications for core certificate failures.
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")

clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
sys.path = [_REPO_ROOT, _AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

from kaggle_environments import make
import config
from main import agent, reset_agent_state, get_last_shadow_result
from observation_parser import parse_observation
from strategy.whole_farm_planner import get_whole_farm_planner
from simulations.experiments.agent_zoo import get_agent


def audit_seed_execution(seed: int, opponent_name: str = "pass", seat: int = 0) -> Dict[str, Any]:
    """Run an episode instrumented to capture ground-truth core outcomes vs certificate predictions."""
    config.set_sw_forward_architecture_mode("SHADOW")
    reset_agent_state()
    opp_agent = get_agent(opponent_name)

    # Step telemetry collection
    step_telemetry: List[Dict[str, Any]] = []

    # Ground truth tracking across steps
    # We will record observations and actions for each step
    episode_snapshots: List[Dict[str, Any]] = []

    def tracking_wrapper(obs, conf=None):
        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)

        # Authoritative agent call
        act = agent(obs, conf)
        sr = get_last_shadow_result()

        # Parse observation for ground truth tracking
        parsed = parse_observation(obs)
        farm = parsed["farm"] if parsed else None

        # Capture farm state at this hour
        unwatered_crops = 0
        unfed_animals = 0
        total_crops = 0
        total_animals = 0
        ripe_crops = 0
        decaying_crops = 0

        if farm:
            for t in farm.iter_tiles():
                # Count animals
                is_anim = getattr(t, "is_animal", False) or getattr(t, "kind", None) in config.ANIMALS
                if is_anim:
                    total_animals += 1
                    if not getattr(t, "fed_today", False):
                        unfed_animals += 1

                # Count plants
                if getattr(t, "is_plant", False):
                    total_crops += 1
                    if not getattr(t, "watered_today", False):
                        unwatered_crops += 1
                    if getattr(t, "yield_units", 0) > 0:
                        ripe_crops += 1
                    if int(getattr(t, "consecutive_unwatered", 0) or 0) >= 1:
                        decaying_crops += 1

        rec = {
            "step": step,
            "day": day,
            "hour": hour,
            "core_feasible": bool(sr.decision.core_only_cert_feasible) if sr else True,
            "comb_feasible": bool(sr.decision.combined_cert_feasible) if sr else True,
            "lc_feasible": bool(sr.decision.lifecycle_workload_feasible) if sr else True,
            "status": str(sr.decision.sw_recommendation_status) if sr else "UNKNOWN",
            "binding_res": str(sr.certificate.binding_resource) if sr and sr.certificate else "NONE",
            "binding_day": int(getattr(sr.certificate, "binding_day", day)) if sr and sr.certificate else day,
            "binding_hour": int(getattr(sr.certificate, "binding_hour", hour)) if sr and sr.certificate else hour,
            "min_slack": int(getattr(sr.certificate, "minimum_slack", 0)) if sr and sr.certificate else 0,
            "unwatered_crops": unwatered_crops,
            "unfed_animals": unfed_animals,
            "total_crops": total_crops,
            "total_animals": total_animals,
            "ripe_crops": ripe_crops,
            "decaying_crops": decaying_crops,
            "active_workers": 1 + len(getattr(farm, "hands", [])) if farm else 1,
            "farmer_action": act.get("farmer", ["PASS"]),
            "hands_actions": act.get("hands", []),
            "market_orders": act.get("market", []),
        }
        step_telemetry.append(rec)
        return act

    p0 = tracking_wrapper if seat == 0 else opp_agent
    p1 = tracking_wrapper if seat == 1 else opp_agent

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([p0, p1])

    # End-of-day ground truth evaluation
    # A true day-level failure occurs if at Hour 23 (midnight):
    # - Any animal was NOT fed (unfed_animals > 0 at hour 23)
    # - Any crop that needed survival water was unwatered (decaying crop died)
    # - Any ripe crop decayed to 0
    day_evaluations: List[Dict[str, Any]] = []
    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for r in step_telemetry:
        d = r["day"]
        if d not in by_day:
            by_day[d] = []
        by_day[d].append(r)

    for d in range(30):
        day_steps = by_day.get(d, [])
        if not day_steps:
            continue
        h23 = day_steps[-1]  # Last hour of the day

        # Midnight status
        final_unfed = h23["unfed_animals"]
        final_unwatered = h23["unwatered_crops"]
        decaying = h23["decaying_crops"]

        # Action efficiency
        total_unit_actions = sum(1 + len(s["hands_actions"]) for s in day_steps)
        total_idle_passes = 0
        for s in day_steps:
            if s["farmer_action"] == ["PASS"]:
                total_idle_passes += 1
            for ha in s["hands_actions"]:
                if ha == ["PASS"]:
                    total_idle_passes += 1

        day_eval = {
            "day": d,
            "final_unfed_animals": final_unfed,
            "final_unwatered_crops": final_unwatered,
            "decaying_crops_at_h23": decaying,
            "total_unit_actions": total_unit_actions,
            "total_idle_passes": total_idle_passes,
            "idle_fraction": round(total_idle_passes / max(1, total_unit_actions), 3),
            "had_starvation": (final_unfed > 0),
            "had_crop_loss": (decaying > 0 and final_unwatered > 0),
        }
        day_evaluations.append(day_eval)

    # Correlate turn-level core certificate prediction with reality over rolling 24h-72h
    # For every turn where core_feasible == False:
    # Check whether within the next 24-72 hours, an actual failure occurred
    tp_count = 0
    fp_count = 0
    tn_count = 0
    fn_count = 0

    forensic_turns = []
    for r in step_telemetry:
        st = r["step"]
        d = r["day"]
        h = r["hour"]
        pred_infeasible = not r["core_feasible"]

        # Actual outcome over [day, min(29, day + 2)]
        horizon_days = [day_evaluations[x] for x in range(d, min(30, d + 3)) if x < len(day_evaluations)]
        real_failure = any(hd["had_starvation"] or hd["had_crop_loss"] for hd in horizon_days)

        if pred_infeasible and real_failure:
            cls = "TP"
            tp_count += 1
        elif pred_infeasible and not real_failure:
            cls = "FP"
            fp_count += 1
        elif not pred_infeasible and not real_failure:
            cls = "TN"
            tn_count += 1
        else:
            cls = "FN"
            fn_count += 1

        if st % 24 == 0 or (r["min_slack"] < -10) or (r["min_slack"] in (-1, -2, -3)):
            forensic_turns.append({
                "step": st,
                "day": d,
                "hour": h,
                "pred_infeasible": pred_infeasible,
                "min_slack": r["min_slack"],
                "binding_hour": r["binding_hour"],
                "binding_res": r["binding_res"],
                "real_failure": real_failure,
                "classification": cls,
                "idle_fraction_today": day_evaluations[d]["idle_fraction"] if d < len(day_evaluations) else 0.0,
            })

    return {
        "seed": seed,
        "opponent": opponent_name,
        "seat": seat,
        "tp": tp_count,
        "fp": fp_count,
        "tn": tn_count,
        "fn": fn_count,
        "day_evaluations": day_evaluations,
        "sample_turns": forensic_turns,
        "final_cash": env.steps[-1][seat]["reward"] or 0.0,
    }


def main():
    print("=" * 80)
    print("GATE 1 FORENSIC CALIBRATION PASS: CERTIFICATE VS. REALITY AUDIT")
    print("=" * 80)

    # Run audit across 5 representative seeds from the Gate 1 panel
    test_seeds = [96501, 96503, 96505, 96507, 96509]
    all_audits = []

    total_tp = 0
    total_fp = 0
    total_tn = 0
    total_fn = 0

    for s in test_seeds:
        t0 = time.perf_counter()
        res = audit_seed_execution(s, opponent_name="pass", seat=0)
        dur = round(time.perf_counter() - t0, 1)
        all_audits.append(res)
        total_tp += res["tp"]
        total_fp += res["fp"]
        total_tn += res["tn"]
        total_fn += res["fn"]
        print(f"Seed {s}: TP={res['tp']}, FP={res['fp']}, TN={res['tn']}, FN={res['fn']} | Cash=${res['final_cash']:,.1f} | T={dur}s")

    total_pred_infeasible = total_tp + total_fp
    fp_rate = (total_fp / max(1, total_pred_infeasible)) * 100.0
    precision = (total_tp / max(1, total_tp + total_fp)) * 100.0
    recall = (total_tp / max(1, total_tp + total_fn)) * 100.0

    print("-" * 80)
    print("AGGREGATE FORENSIC CLASSIFICATION:")
    print(f"Total Evaluated Turns: {total_tp + total_fp + total_tn + total_fn}")
    print(f"True Positives  (TP - Real failure correctly predicted): {total_tp}")
    print(f"False Positives (FP - Infeasible predicted, but baseline succeeded): {total_fp}")
    print(f"True Negatives  (TN - Feasible predicted, and baseline succeeded): {total_tn}")
    print(f"False Negatives (FN - Feasible predicted, but baseline failed): {total_fn}")
    print(f"False Positive Rate of Infeasible Predictions: {fp_rate:.2f}%")
    print(f"Precision: {precision:.2f}%")
    print(f"Recall: {recall:.2f}%")
    print("-" * 80)

    # Inspect day-level idle fraction and actual failures
    print("\nSAMPLE DAY-LEVEL AUDIT (Seed 96501):")
    for de in all_audits[0]["day_evaluations"][:12]:
        d = de["day"]
        unfed = de["final_unfed_animals"]
        unwatered = de["final_unwatered_crops"]
        idle = de["idle_fraction"]
        acts = de["total_unit_actions"]
        print(f"  Day {d:02d}: total_actions={acts:3d} | idle_rate={idle*100:4.1f}% | unfed_animals={unfed} | unwatered_crops={unwatered}")

    # Inspect sample turns with negative slack
    print("\nSAMPLE TURNS CLASSIFICATION (Seed 96501):")
    for st in all_audits[0]["sample_turns"][:15]:
        print(f"  Step {st['step']:3d} (D{st['day']} H{st['hour']:02d}): slack={st['min_slack']:3d} at H{st['binding_hour']:02d} | class={st['classification']} | day_idle={st['idle_fraction_today']*100:4.1f}%")


if __name__ == "__main__":
    main()
