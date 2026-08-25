"""Unified CLI for Kaggriculture Simulation, Benchmarking & A/B Testing Suite."""

import argparse
import json
import os
import sys
from datetime import datetime

from .tournament_runner import TournamentRunner
from .ab_testing_framework import ABTestingFramework
from .replay_analyzer import ReplayAnalyzer
from .visualizer import plot_winrate_matrix, plot_score_distributions, plot_ab_comparison
from .agent_zoo import AGENT_REGISTRY


def main():
    parser = argparse.ArgumentParser(description="Kaggriculture Phase D Simulation & Benchmarking CLI")
    parser.add_argument("--benchmark", action="store_true", help="Run a 1v1 benchmark match")
    parser.add_argument("--agent1", type=str, default="full_production_agent", help="First agent name")
    parser.add_argument("--agent2", type=str, default="starter", help="Second agent name")
    parser.add_argument("--episodes", type=int, default=50, help="Number of episodes to run")
    parser.add_argument("--seed", type=int, default=42, help="Base random seed")

    parser.add_argument("--tournament", action="store_true", help="Run a full round-robin tournament")
    parser.add_argument("--agents", nargs="+", default=None, help="List of agent names for tournament")
    parser.add_argument("--episodes-per-pair", type=int, default=20, help="Episodes per pair in tournament")

    parser.add_argument("--ab-test", action="store_true", help="Run a controlled A/B hypothesis experiment")
    parser.add_argument("--experiment", type=str, default="goose_care_validation", help="A/B experiment ID")

    parser.add_argument("--analyze-replay", action="store_true", help="Analyze an episode replay JSON")
    parser.add_argument("--replay-file", type=str, default=None, help="Path to episode replay JSON")
    parser.add_argument("--player", type=int, default=0, help="Player ID to audit (0 or 1)")

    parser.add_argument("--output", type=str, default="results/", help="Directory to store results and plots")
    parser.add_argument("--export-knowledge", type=str, default=None, help="Path to append Markdown experiment log")

    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)
    plots_dir = os.path.join(args.output, "plots")
    os.makedirs(plots_dir, exist_ok=True)

    # 1. 1v1 Benchmark Mode
    if args.benchmark:
        print(f"=== Running 1v1 Benchmark: {args.agent1} vs {args.agent2} ({args.episodes} episodes) ===")
        runner = TournamentRunner()
        stats = runner.run_1v1_benchmark(args.agent1, args.agent2, n_episodes=args.episodes, base_seed=args.seed)
        
        print("\n--- Benchmark Results ---")
        print(f"Agent A ({args.agent1}): Win Rate = {stats['win_rate_a']*100:.1f}%, Mean Score = ${stats['mean_score_a']} (std: ${stats['std_score_a']})")
        print(f"Agent B ({args.agent2}): Win Rate = {stats['win_rate_b']*100:.1f}%, Mean Score = ${stats['mean_score_b']} (std: ${stats['std_score_b']})")
        print(f"Ties = {stats['tie_rate']*100:.1f}%, Total Execution Time = {stats['elapsed_seconds']}s ({stats['games_per_sec']} games/sec)")

        out_file = os.path.join(args.output, f"benchmark_{args.agent1}_vs_{args.agent2}.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        print(f"Saved benchmark report to: {out_file}")

    # 2. Round-Robin Tournament Mode
    elif args.tournament:
        agent_list = args.agents or [
            "full_production_agent",
            "pure_wheat_rush",
            "goose_wheat_engine",
            "melon_sniper",
            "cow_milk_engine",
            "starter"
        ]
        print(f"=== Starting Round-Robin Tournament across {len(agent_list)} agents ===")
        runner = TournamentRunner()
        results = runner.run_round_robin(agent_list, episodes_per_pair=args.episodes_per_pair, base_seed=args.seed)

        print("\n================ FINAL TOURNAMENT LEADERBOARD ================")
        print(f"{'Rank':<5} {'Agent':<25} {'Win Rate':<10} {'W/L/T':<12} {'Mean Score ($)':<15} {'Std Dev ($)':<12}")
        print("-" * 80)
        for rank, r in enumerate(results["rankings"], 1):
            wlt = f"{r['wins']}/{r['losses']}/{r['ties']}"
            print(f"{rank:<5} {r['agent']:<25} {r['win_rate']*100:>6.1f}%    {wlt:<12} ${r['mean_score']:<14.1f} ${r['std_score']:<11.1f}")

        # Save JSON results
        out_file = os.path.join(args.output, "tournament_leaderboard.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nLeaderboard saved to {out_file}")

        # Generate plots
        plot_winrate_matrix(results["pair_matrix"], agent_list, os.path.join(plots_dir, "winrate_matrix.png"))
        plot_score_distributions(results["rankings"], os.path.join(plots_dir, "score_distributions.png"))
        print(f"Plots saved to {plots_dir}/")

    # 3. A/B Testing Mode
    elif args.ab_test:
        ab = ABTestingFramework()
        report = ab.run_experiment(args.experiment, n_episodes=args.episodes, base_seed=args.seed)

        print("\n================ A/B TEST REPORT ================")
        print(f"Experiment:  {report['title']}")
        print(f"Hypothesis:  {report['hypothesis']}")
        print(f"Agent A:     {report['agent_a']} -> Mean = ${report['mean_score_a']} (Win Rate: {report['win_rate_a']*100:.1f}%)")
        print(f"Agent B:     {report['agent_b']} -> Mean = ${report['mean_score_b']} (Win Rate: {report['win_rate_b']*100:.1f}%)")
        print(f"Lift:        +${report['delta']} (+{report['percent_lift']}%)")
        print(f"Verdict:     {report['verdict']}")

        out_file = os.path.join(args.output, f"ab_test_{args.experiment}.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Saved A/B test data to {out_file}")

        plot_ab_comparison(report, os.path.join(plots_dir, f"ab_{args.experiment}.png"))

        # Optional Memory Curator Markdown Append
        if args.export_knowledge:
            os.makedirs(os.path.dirname(args.export_knowledge), exist_ok=True)
            entry = f"""
### Experiment: {report['title']}
- **Type**: EXPERIMENT
- **Date**: {datetime.now().strftime('%Y-%m-%d')}
- **Agents Tested**: `{report['agent_a']}` vs `{report['agent_b']}`
- **Sample Size**: {report['n_episodes']} games
- **Results**: Mean A = ${report['mean_score_a']} (Win Rate {report['win_rate_a']*100:.1f}%) vs Mean B = ${report['mean_score_b']} (Win Rate {report['win_rate_b']*100:.1f}%), Lift: +{report['percent_lift']}%
- **Verdict**: {report['verdict']}
- **Key Finding**: {report['hypothesis']} -> Confirmed with delta +${report['delta']}.
"""
            with open(args.export_knowledge, "a", encoding="utf-8") as f:
                f.write(entry)
            print(f"Appended experiment entry to: {args.export_knowledge}")

    # 4. Replay Analysis Mode
    elif args.analyze_replay:
        if not args.replay_file:
            print("Error: Please provide --replay-file <path>")
            sys.exit(1)
        analyzer = ReplayAnalyzer()
        analyzer.load_from_file(args.replay_file)
        audit = analyzer.analyze_player(args.player)

        print(f"\n================ REPLAY INEFFICIENCY AUDIT (Player {args.player}) ================")
        print(f"Final Score:                 ${audit['final_reward']:.0f}")
        print(f"Estimated Money Left on Table: ${audit['money_left_on_table_estimate']:.0f}")
        print(f"Wasted Turns (Idle on Task): {audit['inefficiencies']['wasted_turns']}")
        print(f"Shed Capacity Overflows:     {audit['inefficiencies']['shed_overflow_discards']}")
        print(f"Decay Lost Yield Units:      {audit['inefficiencies']['decay_lost_units']}")
        print(f"Missed Animal Fertilizer:    {audit['inefficiencies']['missed_fertilizer_days']} days")

        out_file = os.path.join(args.output, "replay_inefficiency_audit.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(audit, f, indent=2)
        print(f"\nAudit saved to {out_file}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
