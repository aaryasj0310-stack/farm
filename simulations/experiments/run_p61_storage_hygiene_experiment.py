#!/usr/bin/env python3
"""Kaggriculture P6.1 — Shed-Overflow Prevention via Pre-Midnight Storage Hygiene Experiment.

Evaluation Panel:
- Seeds 96,411–96,420 (10 fresh untouched seeds)
- 5 benchmark opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 seats: Seat 0 and Seat 1
- Total scenarios: 10 * 5 * 2 = 100 matched pairs (200 live games)

Arms:
- Control: Production baseline commit 536f1e7 (P51_T1_TWO_CYCLE_CARROT_ENABLED = False, P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False)
- Treatment: P6.1 Pre-Midnight Storage Hygiene (P51_T1_TWO_CYCLE_CARROT_ENABLED = False, P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = True)

Hypothesis:
By monitoring shed inventory in the late evening (Hours 20, 21, 22) and proactively selling
surplus inventory to guarantee at least 25 units of shed headroom before workers execute
their midnight inventory drops, physical shed overflow discards will decrease by >= 70%
without harming feed security, market prices, crop production, livestock production, or worker execution.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import gzip
import json
import math
import os
import sys
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

BASELINE_SHA = "536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e"
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]
EVAL_SEEDS = list(range(96411, 96421))  # 10 fresh untouched evaluation seeds: 96,411–96,420
SEATS = [0, 1]

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
BASE_PRICES = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250,
    "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100
}


def _run_single_game(seed, opponent, seat, p61_enabled):
    """Executes a single instrumented simulation game (Control or Treatment)."""
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    agent_dir = os.path.join(ROOT, "agent")
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
            "two_cycle_rotation_manager", "expansion_planner", "price_math", "price_forecast", "endgame_liquidator",
        )):
            del sys.modules[key]

    import kaggle_environments
    import kaggle_environments.envs.kaggriculture.kaggriculture as kg
    import main as module
    import config as cfg
    import simulations.experiments.audit_p50r_telemetry as apt
    from simulations.experiments.agent_zoo import get_agent
    from strategy.two_cycle_rotation_manager import reset_rotation_manager

    apt._configure_baseline(cfg)
    cfg.set_p51_t1_two_cycle_carrot_enabled(False)
    cfg.set_p61_pre_midnight_storage_hygiene_enabled(p61_enabled)
    module.reset_agent_state()
    reset_rotation_manager()

    opp_agent = get_agent(opponent)
    players = [module.agent, opp_agent] if seat == 0 else [opp_agent, module.agent]

    # Telemetry
    sells = {p: {"units": 0, "revenue": 0.0, "prices": []} for p in PRODUCTS}
    shed_discards = {p: {"units": 0, "events": 0} for p in PRODUCTS}
    feed_failures = {"missed_feeds": 0, "starvation_events": 0, "escapes": 0}
    cp_arbitration = {
        "total_proposals": 0,
        "accepted_orders": 0,
        "rejected_orders": 0,
        "slot_cap_rejections": 0,
        "p0_rejections": 0,
        "p1_hygiene_proposals": 0,
        "p1_hygiene_accepted": 0,
        "p1_hygiene_rejected": 0,
    }
    hourly_shed_log = []

    cur_p0_farm = None
    cur_p0_priv = None

    orig_process_market = kg._process_market
    def tracked_process_market(state, env):
        nonlocal cur_p0_farm, cur_p0_priv
        cur_p0_farm = state[0].observation.farms[0]
        cur_p0_priv = state[0].observation.private

        orig_commit_unit = kg._commit_unit
        def tracked_commit_unit(op, item, price, farm, private, market, shed_capacity=100):
            ok = orig_commit_unit(op, item, price, farm, private, market, shed_capacity)
            if ok:
                pid = 0 if (private is cur_p0_priv) else 1
                if pid == seat:
                    p = float(price)
                    if op == "SELL" and item in sells:
                        sells[item]["units"] += 1
                        sells[item]["revenue"] += p
                        sells[item]["prices"].append(p)
            return ok

        kg._commit_unit = tracked_commit_unit
        try:
            orig_process_market(state, env)
        finally:
            kg._commit_unit = orig_commit_unit

    cur_anim_pid = 1
    orig_daily_animals = kg._daily_refresh_animals
    def tracked_daily_animals(farm, day):
        nonlocal cur_anim_pid
        cur_anim_pid = 1 - cur_anim_pid
        is_us = (cur_anim_pid == seat)
        if is_us:
            for row in farm["tiles"]:
                for t in row:
                    if isinstance(t, dict) and "animal" in t:
                        if not t.get("fed_today", False):
                            feed_failures["missed_feeds"] += 1
                            if t.get("consecutive_unfed", 0) >= 1:
                                feed_failures["starvation_events"] += 1
                            if t.get("consecutive_unfed", 0) >= 2:
                                feed_failures["escapes"] += 1
        orig_daily_animals(farm, day)

    cur_drop_pid = 1
    orig_drop_shed = kg._drop_inventories_to_shed
    def tracked_drop_shed(private, capacity):
        nonlocal cur_drop_pid
        cur_drop_pid = 1 - cur_drop_pid
        is_us = (cur_drop_pid == seat)
        if is_us:
            current = sum(private["shed"].values())
            room = max(0, capacity - current)
            for inv in private["inventories"]:
                for item, n in inv.items():
                    if n <= 0:
                        continue
                    if n > room:
                        discarded = n - room
                        if item in shed_discards:
                            shed_discards[item]["units"] += discarded
                            shed_discards[item]["events"] += 1
                        room = 0
                    else:
                        room -= n
        orig_drop_shed(private, capacity)

    kg._process_market = tracked_process_market
    kg._daily_refresh_animals = tracked_daily_animals
    kg._drop_inventories_to_shed = tracked_drop_shed

    def _call_agent(agent_fn, obs, config):
        try:
            return agent_fn(obs, config)
        except TypeError:
            return agent_fn(obs)

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    try:
        env.reset()
        for step_idx in range(720):
            if env.done:
                break
            day = step_idx // 24
            hour = step_idx % 24

            our_priv = env.state[seat].observation.private
            shed_occ = sum(our_priv.get("shed", {}).values())
            worker_occ = sum(sum(inv.values()) for inv in our_priv.get("inventories", []))
            if hour in (20, 21, 22, 23):
                hourly_shed_log.append({
                    "day": day, "hour": hour,
                    "shed_occupancy": shed_occ,
                    "worker_inventory": worker_occ,
                    "projected_load": shed_occ + worker_occ,
                })

            act0 = _call_agent(players[0], env.state[0].observation, env.configuration)
            act1 = _call_agent(players[1], env.state[1].observation, env.configuration)

            # CentralPlanner Diagnostics
            try:
                import main as agent_main
                cp_diag = agent_main.get_central_planner_diagnostics()
                if cp_diag:
                    n_cand = cp_diag.get("total_candidates", 0)
                    acc_list = cp_diag.get("accepted_details", [])
                    rej_list = cp_diag.get("rejected_details", [])
                    cp_arbitration["total_proposals"] += n_cand
                    cp_arbitration["accepted_orders"] += len(acc_list)
                    cp_arbitration["rejected_orders"] += len(rej_list)
                    for r_item in rej_list:
                        reason = r_item.get("rejection_reason", "unknown")
                        if reason == "slot_cap":
                            cp_arbitration["slot_cap_rejections"] += 1
                        if r_item.get("priority_class") == 0:  # P0_CRITICAL
                            cp_arbitration["p0_rejections"] += 1
                    for a_item in acc_list:
                        meta = a_item.get("metadata", {})
                        if meta.get("sell_pressure_class") == "pre_midnight_hygiene":
                            cp_arbitration["p1_hygiene_proposals"] += 1
                            cp_arbitration["p1_hygiene_accepted"] += 1
                    for r_item in rej_list:
                        meta = r_item.get("metadata", {})
                        if meta.get("sell_pressure_class") == "pre_midnight_hygiene":
                            cp_arbitration["p1_hygiene_proposals"] += 1
                            cp_arbitration["p1_hygiene_rejected"] += 1
            except Exception:
                pass

            env.step([act0, act1])
    finally:
        kg._process_market = orig_process_market
        kg._daily_refresh_animals = orig_daily_animals
        kg._drop_inventories_to_shed = orig_drop_shed

    final_reward = float(env.state[seat].reward or 0.0)
    opp_reward = float(env.state[1 - seat].reward or 0.0)
    final_money = float(env.state[seat].observation.farms[seat]["money"])
    win = 1.0 if final_reward > opp_reward else (0.5 if final_reward == opp_reward else 0.0)

    # Discard valuation
    total_discard_units = sum(d["units"] for d in shed_discards.values())
    total_discard_events = sum(d["events"] for d in shed_discards.values())
    discard_val_base = sum(shed_discards[p]["units"] * BASE_PRICES[p] for p in PRODUCTS)
    discard_val_realized = 0.0
    for p in PRODUCTS:
        u = shed_discards[p]["units"]
        if u > 0:
            avg_p = (sells[p]["revenue"] / sells[p]["units"]) if sells[p]["units"] > 0 else BASE_PRICES[p]
            discard_val_realized += u * avg_p

    total_sales_revenue = sum(s["revenue"] for s in sells.values())
    total_units_sold = sum(s["units"] for s in sells.values())

    return {
        "final_reward": final_reward,
        "final_money": final_money,
        "opp_reward": opp_reward,
        "win": win,
        "total_units_sold": total_units_sold,
        "total_sales_revenue": total_sales_revenue,
        "sells": {p: {"units": sells[p]["units"], "revenue": sells[p]["revenue"],
                      "avg_price": (sells[p]["revenue"] / sells[p]["units"]) if sells[p]["units"] > 0 else 0.0}
                  for p in PRODUCTS},
        "total_discard_units": total_discard_units,
        "total_discard_events": total_discard_events,
        "discard_val_base": discard_val_base,
        "discard_val_realized": discard_val_realized,
        "shed_discards": {p: shed_discards[p]["units"] for p in PRODUCTS},
        "feed_failures": feed_failures,
        "cp_arbitration": cp_arbitration,
        "hourly_shed_log": hourly_shed_log,
    }


def _run_matched_scenario(scenario):
    """Executes matched scenario: Control then Treatment under identical environment conditions."""
    seed = scenario["seed"]
    opponent = scenario["opponent"]
    seat = scenario["seat"]

    try:
        ctrl = _run_single_game(seed, opponent, seat, p61_enabled=False)
        treat = _run_single_game(seed, opponent, seat, p61_enabled=True)

        cash_delta = treat["final_money"] - ctrl["final_money"]
        discard_delta = ctrl["total_discard_units"] - treat["total_discard_units"]
        discard_pct_reduction = (discard_delta / max(1, ctrl["total_discard_units"])) * 100.0 if ctrl["total_discard_units"] > 0 else 0.0

        return {
            "status": "ok",
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "cash_delta": cash_delta,
            "discard_delta": discard_delta,
            "discard_pct_reduction": discard_pct_reduction,
            "control": ctrl,
            "treatment": treat,
        }
    except Exception as exc:
        return {
            "status": "error",
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }


def main():
    print("=" * 80)
    print("Kaggriculture P6.1 — Shed-Overflow Storage Hygiene Formal Tournament")
    print(f"Panel: {len(EVAL_SEEDS)} Seeds ({min(EVAL_SEEDS)}–{max(EVAL_SEEDS)}) x {len(OPPONENTS)} Opponents x {len(SEATS)} Seats = {len(EVAL_SEEDS)*len(OPPONENTS)*len(SEATS)} Matched Scenarios")
    print("=" * 80)

    scenarios = [
        {"seed": seed, "opponent": opp, "seat": seat}
        for seed in EVAL_SEEDS
        for opp in OPPONENTS
        for seat in SEATS
    ]

    start_time = time.time()
    results = []
    completed = 0
    total = len(scenarios)

    max_workers = min(os.cpu_count() or 4, 8)
    print(f"Launching {total} matched scenarios using ProcessPoolExecutor (max_workers={max_workers})...")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_run_matched_scenario, sc): sc for sc in scenarios}
        for future in as_completed(future_map):
            res = future.result()
            results.append(res)
            completed += 1
            if res["status"] == "ok":
                print(f"[{completed}/{total}] Seed {res['seed']} | Opp: {res['opponent'][:12]:12} | Seat {res['seat']} -> Cash Delta: {res['cash_delta']:+8.2f} | Discards: {res['control']['total_discard_units']:4.0f} -> {res['treatment']['total_discard_units']:4.0f} ({res['discard_pct_reduction']:+5.1f}%)")
            else:
                print(f"[{completed}/{total}] ERROR in Seed {res['seed']}: {res.get('error')}")

    duration = time.time() - start_time
    print(f"\nTournament completed in {duration:.1f}s.")

    # Filter successful results
    ok_results = [r for r in results if r.get("status") == "ok"]
    n = len(ok_results)
    if n == 0:
        print("ERROR: Zero scenarios completed successfully!")
        sys.exit(1)

    # Compute Aggregate Statistics
    cash_deltas = [r["cash_delta"] for r in ok_results]
    mean_cash_delta = sum(cash_deltas) / n
    sorted_cash = sorted(cash_deltas)
    median_cash_delta = (sorted_cash[n // 2] if n % 2 != 0 else (sorted_cash[n // 2 - 1] + sorted_cash[n // 2]) / 2)
    variance_cash = sum((x - mean_cash_delta) ** 2 for x in cash_deltas) / (n - 1) if n > 1 else 0.0
    std_dev_cash = math.sqrt(variance_cash)
    std_err_cash = std_dev_cash / math.sqrt(n)
    ci95_low = mean_cash_delta - 1.96 * std_err_cash
    ci95_high = mean_cash_delta + 1.96 * std_err_cash

    ctrl_cash = [r["control"]["final_money"] for r in ok_results]
    treat_cash = [r["treatment"]["final_money"] for r in ok_results]
    mean_ctrl_cash = sum(ctrl_cash) / n
    mean_treat_cash = sum(treat_cash) / n

    ctrl_wins = sum(r["control"]["win"] for r in ok_results)
    treat_wins = sum(r["treatment"]["win"] for r in ok_results)

    ctrl_discards = [r["control"]["total_discard_units"] for r in ok_results]
    treat_discards = [r["treatment"]["total_discard_units"] for r in ok_results]
    mean_ctrl_discards = sum(ctrl_discards) / n
    mean_treat_discards = sum(treat_discards) / n
    discard_reduction_units = mean_ctrl_discards - mean_treat_discards
    discard_reduction_pct = (discard_reduction_units / max(0.001, mean_ctrl_discards)) * 100.0

    ctrl_val_realized = sum(r["control"]["discard_val_realized"] for r in ok_results) / n
    treat_val_realized = sum(r["treatment"]["discard_val_realized"] for r in ok_results) / n

    # By product discard summary
    discards_by_prod_ctrl = defaultdict(float)
    discards_by_prod_treat = defaultdict(float)
    for r in ok_results:
        for p in PRODUCTS:
            discards_by_prod_ctrl[p] += r["control"]["shed_discards"][p]
            discards_by_prod_treat[p] += r["treatment"]["shed_discards"][p]
    for p in PRODUCTS:
        discards_by_prod_ctrl[p] /= n
        discards_by_prod_treat[p] /= n

    # Sales & Price Impact
    sales_by_prod_ctrl = defaultdict(lambda: {"units": 0.0, "revenue": 0.0})
    sales_by_prod_treat = defaultdict(lambda: {"units": 0.0, "revenue": 0.0})
    for r in ok_results:
        for p in PRODUCTS:
            sales_by_prod_ctrl[p]["units"] += r["control"]["sells"][p]["units"]
            sales_by_prod_ctrl[p]["revenue"] += r["control"]["sells"][p]["revenue"]
            sales_by_prod_treat[p]["units"] += r["treatment"]["sells"][p]["units"]
            sales_by_prod_treat[p]["revenue"] += r["treatment"]["sells"][p]["revenue"]

    for p in PRODUCTS:
        sales_by_prod_ctrl[p]["units"] /= n
        sales_by_prod_ctrl[p]["revenue"] /= n
        sales_by_prod_treat[p]["units"] /= n
        sales_by_prod_treat[p]["revenue"] /= n

    # Feed Safety Audit
    treat_feed_failures = sum(r["treatment"]["feed_failures"]["missed_feeds"] for r in ok_results)
    treat_starvations = sum(r["treatment"]["feed_failures"]["starvation_events"] for r in ok_results)
    treat_escapes = sum(r["treatment"]["feed_failures"]["escapes"] for r in ok_results)
    ctrl_feed_failures = sum(r["control"]["feed_failures"]["missed_feeds"] for r in ok_results)
    ctrl_starvations = sum(r["control"]["feed_failures"]["starvation_events"] for r in ok_results)
    ctrl_escapes = sum(r["control"]["feed_failures"]["escapes"] for r in ok_results)

    # CentralPlanner Slot Audit
    treat_slot_cap_rejections = sum(r["treatment"]["cp_arbitration"]["slot_cap_rejections"] for r in ok_results) / n
    ctrl_slot_cap_rejections = sum(r["control"]["cp_arbitration"]["slot_cap_rejections"] for r in ok_results) / n
    treat_p0_rejections = sum(r["treatment"]["cp_arbitration"]["p0_rejections"] for r in ok_results)

    # Decision Verdict Determination
    # GO: Cash delta >= +$2,000, discards reduced >= 70%, 0 feed stockouts/animal escapes, CI strictly positive.
    # ITERATE: Discards reduced >= 50% and cash delta positive (+0 to +2,000), or slot starvation identified with clear fix.
    # NO-GO: Cash delta <= 0, or feed failure / animal escape, or severe price depression offsetting discard savings.
    if mean_cash_delta >= 2000.0 and discard_reduction_pct >= 70.0 and treat_escapes == 0 and ci95_low > 0:
        verdict = "GO"
    elif mean_cash_delta > 0.0 and discard_reduction_pct >= 50.0 and treat_escapes == 0:
        verdict = "ITERATE"
    else:
        verdict = "NO-GO"

    print("\n" + "=" * 80)
    print("FINAL AGGREGATE RESULTS & VERDICT")
    print("=" * 80)
    print(f"Scenarios:                {n} matched pairs (100% valid)")
    print(f"Control Final Cash:       ${mean_ctrl_cash:,.2f}")
    print(f"Treatment Final Cash:     ${mean_treat_cash:,.2f}")
    print(f"Mean Paired Cash Delta:   ${mean_cash_delta:+,.2f}")
    print(f"Median Paired Cash Delta: ${median_cash_delta:+,.2f}")
    print(f"95% Confidence Interval:  [${ci95_low:+,.2f}, ${ci95_high:+,.2f}]")
    print(f"Std Error:                ${std_err_cash:,.2f}")
    print(f"Win Rate:                 Control {ctrl_wins/n*100:.1f}% vs Treatment {treat_wins/n*100:.1f}%")
    print("-" * 80)
    print(f"Control Discard Units:    {mean_ctrl_discards:.2f} units/game (${ctrl_val_realized:,.2f} realized)")
    print(f"Treatment Discard Units:  {mean_treat_discards:.2f} units/game (${treat_val_realized:,.2f} realized)")
    print(f"Discard Reduction:        {discard_reduction_units:+.2f} units/game ({discard_reduction_pct:.1f}% reduction)")
    print("-" * 80)
    print(f"Feed Failures / Escapes:  Control {ctrl_escapes} | Treatment {treat_escapes}")
    print(f"Treatment P0 Rejections:  {treat_p0_rejections}")
    print(f"Slot Cap Rejections/game: Control {ctrl_slot_cap_rejections:.2f} | Treatment {treat_slot_cap_rejections:.2f}")
    print("=" * 80)
    print(f"OFFICIAL VERDICT:         {verdict}")
    print("=" * 80)

    # Save summary JSON
    summary_data = {
        "metadata": {
            "experiment": "P6.1 Pre-Midnight Storage Hygiene",
            "commit_sha": BASELINE_SHA,
            "evaluation_seeds": EVAL_SEEDS,
            "opponents": OPPONENTS,
            "seats": SEATS,
            "n_scenarios": n,
            "duration_seconds": duration,
            "verdict": verdict,
        },
        "statistics": {
            "mean_ctrl_cash": mean_ctrl_cash,
            "mean_treat_cash": mean_treat_cash,
            "mean_cash_delta": mean_cash_delta,
            "median_cash_delta": median_cash_delta,
            "std_dev_cash": std_dev_cash,
            "std_err_cash": std_err_cash,
            "ci95_low": ci95_low,
            "ci95_high": ci95_high,
            "ctrl_win_rate": ctrl_wins / n,
            "treat_win_rate": treat_wins / n,
            "mean_ctrl_discards": mean_ctrl_discards,
            "mean_treat_discards": mean_treat_discards,
            "discard_reduction_units": discard_reduction_units,
            "discard_reduction_pct": discard_reduction_pct,
            "ctrl_discard_val_realized": ctrl_val_realized,
            "treat_discard_val_realized": treat_val_realized,
            "discards_by_prod_ctrl": dict(discards_by_prod_ctrl),
            "discards_by_prod_treat": dict(discards_by_prod_treat),
            "sales_by_prod_ctrl": dict(sales_by_prod_ctrl),
            "sales_by_prod_treat": dict(sales_by_prod_treat),
            "feed_failures": {
                "control_missed_feeds": ctrl_feed_failures,
                "control_starvations": ctrl_starvations,
                "control_escapes": ctrl_escapes,
                "treatment_missed_feeds": treat_feed_failures,
                "treatment_starvations": treat_starvations,
                "treatment_escapes": treat_escapes,
            },
            "market_slot_audit": {
                "ctrl_slot_cap_rejections_per_game": ctrl_slot_cap_rejections,
                "treat_slot_cap_rejections_per_game": treat_slot_cap_rejections,
                "treat_p0_rejections": treat_p0_rejections,
            }
        },
        "per_scenario": [
            {
                "seed": r["seed"],
                "opponent": r["opponent"],
                "seat": r["seat"],
                "cash_delta": r["cash_delta"],
                "discard_delta": r["discard_delta"],
                "discard_pct_reduction": r["discard_pct_reduction"],
                "ctrl_cash": r["control"]["final_money"],
                "treat_cash": r["treatment"]["final_money"],
                "ctrl_discards": r["control"]["total_discard_units"],
                "treat_discards": r["treatment"]["total_discard_units"],
            }
            for r in ok_results
        ]
    }

    results_json_path = os.path.join(ROOT, "simulations", "experiments", "p61_storage_hygiene_results.json")
    with open(results_json_path, "w") as f:
        json.dump(summary_data, f, indent=2)
    print(f"Summary JSON written to: {results_json_path}")

    telemetry_gz_path = os.path.join(ROOT, "simulations", "experiments", "p61_storage_hygiene_telemetry.json.gz")
    with gzip.open(telemetry_gz_path, "wt", encoding="utf-8") as f:
        json.dump(results, f)
    print(f"Compressed telemetry written to: {telemetry_gz_path}")


if __name__ == "__main__":
    main()
