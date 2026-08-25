"""Multiprocess Tournament and Benchmark Runner for Kaggriculture.

Runs parallel matches using multiprocessing, records episode metrics, computes
leaderboard rankings, and supports mirrored 1v1 matchups to eliminate position bias.
"""

import json
import os
import time
from multiprocessing import Pool, cpu_count
import numpy as np

from kaggle_environments import make
from .agent_zoo import get_agent


def _run_single_match(args):
    """Worker function for running one match between two agents."""
    agent1_name, agent2_name, seed, episode_steps, mirrored = args
    
    # If mirrored, swap positions
    if mirrored:
        p0_name, p1_name = agent2_name, agent1_name
        invert = True
    else:
        p0_name, p1_name = agent1_name, agent2_name
        invert = False
        
    try:
        # Load callables or native baseline strings
        p0 = p0_name if p0_name in ["random", "starter", "pass"] else get_agent(p0_name)
        p1 = p1_name if p1_name in ["random", "starter", "pass"] else get_agent(p1_name)
        
        env = make("kaggriculture", configuration={"episodeSteps": episode_steps, "seed": seed}, debug=False)
        env.run([p0, p1])
        
        final_step = env.steps[-1]
        r0 = float(final_step[0].reward or 0.0)
        r1 = float(final_step[1].reward or 0.0)
        
        score_a = r1 if invert else r0
        score_b = r0 if invert else r1
        
        winner = "A" if score_a > score_b else ("B" if score_b > score_a else "TIE")
        
        return {
            "seed": seed,
            "agent_a": agent1_name,
            "agent_b": agent2_name,
            "score_a": score_a,
            "score_b": score_b,
            "winner": winner,
            "steps": len(env.steps),
            "error": None
        }
    except Exception as e:
        return {
            "seed": seed,
            "agent_a": agent1_name,
            "agent_b": agent2_name,
            "score_a": 0.0,
            "score_b": 0.0,
            "winner": "ERROR",
            "steps": 0,
            "error": str(e)
        }


class TournamentRunner:
    def __init__(self, n_workers=None, episode_steps=720):
        self.n_workers = n_workers or max(1, cpu_count() - 1)
        self.episode_steps = episode_steps

    def run_1v1_benchmark(self, agent_a, agent_b, n_episodes=50, base_seed=42):
        """Runs n_episodes mirrored 1v1 matches between Agent A and Agent B."""
        tasks = []
        for i in range(n_episodes):
            seed = base_seed + i
            mirrored = (i % 2 == 1)
            tasks.append((agent_a, agent_b, seed, self.episode_steps, mirrored))

        start_time = time.time()
        with Pool(processes=self.n_workers) as pool:
            results = pool.map(_run_single_match, tasks)
        elapsed = time.time() - start_time

        scores_a = [r["score_a"] for r in results if r["winner"] != "ERROR"]
        scores_b = [r["score_b"] for r in results if r["winner"] != "ERROR"]
        wins_a = sum(1 for r in results if r["winner"] == "A")
        wins_b = sum(1 for r in results if r["winner"] == "B")
        ties = sum(1 for r in results if r["winner"] == "TIE")
        errors = sum(1 for r in results if r["winner"] == "ERROR")
        valid_n = len(scores_a)

        stats = {
            "agent_a": agent_a,
            "agent_b": agent_b,
            "n_episodes": n_episodes,
            "valid_episodes": valid_n,
            "elapsed_seconds": round(elapsed, 2),
            "games_per_sec": round(n_episodes / max(0.01, elapsed), 2),
            "wins_a": wins_a,
            "wins_b": wins_b,
            "ties": ties,
            "errors": errors,
            "win_rate_a": round(wins_a / max(1, valid_n), 4),
            "win_rate_b": round(wins_b / max(1, valid_n), 4),
            "tie_rate": round(ties / max(1, valid_n), 4),
            "mean_score_a": round(float(np.mean(scores_a)), 2) if scores_a else 0,
            "std_score_a": round(float(np.std(scores_a)), 2) if scores_a else 0,
            "mean_score_b": round(float(np.mean(scores_b)), 2) if scores_b else 0,
            "std_score_b": round(float(np.std(scores_b)), 2) if scores_b else 0,
            "min_score_a": round(float(np.min(scores_a)), 2) if scores_a else 0,
            "max_score_a": round(float(np.max(scores_a)), 2) if scores_a else 0,
            "matches": results
        }
        return stats

    def run_round_robin(self, agent_names, episodes_per_pair=20, base_seed=100):
        """Runs a round-robin tournament across all listed agents."""
        leaderboard = {name: {"wins": 0, "losses": 0, "ties": 0, "scores": []} for name in agent_names}
        pair_matrix = {}

        total_pairs = len(agent_names) * (len(agent_names) - 1) // 2
        print(f"Starting Round-Robin Tournament: {len(agent_names)} agents, {total_pairs} pairs, {episodes_per_pair} games/pair")

        for i, a1 in enumerate(agent_names):
            for a2 in agent_names[i + 1:]:
                print(f"  Running matchup: {a1} vs {a2} ({episodes_per_pair} games)...")
                stats = self.run_1v1_benchmark(a1, a2, n_episodes=episodes_per_pair, base_seed=base_seed)
                
                key = f"{a1}_vs_{a2}"
                pair_matrix[key] = stats
                
                leaderboard[a1]["wins"] += stats["wins_a"]
                leaderboard[a1]["losses"] += stats["wins_b"]
                leaderboard[a1]["ties"] += stats["ties"]
                leaderboard[a1]["scores"].extend([m["score_a"] for m in stats["matches"] if m["winner"] != "ERROR"])
                
                leaderboard[a2]["wins"] += stats["wins_b"]
                leaderboard[a2]["losses"] += stats["wins_a"]
                leaderboard[a2]["ties"] += stats["ties"]
                leaderboard[a2]["scores"].extend([m["score_b"] for m in stats["matches"] if m["winner"] != "ERROR"])

        summary = []
        for name, data in leaderboard.items():
            total_games = data["wins"] + data["losses"] + data["ties"]
            win_rate = data["wins"] / max(1, total_games)
            mean_score = float(np.mean(data["scores"])) if data["scores"] else 0.0
            std_score = float(np.std(data["scores"])) if data["scores"] else 0.0
            summary.append({
                "agent": name,
                "win_rate": round(win_rate, 4),
                "wins": data["wins"],
                "losses": data["losses"],
                "ties": data["ties"],
                "mean_score": round(mean_score, 2),
                "std_score": round(std_score, 2),
            })

        summary.sort(key=lambda x: (x["win_rate"], x["mean_score"]), reverse=True)
        return {"rankings": summary, "pair_matrix": pair_matrix}
