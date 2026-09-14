import json

with open("simulations/opponent_benchmark/crop_dusta_eval_report.json") as f:
    rep = json.load(f)

print("=== BRIER SCORES BY PRODUCT (H=4) ===")
for p in ['WHEAT', 'CARROT', 'TOMATO', 'STRAWBERRY', 'MELON', 'EGG', 'MILK', 'WOOL', 'FERTILIZER']:
    z = rep['brier_by_product_h4']['zero'][p]
    g = rep['brier_by_product_h4']['global'][p]
    pr = rep['brier_by_product_h4']['prod'][p]
    leg = rep['brier_by_product_h4']['legacy'][p]
    rep_b = rep['brier_by_product_h4']['repaired'][p]
    print(f"{p:12s} | Zero: {z:.4f} | Global: {g:.4f} | Prod: {pr:.4f} | Leg: {leg:.4f} | Rep: {rep_b:.4f}")

print("\n=== BRIER SCORES BY PHASE (H=4) ===")
for ph in ['early', 'mid', 'late', 'endgame']:
    z = rep['brier_by_phase_h4']['zero'][ph]
    g = rep['brier_by_phase_h4']['global'][ph]
    pr = rep['brier_by_phase_h4']['prod'][ph]
    leg = rep['brier_by_phase_h4']['legacy'][ph]
    rep_b = rep['brier_by_phase_h4']['repaired'][ph]
    print(f"{ph:10s} | Zero: {z:.4f} | Global: {g:.4f} | Prod: {pr:.4f} | Leg: {leg:.4f} | Rep: {rep_b:.4f}")

print("\n=== RELIABILITY CURVES (H=4) ===")
print("Repaired:")
for b in rep['reliability_curves_h4']['repaired']:
    rng = b['bin_range']
    print(f"  Bin [{rng[0]:.1f}, {rng[1]:.1f}): Count={b['count']:6d}, Pred={b['mean_predicted']:.3f}, Observed={b['observed_frequency']:.3f}")
print("Legacy:")
for b in rep['reliability_curves_h4']['legacy']:
    rng = b['bin_range']
    print(f"  Bin [{rng[0]:.1f}, {rng[1]:.1f}): Count={b['count']:6d}, Pred={b['mean_predicted']:.3f}, Observed={b['observed_frequency']:.3f}")

print("\n=== CLASSIFICATION METRICS (H=4) ===")
for tau in ['0.2', '0.4', '0.5', '0.6', '0.8']:
    r_m = rep['classification_metrics_h4']['repaired'][tau]
    l_m = rep['classification_metrics_h4']['legacy'][tau]
    p_m = rep['classification_metrics_h4']['prod'][tau]
    print(f"Tau={tau}: Repaired [Prec={r_m['precision']:.3f}, Rec={r_m['recall']:.3f}, F1={r_m['f1']:.3f}] | Legacy [Prec={l_m['precision']:.3f}, Rec={l_m['recall']:.3f}, F1={l_m['f1']:.3f}] | ProdBase [Prec={p_m['precision']:.3f}, Rec={p_m['recall']:.3f}, F1={p_m['f1']:.3f}]")

print("\n=== HIDDEN INVENTORY PER PRODUCT ===")
for p, v in rep['hidden_inventory_evaluation']['per_product_shed'].items():
    print(f"{p:12s} | Active N={v['active_samples']:5d} | Active Cov={v['active_coverage']*100:.1f}% | Uncond Cov={v['unconditional_coverage']*100:.1f}% | Width={v['mean_interval_width']:.1f} | MAE={v['shed_mae']:.1f}")

print("\n=== TIMING & VOLUME ACCURACY ===")
print(json.dumps(rep['timing_and_volume_accuracy'], indent=2))

print("\n=== FLOOR CENSORING IMPACT ===")
print(json.dumps(rep['floor_censoring_impact'], indent=2))

print("\n=== BEHAVIORAL PROFILE ===")
print(f"Mean Score: {rep['crop_dusta_behavior']['mean_score']:.1f}")
print(f"Median Score: {rep['crop_dusta_behavior']['median_score']:.1f}")
print("Units Harvested vs Sold Per Game (Mean):")
for p, q in rep['crop_dusta_behavior']['total_units_sold_per_game_mean'].items():
    harv = rep['crop_dusta_behavior']['total_units_harvested_per_game_mean'][p]
    print(f"  {p:12s}: Harvested={harv:6.1f} | Sold={q:6.1f}")
