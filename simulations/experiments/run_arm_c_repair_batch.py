"""10-Seed Corrected Arm C Validation Runner using Tournament Infrastructure."""

import os
import sys
import json
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO_ROOT = r"d:\website project\kaggri ox"
sys.path.append(os.path.join(_REPO_ROOT, "simulations", "experiments"))
from run_ab_large_confirmation import _run_single_match

def main():
    seeds = list(range(100, 110))
    print(f"Running Corrected Arm C across {len(seeds)} seeds: {seeds} on 5 workers...", flush=True)

    results = []
    payloads = [{"arm": "ArmC", "seed": s, "opponent": "starter"} for s in seeds]

    with ProcessPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_run_single_match, p): p for p in payloads}
        for f in as_completed(futures):
            r = f.result()
            results.append(r)
            print(f"Completed Seed {r['seed']}: Score=${r['final_score']:.0f}, Cows={r['cows_bought']}, Sheep={r['sheep_bought']}, Violations={r['late_purchase_invariant_violations']}, Escapes={r['animal_escapes']}, UnfedDays={r['unfed_animal_days']}", flush=True)

    scores = [r["final_score"] for r in results]
    cows = [r["cows_bought"] for r in results]
    sheep = [r["sheep_bought"] for r in results]
    first_cow_days = [min(r["cow_buy_days"]) if r["cow_buy_days"] else None for r in results]
    valid_first_cows = [d for d in first_cow_days if d is not None]
    all_cow_days = [d for r in results for d in r["cow_buy_days"]]
    all_sheep_days = [d for r in results for d in r["sheep_buy_days"]]
    violations = sum(r["late_purchase_invariant_violations"] for r in results)
    escapes = sum(r["animal_escapes"] for r in results)
    unfed = [r["unfed_animal_days"] for r in results]

    print("\n======================================================")
    print("=== CORRECTED ARM C (DYNAMIC HERD PLAN) 10-SEED AUDIT ===")
    print("======================================================")
    print(f"Mean Score: ${np.mean(scores):.2f} +/- ${np.std(scores):.2f}")
    print(f"Median Score: ${np.median(scores):.2f}")
    print(f"Min/Max Score: ${np.min(scores):.2f} / ${np.max(scores):.2f}")
    print(f"Mean Cows Bought: {np.mean(cows):.2f}")
    print(f"Mean Sheep Bought: {np.mean(sheep):.2f}")
    print(f"Mean First Cow Buy Day: {np.mean(valid_first_cows):.2f} (Old Arm C was Day 9.32)")
    print(f"Mean Overall Cow Buy Day: {np.mean(all_cow_days):.2f}")
    print(f"Mean Overall Sheep Buy Day: {np.mean(all_sheep_days):.2f}")
    print(f"Total Late-Purchase Invariant Violations: {violations}")
    print(f"Total Animal Escapes: {escapes}")
    print(f"Mean Unfed Animal-Days: {np.mean(unfed):.2f}")

    out_path = os.path.join(_REPO_ROOT, "simulations", "experiments", "results", "arm_c_repair_10seeds.json")
    with open(out_path, "w") as f:
        json.dump({"seeds": seeds, "results": results}, f, indent=2)
    print(f"Results saved to {out_path}")

if __name__ == "__main__":
    main()
