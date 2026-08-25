"""Three-regime ROI matrices: spot base, town scarcity, competitive glut.

Regime price references (from the rules' P(I0-T) / P(I0+T) columns):
  - Spot base: equilibrium prices at I0.
  - Town scarcity: prices once shops have drained T units (P(I0-T)).
  - Competitive glut: depressed prices after heavy dumping (wheat forced to
    $10 per the spec; premiums sit at their $1 floor).

For each asset (5 crops + 3 animals):
  PPTD      = season net profit / tile-days
  ROCI %    = season net profit / capital invested
  Payback   = days until cumulative net >= 0
  Actions   = farmer actions / day / tile

Crop strategy is chosen automatically: fertilized vs unfertilized plans are
both evaluated and the more profitable one wins (recorded in `strategy`).
"""
import json

import action_budget_evaluator as abe
from animal_model import ANIMALS, PRODUCT_BASE, simulate_animal_lifecycle
from crop_model import CROPS, FERTILIZER_COST, OPTIMAL_FERT_DAYS, season_plan

SEASON_DAYS = 30
TILES = 25  # starting quadrant

SCARCITY_PRICES = {          # P(I0 - T) from the rules table
    "WHEAT": 45, "CARROT": 70, "TOMATO": 84, "STRAWBERRY": 204,
    "MELON": 300, "EGG": 70, "MILK": 256, "WOOL": 240,
}
GLUT_PRICES = {              # post-dump regime; wheat pinned to $10 by spec
    "WHEAT": 10, "CARROT": 10, "TOMATO": 24, "STRAWBERRY": 1,
    "MELON": 1, "EGG": 40, "MILK": 1, "WOOL": 1,
}


def _crop_metrics(crop, price, fertilized):
    plan = season_plan(crop, horizon=SEASON_DAYS, fertilized=fertilized, price=price)
    net = plan["season_revenue"] - plan["seed_cost"] - plan["fertilizer_cost"]
    actions = plan["plantings"] * abe.crop_cycle_actions(crop, fertilized)
    capital = plan["seed_cost"] + plan["fertilizer_cost"]
    pptd = net / SEASON_DAYS
    return {
        "asset": crop,
        "kind": "crop",
        "strategy": "fertilized" if fertilized else "unfertilized",
        "price_used": price,
        "season_yield": plan["season_yield"],
        "revenue": round(plan["season_revenue"], 2),
        "capital_invested": round(capital, 2),
        "net_profit": round(net, 2),
        "pptd": round(pptd, 2),
        "roci_pct": round(100 * net / capital, 1) if capital else 0.0,
        "payback_days": round(capital / (pptd if pptd > 0 else 1e-9), 2),
        "actions_per_day_per_tile": round(actions / SEASON_DAYS / TILES, 3),
    }


def evaluate_crop(crop, price):
    variants = [_crop_metrics(crop, price, fertilized=False),
                _crop_metrics(crop, price, fertilized=True)]
    best = max(variants, key=lambda m: m["net_profit"])
    best["alt_strategy_net"] = min(v["net_profit"] for v in variants)
    return best


def evaluate_animal(animal, price, fertilizer_sold=False,
                    care_policy="never", wheat_price=25):
    res = simulate_animal_lifecycle(animal, end_day=SEASON_DAYS,
                                    care_policy=care_policy,
                                    product_price=price,
                                    fertilizer_sold=fertilizer_sold,
                                    wheat_price=wheat_price)
    net = res["net_profit"]
    actions = res["days_owned"] * abe.animal_daily_actions(
        ANIMALS[animal]["interval"], care=(care_policy == "always"))
    return {
        "asset": animal,
        "kind": "animal",
        "strategy": f"care_{care_policy}" + ("+fert_sold" if fertilizer_sold else ""),
        "price_used": price,
        "product_harvested": res["product_harvested"],
        "fertilizer_collected": res["fertilizer_collected"],
        "revenue": round(res["gross_product_revenue"] + res["fertilizer_revenue"], 2),
        "capital_invested": ANIMALS[animal]["cost"],
        "feed_cost": res["feed_cost"],
        "net_profit": round(net, 2),
        "pptd": round(net / SEASON_DAYS, 2),
        "roci_pct": round(100 * net / ANIMALS[animal]["cost"], 1),
        "payback_days": round(ANIMALS[animal]["cost"] /
                              (net / SEASON_DAYS if net > 0 else 1e-9), 2),
        "actions_per_day_per_tile": round(actions / SEASON_DAYS, 3),
    }


def build_roi_matrices(fertilizer_sale_for_animals=False):
    matrices = {}
    for regime, price_map in (("spot_base", None), ("town_scarcity", SCARCITY_PRICES),
                              ("competitive_glut", GLUT_PRICES)):
        rows = {}
        for crop in CROPS:
            base_price = CROPS[crop]["base"]
            rows[crop] = evaluate_crop(crop, base_price if price_map is None else price_map[crop])
        for animal in ANIMALS:
            prod = ANIMALS[animal]["product"]
            p = PRODUCT_BASE[prod] if price_map is None else price_map[prod]
            rows[animal] = evaluate_animal(animal, p,
                                           fertilizer_sold=fertilizer_sale_for_animals)
        ranking = sorted(rows, key=lambda a: rows[a]["pptd"], reverse=True)
        matrices[regime] = {"assets": rows, "ranking_by_pptd": ranking}
    return matrices


def save_rankings(matrices, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matrices, f, indent=2)


if __name__ == "__main__":
    m = build_roi_matrices()
    for regime, data in m.items():
        print(regime, "->", data["ranking_by_pptd"])
