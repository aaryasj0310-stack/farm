"""Offline Opponent Intelligence Benchmark Runner for Crop Dusta Replays.

Evaluates the accuracy of the repaired opponent-intelligence system vs 4 baselines
across 60 evaluation games (frozen calibration on 20 calibration games).

Strict zero-leakage: observers receive only public observations step-by-step.
"""

import os
import sys
import json
import time
import math
from collections import defaultdict, deque
import concurrent.futures
from typing import Dict, List, Any, Tuple, Optional
import numpy as np

# Ensure agent modules can be imported read-only
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
for sub in ("", "state", "strategy", "execution", "market"):
    p = os.path.join(AGENT_DIR, sub) if sub else AGENT_DIR
    if p not in sys.path:
        sys.path.insert(0, p)

from config import PRODUCTS, CROPS, ANIMALS
from state.observation_parser import parse_observation
from state.opponent_model import (
    snapshot_opponent_farm as legacy_snapshot,
    detect_tile_deltas as legacy_detect_deltas,
    forecast_opponent_production as legacy_forecast_prod,
    update_opponent_shed_estimate as legacy_update_shed,
    compute_opponent_sell_probabilities as legacy_compute_sell_probs,
)
from state.repaired_opponent_model import (
    snapshot_farm as repaired_snapshot,
    detect_tile_deltas_repaired,
    forecast_opponent_production_repaired,
    RepairedOpponentInventoryTracker,
)
from strategy.shadow_forecast import ShadowOpponentForecaster

HORIZONS = [1, 4, 8, 24]
THRESHOLDS = [0.2, 0.4, 0.5, 0.6, 0.8]
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
PHASES = ["early", "mid", "late", "endgame"]


def classify_phase(day: int) -> str:
    if day <= 4:
        return "early"
    elif day <= 15:
        return "mid"
    elif day <= 27:
        return "late"
    else:
        return "endgame"


def compute_calibration_base_rates(calib_records: List[Dict[str, Any]], source_dir: str) -> Dict[str, Any]:
    """Compute empirical sale base rates across 20 calibration games."""
    print(f"Computing calibration base rates across {len(calib_records)} games...")
    total_steps = 0
    total_step_products = 0
    global_sales_counts = {h: 0 for h in HORIZONS}
    prod_sales_counts = {p: {h: 0 for h in HORIZONS} for p in PRODUCTS}

    for rec in calib_records:
        fpath = os.path.join(source_dir, rec["filename"])
        cd_seat = rec["crop_dusta_seat"]
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        steps = data if isinstance(data, list) else data.get("steps", [])
        n_steps = len(steps)
        total_steps += n_steps

        sales_by_step = [defaultdict(float) for _ in range(n_steps)]
        for s_idx, st in enumerate(steps):
            act = st[cd_seat].get("action")
            if isinstance(act, dict):
                for order in act.get("market", []):
                    if isinstance(order, list) and len(order) >= 3 and order[0] == "SELL":
                        sales_by_step[s_idx][order[1]] += float(order[2])

        for s_idx in range(n_steps):
            total_step_products += len(PRODUCTS)
            for h in HORIZONS:
                for p in PRODUCTS:
                    sold = False
                    for fut_s in range(s_idx + 1, min(n_steps, s_idx + 1 + h)):
                        if sales_by_step[fut_s].get(p, 0.0) >= 1.0:
                            sold = True
                            break
                    if sold:
                        prod_sales_counts[p][h] += 1
                        global_sales_counts[h] += 1

    calib_params = {
        "total_calibration_games": len(calib_records),
        "total_steps": total_steps,
        "total_step_products": total_step_products,
        "global_sale_rates": {h: global_sales_counts[h] / total_step_products for h in HORIZONS},
        "product_sale_rates": {
            p: {h: prod_sales_counts[p][h] / total_steps for h in HORIZONS}
            for p in PRODUCTS
        },
    }
    return calib_params


def evaluate_replay_worker(args: Tuple[Dict[str, Any], str, Dict[str, Any]]) -> Dict[str, Any]:
    """Worker evaluating a single replay without any state leakage."""
    rec, source_dir, calib_params = args
    fpath = os.path.join(source_dir, rec["filename"])
    cd_seat = rec["crop_dusta_seat"]
    obs_seat = 1 - cd_seat

    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    steps = data if isinstance(data, list) else data.get("steps", [])
    total_steps = len(steps)

    actual_shed_by_step = []
    actual_carried_by_step = []
    actual_sales_by_step = [defaultdict(float) for _ in range(total_steps)]
    actual_sales_floor_censored = [defaultdict(bool) for _ in range(total_steps)]
    actual_market_prices = [{} for _ in range(total_steps)]

    for s_idx in range(total_steps):
        st = steps[s_idx]
        cd_obs = st[cd_seat]["observation"]
        priv = cd_obs.get("private", {})
        if not isinstance(priv, dict):
            priv = getattr(priv, "__dict__", {})

        shed = priv.get("shed", {})
        actual_shed_by_step.append({p: float(shed.get(p, 0)) for p in PRODUCTS})

        inventories = priv.get("inventories", [])
        carried_tot = defaultdict(float)
        for inv in inventories:
            if isinstance(inv, dict):
                for p, qty in inv.items():
                    carried_tot[p] += float(qty)
        actual_carried_by_step.append(dict(carried_tot))

        mkt = cd_obs.get("market", {})
        prices = mkt.get("prices", {})
        actual_market_prices[s_idx] = dict(prices)

        cd_act = st[cd_seat].get("action")
        if isinstance(cd_act, dict):
            for order in cd_act.get("market", []):
                if isinstance(order, list) and len(order) >= 3 and order[0] == "SELL":
                    item = order[1]
                    qty = float(order[2])
                    actual_sales_by_step[s_idx][item] += qty
                    if prices.get(item, 10) <= 1:
                        actual_sales_floor_censored[s_idx][item] = True

    collection_latencies = defaultdict(list)
    delivery_latencies = defaultdict(list)
    delivery_types = defaultdict(lambda: {"eod": 0, "manual": 0})
    actual_harvests_by_step = [defaultdict(float) for _ in range(total_steps)]

    prev_tile_states = {}

    for s_idx in range(total_steps):
        cd_obs = steps[s_idx][cd_seat]["observation"]
        farms = cd_obs.get("farms", [])
        if len(farms) > cd_seat and isinstance(farms[cd_seat], dict):
            tiles = farms[cd_seat].get("tiles", [])
            for y, row in enumerate(tiles):
                for x, t in enumerate(row):
                    key = (x, y)
                    prev = prev_tile_states.get(key)
                    if isinstance(t, dict):
                        y_units = t.get("yield_units", 0)
                        prod = t.get("crop") or (ANIMALS.get(t.get("animal", ""), {}).get("product"))

                        if y_units > 0 and (prev is None or prev["yield"] == 0):
                            prev_tile_states[key] = {
                                "prod": prod,
                                "yield": y_units,
                                "ripe_step": s_idx,
                            }
                        elif prev and prev["yield"] > 0 and y_units == 0:
                            harvest_units = prev["yield"]
                            ripe_s = prev["ripe_step"]
                            coll_lat = s_idx - ripe_s
                            p = prev["prod"]
                            if p:
                                collection_latencies[p].append(coll_lat)
                                actual_harvests_by_step[s_idx][p] += float(harvest_units)
                                for fut_s in range(s_idx, min(total_steps, s_idx + 48)):
                                    prev_s_val = actual_shed_by_step[fut_s - 1].get(p, 0.0) if fut_s > 0 else 0.0
                                    curr_s_val = actual_shed_by_step[fut_s].get(p, 0.0)
                                    if curr_s_val > prev_s_val:
                                        deliv_lat = fut_s - s_idx
                                        delivery_latencies[p].append(deliv_lat)
                                        if fut_s % 24 == 0:
                                            delivery_types[p]["eod"] += 1
                                        else:
                                            delivery_types[p]["manual"] += 1
                                        break
                            prev_tile_states[key] = {"prod": prod, "yield": 0, "ripe_step": None}
                        elif prev:
                            prev["yield"] = y_units
                    else:
                        if prev and prev["yield"] > 0:
                            coll_lat = s_idx - prev["ripe_step"]
                            p = prev["prod"]
                            if p:
                                collection_latencies[p].append(coll_lat)
                                actual_harvests_by_step[s_idx][p] += float(prev["yield"])
                                for fut_s in range(s_idx, min(total_steps, s_idx + 48)):
                                    prev_s_val = actual_shed_by_step[fut_s - 1].get(p, 0.0) if fut_s > 0 else 0.0
                                    curr_s_val = actual_shed_by_step[fut_s].get(p, 0.0)
                                    if curr_s_val > prev_s_val:
                                        deliv_lat = fut_s - s_idx
                                        delivery_latencies[p].append(deliv_lat)
                                        if fut_s % 24 == 0:
                                            delivery_types[p]["eod"] += 1
                                        else:
                                            delivery_types[p]["manual"] += 1
                                        break
                        prev_tile_states[key] = None

    legacy_prev_snap = None
    legacy_shed_est = None
    repaired_forecaster = ShadowOpponentForecaster()

    mock_mem = {
        "opp_sales_step": {},
        "opp_sales_inferred": {},
        "opp_market_inference": {},
        "opp_sales_history": deque(maxlen=100),
    }
    prev_market_inv = None

    shed_cov_active = defaultdict(lambda: {"correct": 0, "total": 0, "width_sum": 0.0, "mae_sum": 0.0})
    shed_cov_uncond = defaultdict(lambda: {"correct": 0, "total": 0})
    carried_cov_active = defaultdict(lambda: {"correct": 0, "total": 0, "width_sum": 0.0})
    carried_cov_uncond = defaultdict(lambda: {"correct": 0, "total": 0})

    predictors = ["zero", "global", "prod", "legacy", "repaired"]
    brier_sums = {pred: {h: 0.0 for h in HORIZONS} for pred in predictors}
    brier_by_prod = {pred: {h: defaultdict(float) for h in HORIZONS} for pred in predictors}
    brier_by_phase = {pred: {h: defaultdict(float) for h in HORIZONS} for pred in predictors}
    brier_counts_by_phase = defaultdict(int)

    reliability_bins = {
        "repaired": {h: {b_idx: {"count": 0, "pred_sum": 0.0, "actual_sum": 0.0} for b_idx in range(len(BINS))} for h in HORIZONS},
        "legacy": {h: {b_idx: {"count": 0, "pred_sum": 0.0, "actual_sum": 0.0} for b_idx in range(len(BINS))} for h in HORIZONS},
    }

    conf_matrices = {
        pred: {h: {tau: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for tau in THRESHOLDS} for h in HORIZONS}
        for pred in predictors
    }

    timing_errors = []
    volume_errors = []
    floor_censored_eval = {"total": 0, "repaired_correct_sale": 0, "repaired_suppressed": 0}

    total_step_samples = 0

    for s_idx in range(total_steps):
        obs_raw = steps[s_idx][obs_seat]["observation"]
        parsed_ctx = parse_observation(obs_raw)
        if parsed_ctx is None:
            continue

        opp_farm = parsed_ctx["opponent_farm"]
        day = parsed_ctx.get("day", 0)
        hour = parsed_ctx.get("hour", 0)
        phase = classify_phase(day)

        market_now = parsed_ctx.get("market", {})
        inv_now = market_now.get("inventory", {}) if isinstance(market_now, dict) else getattr(market_now, "inventory", {})
        step_sales = {}
        if prev_market_inv is not None:
            for p in PRODUCTS:
                delta_inv = inv_now.get(p, 10000) - prev_market_inv.get(p, 10000)
                if delta_inv > 0:
                    step_sales[p] = float(delta_inv)
                    mock_mem["opp_sales_inferred"][p] = mock_mem["opp_sales_inferred"].get(p, 0.0) + float(delta_inv)
                    mock_mem["opp_sales_history"].append((s_idx, p, float(delta_inv)))
        mock_mem["opp_sales_step"] = step_sales
        prev_market_inv = dict(inv_now)

        leg_snap = legacy_snapshot(opp_farm)
        leg_deltas = legacy_detect_deltas(opp_farm, legacy_prev_snap)
        legacy_prev_snap = leg_snap

        opp_animals = sum(1 for t in opp_farm.iter_tiles() if t.is_animal)
        legacy_shed_est = legacy_update_shed(
            legacy_shed_est, leg_deltas, step_sales, opp_animals, day, hour,
        )
        leg_sell_scores = legacy_compute_sell_probs(
            opp_farm, legacy_shed_est or {}, parsed_ctx, mock_mem,
        )

        rep_telemetry = repaired_forecaster.update(opp_farm, parsed_ctx, mock_mem)
        rep_p_sale_4 = rep_telemetry.get("p_sale_next_4_turns", {})
        rep_p_sale_by_h = rep_telemetry.get("p_sale_by_horizon", {})
        rep_shed_bounds = rep_telemetry.get("shed_bounds", {})
        rep_carried_bounds = rep_telemetry.get("carried_bounds", {})
        rep_shed_pt = rep_telemetry.get("shed_point_estimate", {})
        rep_vol_forecast = rep_telemetry.get("sale_volume_forecast", {})
        rep_next_sell = rep_telemetry.get("next_sell_step", s_idx + 1)

        act_shed = actual_shed_by_step[s_idx]
        act_carried = actual_carried_by_step[s_idx]

        y_by_h = {}
        for h in HORIZONS:
            y_by_h[h] = {}
            for p in PRODUCTS:
                sold_qty = 0.0
                for fut_s in range(s_idx + 1, min(total_steps, s_idx + 1 + h)):
                    sold_qty += actual_sales_by_step[fut_s].get(p, 0.0)
                y_by_h[h][p] = 1.0 if sold_qty >= 1.0 else 0.0

        total_step_samples += 1
        brier_counts_by_phase[phase] += 1

        for p in PRODUCTS:
            act_s = act_shed.get(p, 0.0)
            act_c = act_carried.get(p, 0.0)

            s_bnd = rep_shed_bounds.get(p, [0.0, 0.0])
            s_in_bnd = (s_bnd[0] <= act_s <= s_bnd[1])
            s_width = s_bnd[1] - s_bnd[0]
            s_pt = rep_shed_pt.get(p, 0.0)
            s_mae = abs(s_pt - act_s)

            shed_cov_uncond[p]["total"] += 1
            if s_in_bnd:
                shed_cov_uncond[p]["correct"] += 1

            if act_s > 0 or s_bnd[1] > 0:
                shed_cov_active[p]["total"] += 1
                if s_in_bnd:
                    shed_cov_active[p]["correct"] += 1
                shed_cov_active[p]["width_sum"] += s_width
                shed_cov_active[p]["mae_sum"] += s_mae

            c_bnd = rep_carried_bounds.get(p, [0.0, 0.0])
            c_in_bnd = (c_bnd[0] <= act_c <= c_bnd[1])
            c_width = c_bnd[1] - c_bnd[0]

            carried_cov_uncond[p]["total"] += 1
            if c_in_bnd:
                carried_cov_uncond[p]["correct"] += 1

            if act_c > 0 or c_bnd[1] > 0:
                carried_cov_active[p]["total"] += 1
                if c_in_bnd:
                    carried_cov_active[p]["correct"] += 1
                carried_cov_active[p]["width_sum"] += c_width

            p_4 = rep_p_sale_4.get(p, 0.0)
            p_leg = leg_sell_scores.get(p, 0.0)

            for h in HORIZONS:
                y = y_by_h[h][p]

                p_preds = {
                    "zero": 0.0,
                    "global": calib_params["global_sale_rates"][h],
                    "prod": calib_params["product_sale_rates"][p][h],
                    "legacy": min(1.0, max(0.0, p_leg)),
                    "repaired": rep_p_sale_by_h.get(h, {}).get(p, p_4),
                }

                for pred_name, prob in p_preds.items():
                    sq_err = (prob - y) ** 2
                    brier_sums[pred_name][h] += sq_err
                    brier_by_prod[pred_name][h][p] += sq_err
                    brier_by_phase[pred_name][h][phase] += sq_err

                    for tau in THRESHOLDS:
                        pred_pos = (prob >= tau)
                        cm = conf_matrices[pred_name][h][tau]
                        if pred_pos and y == 1.0:
                            cm["tp"] += 1
                        elif pred_pos and y == 0.0:
                            cm["fp"] += 1
                        elif not pred_pos and y == 1.0:
                            cm["fn"] += 1
                        else:
                            cm["tn"] += 1

                for model_name, prob_val in [("repaired", p_preds["repaired"]), ("legacy", p_preds["legacy"])]:
                    for b_idx, (b_low, b_high) in enumerate(BINS):
                        if (b_low <= prob_val < b_high) or (b_idx == len(BINS) - 1 and b_low <= prob_val <= b_high):
                            rb = reliability_bins[model_name][h][b_idx]
                            rb["count"] += 1
                            rb["pred_sum"] += prob_val
                            rb["actual_sum"] += y
                            break

            prob_rep_4 = rep_p_sale_4.get(p, 0.0)
            if prob_rep_4 >= 0.5:
                next_act_step = None
                for fut_s in range(s_idx + 1, min(total_steps, s_idx + 25)):
                    if actual_sales_by_step[fut_s].get(p, 0.0) >= 1.0:
                        next_act_step = fut_s
                        break
                if next_act_step is not None:
                    timing_errors.append(abs(next_act_step - rep_next_sell))

            act_sold_now = actual_sales_by_step[s_idx].get(p, 0.0)
            if act_sold_now >= 1.0:
                pred_vol = rep_vol_forecast.get(p, {}).get("expected_sale_units", 0.0)
                volume_errors.append(abs(pred_vol - act_sold_now))

                if actual_sales_floor_censored[s_idx].get(p, False):
                    floor_censored_eval["total"] += 1
                    if prob_rep_4 >= 0.3:
                        floor_censored_eval["repaired_correct_sale"] += 1
                    else:
                        floor_censored_eval["repaired_suppressed"] += 1

    actual_sales_total = {
        p: sum(actual_sales_by_step[s].get(p, 0.0) for s in range(total_steps))
        for p in PRODUCTS
    }
    actual_harvests_total = {
        p: sum(actual_harvests_by_step[s].get(p, 0.0) for s in range(total_steps))
        for p in PRODUCTS
    }

    return {
        "filename": rec["filename"],
        "game_id": rec.get("game_id", ""),
        "total_steps": total_steps,
        "crop_dusta_score": rec.get("crop_dusta_score", 0.0),
        "actual_sales_total": actual_sales_total,
        "actual_harvests_total": actual_harvests_total,
        "collection_latencies": {p: list(lat_list) for p, lat_list in collection_latencies.items()},
        "delivery_latencies": {p: list(lat_list) for p, lat_list in delivery_latencies.items()},
        "delivery_types": {p: dict(dt) for p, dt in delivery_types.items()},
        "shed_cov_active": {p: dict(v) for p, v in shed_cov_active.items()},
        "shed_cov_uncond": {p: dict(v) for p, v in shed_cov_uncond.items()},
        "carried_cov_active": {p: dict(v) for p, v in carried_cov_active.items()},
        "carried_cov_uncond": {p: dict(v) for p, v in carried_cov_uncond.items()},
        "brier_sums": brier_sums,
        "brier_by_prod": {pred: {h: dict(v) for h, v in brier_by_prod[pred].items()} for pred in predictors},
        "brier_by_phase": {pred: {h: dict(v) for h, v in brier_by_phase[pred].items()} for pred in predictors},
        "brier_counts_by_phase": dict(brier_counts_by_phase),
        "reliability_bins": reliability_bins,
        "conf_matrices": conf_matrices,
        "timing_errors": timing_errors,
        "volume_errors": volume_errors,
        "floor_censored_eval": floor_censored_eval,
    }


def aggregate_benchmark_results(results: List[Dict[str, Any]], calib_params: Dict[str, Any]) -> Dict[str, Any]:
    num_games = len(results)
    total_steps = sum(r["total_steps"] for r in results)
    total_eval_samples = total_steps * len(PRODUCTS)

    print(f"Aggregating evaluation across {num_games} games ({total_steps} steps, {total_eval_samples:,} product-steps)...")

    brier_scores = {pred: {} for pred in ["zero", "global", "prod", "legacy", "repaired"]}
    for pred in brier_scores:
        for h in HORIZONS:
            tot_sq_err = sum(r["brier_sums"][pred][h] for r in results)
            brier_scores[pred][h] = tot_sq_err / total_eval_samples

    brier_by_prod_h4 = {pred: {} for pred in ["zero", "global", "prod", "legacy", "repaired"]}
    for pred in brier_by_prod_h4:
        for p in PRODUCTS:
            tot_sq_err = sum(r["brier_by_prod"][pred][4].get(p, 0.0) for r in results)
            brier_by_prod_h4[pred][p] = tot_sq_err / total_steps

    total_phase_samples = defaultdict(int)
    for r in results:
        for phase, cnt in r["brier_counts_by_phase"].items():
            total_phase_samples[phase] += cnt * len(PRODUCTS)

    brier_by_phase_h4 = {pred: {} for pred in ["zero", "global", "prod", "legacy", "repaired"]}
    for pred in brier_by_phase_h4:
        for phase in PHASES:
            tot_sq_err = sum(r["brier_by_phase"][pred][4].get(phase, 0.0) for r in results)
            brier_by_phase_h4[pred][phase] = tot_sq_err / total_phase_samples[phase] if total_phase_samples[phase] > 0 else 0.0

    reliability_curves = {"repaired": {}, "legacy": {}}
    for model in ["repaired", "legacy"]:
        bins_data = []
        for b_idx, (b_low, b_high) in enumerate(BINS):
            cnt = sum(r["reliability_bins"][model][4][b_idx]["count"] for r in results)
            pred_sum = sum(r["reliability_bins"][model][4][b_idx]["pred_sum"] for r in results)
            act_sum = sum(r["reliability_bins"][model][4][b_idx]["actual_sum"] for r in results)
            bins_data.append({
                "bin_range": [b_low, b_high],
                "count": cnt,
                "mean_predicted": pred_sum / cnt if cnt > 0 else (b_low + b_high) / 2.0,
                "observed_frequency": act_sum / cnt if cnt > 0 else 0.0,
            })
        reliability_curves[model] = bins_data

    classification_metrics = {pred: {} for pred in ["zero", "global", "prod", "legacy", "repaired"]}
    for pred in classification_metrics:
        for tau in THRESHOLDS:
            tp = sum(r["conf_matrices"][pred][4][tau]["tp"] for r in results)
            fp = sum(r["conf_matrices"][pred][4][tau]["fp"] for r in results)
            fn = sum(r["conf_matrices"][pred][4][tau]["fn"] for r in results)
            tn = sum(r["conf_matrices"][pred][4][tau]["tn"] for r in results)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

            classification_metrics[pred][tau] = {
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
            }

    shed_cov_summary = {}
    carried_cov_summary = {}
    for p in PRODUCTS:
        tot_active = sum(r["shed_cov_active"].get(p, {}).get("total", 0) for r in results)
        cor_active = sum(r["shed_cov_active"].get(p, {}).get("correct", 0) for r in results)
        w_sum = sum(r["shed_cov_active"].get(p, {}).get("width_sum", 0.0) for r in results)
        mae_sum = sum(r["shed_cov_active"].get(p, {}).get("mae_sum", 0.0) for r in results)

        tot_uncond = sum(r["shed_cov_uncond"].get(p, {}).get("total", 0) for r in results)
        cor_uncond = sum(r["shed_cov_uncond"].get(p, {}).get("correct", 0) for r in results)

        shed_cov_summary[p] = {
            "active_samples": tot_active,
            "active_coverage": cor_active / tot_active if tot_active > 0 else 1.0,
            "unconditional_coverage": cor_uncond / tot_uncond if tot_uncond > 0 else 1.0,
            "mean_interval_width": w_sum / tot_active if tot_active > 0 else 0.0,
            "shed_mae": mae_sum / tot_active if tot_active > 0 else 0.0,
        }

        c_tot_act = sum(r["carried_cov_active"].get(p, {}).get("total", 0) for r in results)
        c_cor_act = sum(r["carried_cov_active"].get(p, {}).get("correct", 0) for r in results)
        c_w_sum = sum(r["carried_cov_active"].get(p, {}).get("width_sum", 0.0) for r in results)

        c_tot_un = sum(r["carried_cov_uncond"].get(p, {}).get("total", 0) for r in results)
        c_cor_un = sum(r["carried_cov_uncond"].get(p, {}).get("correct", 0) for r in results)

        carried_cov_summary[p] = {
            "active_samples": c_tot_act,
            "active_coverage": c_cor_act / c_tot_act if c_tot_act > 0 else 1.0,
            "unconditional_coverage": c_cor_un / c_tot_un if c_tot_un > 0 else 1.0,
            "mean_interval_width": c_w_sum / c_tot_act if c_tot_act > 0 else 0.0,
        }

    active_shed_cov_macro = np.mean([v["active_coverage"] for v in shed_cov_summary.values() if v["active_samples"] > 0])
    uncond_shed_cov_macro = np.mean([v["unconditional_coverage"] for v in shed_cov_summary.values()])
    macro_shed_mae = np.mean([v["shed_mae"] for v in shed_cov_summary.values() if v["active_samples"] > 0])
    active_carried_cov_macro = np.mean([v["active_coverage"] for v in carried_cov_summary.values() if v["active_samples"] > 0])

    coll_latencies_flat = []
    for r in results:
        for lat_list in r["collection_latencies"].values():
            coll_latencies_flat.extend(lat_list)

    deliv_latencies_flat = []
    for r in results:
        for lat_list in r["delivery_latencies"].values():
            deliv_latencies_flat.extend(lat_list)

    eod_drops = sum(sum(p_dict.get("eod", 0) for p_dict in r["delivery_types"].values()) for r in results)
    manual_drops = sum(sum(p_dict.get("manual", 0) for p_dict in r["delivery_types"].values()) for r in results)

    collection_stats = {
        "total_harvest_events": len(coll_latencies_flat),
        "mean_latency_turns": float(np.mean(coll_latencies_flat)) if coll_latencies_flat else 0.0,
        "median_latency_turns": float(np.median(coll_latencies_flat)) if coll_latencies_flat else 0.0,
        "p25": float(np.percentile(coll_latencies_flat, 25)) if coll_latencies_flat else 0.0,
        "p75": float(np.percentile(coll_latencies_flat, 75)) if coll_latencies_flat else 0.0,
        "p90": float(np.percentile(coll_latencies_flat, 90)) if coll_latencies_flat else 0.0,
        "collected_within_1_turn_pct": float(np.mean([x <= 1 for x in coll_latencies_flat])) if coll_latencies_flat else 0.0,
        "collected_within_4_turns_pct": float(np.mean([x <= 4 for x in coll_latencies_flat])) if coll_latencies_flat else 0.0,
    }

    delivery_stats = {
        "total_deliveries_tracked": len(deliv_latencies_flat),
        "mean_latency_turns": float(np.mean(deliv_latencies_flat)) if deliv_latencies_flat else 0.0,
        "median_latency_turns": float(np.median(deliv_latencies_flat)) if deliv_latencies_flat else 0.0,
        "p25": float(np.percentile(deliv_latencies_flat, 25)) if deliv_latencies_flat else 0.0,
        "p75": float(np.percentile(deliv_latencies_flat, 75)) if deliv_latencies_flat else 0.0,
        "eod_deposit_count": eod_drops,
        "manual_deposit_count": manual_drops,
        "eod_deposit_pct": eod_drops / (eod_drops + manual_drops) if (eod_drops + manual_drops) > 0 else 0.0,
    }

    all_timing_errors = []
    all_volume_errors = []
    for r in results:
        all_timing_errors.extend(r["timing_errors"])
        all_volume_errors.extend(r["volume_errors"])

    timing_volume_stats = {
        "timing_error_samples": len(all_timing_errors),
        "timing_mae_turns": float(np.mean(all_timing_errors)) if all_timing_errors else 0.0,
        "timing_median_turns": float(np.median(all_timing_errors)) if all_timing_errors else 0.0,
        "volume_error_samples": len(all_volume_errors),
        "volume_mae_units": float(np.mean(all_volume_errors)) if all_volume_errors else 0.0,
        "volume_median_units": float(np.median(all_volume_errors)) if all_volume_errors else 0.0,
    }

    floor_tot = sum(r["floor_censored_eval"]["total"] for r in results)
    floor_cor = sum(r["floor_censored_eval"]["repaired_correct_sale"] for r in results)
    floor_sup = sum(r["floor_censored_eval"]["repaired_suppressed"] for r in results)

    floor_censoring_stats = {
        "floor_censored_sales_count": floor_tot,
        "repaired_predicted_sale_count": floor_cor,
        "repaired_suppressed_count": floor_sup,
        "repaired_recall_on_floor_sales": floor_cor / floor_tot if floor_tot > 0 else 0.0,
    }

    total_sales_by_prod = defaultdict(float)
    total_harvests_by_prod = defaultdict(float)
    scores = [r["crop_dusta_score"] for r in results]

    for r in results:
        for p, q in r["actual_sales_total"].items():
            total_sales_by_prod[p] += q
        for p, q in r["actual_harvests_total"].items():
            total_harvests_by_prod[p] += q

    behavioral_profile = {
        "mean_score": float(np.mean(scores)),
        "median_score": float(np.median(scores)),
        "min_score": float(np.min(scores)),
        "max_score": float(np.max(scores)),
        "total_units_sold_per_game_mean": {p: total_sales_by_prod[p] / num_games for p in PRODUCTS},
        "total_units_harvested_per_game_mean": {p: total_harvests_by_prod[p] / num_games for p in PRODUCTS},
    }

    report = {
        "benchmark_metadata": {
            "num_eval_games": num_games,
            "total_steps": total_steps,
            "total_eval_samples": total_eval_samples,
            "calib_games": calib_params["total_calibration_games"],
            "calibration_parameters": calib_params,
        },
        "sales_brier_scores": brier_scores,
        "brier_by_product_h4": brier_by_prod_h4,
        "brier_by_phase_h4": brier_by_phase_h4,
        "reliability_curves_h4": reliability_curves,
        "classification_metrics_h4": classification_metrics,
        "hidden_inventory_evaluation": {
            "macro_shed_active_coverage": float(active_shed_cov_macro),
            "macro_shed_unconditional_coverage": float(uncond_shed_cov_macro),
            "macro_shed_mae": float(macro_shed_mae),
            "macro_carried_active_coverage": float(active_carried_cov_macro),
            "per_product_shed": shed_cov_summary,
            "per_product_carried": carried_cov_summary,
        },
        "collection_timing": collection_stats,
        "delivery_timing": delivery_stats,
        "timing_and_volume_accuracy": timing_volume_stats,
        "floor_censoring_impact": floor_censoring_stats,
        "crop_dusta_behavior": behavioral_profile,
    }

    return report


def main():
    start_time = time.time()
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    source_dir = manifest["source_dir"]
    calib_recs = [r for r in manifest["records"] if r["split"] == "calibration"]
    eval_recs = [r for r in manifest["records"] if r["split"] == "eval"]

    print(f"Loaded manifest: {len(calib_recs)} calibration games, {len(eval_recs)} eval games.")

    calib_params = compute_calibration_base_rates(calib_recs, source_dir)
    calib_save_path = os.path.join(os.path.dirname(__file__), "calibration_parameters.json")
    with open(calib_save_path, "w", encoding="utf-8") as f:
        json.dump(calib_params, f, indent=2)
    print(f"Calibration parameters saved to {calib_save_path}")

    print(f"Starting parallel evaluation of {len(eval_recs)} eval games...")
    worker_args = [(rec, source_dir, calib_params) for rec in eval_recs]

    eval_results = []
    max_workers = min(12, os.cpu_count() or 4)
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(evaluate_replay_worker, arg): arg[0]["filename"] for arg in worker_args}
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            fname = futures[future]
            try:
                res = future.result()
                eval_results.append(res)
                completed += 1
                if completed % 10 == 0 or completed == len(eval_recs):
                    print(f"  Progress: {completed}/{len(eval_recs)} games evaluated ({completed/len(eval_recs)*100:.1f}%)")
            except Exception as e:
                print(f"Error evaluating {fname}: {e}")
                import traceback
                traceback.print_exc()

    report = aggregate_benchmark_results(eval_results, calib_params)
    report_save_path = os.path.join(os.path.dirname(__file__), "crop_dusta_eval_report.json")
    with open(report_save_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    report_v2_path = os.path.join(os.path.dirname(__file__), "crop_dusta_eval_report_v2.json")
    with open(report_v2_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    elapsed = time.time() - start_time
    print(f"\nBenchmark completed successfully in {elapsed:.1f} seconds!")
    print(f"Report saved to: {report_save_path}")

    print("\n" + "="*80)
    print("KEY BENCHMARK FINDINGS: BRIER SCORES (LOWER IS BETTER)")
    print("="*80)
    print(f"{'Predictor':25s} | {'H=1':10s} | {'H=4':10s} | {'H=8':10s} | {'H=24':10s}")
    print("-" * 80)
    for pred in ["zero", "global", "prod", "legacy", "repaired"]:
        b = report["sales_brier_scores"][pred]
        print(f"{pred:25s} | {b[1]:.5f}    | {b[4]:.5f}    | {b[8]:.5f}    | {b[24]:.5f}")
    print("="*80)

    print("\nHIDDEN INVENTORY METRICS:")
    inv = report["hidden_inventory_evaluation"]
    print(f"  Macro Shed Active Coverage:       {inv['macro_shed_active_coverage']*100:.2f}% (Target: >= 85%)")
    print(f"  Macro Shed Unconditional Coverage: {inv['macro_shed_unconditional_coverage']*100:.2f}%")
    print(f"  Macro Shed Point MAE:              {inv['macro_shed_mae']:.2f} units")
    print(f"  Macro Carried Active Coverage:    {inv['macro_carried_active_coverage']*100:.2f}%")

    print("\nCOLLECTION & DELIVERY LATENCIES:")
    print(f"  Collection Latency (Ripe->Harv):   Mean={report['collection_timing']['mean_latency_turns']:.1f} turns, Median={report['collection_timing']['median_latency_turns']:.1f} turns")
    print(f"  Delivery Latency (Harv->Shed):     Mean={report['delivery_timing']['mean_latency_turns']:.1f} turns, Median={report['delivery_timing']['median_latency_turns']:.1f} turns (EOD auto-drop pct: {report['delivery_timing']['eod_deposit_pct']*100:.1f}%)")


if __name__ == "__main__":
    main()
