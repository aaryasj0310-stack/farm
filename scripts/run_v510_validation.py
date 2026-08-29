"""Quick 5-game validation for v5.10."""
import sys, os, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "submission"))
for sub in ["state", "strategy", "execution", "market"]:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "submission", sub))

from main import agent
from kaggle_environments import make
from config import get_target_hands

SEEDS = [101, 202, 303, 404, 505]

results = []
for seed in SEEDS:
    env = make("kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"})
    t0 = time.time()
    env.run([agent, "random"])
    dt = time.time() - t0
    money = env.steps[-1][0].observation["farms"][0]["money"]

    # Check hiring schedule
    violations = []
    for step in env.steps:
        obs = step[0].observation
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        if hour == 23:
            hands = len(obs["farms"][0]["hands"])
            expected = get_target_hands(day)
            if hands != expected:
                violations.append(f"Day {day}: got {hands}, expected {expected}")

    # Check Q4
    q4_violations = 0
    for step in env.steps:
        unlocked = step[0].observation["farms"][0].get("unlocked_quadrants", [])
        if 4 in unlocked:
            q4_violations += 1

    results.append({
        "seed": seed,
        "money": money,
        "time": dt,
        "hiring_violations": len(violations),
        "q4_violations": q4_violations,
    })
    status = "PASS" if len(violations) == 0 and q4_violations == 0 else "FAIL"
    print(f"Seed {seed}: ${money:,.0f} ({dt:.1f}s) hire_v={len(violations)} q4_v={q4_violations} [{status}]")
    if violations:
        for v in violations[:3]:
            print(f"  {v}")

avg = sum(r["money"] for r in results) / len(results)
total_hire_v = sum(r["hiring_violations"] for r in results)
total_q4_v = sum(r["q4_violations"] for r in results)
print(f"\nAverage: ${avg:,.0f}")
print(f"Total hiring violations: {total_hire_v}")
print(f"Total Q4 violations: {total_q4_v}")
print(f"Overall: {'PASS' if total_hire_v == 0 and total_q4_v == 0 else 'FAIL'}")
