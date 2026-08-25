"""Tests for the replay analyzer and inefficiency inspector."""

import pytest
from simulations.experiments.replay_analyzer import ReplayAnalyzer


def test_replay_analyzer_structure():
    mock_episode = {
        "steps": [
            [{"observation": {"player": 0}, "action": {}}, {"observation": {"player": 1}, "action": {}}],
            [
                {
                    "observation": {
                        "player": 0, "day": 0, "hour": 23,
                        "farms": [{"farmer": [0, 0], "tiles": [[{"kind": "COOP", "animal": "GOOSE", "fertilizer_available": True}]]}],
                        "private": {"shed": {}}
                    },
                    "action": {"farmer": ["PASS"]}
                },
                {
                    "observation": {"player": 1, "farms": [{"farmer": [0, 0], "tiles": []}], "private": {"shed": {}}},
                    "action": {"farmer": ["PASS"]}
                }
            ]
        ]
    }

    analyzer = ReplayAnalyzer(mock_episode)
    audit = analyzer.analyze_player(0)

    assert "inefficiencies" in audit
    assert audit["inefficiencies"]["missed_fertilizer_days"] == 1
    assert audit["money_left_on_table_estimate"] >= 100.0
