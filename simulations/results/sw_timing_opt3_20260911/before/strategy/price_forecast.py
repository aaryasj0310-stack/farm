"""W1: Validated price distributions -> agent-consumable forecasts.

Reads the exhaustive enumeration reference (population-exact statistics over
all 8^8 shop sequences) and exposes decision-grade queries:

    PriceForecast.load()                    # baked table -> npz fallback
    f.expected_price("MELON", 21)           # E[P | day]
    f.prob_above("CARROT", 15, 100)         # P(P > threshold | day)
    f.prob_floor("MELON", 25)               # P(price == $1 | day)
    f.quantile("WOOL", 20, 0.9)             # exact-at-knot quantiles

Bundling constraint: the Kaggle submission is a single file with no repo
access, so numpy lives ONLY inside `from_reference` (dev-time). Runtime uses
a plain-dict table that is either imported from the generated
`baked_price_table.py` module or passed in directly. Regenerate with:

    python price_forecast.py --build-table

Reference schema produced by simulations/monte_carlo_shops/exhaustive_enumerator.py.
"""
import json
import os

# Repo layout: <root>/agent/strategy/price_forecast.py
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE)) if "_HERE" in globals() else os.getcwd()
DEFAULT_REFERENCE = os.path.join(
    _REPO_ROOT, "simulations", "monte_carlo_shops", "results", "exhaustive",
    "town_only_reference.npz")
DEFAULT_BAKED = os.path.join(_HERE, "baked_price_table.py")

QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
TABLE_VERSION = 1


def _round_floats(value, nd=4):
    if isinstance(value, float):
        return round(value, nd)
    if isinstance(value, list):
        return [_round_floats(v, nd) for v in value]
    if isinstance(value, dict):
        return {k: _round_floats(v, nd) for k, v in value.items()}
    return value


class PriceForecast:
    """Decision-grade view over an exhaustive price reference table.

    DAY-CELL SEMANTICS (important for consumers): cell `day=h` holds the
    market state after day h's town-consumption ticks are applied -- i.e. the
    state sellers actually face during day h's action window (the town center
    drains at hour 0, before the t%4==1 sell windows). Example: day 0 already
    includes one TC tick, so WHEAT day-0 E[P] = quote(I0 - 1) = $26.
    """

    def __init__(self, table):
        if table.get("version") != TABLE_VERSION:
            raise ValueError(f"unsupported price table version {table.get('version')}")
        self.table = table
        self.products = list(table["products"])
        self.n_days = int(table["days"])
        self.scenario = table.get("scenario", "unknown")
        self._idx = {p: i for i, p in enumerate(self.products)}
        # Sanitized per-product threshold anchors: grid rows are padded with
        # trailing $1 entries; tail columns for equal thresholds are equal,
        # so keep first occurrence and sort ascending.
        self._anchors = {}
        for p in self.products:
            pairs = {}
            for j, gval in enumerate(table["grid"][p]):
                gval = int(gval)
                if gval not in pairs:
                    pairs[gval] = table["tail_prob"][p][j]
            self._anchors[p] = sorted(pairs.items())

    # ------------------------------------------------------------ loaders --
    @classmethod
    def from_table(cls, table):
        return cls(table)

    @classmethod
    def from_reference(cls, path=DEFAULT_REFERENCE):
        """Dev-time loader (requires numpy); produces the compact table."""
        import numpy as np  # dev-time only: never imported at submission runtime

        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        products = meta["products"]
        n_days = int(z["mean"].shape[0])
        count = float(z["count"])

        def by_product(arr):
            return {p: [round(float(v), 4) for v in arr[:, i]]
                    for i, p in enumerate(products)}

        hist = z["hist"].astype(np.int64)
        cdf = np.cumsum(hist, axis=-1)
        quantiles = {}
        for level in QUANTILE_LEVELS:
            key = f"q{int(round(level * 100)):02d}"
            target = level * count
            vals = {}
            for i, p in enumerate(products):
                col = []
                for d in range(n_days):
                    row = cdf[d, i]
                    v = int(np.searchsorted(row, target, side="left"))
                    col.append(min(v, HIST_CAP))
                vals[p] = col
            quantiles[key] = vals

        grid = z["grid"]
        tail = z["tail_prob"]          # (n_prod, G, n_days)
        grid_t = {}
        tail_t = {}
        for i, p in enumerate(products):
            seen = {}
            for j in range(grid.shape[1]):
                gval = int(grid[i, j])
                if gval not in seen:
                    seen[gval] = [round(float(v), 6) for v in tail[i, j]]
            pairs = sorted(seen.items())
            grid_t[p] = [g for g, _ in pairs]
            tail_t[p] = [t for _, t in pairs]

        table = {
            "version": TABLE_VERSION,
            "scenario": meta.get("scenario", "unknown"),
            "complete_enumeration": bool(meta.get("complete_enumeration", False)),
            "count": int(count),
            "days": n_days,
            "products": products,
            "mean": by_product(z["mean"]),
            "std": by_product(z["std"]),
            "floor_prob": by_product(z["floor_prob"]),
            "quantiles": quantiles,
            "grid": grid_t,
            "tail_prob": tail_t,
        }
        return cls(_round_floats(table))

    @staticmethod
    def load(reference_path=None):
        """Baked module first, then npz reference. Raises if neither exists."""
        if "PRICE_TABLE" in globals():
            return PriceForecast.from_table(globals()["PRICE_TABLE"])
        try:
            from baked_price_table import PRICE_TABLE      # bundled flat layout
            return PriceForecast.from_table(PRICE_TABLE)
        except ImportError:
            pass
        try:
            from strategy.baked_price_table import PRICE_TABLE   # package layout
            return PriceForecast.from_table(PRICE_TABLE)
        except ImportError:
            pass
        path = reference_path or DEFAULT_REFERENCE
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"no baked_price_table and no reference at {path}; "
                f"build one via: python price_forecast.py --build-table")
        return PriceForecast.from_reference(path)

    # ----------------------------------------------------------- queries ---
    def _day(self, day):
        return max(0, min(int(day), self.n_days - 1))

    def expected_price(self, product, day):
        return self.table["mean"][product][self._day(day)]

    def std_price(self, product, day):
        return self.table["std"][product][self._day(day)]

    def prob_floor(self, product, day):
        return self.table["floor_prob"][product][self._day(day)]

    def prob_above(self, product, day, threshold):
        """P(price > threshold | day). Exact on grid anchors; linear interp
        between anchors; clamped to anchor values outside the grid range."""
        anchors = self._anchors[product]
        d = self._day(day)
        t = float(threshold)
        if t <= anchors[0][0]:
            return anchors[0][1][d]
        if t >= anchors[-1][0]:
            return anchors[-1][1][d]
        for (g0, t0), (g1, t1) in zip(anchors, anchors[1:]):
            if g0 < t <= g1:
                w = (t - g0) / float(g1 - g0)
                return t0[d] + w * (t1[d] - t0[d])
        return anchors[-1][1][d]

    def quantile(self, product, day, q):
        """Price quantile, piecewise-linear across the baked knot levels.

        Exact at baked knots (integer prices); +/- $1 between knots.
        """
        qs = self.table["quantiles"]
        keys = sorted(qs.keys())
        levels = [int(k[1:]) / 100.0 for k in keys]
        qq = min(max(float(q), 0.0), 1.0)
        d = self._day(day)
        vals = []
        for k in keys:
            row = qs[k][product]
            vals.append(row[d] if d < len(row) else row[-1])
        if qq <= levels[0]:
            return vals[0]
        if qq >= levels[-1]:
            return vals[-1]
        for l0, l1, v0, v1 in zip(levels, levels[1:], vals, vals[1:]):
            if l0 <= qq <= l1:
                w = (qq - l0) / (l1 - l0) if l1 > l0 else 0.0
                return v0 + w * (v1 - v0)
        return vals[-1]

    def summary(self, day):
        out = {"scenario": self.scenario, "day": self._day(day)}
        for p in self.products:
            out[p] = {
                "E": self.expected_price(p, day),
                "p_floor": self.prob_floor(p, day),
            }
        return out


HIST_CAP = 20000   # overflow bucket index used by the enumerator's histogram


def export_table_literal(table):
    """Python source literal for baking into the bundled submission."""
    import pprint
    return "# Auto-generated by price_forecast.py --build-table. Do not edit.\n" \
           "PRICE_TABLE = " + pprint.pformat(_round_floats(table, 4),
                                             sort_dicts=False, width=96) + "\n"


def write_baked_table(table, path=DEFAULT_BAKED):
    src = export_table_literal(table.table if isinstance(table, PriceForecast)
                               else table)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    return path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="W1 price forecast utility")
    ap.add_argument("--reference", type=str, default=DEFAULT_REFERENCE)
    ap.add_argument("--build-table", action="store_true",
                    help=f"write compact table to {DEFAULT_BAKED}")
    ap.add_argument("--print-sample", type=int, default=None,
                    help="print E[P]/P(floor) for every product on a given day")
    args = ap.parse_args(argv)

    fc = PriceForecast.from_reference(args.reference)
    print(f"reference: scenario={fc.scenario} complete="
          f"{fc.table['complete_enumeration']} days={fc.n_days} "
          f"sequences={fc.table['count']:,}")
    if args.print_sample is not None:
        for line in json.dumps(fc.summary(args.print_sample), indent=2).splitlines():
            print(line)
    if args.build_table:
        path = write_baked_table(fc)
        size_kb = os.path.getsize(path) / 1024
        print(f"baked table -> {path} ({size_kb:.1f} KB)")
    return fc


if __name__ == "__main__":
    main()
