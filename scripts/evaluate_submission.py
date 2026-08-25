"""Benchmark our submission agent against random and starter baselines."""

from kaggle_environments import make
import time


def run_benchmark(agent1_path, agent2_path, name1, name2, episodes=3):
    print(f"\n{'='*60}")
    print(f"Matchup: {name1} (P0) vs {name2} (P1) | {episodes} Episodes (720 steps each)")
    print(f"{'='*60}")
    
    scores1, scores2 = [], []
    start_t = time.time()
    
    for ep in range(episodes):
        env = make("kaggriculture", debug=True)
        env.run([agent1_path, agent2_path])
        last_obs = env.steps[-1][0].observation
        m1 = last_obs["farms"][0]["money"]
        m2 = last_obs["farms"][1]["money"]
        scores1.append(m1)
        scores2.append(m2)
        winner = f"P0 ({name1})" if m1 > m2 else (f"P1 ({name2})" if m2 > m1 else "Tie")
        diff = m1 - m2
        print(f"  [Ep {ep+1}] {name1}: ${m1:,.2f} | {name2}: ${m2:,.2f} | Margin: +${diff:,.2f} -> Winner: {winner}")
    
    elapsed = time.time() - start_t
    avg1 = sum(scores1) / len(scores1)
    avg2 = sum(scores2) / len(scores2)
    win_rate1 = sum(1 for s1, s2 in zip(scores1, scores2) if s1 > s2) / len(scores1) * 100.0
    
    print(f"\n--- Summary ---")
    print(f"{name1}: Win Rate = {win_rate1:.1f}%, Mean Score = ${avg1:,.2f}")
    print(f"{name2}: Win Rate = {100.0 - win_rate1:.1f}%, Mean Score = ${avg2:,.2f}")
    print(f"Total Match Time: {elapsed:.2f}s ({elapsed/episodes:.2f}s/game)")
    return avg1, avg2, win_rate1


if __name__ == "__main__":
    submission_path = "submission/main.py"
    
    # 1. Evaluate vs Random Agent
    run_benchmark(submission_path, "random", "Our Submission Agent", "Random Baseline", episodes=3)
    
    # 2. Evaluate vs Starter Baseline
    starter_path = "simulations/experiments/agent_zoo/baselines.py"
    run_benchmark(submission_path, starter_path, "Our Submission Agent", "Starter Baseline", episodes=3)
