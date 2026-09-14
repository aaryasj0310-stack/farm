"""Fit empirical opponent behavior tables strictly on the 20 calibration replays.

Learns:
1. Empirical collection hazard: P(collect in turn t | product, phase, turns_since_ripe_bin)
2. Behavioral manual deposit hazard: P(manual shed deposit | worker on shed tile, hour != 0)
3. Empirical conditional sell hazard tables: P(sale in next H turns | product, phase, shed_bin, price_ratio_bin, is_drain)

Outputs frozen tables to simulations/opponent_benchmark/empirical_behavior_tables.json.
"""

import os
import sys
import json
from collections import defaultdict
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
for sub in ("", "state", "strategy", "execution", "market"):
    p = os.path.join(AGENT_DIR, sub) if sub else AGENT_DIR
    if p not in sys.path:
        sys.path.insert(0, p)

from config import PRODUCTS, CROPS, ANIMALS, MARKET_PARAMS

HORIZONS = [1, 4, 8, 24]
PHASES = ["early", "mid", "late", "endgame"]
RIPE_BINS = ["0-4", "5-12", "13-24", "25-48", "49+"]
SHED_BINS = ["0", "1-4", "5-10", "11-20", "21+"]
PRICE_BINS = ["depressed", "normal", "elevated"]


def get_phase(day: int) -> str:
    if day <= 4:
        return "early"
    elif day <= 15:
        return "mid"
    elif day <= 27:
        return "late"
    return "endgame"


def get_ripe_bin(turns: int) -> str:
    if turns <= 4:
        return "0-4"
    elif turns <= 12:
        return "5-12"
    elif turns <= 24:
        return "13-24"
    elif turns <= 48:
        return "25-48"
    return "49+"


def get_shed_bin(units: float) -> str:
    if units <= 0.0:
        return "0"
    elif units <= 4.0:
        return "1-4"
    elif units <= 10.0:
        return "5-10"
    elif units <= 20.0:
        return "11-20"
    return "21+"


def get_price_bin(prod: str, price: float) -> str:
    base = MARKET_PARAMS.get(prod, {}).get("base", 50)
    ratio = price / base if base > 0 else 1.0
    if ratio < 0.8:
        return "depressed"
    elif ratio <= 1.2:
        return "normal"
    return "elevated"


def fit_tables():
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        mf = json.load(f)

    source_dir = mf["source_dir"]
    calib_recs = [r for r in mf["records"] if r["split"] == "calibration"]
    print(f"Fitting behavior models on {len(calib_recs)} calibration replays...")

    # 1. Collection hazard trackers: (prod, phase, ripe_bin) -> {exposure: int, harvests: int}
    coll_stats = defaultdict(lambda: {"exposure": 0, "harvests": 0})

    # 2. Manual deposit tracker: worker on shed tile -> {exposure: int, deposits: int}
    shed_deposit_stats = {"exposure": 0, "deposits": 0}

    # 3. Sell hazard trackers: (prod, H, phase, shed_bin, price_bin, is_drain) -> {exposure: int, sales: int}
    sell_stats = defaultdict(lambda: {"exposure": 0, "sales": 0})

    for rec in calib_recs:
        fpath = os.path.join(source_dir, rec["filename"])
        cd_seat = rec["crop_dusta_seat"]
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        steps = data if isinstance(data, list) else data.get("steps", [])
        n_steps = len(steps)

        # Pre-extract ground truth
        actual_shed = []
        actual_carried = []
        actual_sales = [defaultdict(float) for _ in range(n_steps)]
        worker_on_shed = [False] * n_steps

        for s_idx in range(n_steps):
            st = steps[s_idx]
            cd_obs = st[cd_seat]["observation"]
            priv = cd_obs.get("private", {})
            if not isinstance(priv, dict):
                priv = getattr(priv, "__dict__", {})

            shed = priv.get("shed", {})
            actual_shed.append({p: float(shed.get(p, 0)) for p in PRODUCTS})

            inventories = priv.get("inventories", [])
            tot_c = defaultdict(float)
            for inv in inventories:
                if isinstance(inv, dict):
                    for p, q in inv.items():
                        tot_c[p] += float(q)
            actual_carried.append(dict(tot_c))

            # Actions
            act = st[cd_seat].get("action")
            if isinstance(act, dict):
                for o in act.get("market", []):
                    if isinstance(o, list) and len(o) >= 3 and o[0] == "SELL":
                        actual_sales[s_idx][o[1]] += float(o[2])

            # Check if any worker is on shed access tiles: (4,4), (4,5), (5,4), (5,5)
            farms = cd_obs.get("farms", [])
            if len(farms) > cd_seat and isinstance(farms[cd_seat], dict):
                all_pos = [farms[cd_seat].get("farmer", (4, 4))] + farms[cd_seat].get("hands", [])
                on_shed = any(tuple(pos) in [(4, 4), (4, 5), (5, 4), (5, 5)] for pos in all_pos)
                has_carried = sum(tot_c.values()) > 0
                worker_on_shed[s_idx] = (on_shed and has_carried)

        # Track collection hazard & manual deposits
        prev_tiles = {}
        for s_idx in range(n_steps):
            st = steps[s_idx]
            cd_obs = st[cd_seat]["observation"]
            day = s_idx // 24
            hour = s_idx % 24
            phase = get_phase(day)

            # Manual deposit tracking (hour != 0 to avoid conflating with EOD auto-drop)
            if hour != 0 and worker_on_shed[s_idx]:
                shed_deposit_stats["exposure"] += 1
                # check if shed increased in step s_idx
                if s_idx > 0:
                    delta_shed = sum(actual_shed[s_idx].values()) - sum(actual_shed[s_idx - 1].values())
                    if delta_shed > 0:
                        shed_deposit_stats["deposits"] += 1

            farms = cd_obs.get("farms", [])
            if len(farms) > cd_seat and isinstance(farms[cd_seat], dict):
                tiles = farms[cd_seat].get("tiles", [])
                for y, row in enumerate(tiles):
                    for x, t in enumerate(row):
                        key = (x, y)
                        prev = prev_tiles.get(key)
                        if isinstance(t, dict):
                            y_units = t.get("yield_units", 0)
                            prod = t.get("crop") or (ANIMALS.get(t.get("animal", ""), {}).get("product"))
                            if y_units > 0 and (prev is None or prev["yield"] == 0):
                                prev_tiles[key] = {"prod": prod, "yield": y_units, "ripe_since": s_idx}
                            elif prev and prev["yield"] > 0:
                                turns_ripe = s_idx - prev["ripe_since"]
                                r_bin = get_ripe_bin(turns_ripe)
                                coll_stats[(prev["prod"], phase, r_bin)]["exposure"] += 1
                                if y_units == 0:
                                    coll_stats[(prev["prod"], phase, r_bin)]["harvests"] += 1
                                    prev_tiles[key] = {"prod": prod, "yield": 0, "ripe_since": None}
                                else:
                                    prev["yield"] = y_units
                        else:
                            if prev and prev["yield"] > 0:
                                turns_ripe = s_idx - prev["ripe_since"]
                                r_bin = get_ripe_bin(turns_ripe)
                                coll_stats[(prev["prod"], phase, r_bin)]["exposure"] += 1
                                coll_stats[(prev["prod"], phase, r_bin)]["harvests"] += 1
                            prev_tiles[key] = None

            # Track sell hazard across horizons
            prices = cd_obs.get("market", {}).get("prices", {})
            is_drain = (hour % 4 in (0, 1))

            for p in PRODUCTS:
                s_units = actual_shed[s_idx].get(p, 0.0)
                s_bin = get_shed_bin(s_units)
                p_bin = get_price_bin(p, prices.get(p, 50))

                for h in HORIZONS:
                    sold_qty = 0.0
                    for fut_s in range(s_idx + 1, min(n_steps, s_idx + 1 + h)):
                        sold_qty += actual_sales[fut_s].get(p, 0.0)
                    y_sold = 1 if sold_qty >= 1.0 else 0

                    key = (p, h, phase, s_bin, p_bin, is_drain)
                    sell_stats[key]["exposure"] += 1
                    if y_sold:
                        sell_stats[key]["sales"] += 1

    # Format collection hazard table
    collection_hazard_table = {}
    for (p, phase, r_bin), counts in coll_stats.items():
        if p not in collection_hazard_table:
            collection_hazard_table[p] = {}
        if phase not in collection_hazard_table[p]:
            collection_hazard_table[p][phase] = {}
        exp = counts["exposure"]
        harv = counts["harvests"]
        # Laplace smoothing (alpha=1, beta=20)
        p_hazard = (harv + 1.0) / (exp + 20.0) if exp > 0 else 0.05
        collection_hazard_table[p][phase][r_bin] = round(p_hazard, 4)

    # Format manual deposit probability
    manual_dep_p = (shed_deposit_stats["deposits"] + 1.0) / (shed_deposit_stats["exposure"] + 10.0)

    # Format conditional sell hazard table
    # Stored as nested dict: [p][h][phase][s_bin][p_bin][is_drain] -> prob
    conditional_sell_hazard = {}
    for (p, h, phase, s_bin, p_bin, is_drain), counts in sell_stats.items():
        if p not in conditional_sell_hazard:
            conditional_sell_hazard[p] = {}
        h_str = str(h)
        if h_str not in conditional_sell_hazard[p]:
            conditional_sell_hazard[p][h_str] = {}
        if phase not in conditional_sell_hazard[p][h_str]:
            conditional_sell_hazard[p][h_str][phase] = {}
        if s_bin not in conditional_sell_hazard[p][h_str][phase]:
            conditional_sell_hazard[p][h_str][phase][s_bin] = {}
        if p_bin not in conditional_sell_hazard[p][h_str][phase][s_bin]:
            conditional_sell_hazard[p][h_str][phase][s_bin][p_bin] = {}

        exp = counts["exposure"]
        sls = counts["sales"]
        # Empirical probability with light prior smoothing
        prob = (sls + 1.0) / (exp + 10.0) if exp > 0 else 0.05
        conditional_sell_hazard[p][h_str][phase][s_bin][p_bin][str(is_drain)] = round(prob, 4)

    output = {
        "metadata": {
            "source_split": "calibration",
            "games_count": len(calib_recs),
            "description": "Empirical hazard tables learned strictly from calibration split without future-leakage",
        },
        "collection_hazard_table": collection_hazard_table,
        "behavioral_manual_deposit_rate": round(manual_dep_p, 4),
        "conditional_sell_hazard": conditional_sell_hazard,
    }

    out_path = os.path.join(os.path.dirname(__file__), "empirical_behavior_tables.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Successfully wrote empirical behavior tables to {out_path}!")


if __name__ == "__main__":
    fit_tables()
