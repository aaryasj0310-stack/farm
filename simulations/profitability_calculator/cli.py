"""Unified CLI for the Crop & Livestock Profitability Calculator.

Examples:
    python cli.py --crop-roi --all-crops
    python cli.py --animal-roi --include-fertilizer-sale
    python cli.py --endgame-cutoffs
    python cli.py --generate-report --output results/profitability_report.md
"""
import argparse
import json
import os

from action_budget_evaluator import labor_scaling
from animal_model import ANIMALS
from crop_model import CROPS
from endgame_cutoff_planner import build_cutoff_table
from roi_matrix_engine import build_roi_matrices, save_rankings


def _print_rows(rows):
    keys = ["asset", "strategy", "price_used", "season_yield",
            "net_profit", "pptd", "roci_pct", "payback_days"]
    print(" | ".join(k.replace("_", " ") for k in keys))
    for r in rows:
        print(" | ".join(str(r.get(k, "")) for k in keys))


def cmd_crop_roi(args):
    matrices = build_roi_matrices()
    regime = args.regime if args.regime in matrices else "spot_base"
    data = matrices[regime]["assets"]
    crops = list(CROPS) if args.all_crops else [args.crop.upper()]
    rows = [data[c] for c in crops if c in data]
    print(f"== CROP ROI ({regime}) ==")
    _print_rows(rows)
    if args.reference:
        from distributional_roi import build_distributional_matrices
        dist = build_distributional_matrices(
            args.reference, fertilizer_sale_for_animals=False)
        print(f"== CROP ROI (distributional | {dist['price_model']}) ==")
        drows = [dist["assets"][c] for c in crops if c in dist["assets"]]
        keys = ["asset", "strategy", "net_profit", "pptd", "roci_pct",
                "floor_risk_pct", "price_p10", "price_p90"]
        print(" | ".join(keys))
        for r in drows:
            print(" | ".join(str(r.get(k, "")) for k in keys))


def cmd_animal_roi(args):
    matrices = build_roi_matrices(fertilizer_sale_for_animals=args.include_fertilizer_sale)
    data = matrices["spot_base"]["assets"]
    rows = [data[a] for a in ANIMALS]
    extra = " (incl. fertilizer sold @$100)" if args.include_fertilizer_sale else ""
    print(f"== ANIMAL ROI (spot base){extra} ==")
    _print_rows(rows)
    print("\nlabor scaling by farm size:")
    for row in labor_scaling():
        print(" ", row)


def cmd_endgame_cutoffs(args):
    table = build_cutoff_table()
    for asset, v in table.items():
        cuts = {k: w for k, w in v.items() if "cutoff" in k}
        print(f"{asset:12s} {cuts}")


def generate_report(path, fertilizer_sale=False, reference=None):
    matrices = build_roi_matrices(fertilizer_sale_for_animals=fertilizer_sale)
    table = build_cutoff_table()
    out_dir = os.path.dirname(path) or "."
    os.makedirs(out_dir, exist_ok=True)
    save_rankings(matrices, os.path.join(out_dir, "profitability_rankings.json"))

    dist = None
    if reference:
        from distributional_roi import build_distributional_matrices
        dist = build_distributional_matrices(
            reference, fertilizer_sale_for_animals=fertilizer_sale)
        # keep both regimes in one rankings artifact for old-vs-new comparison
        with open(os.path.join(out_dir, "profitability_rankings.json"),
                  "r", encoding="utf-8") as f:
            combined = json.load(f)
        combined["distributional"] = dist
        save_rankings(combined,
                      os.path.join(out_dir, "profitability_rankings.json"))

    lines = [
        "# Kaggriculture Profitability Report",
        "",
        "Season = 30 days, starting quadrant = 25 tiles. Crops replanted",
        "back-to-back; the fertilized vs unfertilized variant is chosen per",
        "asset by higher season net profit. Animals: daily feeding (1 wheat @ $25),",
        "care policy 'never', fertilizer collected but not sold unless noted.",
        "",
        "## Regime rankings (by PPTD = profit / tile / day)",
        "",
    ]
    for regime, data in matrices.items():
        lines.append(f"### {regime.replace('_', ' ').title()}")
        lines.append("")
        lines.append("| rank | asset | strategy | price | net/season | PPTD | ROCI % | payback d |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for i, asset in enumerate(data["ranking_by_pptd"], 1):
            m = data["assets"][asset]
            lines.append(
                f"| {i} | {asset} | {m['strategy']} | ${m['price_used']} | "
                f"${m['net_profit']:,.0f} | ${m['pptd']:,.2f} | {m['roci_pct']}% | "
                f"{m['payback_days']:.1f} |")
        lines.append("")

    lines += ["## Endgame cutoff days", "",
              "| asset | hard cutoff | first-yield cutoff | economic cutoff |", "|---|---|---|---|"]
    for asset, v in table.items():
        hard = v.get("hard_cutoff_fertilized", v.get("hard_cutoff"))
        fy = v.get("first_yield_cutoff", "-")
        eco = v.get("economic_cutoff_best_variant",
                    v.get("economic_cutoff_base_prices"))
        lines.append(f"| {asset} | {hard} | {fy} | {eco} |")

    if dist is not None:
        lines += [
            "",
            "## Distributional ROI (exhaustive E[P|day]) vs legacy spot_base",
            "",
            f"Reference scenario: **{dist['scenario']}** "
            f"(complete enumeration: {dist['complete_enumeration']}).",
            "",
            "| asset | strategy | legacy PPTD | dist PPTD | delta | net (dist) "
            "| floor risk % | price P10/P90 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        base_assets = matrices["spot_base"]["assets"]
        for asset in dist["ranking_by_pptd"]:
            m = dist["assets"][asset]
            legacy_pptd = base_assets[asset]["pptd"]
            lines.append(
                f"| {asset} | {m['strategy']} | ${legacy_pptd:,.2f} | "
                f"${m['pptd']:,.2f} | ${m['pptd'] - legacy_pptd:+,.2f} | "
                f"${m['net_profit']:,.0f} | {m.get('floor_risk_pct', 0):.2f} | "
                f"${m.get('price_p10', 0)}/"
                f"${m.get('price_p90', 0)} |")

    lines += [
        "",
        "## Key strategic notes",
        "",
        "- **Melon dominates spot economics** only while prices hold; its glut curve",
        "  (sq, target 3.6) crashes to $1 within ~160 dumped units — sell in small",
        "  slices across days.",
        "- Fertilizer ($100) is +EV on melon (cycle 10d -> 8d enables a 4th harvest)",
        "  and on ongoing crops with two applications, but -EV on wheat/carrot at",
        "  base prices (extra yield < fertilizer cost). Animal fertilizer is free.",
        "- Animals amortize slowly: a goose needs ~10 days to break even at base",
        "  egg prices; buy animals early or not at all.",
        "- In a competitive glut, staples (wheat/tomato/carrot) retain positive",
        "  margin while premium goods sit at the $1 floor — diversify.",
        "",
        "## Assumptions",
        "",
        "- Feed = 1 wheat/day at $25 (base market price).",
        "- Coop/pasture build cost treated as $0 cash (rules do not price them);",
        "  each structure occupies one tile.",
        "- Travel amortized 1 move per field action; hands cost fib(n)/day.",
    ]
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"report written to {path}")
    print(f"rankings written to {os.path.join(out_dir, 'profitability_rankings.json')}")


def main():
    ap = argparse.ArgumentParser(description="Kaggriculture profitability calculator")
    ap.add_argument("--crop-roi", action="store_true")
    ap.add_argument("--all-crops", action="store_true")
    ap.add_argument("--crop", type=str, default="WHEAT", choices=list(CROPS))
    ap.add_argument("--animal-roi", action="store_true")
    ap.add_argument("--include-fertilizer-sale", action="store_true")
    ap.add_argument("--endgame-cutoffs", action="store_true")
    ap.add_argument("--generate-report", action="store_true")
    ap.add_argument("--output", type=str, default="results/profitability_report.md",
                    help="report path for --generate-report")
    ap.add_argument("--generate-all-plots", metavar="DIR", nargs="?", const="results/plots")
    ap.add_argument("--regime", type=str, default="spot_base",
                    choices=["spot_base", "town_scarcity", "competitive_glut"])
    ap.add_argument("--reference", type=str, default=None,
                    help="path to exhaustive reference npz; enables the "
                         "distributional ROI regime (W4) alongside legacy")
    args = ap.parse_args()

    did = False
    if args.crop_roi:
        cmd_crop_roi(args); did = True
    if args.animal_roi:
        cmd_animal_roi(args); did = True
    if args.endgame_cutoffs:
        cmd_endgame_cutoffs(args); did = True
    if args.generate_all_plots:
        import visualizer as viz
        files = viz.generate_all_plots(args.generate_all_plots)
        print(f"plots written to {args.generate_all_plots}: {files}"); did = True
    if args.generate_report:
        generate_report(args.output,
                        fertilizer_sale=args.include_fertilizer_sale,
                        reference=args.reference)
        did = True
    if not did:
        ap.print_help()


if __name__ == "__main__":
    main()
