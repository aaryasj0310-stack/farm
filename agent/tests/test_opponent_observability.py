"""Unit tests for opponent-model failure observability."""
import pytest
import main as agent_main


def setup_function():
    import config
    config.set_opponent_intelligence_mode("O1")
    agent_main.reset_opponent_model_state()


def test_opponent_diagnostics_clean_baseline():
    """Initial diagnostics have zero failure count and is_degraded=False."""
    diag = agent_main.get_opponent_model_diagnostics()
    assert diag["failure_count"] == 0
    assert diag["is_degraded"] is False
    assert diag["last_exception_type"] is None
    assert diag["last_exception_message"] is None
    assert diag["last_failure_step"] is None


def test_opponent_diagnostics_records_failure():
    """Malformed opponent observation triggers exception and records diagnostic failure."""
    # A ctx with an opponent_farm that raises during iter_tiles or snapshot
    class FaultyOpponentFarm:
        def iter_tiles(self):
            raise ValueError("Simulated malformed opponent farm observation")

    ctx = {
        "opponent_farm": FaultyOpponentFarm(),
        "day": 5,
        "hour": 2,
        "step": 122,
    }
    mem = {}
    advice = agent_main._build_opp_advice(ctx, mem)

    # Main agent does not crash, returns safe OpponentAdvice
    assert advice is not None

    # Diagnostics recorded failure
    diag = agent_main.get_opponent_model_diagnostics()
    assert diag["failure_count"] == 1
    assert diag["is_degraded"] is True
    assert diag["last_exception_type"] == "ValueError"
    assert "Simulated malformed" in diag["last_exception_message"]
    assert diag["last_failure_step"] == 122


def test_opponent_diagnostics_reset():
    """reset_opponent_model_state() cleans failure counters and degraded flags."""
    class FaultyOpponentFarm:
        def iter_tiles(self):
            raise RuntimeError("Failure before reset")

    ctx = {"opponent_farm": FaultyOpponentFarm(), "step": 50}
    agent_main._build_opp_advice(ctx, {})
    assert agent_main.get_opponent_model_diagnostics()["failure_count"] == 1

    # Reset
    agent_main.reset_opponent_model_state()
    diag = agent_main.get_opponent_model_diagnostics()
    assert diag["failure_count"] == 0
    assert diag["is_degraded"] is False
    assert diag["last_exception_type"] is None
