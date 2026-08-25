"""Controlled A/B Hypothesis Testing Framework for Kaggriculture.

Runs isolated, single-variable experiments to validate specific strategic hypotheses:
- Exp 1: Goose CARE (+1 bonus) vs No-CARE
- Exp 2: Melon Fertilizer Timing & Yield Acceleration
- Exp 3: Full Production Agent vs Pure Wheat Rush vs Baseline
- Exp 4: Drip-selling vs Bulk liquidation
"""

import json
import os
from typing import Dict, Any, List
import numpy as np

from .tournament_runner import TournamentRunner


class ABTestingFramework:
    def __init__(self, n_workers=None, episode_steps=720):
        self.runner = TournamentRunner(n_workers=n_workers, episode_steps=episode_steps)

    def run_experiment(self, experiment_id: str, n_episodes: int = 50, base_seed: int = 42) -> Dict[str, Any]:
        """Runs an isolated A/B hypothesis test."""
        experiments = {
            "goose_care_validation": {
                "title": "Goose Daily CARE (+1 Bonus) vs No-CARE",
                "agent_a": "goose_wheat_engine",
                "agent_b": "goose_no_care",
                "hypothesis": "Caring for geese daily yields exactly 2x egg production under v1.32.7 engine rules, increasing net profit.",
            },
            "melon_fertilizer_optimization": {
                "title": "Melon Day-5 Fertilizer Application vs Unfertilized",
                "agent_a": "melon_sniper",
                "agent_b": "melon_unfertilized",
                "hypothesis": "Fertilizing melons on Day 5 accelerates max yield to Day 8 and saves 4+ watering actions before Day 10 harvest.",
            },
            "production_vs_wheat_rush": {
                "title": "Full Production Agent vs Pure Wheat Rush",
                "agent_a": "full_production_agent",
                "agent_b": "pure_wheat_rush",
                "hypothesis": "Multi-tier decoupled production architecture outperforms pure wheat monoculture.",
            },
            "production_vs_starter": {
                "title": "Full Production Agent vs Kaggle Starter Baseline",
                "agent_a": "full_production_agent",
                "agent_b": "starter",
                "hypothesis": "Full production agent achieves 100% win rate against starter baseline.",
            }
        }

        if experiment_id not in experiments:
            raise ValueError(f"Unknown experiment '{experiment_id}'. Available: {list(experiments.keys())}")

        exp_config = experiments[experiment_id]
        print(f"Running A/B Experiment: {exp_config['title']} ({n_episodes} games, base seed {base_seed})...")

        stats = self.runner.run_1v1_benchmark(
            agent_a=exp_config["agent_a"],
            agent_b=exp_config["agent_b"],
            n_episodes=n_episodes,
            base_seed=base_seed
        )

        scores_a = [m["score_a"] for m in stats["matches"] if m["winner"] != "ERROR"]
        scores_b = [m["score_b"] for m in stats["matches"] if m["winner"] != "ERROR"]
        
        # Calculate Delta and simple t-statistic proxy
        mean_a = float(np.mean(scores_a)) if scores_a else 0.0
        mean_b = float(np.mean(scores_b)) if scores_b else 0.0
        delta = mean_a - mean_b
        percent_lift = (delta / max(1.0, mean_b)) * 100.0

        report = {
            "experiment_id": experiment_id,
            "title": exp_config["title"],
            "hypothesis": exp_config["hypothesis"],
            "agent_a": exp_config["agent_a"],
            "agent_b": exp_config["agent_b"],
            "n_episodes": n_episodes,
            "mean_score_a": round(mean_a, 2),
            "std_score_a": round(float(np.std(scores_a)), 2) if scores_a else 0.0,
            "mean_score_b": round(mean_b, 2),
            "std_score_b": round(float(np.std(scores_b)), 2) if scores_b else 0.0,
            "delta": round(delta, 2),
            "percent_lift": round(percent_lift, 2),
            "win_rate_a": stats["win_rate_a"],
            "win_rate_b": stats["win_rate_b"],
            "tie_rate": stats["tie_rate"],
            "verdict": "CONFIRMED" if mean_a > mean_b and stats["win_rate_a"] > 0.55 else ("REFUTED" if mean_b > mean_a else "INCONCLUSIVE"),
            "full_stats": stats
        }
        return report
