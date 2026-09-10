"""Reproducible full-season evaluation of isolated standalone submissions.

Builds a candidate from agent/ without overwriting the production bundle.
Every player/match gets a fresh module, so singleton state cannot leak.
Reports fallback failures, daily farm composition and issued actions alongside
cash scores. Use --opponent pass for a controlled economic diagnostic, then
--opponent baseline for mirrored competition against the frozen input bundle.
"""
import argparse
from collections import Counter
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def load_bundle(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_game(make, candidate, opponent, seed, seat):
    modules = [load_bundle(candidate, "bench_candidate")]
    other = load_bundle(opponent, "bench_opponent") if opponent else None
    modules = [modules[0], other] if seat == 0 else [other, modules[0]]
    daily = [{}, {}]
    counts = [Counter(), Counter()]
    fallbacks = []
    durations = []

    def wrap(module, player):
        def act(obs, config):
            if module is None:
                return {"farmer": ["PASS"], "hands": [], "market": []}
            start = time.perf_counter()
            action = module.agent(obs, config)
            durations.append(time.perf_counter() - start)
            diagnostic = module.get_last_fallback_diagnostic()
            if diagnostic:
                fallbacks.append({"player": player, **diagnostic})
            for op in [action["farmer"], *action["hands"]]:
                if op:
                    counts[player][op[0]] += 1
            for order in action["market"]:
                if len(order) > 2:
                    counts[player][order[0] + ":" + order[1]] += order[2]
            if obs["hour"] == 23:
                farm = obs["farms"][player]
                tiles = [t for row in farm["tiles"] for t in row if isinstance(t, dict)]
                daily[player][obs["day"]] = {
                    "money": farm["money"],
                    "tiles": dict(Counter(t.get("animal") or t.get("crop") or t["kind"] for t in tiles)),
                    "unlocked": farm["unlocked_quadrants"],
                    "shed": dict(obs["private"]["shed"]),
                }
            return action
        return act

    env = make("kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"})
    start = time.perf_counter()
    env.run([wrap(m, p) for p, m in enumerate(modules)])
    scores = [f["money"] for f in env.steps[-1][0].observation["farms"]]
    statuses = [s.status for s in env.steps[-1]]
    if any(s in ("ERROR", "INVALID", "TIMEOUT") for s in statuses) or fallbacks:
        raise RuntimeError(json.dumps({"statuses": statuses, "fallbacks": fallbacks[:3]}))
    return {"seed": seed, "candidate_seat": seat, "scores": scores,
            "candidate_score": scores[seat], "opponent_score": scores[1-seat],
            "margin": scores[seat] - scores[1-seat], "steps": len(env.steps),
            "seconds": round(time.perf_counter()-start, 2), "fallbacks": len(fallbacks),
            "max_decision_seconds": round(max(durations, default=0), 4),
            "daily": daily, "issued_actions": [dict(c) for c in counts]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", help="Existing standalone bundle; otherwise build agent/")
    parser.add_argument("--baseline", default=str(ROOT / "submission.py"))
    parser.add_argument("--opponent", choices=["baseline", "pass"], default="baseline")
    parser.add_argument("--seeds", nargs="+", type=int, default=[101, 202, 303, 404, 505])
    parser.add_argument("--both-seats", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    # Suppress unrelated OpenSpiel optional-game import diagnostics.
    with contextlib.redirect_stdout(sys.stderr):
        from kaggle_environments import make
        from build_submission import build_single_file_submission
    with tempfile.TemporaryDirectory(prefix="kaggriculture-benchmark-") as temp:
        candidate = args.candidate or build_single_file_submission(str(ROOT / "agent"), temp)
        opponent = args.baseline if args.opponent == "baseline" else None
        result = {"candidate_sha256": hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),
                  "baseline_sha256": hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest(),
                  "opponent": args.opponent, "games": []}
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        for seed in args.seeds:
            for seat in ([0, 1] if args.both_seats else [0]):
                game = run_game(make, candidate, opponent, seed, seat)
                result["games"].append(game)
                print(json.dumps({k: v for k, v in game.items() if k not in ("daily", "issued_actions")}), flush=True)
                output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        games = result["games"]
        result["summary"] = {"games": len(games),
            "candidate_mean": sum(g["candidate_score"] for g in games) / len(games),
            "opponent_mean": sum(g["opponent_score"] for g in games) / len(games),
            "mean_margin": sum(g["margin"] for g in games) / len(games),
            "wins": sum(g["margin"] > 0 for g in games),
            "ties": sum(g["margin"] == 0 for g in games)}
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result["summary"]), flush=True)


if __name__ == "__main__":
    main()
