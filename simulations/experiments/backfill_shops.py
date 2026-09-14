import sys, os
sys.path.insert(0, os.path.abspath("."))
import json
import time
from kaggle_environments import make
from simulations.experiments.run_definitive_livestock_tournament import analyze_tournament_results

print("Extracting exact engine shops for seeds 100..149...")
t0 = time.time()
shops_by_seed = {}

for s in range(100, 150):
    env = make("kaggriculture", configuration={"episodeSteps": 720}, info={"seed": s})
    env.run(["pass", "pass"])
    shops = list(env.state[0].observation["town"]["unlocked_shops"])
    shops_by_seed[s] = shops

print(f"Extracted shops for 50 seeds in {time.time() - t0:.2f}s.")

# Load tournament results
with open("simulations/experiments/results/livestock_tournament_results.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for r in d["raw_results"]:
    seed = r["seed"]
    shops = shops_by_seed[seed]
    r["town_shops"] = shops
    r["yarn_store_count"] = shops.count("YARN_STORE")
    r["milk_shop_count"] = sum(shops.count(s) for s in ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP"))
    r["egg_shop_count"] = sum(shops.count(s) for s in ("BAKERY", "BRUNCH_SPOT"))

# Re-run analysis with correct shops
new_analysis = analyze_tournament_results(d["raw_results"])
d["analysis"] = new_analysis

with open("simulations/experiments/results/livestock_tournament_results.json", "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2)

print("Saved updated tournament analysis to simulations/experiments/results/livestock_tournament_results.json")
