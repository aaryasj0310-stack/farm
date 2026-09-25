import json

with open("simulations/results/phase_m0_d_storage_rescue/matched_results.json") as f:
    pairs = json.load(f)

losses = [p for p in pairs if p["delta_cash"] < 0]
print(f"Total losses: {len(losses)} / {len(pairs)}")
print("-" * 100)
for l in sorted(losses, key=lambda x: x["delta_cash"]):
    s = l["seed"]
    opp = l["opponent"]
    seat = l["seat"]
    d_cash = l["delta_cash"]
    c0 = l["c0"]["final_cash"]
    c2 = l["c2"]["final_cash"]
    disc0 = l["c0"]["total_discarded_units"]
    disc2 = l["c2"]["total_discarded_units"]
    sold = l["c2"]["rescue_units_sold"]
    print(f"Seed {s} vs {opp:22s} seat {seat}: delta={d_cash:+10,.2f} | C0=${c0:9,.2f} C2=${c2:9,.2f} | disc: C0={disc0:2d} -> C2={disc2:2d} | sold={sold:3d}")

print("-" * 100)
severe_losses = [l for l in losses if l["delta_cash"] < -5000]
print(f"Severe losses (< -$5,000): {len(severe_losses)}")
for sl in severe_losses:
    print(f"Severe loss: Seed {sl['seed']} vs {sl['opponent']} seat {sl['seat']}: delta={sl['delta_cash']:+,.2f}")
