"""W4: Distributional ROI — replaces point-regime prices with the validated
exhaustive-price reference (E[P | day] paths, floor probability, quantiles).

Legacy three-point regimes (`roi_matrix_engine.build_roi_matrices`) remain
untouched and remain the default; this module is opt-in via
`cli.py --reference <npz>` so old-vs-new can be compared side by side.

Pricing model upgrade per asset:
  crops   revenue = cycle_yield * sum(E[P|harvest_day]) across replant cycles
  animals revenue = season_output * mean(E[P|production/sale days])
plus new distributional metrics: floor-risk share, P10/P90 price bands.
"""
import json

import numpy as np

_QLEVELS = {"q05": 0.05, "q10": 0.10, "q25": 0.25, "q50": 0.50,
            "q75": 0.75, "q90": 0.90, "q95": 0.95}


class ReferencePrices:
    """Numpy-native view over an exhaustive reference npz (dev/offline tool)."""

    def __init__(self, path):
        z = np.load(path, allow_pickle=False)
        self.meta = json.loads(str(z["meta"]))
        self.scenario = self.meta.get("scenario", "unknown")
        self.complete = bool(self.meta.get("complete_enumeration", False))
        self.count = int(z["count"])
        self.products = list(self.meta["products"])
        self._idx = {p: i for i, p in enumerate(self.products)}
        self.mean = z["mean"].astype(np.float64)            # (30, 9)
        self.floor_prob = z["floor_prob"].astype(np.float64)
        self.hist = z["hist"]
        # Quantiles are derived exactly from the integer-mass histograms
        # (same procedure as agent/strategy/price_forecast.from_reference).
        self._qcache = {}

    def quantile_path(self, product, key):
        # cache keyed by (product, key): a level-only key leaked one product's
        # path into another during multi-crop loops.
        cache_key = (product, key)
        if cache_key in self._qcache:
            return self._qcache[cache_key].copy()
        level = _QLEVELS[key]           # KeyError => invalid key, fine
        i = self.idx(product)
        target = level * self.count
        cdf = np.cumsum(self.hist[:, i, :].astype(np.int64), axis=-1)
        idxs = (cdf >= target).argmax(axis=-1).astype(np.float64)
        self._qcache[cache_key] = idxs
        return idxs.copy()

    def idx(self, product):
        return self._idx[product]

    def expected_path(self, product):
        return self.mean[:, self.idx(product)]

    def floor_path(self, product):
        return self.floor_prob[:, self.idx(product)]

    def expected_over_days(self, product, days):
        e = self.expected_path(product)
        return float(np.mean([e[min(max(int(d), 0), len(e) - 1)] for d in days]))


def _crop_metrics_distributional(crop, ref, fertilized, FERT_COST=100):
    """Mirror of roi_matrix_engine._crop_metrics but priced by E[P|day]."""
    from crop_model import default_harvest_day, season_plan
    from crop_model import OPTIMAL_FERT_DAYS
    plan = season_plan(crop, horizon=30, fertilized=fertilized)
    hday = default_harvest_day(crop, fertilized)
    cyc = hday + 1
    harvest_days = [s + hday for s in range(plan["plantings"])]
    cycle_yield = (plan["season_yield"] / plan["plantings"]) if plan["plantings"] else 0.0
    revenue = cycle_yield * sum(ref.expected_path(crop)[hd] for hd in harvest_days)

    apps = plan["plantings"] * len(OPTIMAL_FERT_DAYS[crop]) if fertilized else 0
    capital = plan["seed_cost"] + apps * FERT_COST
    net = revenue - capital
    pptd = net / 30.0

    # distributional extras
    fp = ref.floor_path(crop)
    floor_risk = (sum(fp[hd] for hd in harvest_days) / len(harvest_days)) \
        if harvest_days else 0.0
    q10 = ref.quantile_path(crop, "q10")
    q90 = ref.quantile_path(crop, "q90")
    p10 = min((q10[hd] for hd in harvest_days), default=0.0)
    p90 = max((q90[hd] for hd in harvest_days), default=0.0)

    actions = plan["watering_actions"] + 2 * plan["plantings"]
    return {
        "asset": crop, "kind": "crop",
        "strategy": "fertilized" if fertilized else "unfertilized",
        "price_model": f"exhaustive E[P|day] ({ref.scenario})",
        "harvest_days": harvest_days,
        "season_yield": plan["season_yield"],
        "revenue": round(revenue, 2),
        "capital_invested": round(capital, 2),
        "net_profit": round(net, 2),
        "pptd": round(pptd, 2),
        "roci_pct": round(100 * net / capital, 1) if capital else 0.0,
        "payback_days": round(capital / pptd, 2) if pptd > 0 else None,
        "actions_per_day_per_tile": round(
            actions / 30.0 / 25.0, 3),
        "floor_risk_pct": round(100 * floor_risk, 3),
        "price_p10": round(float(p10), 2),
        "price_p90": round(float(p90), 2),
    }


def _animal_metrics_distributional(animal, ref, ANIMALS, fertilizer_sold=False,
                                   care_policy="never", wheat_price=25.0):
    from animal_model import simulate_animal_lifecycle
    res = simulate_animal_lifecycle(animal, end_day=30,
                                    care_policy=care_policy,
                                    fertilizer_sold=False,
                                    wheat_price=wheat_price)
    prod = ANIMALS[animal]["product"]
    first = ANIMALS[animal]["delay"]
    interval = ANIMALS[animal]["interval"]
    sale_days = list(range(first, 30, interval))
    e_price = ref.expected_over_days(prod, sale_days)
    revenue = res["product_harvested"] * e_price
    if fertilizer_sold:
        fert_days = list(range(res["days_owned"]))
        e_fert = ref.expected_over_days("FERTILIZER", fert_days)
        revenue += res["fertilizer_collected"] * e_fert
    net = revenue - res["feed_cost"] - res["purchase_cost"]
    fp = ref.floor_path(prod)
    floor_risk = float(np.mean([fp[d] for d in sale_days])) if sale_days else 0.0
    return {
        "asset": animal, "kind": "animal",
        "strategy": f"care_{care_policy}" + ("+fert_sold" if fertilizer_sold else ""),
        "price_model": f"exhaustive E[P|sale-day] ({ref.scenario})",
        "product_harvested": res["product_harvested"],
        "revenue": round(revenue, 2),
        "capital_invested": ANIMALS[animal]["cost"],
        "feed_cost": res["feed_cost"],
        "net_profit": round(net, 2),
        "pptd": round(net / 30.0, 2),
        "roci_pct": round(100 * net / ANIMALS[animal]["cost"], 1),
        "payback_days": round(ANIMALS[animal]["cost"] /
                              (net / 30.0), 2) if net > 0 else None,
        "floor_risk_pct": round(100 * floor_risk, 3),
    }


def build_distributional_matrices(reference_path,
                                  fertilizer_sale_for_animals=False,
                                  care_policy="never",
                                  wheat_price=25.0):
    """Same contract as roi_matrix_engine.build_roi_matrices, priced by E[P|day].

    Crop fertilizer variant chosen by higher distributional net (mirrors
    legacy evaluate_crop selection logic).
    """
    ref = ReferencePrices(reference_path)
    from crop_model import CROPS
    from animal_model import ANIMALS

    rows = {}
    for crop in CROPS:
        variants = [
            _crop_metrics_distributional(crop, ref, fertilized=f)
            for f in (False, True)
        ]
        best = max(variants, key=lambda m: m["net_profit"])
        best.pop("_alt_probe", None)
        rows[crop] = best
    for animal in ANIMALS:
        rows[animal] = _animal_metrics_distributional(
            animal, ref, ANIMALS,
            fertilizer_sold=fertilizer_sale_for_animals,
            care_policy=care_policy, wheat_price=wheat_price)

    ranking = sorted(rows, key=lambda a: rows[a]["pptd"], reverse=True)
    return {
        "assets": rows,
        "ranking_by_pptd": ranking,
        "scenario": ref.scenario,
        "complete_enumeration": ref.complete,
        "price_model": f"exhaustive E[P|day] ({ref.scenario})",
    }
