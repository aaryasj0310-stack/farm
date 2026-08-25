"""Tests for the tournament and benchmarking engine."""

import pytest
from simulations.experiments.tournament_runner import TournamentRunner, _run_single_match
from simulations.experiments.agent_zoo import AGENT_REGISTRY


def test_agent_registry_contains_all_archetypes():
    expected = [
        "random", "starter", "pass", "pure_wheat_rush",
        "goose_wheat_engine", "goose_no_care", "melon_sniper",
        "melon_unfertilized", "cow_milk_engine", "full_production_agent"
    ]
    for name in expected:
        assert name in AGENT_REGISTRY, f"Missing agent: {name}"


def test_run_single_match():
    res = _run_single_match(("starter", "random", 42, 30, False))
    assert res["winner"] in ["A", "B", "TIE"]
    assert res["steps"] > 0
    assert res["error"] is None
    assert res["score_a"] >= 0


def test_benchmark_1v1_determinism():
    runner = TournamentRunner(n_workers=1, episode_steps=30)
    stats1 = runner.run_1v1_benchmark("pure_wheat_rush", "starter", n_episodes=4, base_seed=123)
    stats2 = runner.run_1v1_benchmark("pure_wheat_rush", "starter", n_episodes=4, base_seed=123)

    assert stats1["win_rate_a"] == stats2["win_rate_a"]
    assert stats1["mean_score_a"] == stats2["mean_score_a"]
    assert stats1["mean_score_b"] == stats2["mean_score_b"]
