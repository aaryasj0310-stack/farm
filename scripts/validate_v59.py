"""v5.9 vs v5.8 validation: 5-game comparison with fixed seeds."""

import json
import os
import sys
import time
from pathlib import Path

# Add agent paths for v5.9
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
_agent_dir = str(Path(__file__).resolve().parent.parent / "agent")
for _sub in ("state", "strategy", "execution", "market"):
    sys.path.insert(0, os.path.join(_agent_dir, _sub))

import kaggle_environments

# Seeds from five_games_log.json
SEEDS = [101, 202, 303, 404, 505]

# v5.8 baseline scores from five_games_log.json
V58_SCORES = {
    101: 9990.0,
    202: 10284.0,
    303: 14785.0,
    404: 12593.0,
    505: 10623.0,
}


def load_agent(path):
    """Load an agent function from a file path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.agent


def run_game(agent_path, seed, vs_random=True):
    """Run a single game and return (our_score, opp_score, utilization_log)."""
    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"seed": seed, "loglevel": "ERROR"},
    )
    
    if vs_random:
        env.run([agent_path, "random"])
    else:
        env.run([agent_path, agent_path])
    
    # Extract scores
    last_step = env.steps[-1]
    p0_obs = last_step[0].observation
    p1_obs = last_step[1].observation
    
    our_score = p0_obs["farms"][0]["money"]
    opp_score = p0_obs["farms"][1]["money"]
    
    # Check for errors
    errors = [s for s in env.steps if s[0].status == "ERROR"]
    
    return our_score, opp_score, len(errors)


def validate_hiring_schedule(agent_path, seed):
    """Validate that hiring matches the fixed schedule.
    
    Check at hour 23 (end of day) since hires happen during market phase
    which executes after unit actions. At hour 23, the day's hires are done.
    """
    from config import get_target_hands, DAY_TO_HANDS
    
    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"seed": seed, "loglevel": "ERROR"},
    )
    env.run([agent_path, "random"])
    
    violations = []
    for step_idx, step in enumerate(env.steps):
        obs = step[0].observation
        day = obs["day"]
        hour = obs["hour"]
        
        if hour == 23:  # Check at end of day (after hires processed)
            hands = len(obs["farms"][0]["hands"])
            expected = get_target_hands(day)
            if hands != expected:
                violations.append({
                    "step": step_idx,
                    "day": day,
                    "hands": hands,
                    "expected": expected,
                })
    
    return violations


def validate_quadrant_block(agent_path, seed):
    """Validate that quadrant 4 is never purchased."""
    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"seed": seed, "loglevel": "ERROR"},
    )
    env.run([agent_path, "random"])
    
    violations = []
    for step_idx, step in enumerate(env.steps):
        obs = step[0].observation
        unlocked = obs["farms"][0]["unlocked_quadrants"]
        if 4 in unlocked:
            violations.append({
                "step": step_idx,
                "day": obs["day"],
                "unlocked": unlocked,
            })
    
    return violations


def main():
    print("=" * 80)
    print("v5.9 vs v5.8 VALIDATION: 5-Game Comparison")
    print("=" * 80)
    
    # Load v5.9 agent
    v59_path = str(Path(__file__).resolve().parent.parent / "submission" / "main.py")
    v58_path = str(Path(__file__).resolve().parent.parent / "submission_v5_8" / "main.py")
    
    print(f"\nv5.9 agent: {v59_path}")
    print(f"v5.8 agent: {v58_path}")
    
    results = []
    
    for seed in SEEDS:
        print(f"\n--- Seed {seed} ---")
        
        # Run v5.9
        start = time.time()
        v59_score, v59_opp, v59_errors = run_game(v59_path, seed)
        v59_time = time.time() - start
        
        # Run v5.8
        start = time.time()
        v58_score, v58_opp, v58_errors = run_game(v58_path, seed)
        v58_time = time.time() - start
        
        delta = v59_score - v58_score
        baseline = V58_SCORES.get(seed, v58_score)
        delta_vs_baseline = v59_score - baseline
        
        print(f"  v5.9: ${v59_score:,.0f} ({v59_errors} errors) [{v59_time:.1f}s]")
        print(f"  v5.8: ${v58_score:,.0f} ({v58_errors} errors) [{v58_time:.1f}s]")
        print(f"  Delta: ${delta:+,.0f} (vs baseline: ${delta_vs_baseline:+,.0f})")
        
        results.append({
            "seed": seed,
            "v59_score": v59_score,
            "v58_score": v58_score,
            "v59_errors": v59_errors,
            "v58_errors": v58_errors,
            "delta": delta,
            "delta_vs_baseline": delta_vs_baseline,
        })
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    avg_v59 = sum(r["v59_score"] for r in results) / len(results)
    avg_v58 = sum(r["v58_score"] for r in results) / len(results)
    avg_delta = avg_v59 - avg_v58
    
    print(f"\n{'Seed':<8} {'v5.9':>12} {'v5.8':>12} {'Delta':>10} {'Errors':>8}")
    print("-" * 55)
    for r in results:
        print(f"{r['seed']:<8} ${r['v59_score']:>10,.0f} ${r['v58_score']:>10,.0f} ${r['delta']:>+8,.0f} {r['v59_errors']:>8}")
    print("-" * 55)
    print(f"{'AVERAGE':<8} ${avg_v59:>10,.0f} ${avg_v58:>10,.0f} ${avg_delta:>+8,.0f}")
    
    # Validation checks
    print("\n" + "=" * 80)
    print("VALIDATION CHECKS")
    print("=" * 80)
    
    # Check hiring schedule on seed 101
    print("\n1. Hiring Schedule Validation (seed 101):")
    hiring_violations = validate_hiring_schedule(v59_path, 101)
    if hiring_violations:
        print(f"   FAIL: {len(hiring_violations)} violations")
        for v in hiring_violations[:5]:
            print(f"     Day {v['day']}: got {v['hands']} hands, expected {v['expected']}")
    else:
        print("   PASS: All days match fixed schedule")
    
    # Check quadrant 4 block on seed 101
    print("\n2. Quadrant 4 Block Validation (seed 101):")
    quadrant_violations = validate_quadrant_block(v59_path, 101)
    if quadrant_violations:
        print(f"   FAIL: {len(quadrant_violations)} violations")
        for v in quadrant_violations:
            print(f"     Day {v['day']}: unlocked {v['unlocked']}")
    else:
        print("   PASS: Quadrant 4 never purchased")
    
    # Check error counts
    print("\n3. Engine Error Check:")
    total_errors = sum(r["v59_errors"] for r in results)
    if total_errors > 0:
        print(f"   WARNING: {total_errors} total errors across all games")
    else:
        print("   PASS: Zero engine errors")
    
    # Save results
    output_path = Path(__file__).resolve().parent / "v59_comparison_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "v59_scores": [r["v59_score"] for r in results],
            "v58_scores": [r["v58_score"] for r in results],
            "deltas": [r["delta"] for r in results],
            "avg_v59": avg_v59,
            "avg_v58": avg_v58,
            "avg_delta": avg_delta,
            "hiring_violations": len(hiring_violations),
            "quadrant_violations": len(quadrant_violations),
            "total_errors": total_errors,
        }, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")
    
    return avg_v59, avg_v58, avg_delta


if __name__ == "__main__":
    main()
