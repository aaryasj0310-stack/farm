"""Rigorous 30-Seed Paired Tournament: Control (Arm A) vs Dynamic Feed-Required Wheat Floor (Treatment)

Authoritative Invariants Tested:
1. Control (Arm A): Unchanged production baseline (Static 8/20/30 Wheat target, NW+NE only, SW/SE hard-blocked).
2. Treatment (Arm A-DynWheat): Dynamic feed-required Wheat floor (calculates minimum wheat needed to cover
   authoritative feed buffer; all other tiles compete in _crop_score() portfolio economics).
3. Day-0 8-Wheat springboard preserved in both.
4. Livestock targets, DynamicHerdPlan, feed safety, Day-12 cutoff, physical structure requirement,
   treasury reserve, market wheat buying, scheduler, and all deadlines (Melon D17, Strawberry D13) 100% preserved.

Full Telemetry:
- Final Score & Statistical Tests (Bootstrap 95% CI, Paired t-test, Wilcoxon, Win/Loss)
- Wheat Produced, Consumed as Feed, Sold, Bought from Market, Buy Cost
- Feed-shortage incidents, Max consecutive unfed, Animal starvation deaths
- Herd size EOD, Animal product output & revenue
- Crop mix planted & harvested (Wheat, Carrot, Tomato, Strawberry, Melon)
- Productive actions, Movement actions, Idle passes, Move ratio
"""

import os
import sys
import time
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
from scipy import stats

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)


def compute_bootstrap_ci(
    data: List[float],
    num_resamples: int = 10000,
    ci: float = 0.95,
    seed: int = 42
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
    arm = payload["arm"]
    seed = payload["seed"]
    opponent = payload.get("opponent", "random")

    # Clean module cache for fresh match isolation
    to_delete = [k for k in list(sys.modules.keys()) if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    from observation_parser import parse_observation
    import execution.task_scheduler as task_scheduler

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    task_scheduler.reset_worker_locality()

    # Configure Arm: NW+NE enabled, SW+SE hard-blocked for both arms
    config.set_sw_experiment_arm("ArmA")

    if arm == "ArmA-DynWheat":
        config.set_dynamic_feed_wheat_floor_enabled(True)
    else:
        config.set_dynamic_feed_wheat_floor_enabled(False)

    # Telemetry Tracking
    crop_planted = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}
    crop_harvested = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}

    wheat_produced = 0
    wheat_consumed_feed = 0
    wheat_sold = 0
    wheat_bought = 0
    wheat_buy_cost = 0.0

    feed_shortage_incidents = 0
    max_consecutive_unfed = 0
    starvation_deaths = 0

    animal_product_units = {"MILK": 0, "WOOL": 0, "FEATHER": 0}
    animal_product_revenue = 0.0

    total_productive_actions = 0
    total_movement_actions = 0
    total_idle_passes = 0
    total_actions_available = 0

    def tracking_agent(obs, configuration=None):
        nonlocal wheat_produced, wheat_consumed_feed, wheat_sold, wheat_bought, wheat_buy_cost
        nonlocal feed_shortage_incidents, max_consecutive_unfed, starvation_deaths
        nonlocal animal_product_revenue
        nonlocal total_productive_actions, total_movement_actions, total_idle_passes, total_actions_available

        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)

        parsed = parse_observation(obs)
        farm = parsed["farm"] if parsed else None

        # Check animal hunger state at current hour
        if farm:
            for t in farm.iter_tiles():
                if getattr(t, "is_animal", False):
                    consec = getattr(t, "consecutive_unfed", 0)
                    if consec > max_consecutive_unfed:
                        max_consecutive_unfed = consec
                    if hour == 23 and consec > 0:
                        feed_shortage_incidents += 1
                    if consec >= 3:
                        starvation_deaths += 1

        # Call agent
        action = agent_module.agent(obs, configuration)
        if farm is None:
            return action

        all_units = [farm.farmer] + getattr(farm, "hands", [])
        total_actions_available += len(all_units)

        farmer_act = action.get("farmer", ["PASS"])
        hands_act = action.get("hands", [])
        all_actions = [farmer_act] + hands_act

        for u_idx, act in enumerate(all_actions):
            if not act:
                act = ["PASS"]
            op = act[0]
            upos = all_units[u_idx] if u_idx < len(all_units) else (4, 4)

            if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                total_movement_actions += 1
            elif op == "PASS":
                total_idle_passes += 1
            else:
                total_productive_actions += 1

                if op == "PLANT":
                    c_name = act[1] if len(act) > 1 else ""
                    if c_name in crop_planted:
                        crop_planted[c_name] += 1
                elif op == "HARVEST":
                    tile = farm.tile_at(upos)
                    if tile:
                        if getattr(tile, "is_plant", False) or getattr(tile, "crop", None):
                            c_name = getattr(tile, "crop", "")
                            units = getattr(tile, "yield_units", 0)
                            if c_name in crop_harvested:
                                crop_harvested[c_name] += units
                            if c_name == "WHEAT":
                                wheat_produced += units
                        elif getattr(tile, "is_animal", False) or getattr(tile, "animal", None):
                            a_name = getattr(tile, "animal", "")
                            prod_item = config.ANIMALS.get(a_name, {}).get("product", "")
                            units = getattr(tile, "yield_units", 0)
                            if prod_item in animal_product_units:
                                animal_product_units[prod_item] += units
                            base_p = config.MARKET_PARAMS.get(prod_item, {}).get("base", 0)
                            animal_product_revenue += (units * base_p)
                elif op == "FEED":
                    wheat_consumed_feed += 1

        # Track market actions
        market_orders = action.get("market", [])
        for order in market_orders:
            if not order:
                continue
            otype = order[0]
            if otype == "BUY_PRODUCT":
                item = order[1] if len(order) > 1 else ""
                qty = int(order[2]) if len(order) > 2 else 0
                if item == "WHEAT":
                    wheat_bought += qty
                    # Estimate cost from current market quote or base
                    p = getattr(farm, "market", {}).get("WHEAT", {}).get("price", 25.0) if hasattr(farm, "market") else 25.0
                    wheat_buy_cost += qty * p
            elif otype == "SELL":
                item = order[1] if len(order) > 1 else ""
                qty = int(order[2]) if len(order) > 2 else 0
                if item == "WHEAT":
                    wheat_sold += qty

        return action

    # Run match
    env = make("kaggriculture", configuration={"randomSeed": seed}, debug=True)
    steps = env.run([tracking_agent, opponent])
    final_score = steps[-1][0]["reward"] or 0.0

    # Final farm audit at Day 29
    final_obs = parse_observation(steps[-1][0]["observation"])
    end_farm = final_obs["farm"] if final_obs else None
    herd_size_eod = 0
    animals_by_species = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    if end_farm:
        for t in end_farm.iter_tiles():
            if getattr(t, "is_animal", False):
                herd_size_eod += 1
                sp = getattr(t, "animal", "")
                if sp in animals_by_species:
                    animals_by_species[sp] += 1

    move_ratio = total_movement_actions / max(1, total_productive_actions)

    return {
        "arm": arm,
        "seed": seed,
        "final_score": float(final_score),
        "productive_actions": total_productive_actions,
        "movement_actions": total_movement_actions,
        "idle_passes": total_idle_passes,
        "move_ratio": float(move_ratio),
        "total_actions_available": total_actions_available,
        "idle_rate": total_idle_passes / max(1, total_actions_available),
        # Crop metrics
        "crop_planted": crop_planted,
        "crop_harvested": crop_harvested,
        "wheat_produced": wheat_produced,
        "wheat_consumed_feed": wheat_consumed_feed,
        "wheat_sold": wheat_sold,
        "wheat_bought": wheat_bought,
        "wheat_buy_cost": float(wheat_buy_cost),
        # Animal metrics
        "feed_shortage_incidents": feed_shortage_incidents,
        "max_consecutive_unfed": max_consecutive_unfed,
        "starvation_deaths": starvation_deaths,
        "herd_size_eod": herd_size_eod,
        "animals_by_species": animals_by_species,
        "animal_product_units": animal_product_units,
        "animal_product_revenue": float(animal_product_revenue),
    }


def analyze_tournament(
    results_by_arm: Dict[str, List[Dict[str, Any]]],
    control_arm: str = "ArmA",
    treatment_arm: str = "ArmA-DynWheat"
) -> Dict[str, Any]:
    ctrl_list = sorted(results_by_arm[control_arm], key=lambda x: x["seed"])
    treat_list = sorted(results_by_arm[treatment_arm], key=lambda x: x["seed"])

    ctrl_map = {r["seed"]: r for r in ctrl_list}
    treat_map = {r["seed"]: r for r in treat_list}

    common_seeds = sorted(set(ctrl_map.keys()) & set(treat_map.keys()))
    n_pairs = len(common_seeds)

    # Score Deltas (Treatment - Control)
    score_deltas = [treat_map[s]["final_score"] - ctrl_map[s]["final_score"] for s in common_seeds]
    prod_deltas = [treat_map[s]["productive_actions"] - ctrl_map[s]["productive_actions"] for s in common_seeds]
    move_deltas = [treat_map[s]["movement_actions"] - ctrl_map[s]["movement_actions"] for s in common_seeds]
    ratio_deltas = [treat_map[s]["move_ratio"] - ctrl_map[s]["move_ratio"] for s in common_seeds]

    # Wheat & Feed Deltas
    wheat_prod_deltas = [treat_map[s]["wheat_produced"] - ctrl_map[s]["wheat_produced"] for s in common_seeds]
    wheat_feed_deltas = [treat_map[s]["wheat_consumed_feed"] - ctrl_map[s]["wheat_consumed_feed"] for s in common_seeds]
    wheat_sold_deltas = [treat_map[s]["wheat_sold"] - ctrl_map[s]["wheat_sold"] for s in common_seeds]
    wheat_bought_deltas = [treat_map[s]["wheat_bought"] - ctrl_map[s]["wheat_bought"] for s in common_seeds]
    wheat_buy_cost_deltas = [treat_map[s]["wheat_buy_cost"] - ctrl_map[s]["wheat_buy_cost"] for s in common_seeds]

    # Statistical tests
    t_stat, p_val = stats.ttest_rel(
        [treat_map[s]["final_score"] for s in common_seeds],
        [ctrl_map[s]["final_score"] for s in common_seeds]
    )
    try:
        w_res = stats.wilcoxon(score_deltas)
        w_pval = float(w_res.pvalue)
    except Exception:
        w_pval = 1.0

    ci_lower, ci_upper = compute_bootstrap_ci(score_deltas, num_resamples=10000, ci=0.95)
    win_count = sum(1 for d in score_deltas if d > 0)
    tie_count = sum(1 for d in score_deltas if d == 0)
    loss_count = sum(1 for d in score_deltas if d < 0)
    win_rate = win_count / max(1, n_pairs - tie_count)

    def mean_attr(r_list, key):
        return float(np.mean([r[key] for r in r_list]))

    def sum_attr(r_list, key):
        return float(np.sum([r[key] for r in r_list]))

    analysis = {
        "n_pairs": n_pairs,
        "control_arm": control_arm,
        "treatment_arm": treatment_arm,
        # Score Contrast
        "score_control_mean": mean_attr(ctrl_list, "final_score"),
        "score_treatment_mean": mean_attr(treat_list, "final_score"),
        "score_delta_mean": float(np.mean(score_deltas)),
        "score_delta_median": float(np.median(score_deltas)),
        "score_delta_trimmed_mean": float(stats.trim_mean(score_deltas, 0.1)),
        "score_delta_std": float(np.std(score_deltas, ddof=1)) if n_pairs > 1 else 0.0,
        "score_delta_ci_95": [ci_lower, ci_upper],
        "win_count": win_count,
        "tie_count": tie_count,
        "loss_count": loss_count,
        "win_rate": float(win_rate),
        "paired_t_stat": float(t_stat),
        "paired_t_pval": float(p_val),
        "wilcoxon_pval": float(w_pval),
        # Action Contrast
        "prod_ops_control_mean": mean_attr(ctrl_list, "productive_actions"),
        "prod_ops_treatment_mean": mean_attr(treat_list, "productive_actions"),
        "prod_ops_delta_mean": float(np.mean(prod_deltas)),
        "move_ratio_control_mean": mean_attr(ctrl_list, "move_ratio"),
        "move_ratio_treatment_mean": mean_attr(treat_list, "move_ratio"),
        "move_ratio_delta_mean": float(np.mean(ratio_deltas)),
        # Wheat & Feed Economics
        "wheat_produced_ctrl_mean": mean_attr(ctrl_list, "wheat_produced"),
        "wheat_produced_treat_mean": mean_attr(treat_list, "wheat_produced"),
        "wheat_consumed_ctrl_mean": mean_attr(ctrl_list, "wheat_consumed_feed"),
        "wheat_consumed_treat_mean": mean_attr(treat_list, "wheat_consumed_feed"),
        "wheat_sold_ctrl_mean": mean_attr(ctrl_list, "wheat_sold"),
        "wheat_sold_treat_mean": mean_attr(treat_list, "wheat_sold"),
        "wheat_bought_ctrl_mean": mean_attr(ctrl_list, "wheat_bought"),
        "wheat_bought_treat_mean": mean_attr(treat_list, "wheat_bought"),
        "wheat_buy_cost_ctrl_mean": mean_attr(ctrl_list, "wheat_buy_cost"),
        "wheat_buy_cost_treat_mean": mean_attr(treat_list, "wheat_buy_cost"),
        # Livestock Safety
        "feed_shortages_ctrl_total": sum_attr(ctrl_list, "feed_shortage_incidents"),
        "feed_shortages_treat_total": sum_attr(treat_list, "feed_shortage_incidents"),
        "starvation_deaths_ctrl_total": sum_attr(ctrl_list, "starvation_deaths"),
        "starvation_deaths_treat_total": sum_attr(treat_list, "starvation_deaths"),
        "max_unfed_ctrl": int(np.max([r["max_consecutive_unfed"] for r in ctrl_list])),
        "max_unfed_treat": int(np.max([r["max_consecutive_unfed"] for r in treat_list])),
        "herd_size_ctrl_mean": mean_attr(ctrl_list, "herd_size_eod"),
        "herd_size_treat_mean": mean_attr(treat_list, "herd_size_eod"),
        "animal_rev_ctrl_mean": mean_attr(ctrl_list, "animal_product_revenue"),
        "animal_rev_treat_mean": mean_attr(treat_list, "animal_product_revenue"),
        # Crop Mix Planted
        "planted_mix_control": {
            c: float(np.mean([r["crop_planted"][c] for r in ctrl_list]))
            for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
        },
        "planted_mix_treatment": {
            c: float(np.mean([r["crop_planted"][c] for r in treat_list]))
            for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
        },
    }
    return analysis


def run_tournament(
    seeds: List[int] = list(range(100, 130)),
    max_workers: int = 4,
    output_path: str = "simulations/experiments/results/wheat_floor_tournament_30seeds.json"
):
    print("================================================================")
    print(f"DYNAMIC FEED-REQUIRED WHEAT FLOOR TOURNAMENT")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Workers: {max_workers}")
    print(f"Arms: Control (Arm A) vs Treatment (Arm A-DynWheat)")
    print("================================================================")

    payloads = []
    for s in seeds:
        for arm in ("ArmA", "ArmA-DynWheat"):
            payloads.append({"arm": arm, "seed": s, "opponent": "random"})

    results_by_arm: Dict[str, List[Dict[str, Any]]] = {"ArmA": [], "ArmA-DynWheat": []}
    start_time = time.time()
    completed = 0
    total = len(payloads)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_match, p): p for p in payloads}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                res = fut.result()
                results_by_arm[res["arm"]].append(res)
                completed += 1
                elapsed = time.time() - start_time
                print(f"[{completed:02d}/{total:02d}] {res['arm']:<15} seed={res['seed']:<3} score=${res['final_score']:>8,.0f} | Wheat Pl={res['crop_planted']['WHEAT']:<2} Har={res['wheat_produced']:<3} Fed={res['wheat_consumed_feed']:<3} | Herd={res['herd_size_eod']} [{elapsed:.1f}s]", flush=True)
            except Exception as e:
                print(f"ERROR on {p['arm']} seed {p['seed']}: {e}", flush=True)
                import traceback
                traceback.print_exc()

    analysis = analyze_tournament(results_by_arm)

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump({
                "analysis": analysis,
                "raw_results": results_by_arm,
            }, f, indent=2)
        print(f"\nSaved tournament results to {output_path}")

    # Display Comprehensive Results Table
    print("\n================================================================")
    print("TOURNAMENT RESULTS & STATISTICAL CONTRAST")
    print("================================================================")
    print(f"Control (Arm A) Mean Score:     ${analysis['score_control_mean']:,.1f}")
    print(f"Treatment (DynWheat) Mean Score: ${analysis['score_treatment_mean']:,.1f}")
    print(f"Mean Score Delta (T - C):       ${analysis['score_delta_mean']:+,.1f}")
    print(f"Median Score Delta:             ${analysis['score_delta_median']:+,.1f}")
    print(f"95% Bootstrap CI:               [${analysis['score_delta_ci_95'][0]:+,.1f}, ${analysis['score_delta_ci_95'][1]:+,.1f}]")
    print(f"Paired t-test:                  t={analysis['paired_t_stat']:.3f}, p={analysis['paired_t_pval']:.4f}")
    print(f"Wilcoxon signed-rank p-value:   p={analysis['wilcoxon_pval']:.4f}")
    print(f"Win / Tie / Loss:               {analysis['win_count']} / {analysis['tie_count']} / {analysis['loss_count']} (Win Rate: {analysis['win_rate']*100:.1f}%)")

    print("\n--- Wheat & Feed Economics (Per Match Averages) ---")
    print(f"Wheat Planted:     Control={analysis['planted_mix_control']['WHEAT']:.1f} vs Treatment={analysis['planted_mix_treatment']['WHEAT']:.1f} (Delta: {analysis['planted_mix_treatment']['WHEAT'] - analysis['planted_mix_control']['WHEAT']:+.1f})")
    print(f"Wheat Produced:    Control={analysis['wheat_produced_ctrl_mean']:.1f} vs Treatment={analysis['wheat_produced_treat_mean']:.1f} (Delta: {analysis['wheat_produced_treat_mean'] - analysis['wheat_produced_ctrl_mean']:+.1f})")
    print(f"Wheat Fed:         Control={analysis['wheat_consumed_ctrl_mean']:.1f} vs Treatment={analysis['wheat_consumed_treat_mean']:.1f} (Delta: {analysis['wheat_consumed_treat_mean'] - analysis['wheat_consumed_ctrl_mean']:+.1f})")
    print(f"Wheat Sold:        Control={analysis['wheat_sold_ctrl_mean']:.1f} vs Treatment={analysis['wheat_sold_treat_mean']:.1f} (Delta: {analysis['wheat_sold_treat_mean'] - analysis['wheat_sold_ctrl_mean']:+.1f})")
    print(f"Wheat Bought:      Control={analysis['wheat_bought_ctrl_mean']:.1f} vs Treatment={analysis['wheat_bought_treat_mean']:.1f} (Delta: {analysis['wheat_bought_treat_mean'] - analysis['wheat_bought_ctrl_mean']:+.1f})")
    print(f"Wheat Buy Spend:   Control=${analysis['wheat_buy_cost_ctrl_mean']:,.1f} vs Treatment=${analysis['wheat_buy_cost_treat_mean']:,.1f} (Delta: ${analysis['wheat_buy_cost_treat_mean'] - analysis['wheat_buy_cost_ctrl_mean']:+,.1f})")

    print("\n--- Livestock Safety & Output ---")
    print(f"Feed Shortages:    Control={analysis['feed_shortages_ctrl_total']} vs Treatment={analysis['feed_shortages_treat_total']}")
    print(f"Starvation Deaths: Control={analysis['starvation_deaths_ctrl_total']} vs Treatment={analysis['starvation_deaths_treat_total']}")
    print(f"Max Consecutive Unfed: Control={analysis['max_unfed_ctrl']} vs Treatment={analysis['max_unfed_treat']}")
    print(f"Herd Size EOD:     Control={analysis['herd_size_ctrl_mean']:.1f} vs Treatment={analysis['herd_size_treat_mean']:.1f}")
    print(f"Animal Revenue:    Control=${analysis['animal_rev_ctrl_mean']:,.1f} vs Treatment=${analysis['animal_rev_treat_mean']:,.1f}")

    print("\n--- Crop Mix Planted (Per Match Averages) ---")
    for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
        cp = analysis['planted_mix_control'][c]
        tp = analysis['planted_mix_treatment'][c]
        print(f"  {c:<10}: Control={cp:>5.1f} | Treatment={tp:>5.1f} | Delta={tp - cp:>+5.1f}")

    print("\n--- Labor & Action Efficiency ---")
    print(f"Productive Actions: Control={analysis['prod_ops_control_mean']:.1f} vs Treatment={analysis['prod_ops_treatment_mean']:.1f} (Delta: {analysis['prod_ops_delta_mean']:+.1f})")
    print(f"Moves / Prod Op:    Control={analysis['move_ratio_control_mean']:.2f} vs Treatment={analysis['move_ratio_treatment_mean']:.2f} (Delta: {analysis['move_ratio_delta_mean']:+.2f})")

    return analysis


if __name__ == "__main__":
    seeds = list(range(100, 130))
    run_tournament(seeds=seeds, max_workers=4)
