"""Offline Opponent Intelligence Benchmark Engine for Crop Dusta Replays.

Enforces zero-leakage: at step t, predictors receive ONLY what would be observable
to a live agent in the opposing seat at that exact step.

Privileged ground truth from Crop Dusta's private state and future steps is extracted
strictly for evaluation:
- Actual hidden shed inventory
- Actual worker carried stock
- Actual visible sales in next 1, 4, 8, 24 turns
- Actual crop harvests and animal collections
- Floor-price censored sales ($1)
"""

import os
import sys
import json
from collections import defaultdict, deque
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


def evaluate_single_replay(
    replay_path: str,
    cd_seat: int = 0,
    calibrated_base_rates: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Replay one game offline and compute step-by-step predictions vs ground truth."""
    with open(replay_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    steps = data if isinstance(data, list) else data.get("steps", [])
    total_steps = len(steps)
    obs_seat = 1 - cd_seat

    # Predictor states (strictly tracking from public observations)
    legacy_prev_snap = None
    legacy_shed_est = None

    repaired_forecaster = ShadowOpponentForecaster()

    # Pre-extract all ground truth across the entire episode
    actual_shed_by_step = []
    actual_carried_by_step = []
    actual_sales_by_step = [defaultdict(float) for _ in range(total_steps)]
    actual_sales_floor_censored = [defaultdict(bool) for _ in range(total_steps)]
    actual_harvests_by_step = [defaultdict(float) for _ in range(total_steps)]

    for s_idx in range(total_steps):
        step_entry = steps[s_idx]
        cd_obs = step_entry[cd_seat]["observation"]
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

        # Check market actions executed by Crop Dusta at step s_idx
        cd_action = step_entry[cd_seat].get("action")
        if isinstance(cd_action, dict):
            market_orders = cd_action.get("market", [])
            for order in market_orders:
                if isinstance(order, list) and len(order) >= 3 and order[0] == "SELL":
                    item = order[1]
                    qty = float(order[2])
                    actual_sales_by_step[s_idx][item] += qty
                    mkt = cd_obs.get("market", {})
                    prices = mkt.get("prices", {})
                    if prices.get(item, 10) <= 1:
                        actual_sales_floor_censored[s_idx][item] = True

        # Check harvest actions executed by units
        # (Unit actions: HARVEST on ripe tile)
        farms = cd_obs.get("farms", [])
        if len(farms) > cd_seat and isinstance(farms[cd_seat], dict):
            tiles = farms[cd_seat].get("tiles", [])
            # Action check
            all_unit_acts = [cd_action.get("farmer", ["PASS"])] + cd_action.get("hands", []) if isinstance(cd_action, dict) else []
            all_pos = [farms[cd_seat].get("farmer", [4, 4])] + farms[cd_seat].get("hands", [])
            for u_idx, u_act in enumerate(all_unit_acts):
                if u_act and u_act[0] == "HARVEST" and u_idx < len(all_pos):
                    ux, uy = all_pos[u_idx]
                    if uy < len(tiles) and ux < len(tiles[uy]):
                        tile = tiles[uy][ux]
                        if isinstance(tile, dict) and tile.get("yield_units", 0) > 0:
                            prod = tile.get("crop") or (ANIMALS.get(tile.get("animal", ""), {}).get("product"))
                            if prod:
                                actual_harvests_by_step[s_idx][prod] += float(tile["yield_units"])

    # Base rates default fallback
    global_sale_rate = (calibrated_base_rates.get("global", 0.05) if calibrated_base_rates else 0.05)
    prod_sale_rate = (calibrated_base_rates.get("products", {}) if calibrated_base_rates else {})

    # Per-step evaluation metrics collectors
    step_records = []

    # Mock context and memory for observers
    mock_mem = {
        "opp_sales_step": {},
        "opp_sales_inferred": {},
        "opp_market_inference": {},
        "opp_sales_history": deque(maxlen=100),
    }
    prev_market_inv = None

    for s_idx in range(total_steps):
        obs_raw = steps[s_idx][obs_seat]["observation"]
        parsed_ctx = parse_observation(obs_raw)
        if parsed_ctx is None:
            continue

        opp_farm = parsed_ctx["opponent_farm"]
        day = parsed_ctx.get("day", 0)
        hour = parsed_ctx.get("hour", 0)

        # Update visible market drain ledger for mock_mem
        market_now = parsed_ctx.get("market", {})
        inv_now = market_now.get("inventory", {}) if isinstance(market_now, dict) else getattr(market_now, "inventory", {})
        step_sales = {}
        if prev_market_inv is not None:
            for p in PRODUCTS:
                delta_inv = inv_now.get(p, 10000) - prev_market_inv.get(p, 10000)
                # If inventory increased, someone sold
                if delta_inv > 0:
                    step_sales[p] = float(delta_inv)
                    mock_mem["opp_sales_inferred"][p] = mock_mem["opp_sales_inferred"].get(p, 0.0) + float(delta_inv)
                    mock_mem["opp_sales_history"].append((s_idx, p, float(delta_inv)))
        mock_mem["opp_sales_step"] = step_sales
        prev_market_inv = dict(inv_now)

        # -------------------------------------------------------------------
        # Predictor 1: Legacy Predictor
        # -------------------------------------------------------------------
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
        leg_forecast = legacy_forecast_prod(opp_farm, day)

        # -------------------------------------------------------------------
        # Predictor 2: Repaired Shadow Predictor
        # -------------------------------------------------------------------
        rep_telemetry = repaired_forecaster.update(opp_farm, parsed_ctx, mock_mem)
        rep_sell_scores = rep_telemetry.get("sell_intent_scores", {})
        rep_p_sale_4 = rep_telemetry.get("p_sale_next_4_turns", {})
        rep_shed_bounds = rep_telemetry.get("shed_bounds", {})
        rep_carried_bounds = rep_telemetry.get("carried_bounds", {})
        rep_shed_pt = rep_telemetry.get("shed_point_estimate", {})
        rep_prod_forecast = rep_telemetry.get("production_forecast", {})
        rep_next_sell_step = rep_telemetry.get("next_sell_step", s_idx + 1)

        # -------------------------------------------------------------------
        # Ground Truth for Horizons: 1, 4, 8, 24
        # -------------------------------------------------------------------
        act_shed = actual_shed_by_step[s_idx]
        act_carried = actual_carried_by_step[s_idx]

        horizons = [1, 4, 8, 24]
        actual_sold_h = {}
        for h in horizons:
            sold_h = defaultdict(float)
            for fut_s in range(s_idx + 1, min(total_steps, s_idx + 1 + h)):
                for p, q in actual_sales_by_step[fut_s].items():
                    sold_h[p] += q
            actual_sold_h[h] = sold_h

        # Classify game phase
        if day <= 4:
            phase = "early"
        elif day <= 15:
            phase = "mid"
        elif day <= 27:
            phase = "late"
        else:
            phase = "endgame"

        # Record step evaluation
        for p in PRODUCTS:
            act_s_units = act_shed.get(p, 0.0)
            act_c_units = act_carried.get(p, 0.0)

            # Shed bounds evaluation
            bnd = rep_shed_bounds.get(p, [0.0, 0.0])
            shed_cov = (bnd[0] <= act_s_units <= bnd[1]) if (act_s_units > 0 or bnd[1] > 0) else None
            shed_width = (bnd[1] - bnd[0]) if (act_s_units > 0 or bnd[1] > 0) else None
            shed_pt = rep_shed_pt.get(p, 0.0)
            shed_mae = abs(shed_pt - act_s_units) if (act_s_units > 0 or bnd[1] > 0) else None

            # Carried bounds evaluation
            c_bnd = rep_carried_bounds.get(p, [0.0, 0.0])
            carried_cov = (c_bnd[0] <= act_c_units <= c_bnd[1]) if (act_c_units > 0 or c_bnd[1] > 0) else None

            # Sales predictions & outcomes across horizons
            p_sale_record = {}
            for h in horizons:
                y = 1.0 if actual_sold_h[h].get(p, 0.0) >= 1.0 else 0.0

                # Predictors for horizon h:
                # 1. No sale
                pred_zero = 0.0
                # 2. Global base rate
                pred_global = global_sale_rate.get(h, 0.05) if isinstance(global_sale_rate, dict) else 0.05
                # 3. Product base rate
                pred_prod = prod_sale_rate.get(p, {}).get(h, pred_global)
                # 4. Legacy heuristic score
                pred_legacy = leg_sell_scores.get(p, 0.0)
                # 5. Repaired calibrated probability (scaled for horizon h)
                if h == 4:
                    pred_rep = rep_p_sale_4.get(p, 0.0)
                elif h == 1:
                    pred_rep = min(1.0, rep_p_sale_4.get(p, 0.0) * 0.35)
                elif h == 8:
                    pred_rep = min(1.0, rep_p_sale_4.get(p, 0.0) * 1.5)
                else:  # h == 24
                    pred_rep = min(1.0, rep_p_sale_4.get(p, 0.0) * 2.5)

                p_sale_record[h] = {
                    "y_actual": y,
                    "pred_zero": pred_zero,
                    "pred_global": pred_global,
                    "pred_prod": pred_prod,
                    "pred_legacy": pred_legacy,
                    "pred_repaired": pred_rep,
                    "brier_zero": (pred_zero - y) ** 2,
                    "brier_global": (pred_global - y) ** 2,
                    "brier_prod": (pred_prod - y) ** 2,
                    "brier_legacy": (pred_legacy - y) ** 2,
                    "brier_repaired": (pred_rep - y) ** 2,
                }

            step_records.append({
                "step": s_idx,
                "day": day,
                "hour": hour,
                "phase": phase,
                "product": p,
                "act_shed": act_s_units,
                "act_carried": act_c_units,
                "shed_cov": shed_cov,
                "shed_width": shed_width,
                "shed_mae": shed_mae,
                "carried_cov": carried_cov,
                "horizons": p_sale_record,
            })

    return {
        "replay_path": replay_path,
        "cd_seat": cd_seat,
        "total_steps": total_steps,
        "step_records": step_records,
        "actual_sales_total": {p: sum(actual_sales_by_step[s].get(p, 0) for s in range(total_steps)) for p in PRODUCTS},
        "actual_harvests_total": {p: sum(actual_harvests_by_step[s].get(p, 0) for s in range(total_steps)) for p in PRODUCTS},
    }
