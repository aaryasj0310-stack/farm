"""Census metrics aggregation and reporting across five economic domains.

Processes raw events from CensusSession into structured diagnostics:
A. Capital Allocation
B. Productive Land Utilization
C. Crop Portfolio Economics
D. Worker Throughput
E. Livestock Economics
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from simulations.census.engine_instrumentation import (
    CensusSession,
    PRODUCT_BASE_PRICES,
    SEED_PRICES,
    ANIMAL_PRICES,
)


def summarize_match(session: CensusSession, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Compile comprehensive match-level census summary across all five domains."""
    # -------------------------------------------------------------
    # Domain A: Capital Allocation
    # -------------------------------------------------------------
    total_land_spend = sum(lp["cost"] for lp in session.land_purchases)
    total_hire_spend = sum(h["cost"] for h in session.hires)

    seed_spend_by_crop = defaultdict(float)
    seed_units_by_crop = defaultdict(int)
    animal_spend_by_type = defaultdict(float)
    animal_units_by_type = defaultdict(int)
    product_buy_spend = defaultdict(float)
    product_buy_units = defaultdict(int)

    sales_revenue_by_product = defaultdict(float)
    sales_units_by_product = defaultdict(int)

    for tx in session.executed_transactions:
        op = tx["op"]
        item = tx["item"]
        price = tx["price"]
        if op == "BUY_SEED":
            seed_spend_by_crop[item] += price
            seed_units_by_crop[item] += 1
        elif op == "BUY_ANIMAL":
            animal_spend_by_type[item] += price
            animal_units_by_type[item] += 1
        elif op == "BUY_PRODUCT":
            product_buy_spend[item] += price
            product_buy_units[item] += 1
        elif op == "SELL":
            sales_revenue_by_product[item] += price
            sales_units_by_product[item] += 1

    total_seed_spend = sum(seed_spend_by_crop.values())
    total_animal_spend = sum(animal_spend_by_type.values())
    total_product_buy_spend = sum(product_buy_spend.values())
    total_sales_revenue = sum(sales_revenue_by_product.values())

    total_capital_invested = (
        total_land_spend + total_hire_spend + total_seed_spend +
        total_animal_spend + total_product_buy_spend
    )

    # Terminal assets
    shed_final = session.our_private.get("shed", {}) if session.our_private else {}
    seeds_final = session.our_private.get("seeds", {}) if session.our_private else {}
    terminal_shed_units = sum(shed_final.values())
    terminal_shed_base_val = sum(cnt * PRODUCT_BASE_PRICES.get(itm, 25.0) for itm, cnt in shed_final.items())
    terminal_shed_spot_val = sum(
        cnt * float(session.current_market_prices.get(itm, PRODUCT_BASE_PRICES.get(itm, 25.0)))
        for itm, cnt in shed_final.items()
    )
    terminal_seeds_val = sum(cnt * SEED_PRICES.get(itm, 10.0) for itm, cnt in seeds_final.items())

    capital_domain = {
        "starting_cash": 3000.0,
        "final_cash": metadata.get("final_cash", 0.0),
        "total_sales_revenue": total_sales_revenue,
        "total_capital_invested": total_capital_invested,
        "breakdown_spending": {
            "land_spend": total_land_spend,
            "hire_spend": total_hire_spend,
            "seed_spend": total_seed_spend,
            "animal_spend": total_animal_spend,
            "product_buy_spend": total_product_buy_spend,
        },
        "seed_spend_by_crop": dict(seed_spend_by_crop),
        "seed_units_by_crop": dict(seed_units_by_crop),
        "animal_spend_by_type": dict(animal_spend_by_type),
        "animal_units_by_type": dict(animal_units_by_type),
        "product_buy_spend": dict(product_buy_spend),
        "product_buy_units": dict(product_buy_units),
        "sales_revenue_by_product": dict(sales_revenue_by_product),
        "sales_units_by_product": dict(sales_units_by_product),
        "executed_transactions_count": len(session.executed_transactions),
        "rejected_transactions_count": len(session.rejected_transactions),
        "terminal_assets": {
            "shed_units": terminal_shed_units,
            "shed_base_value": terminal_shed_base_val,
            "shed_spot_value": terminal_shed_spot_val,
            "seeds_cost_value": terminal_seeds_val,
            "shed_items": dict(shed_final),
            "unplanted_seeds": dict(seeds_final),
        }
    }

    # -------------------------------------------------------------
    # Domain B: Productive Land Utilization
    # -------------------------------------------------------------
    quadrants = ["NW", "NE", "SW", "SE"]
    quad_stats = {}
    for q in quadrants:
        quad_stats[q] = {
            "unlocked": session.quadrant_unlock_step[q] is not None,
            "unlock_step": session.quadrant_unlock_step[q],
            "unlock_day": (session.quadrant_unlock_step[q] // 24) if session.quadrant_unlock_step[q] is not None else None,
            "owned_tile_days": 0,
            "productive_tile_days": 0,  # PLANT + ANIMAL
            "plant_tile_days": 0,
            "animal_tile_days": 0,
            "structure_tile_days": 0,
            "weed_tile_days": 0,
            "idle_tile_days": 0,
            "utilization_rate": 0.0,
            "first_active_day": None,
            "idle_delay_days": None,
        }

    for day, census in session.daily_quadrant_census.items():
        for q in quadrants:
            q_data = census.get(q, {})
            locked = q_data.get("LOCKED", 0)
            if locked == 0:  # quadrant is owned
                quad_stats[q]["owned_tile_days"] += 25
                p = q_data.get("PLANT", 0)
                a = q_data.get("ANIMAL", 0)
                s = q_data.get("STRUCTURE", 0)
                w = q_data.get("WEED", 0)
                e = q_data.get("EMPTY", 0)
                quad_stats[q]["plant_tile_days"] += p
                quad_stats[q]["animal_tile_days"] += a
                quad_stats[q]["productive_tile_days"] += (p + a)
                quad_stats[q]["structure_tile_days"] += s
                quad_stats[q]["weed_tile_days"] += w
                quad_stats[q]["idle_tile_days"] += e

                if (p + a + s) > 0 and quad_stats[q]["first_active_day"] is None:
                    quad_stats[q]["first_active_day"] = day

    for q in quadrants:
        otd = quad_stats[q]["owned_tile_days"]
        if otd > 0:
            quad_stats[q]["utilization_rate"] = round(quad_stats[q]["productive_tile_days"] / otd, 4)
            if quad_stats[q]["unlock_day"] is not None and quad_stats[q]["first_active_day"] is not None:
                quad_stats[q]["idle_delay_days"] = max(0, quad_stats[q]["first_active_day"] - quad_stats[q]["unlock_day"])

    land_domain = {
        "quadrant_metrics": quad_stats,
        "total_owned_tile_days": sum(qs["owned_tile_days"] for qs in quad_stats.values()),
        "total_productive_tile_days": sum(qs["productive_tile_days"] for qs in quad_stats.values()),
        "total_idle_tile_days": sum(qs["idle_tile_days"] for qs in quad_stats.values()),
        "overall_utilization_rate": (
            round(sum(qs["productive_tile_days"] for qs in quad_stats.values()) / max(1, sum(qs["owned_tile_days"] for qs in quad_stats.values())), 4)
        ),
    }

    # -------------------------------------------------------------
    # Domain C: Crop Portfolio Economics
    # -------------------------------------------------------------
    crops = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
    crop_stats = {}
    for c in crops:
        crop_stats[c] = {
            "seeds_bought": seed_units_by_crop.get(c, 0),
            "seed_expenditure": seed_spend_by_crop.get(c, 0.0),
            "plantings_total": 0,
            "plantings_by_quadrant": {"NW": 0, "NE": 0, "SW": 0, "SE": 0},
            "waterings_total": 0,
            "fertilizations_total": 0,
            "harvest_actions": 0,
            "harvest_units": 0,
            "harvest_by_quadrant": {"NW": 0, "NE": 0, "SW": 0, "SE": 0},
            "sales_units": sales_units_by_product.get(c, 0),
            "realized_revenue": sales_revenue_by_product.get(c, 0.0),
            "avg_realized_price": (
                round(sales_revenue_by_product.get(c, 0.0) / max(1, sales_units_by_product.get(c, 0)), 2)
                if sales_units_by_product.get(c, 0) > 0 else 0.0
            ),
            "unsold_units": shed_final.get(c, 0),
            "discarded_units": sum(d["discarded"].get(c, 0) for d in session.midnight_discards),
            "gross_margin": sales_revenue_by_product.get(c, 0.0) - seed_spend_by_crop.get(c, 0.0),
            "labor_actions": 0,
        }

    for p in session.crop_plantings:
        c = p["crop"]
        if c in crop_stats:
            crop_stats[c]["plantings_total"] += 1
            crop_stats[c]["plantings_by_quadrant"][p.get("quadrant", "NW")] += 1

    for w in session.crop_waterings:
        c = w["crop"]
        if c in crop_stats:
            crop_stats[c]["waterings_total"] += 1

    for f in session.crop_fertilizations:
        c = f["crop"]
        if c in crop_stats:
            crop_stats[c]["fertilizations_total"] += 1

    for h in session.crop_harvests:
        c = h["crop"]
        if c in crop_stats:
            crop_stats[c]["harvest_actions"] += 1
            crop_stats[c]["harvest_units"] += h["units"]
            crop_stats[c]["harvest_by_quadrant"][h.get("quadrant", "NW")] += h["units"]

    for c in crops:
        crop_stats[c]["labor_actions"] = (
            crop_stats[c]["plantings_total"] +
            crop_stats[c]["waterings_total"] +
            crop_stats[c]["fertilizations_total"] +
            crop_stats[c]["harvest_actions"]
        )

    crop_domain = {
        "by_crop": crop_stats,
        "total_seed_expenditure": total_seed_spend,
        "total_harvest_units": sum(cs["harvest_units"] for cs in crop_stats.values()),
        "total_realized_crop_revenue": sum(cs["realized_revenue"] for cs in crop_stats.values()),
        "total_crop_gross_margin": sum(cs["gross_margin"] for cs in crop_stats.values()),
        "total_crop_labor_actions": sum(cs["labor_actions"] for cs in crop_stats.values()),
    }

    # -------------------------------------------------------------
    # Domain D: Worker Throughput
    # -------------------------------------------------------------
    action_counts = defaultdict(int)
    blocked_counts = defaultdict(int)
    quadrant_worker_turns = defaultdict(int)
    unit_total_actions = defaultdict(int)

    for wa in session.worker_actions:
        op = wa["op"]
        action_counts[op] += 1
        unit_total_actions[wa["unit_idx"]] += 1
        quadrant_worker_turns[wa["quadrant"]] += 1
        if not wa["success"] and op != "PASS":
            blocked_counts[op] += 1

    total_actions = len(session.worker_actions)
    move_ops = ("NORTH", "SOUTH", "EAST", "WEST")
    move_actions = sum(action_counts[m] for m in move_ops)
    idle_pass = action_counts["PASS"]
    blocked_actions = sum(blocked_counts.values())

    # Productive: plant, water, fertilize, harvest, deposit, animal service, build, dig
    productive_ops = {
        "PLANT", "WATER", "FERTILIZE", "HARVEST", "DROP", "PLACE",
        "FEED", "CARE", "COLLECT_FERTILIZER", "BUILD_COOP", "BUILD_PASTURE", "DIG", "PICKUP"
    }
    productive_actions = sum(action_counts[op] for op in productive_ops)

    worker_domain = {
        "total_worker_actions": total_actions,
        "action_breakdown": dict(action_counts),
        "blocked_breakdown": dict(blocked_counts),
        "quadrant_worker_turns": dict(quadrant_worker_turns),
        "productive_actions": productive_actions,
        "productive_utilization_pct": round(productive_actions / max(1, total_actions) * 100.0, 2),
        "travel_actions": move_actions,
        "travel_overhead_pct": round(move_actions / max(1, total_actions) * 100.0, 2),
        "idle_pass_actions": idle_pass,
        "idle_pass_pct": round(idle_pass / max(1, total_actions) * 100.0, 2),
        "blocked_actions": blocked_actions,
        "blocked_pct": round(blocked_actions / max(1, total_actions) * 100.0, 2),
        "hands_hired_count": len(session.hires),
    }

    # -------------------------------------------------------------
    # Domain E: Livestock Economics
    # -------------------------------------------------------------
    animals = ["GOOSE", "COW", "SHEEP"]
    animal_product_map = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
    animal_stats = {}

    for a in animals:
        prod = animal_product_map[a]
        animal_stats[a] = {
            "bought_count": animal_units_by_type.get(a, 0),
            "purchase_spend": animal_spend_by_type.get(a, 0.0),
            "placed_count": sum(1 for p in session.animal_placements if p["animal"] == a),
            "feed_actions": sum(1 for f in session.animal_feeds if f["animal"] == a),
            "care_actions": sum(1 for c in session.animal_cares if c["animal"] == a),
            "fertilizer_collected": sum(1 for fc in session.fertilizer_collections if fc.get("animal") == a),
            "product_harvest_units": sum(h["units"] for h in session.animal_harvests if h["product"] == prod),
            "product_sales_units": sales_units_by_product.get(prod, 0),
            "product_realized_revenue": sales_revenue_by_product.get(prod, 0.0),
            "unsold_product_units": shed_final.get(prod, 0),
            "discarded_product_units": sum(d["discarded"].get(prod, 0) for d in session.midnight_discards),
            "net_contribution": (
                sales_revenue_by_product.get(prod, 0.0) - animal_spend_by_type.get(a, 0.0)
                # Feed valued at base wheat price ($25)
                - sum(1 for f in session.animal_feeds if f["animal"] == a) * 25.0
            ),
        }

    # Fertilizer overall economics
    fert_stats = {
        "fertilizer_collected_total": len(session.fertilizer_collections),
        "fertilizer_applied_total": len(session.crop_fertilizations),
        "fertilizer_sales_units": sales_units_by_product.get("FERTILIZER", 0),
        "fertilizer_realized_revenue": sales_revenue_by_product.get("FERTILIZER", 0.0),
        "fertilizer_unsold_units": shed_final.get("FERTILIZER", 0),
        "fertilizer_discarded_units": sum(d["discarded"].get("FERTILIZER", 0) for d in session.midnight_discards),
    }

    livestock_domain = {
        "by_animal": animal_stats,
        "fertilizer": fert_stats,
        "total_livestock_spend": total_animal_spend,
        "total_product_revenue": sum(
            sales_revenue_by_product.get(animal_product_map[a], 0.0) for a in animals
        ),
        "total_feed_wheat_consumed": sum(ans["feed_actions"] for ans in animal_stats.values()),
        "total_livestock_labor_actions": (
            sum(ans["feed_actions"] + ans["care_actions"] + ans["fertilizer_collected"] for ans in animal_stats.values())
            + sum(h["units"] for h in session.animal_harvests)
        ),
    }

    # Storage discard summary
    discard_summary = {
        "total_discards_count": len(session.midnight_discards),
        "total_units_discarded": sum(d["discarded_total"] for d in session.midnight_discards),
        "total_base_value_lost": sum(d["base_value_lost"] for d in session.midnight_discards),
        "total_spot_value_lost": sum(d["spot_value_lost"] for d in session.midnight_discards),
    }

    return {
        "metadata": metadata,
        "capital": capital_domain,
        "land": land_domain,
        "crop": crop_domain,
        "worker": worker_domain,
        "livestock": livestock_domain,
        "storage": discard_summary,
    }


def aggregate_census_population(match_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute multi-match population statistics across all five domains."""
    n = len(match_summaries)
    if n == 0:
        return {}

    final_cashes = [m["capital"]["final_cash"] for m in match_summaries]
    total_revenues = [m["capital"]["total_sales_revenue"] for m in match_summaries]
    total_invested = [m["capital"]["total_capital_invested"] for m in match_summaries]

    # Land utilization
    overall_util = [m["land"]["overall_utilization_rate"] for m in match_summaries]
    nw_util = [m["land"]["quadrant_metrics"]["NW"]["utilization_rate"] for m in match_summaries]
    ne_util = [m["land"]["quadrant_metrics"]["NE"]["utilization_rate"] for m in match_summaries]
    sw_util = [m["land"]["quadrant_metrics"]["SW"]["utilization_rate"] for m in match_summaries]
    se_util = [m["land"]["quadrant_metrics"]["SE"]["utilization_rate"] for m in match_summaries]

    # Worker utilization
    productive_pct = [m["worker"]["productive_utilization_pct"] for m in match_summaries]
    travel_pct = [m["worker"]["travel_overhead_pct"] for m in match_summaries]
    idle_pct = [m["worker"]["idle_pass_pct"] for m in match_summaries]
    blocked_pct = [m["worker"]["blocked_pct"] for m in match_summaries]

    # Crop gross margins
    crop_names = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
    crop_margins = {c: [m["crop"]["by_crop"][c]["gross_margin"] for m in match_summaries] for c in crop_names}
    crop_revs = {c: [m["crop"]["by_crop"][c]["realized_revenue"] for m in match_summaries] for c in crop_names}
    crop_costs = {c: [m["crop"]["by_crop"][c]["seed_expenditure"] for m in match_summaries] for c in crop_names}

    # Livestock net contributions
    animal_names = ["GOOSE", "COW", "SHEEP"]
    animal_nets = {a: [m["livestock"]["by_animal"][a]["net_contribution"] for m in match_summaries] for a in animal_names}

    # Storage discards
    units_discarded = [m["storage"]["total_units_discarded"] for m in match_summaries]
    spot_val_lost = [m["storage"]["total_spot_value_lost"] for m in match_summaries]

    def _stats(arr):
        a = np.array(arr, dtype=float)
        return {
            "mean": float(np.mean(a)),
            "std": float(np.std(a, ddof=1)) if len(a) > 1 else 0.0,
            "median": float(np.median(a)),
            "p10": float(np.percentile(a, 10)),
            "p25": float(np.percentile(a, 25)),
            "p75": float(np.percentile(a, 75)),
            "p90": float(np.percentile(a, 90)),
        }

    return {
        "total_matches": n,
        "cash_distribution": _stats(final_cashes),
        "revenue_distribution": _stats(total_revenues),
        "investment_distribution": _stats(total_invested),
        "land_utilization": {
            "overall": _stats(overall_util),
            "NW": _stats(nw_util),
            "NE": _stats(ne_util),
            "SW": _stats(sw_util),
            "SE": _stats(se_util),
        },
        "worker_throughput": {
            "productive_pct": _stats(productive_pct),
            "travel_pct": _stats(travel_pct),
            "idle_pct": _stats(idle_pct),
            "blocked_pct": _stats(blocked_pct),
        },
        "crop_economics": {
            c: {
                "margin": _stats(crop_margins[c]),
                "revenue": _stats(crop_revs[c]),
                "cost": _stats(crop_costs[c]),
            } for c in crop_names
        },
        "livestock_economics": {
            a: _stats(animal_nets[a]) for a in animal_names
        },
        "storage_discards": {
            "units_destroyed": _stats(units_discarded),
            "spot_value_lost": _stats(spot_val_lost),
        }
    }
