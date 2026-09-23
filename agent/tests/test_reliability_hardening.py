"""Reliability Hardening Tests for Bug 1, Bug 2, and Bug 3.

Bug 1: Cross-episode stale opponent state reset
Bug 2: Top-level exception deterministic safe fallback with diagnostics
Bug 3: Hour-23 survival watering safeguard
"""
import copy
import pytest
from unittest.mock import patch

from config import PRIORITY_URGENT_SURVIVAL
import main as agent_module
from main import agent, get_last_fallback_diagnostic, reset_opponent_model_state
from state.state_tracker import get_state, reset_memory, _STATE
from state.observation_parser import parse_observation
from execution.task_scheduler import build_tasks, assign_tasks
from strategy.macro_planner import MacroPlan


def _make_minimal_obs(day=0, hour=0, step=0, player=0, money=3000.0, num_hands=0):
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    for y in range(board):
        for x in range(board):
            if x >= 5 or y >= 5:
                tiles[y][x] = "LOCKED"
    our_farm = {
        "money": money,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4] for _ in range(num_hands)],
        "unlocked_quadrants": ["NW"],
        "hires_today": 0,
    }
    opp_farm = {
        "money": money,
        "tiles": copy.deepcopy(tiles),
        "farmer": [4, 4],
        "hands": [],
        "unlocked_quadrants": ["NW"],
        "hires_today": 0,
    }
    return {
        "player": player,
        "day": day,
        "hour": hour,
        "step": step,
        "farms": [our_farm, opp_farm],
        "market": {"inventory": {"WHEAT": 1000}, "prices": {"WHEAT": 25}},
        "town": {"unlocked_shops": []},
        "private": {"shed": {}, "seeds": {}, "inventories": [{}] * (1 + num_hands)},
    }


# ==============================================================================
# BUG 1 TESTS — Cross-episode stale opponent state lifecycle
# ==============================================================================
class TestBug1OpponentStateLifecycle:
    def setup_method(self):
        from config import get_opponent_intelligence_mode, set_opponent_intelligence_mode
        self._orig_opp_mode = get_opponent_intelligence_mode()
        set_opponent_intelligence_mode("O1")
        reset_memory(_STATE)
        reset_opponent_model_state()

    def teardown_method(self):
        from config import set_opponent_intelligence_mode
        set_opponent_intelligence_mode(getattr(self, "_orig_opp_mode", "O0_SHADOW"))

    def test_opponent_state_modified_in_game_a(self):
        """Game A populates opponent snapshot and shed estimate."""
        obs = _make_minimal_obs(day=0, hour=0)
        obs["farms"][1]["tiles"][0][0] = {
            "kind": "PLANT", "crop": "MELON", "planted_day": 0,
            "yield_units": 1, "watered_today": True, "consecutive_unwatered": 0,
            "fertilized_until_day": -1,
        }
        agent(obs)
        assert agent_module._prev_opp_snapshot is not None
        assert agent_module._estimated_shed is not None

    def test_game_b_day0_resets_opponent_state(self):
        """Game B starting at Day 0 does NOT inherit Game A's opponent snapshot or estimated shed."""
        obs_a = _make_minimal_obs(day=15, hour=12, step=372)
        obs_a["farms"][1]["tiles"][0][0] = {
            "kind": "PLANT", "crop": "MELON", "planted_day": 0,
            "yield_units": 1, "watered_today": True, "consecutive_unwatered": 0,
            "fertilized_until_day": -1,
        }
        agent(obs_a)
        prev_snap_a = agent_module._prev_opp_snapshot
        assert prev_snap_a is not None

        # Game B starts at Day 0 Hour 0
        obs_b = _make_minimal_obs(day=0, hour=0, step=0)
        agent(obs_b)

        assert agent_module._prev_opp_snapshot != prev_snap_a
        assert agent_module._estimated_shed.get("MELON", 0) == 0

    def test_reset_memory_triggers_opponent_state_reset(self):
        """Direct invocation of reset_memory() resets opponent model state."""
        agent_module._prev_opp_snapshot = {"dummy": 1}
        agent_module._estimated_shed = {"MELON": 50}

        reset_memory(_STATE)
        assert agent_module._prev_opp_snapshot is None
        assert agent_module._estimated_shed is None

    def test_same_episode_normal_progression_does_not_reset(self):
        """Progression from Day 0 -> Day 1 -> Day 2 does NOT reset opponent state."""
        obs_d0 = _make_minimal_obs(day=0, hour=0, step=0)
        agent(obs_d0)
        snap_d0 = agent_module._prev_opp_snapshot
        assert snap_d0 is not None

        obs_d1 = _make_minimal_obs(day=1, hour=0, step=24)
        agent(obs_d1)
        assert agent_module._prev_opp_snapshot is not None
        assert len(_STATE["days_seen"]) >= 2

        obs_d2 = _make_minimal_obs(day=2, hour=0, step=48)
        agent(obs_d2)
        assert agent_module._prev_opp_snapshot is not None

    def test_existing_same_episode_tracking_continues_to_work(self):
        """Within one game, delta detection tracks opponent crop state changes."""
        obs_h0 = _make_minimal_obs(day=1, hour=0, step=24)
        obs_h0["market"]["inventory"]["MELON"] = 100
        obs_h0["farms"][1]["tiles"][0][0] = {
            "kind": "PLANT", "crop": "MELON", "planted_day": 0,
            "yield_units": 1, "watered_today": False, "consecutive_unwatered": 0,
            "fertilized_until_day": -1,
        }
        agent(obs_h0)

        obs_h1 = _make_minimal_obs(day=1, hour=1, step=25)
        obs_h1["market"]["inventory"]["MELON"] = 99
        obs_h1["farms"][1]["tiles"][0][0] = None
        agent(obs_h1)

        assert agent_module._estimated_shed.get("MELON", 0) >= 1


# ==============================================================================
# BUG 2 TESTS — Top-level exception deterministic safe fallback
# ==============================================================================
class TestBug2EmergencyFallback:
    def setup_method(self):
        reset_memory(_STATE)
        reset_opponent_model_state()

    def test_observation_parsing_failure_returns_safe_fallback(self):
        """Failure in parse_observation does not crash and returns deterministic fallback."""
        obs = _make_minimal_obs(day=5, hour=3, step=123, num_hands=2)
        with patch("main.get_state", side_effect=ValueError("Corrupted obs")):
            action = agent(obs)

        assert action["farmer"] == ["PASS"]
        assert action["hands"] == [["PASS"], ["PASS"]]
        assert action["market"] == []
        assert action["_emergency_fallback"] is True

        diag = get_last_fallback_diagnostic()
        assert diag is not None
        assert diag["is_fallback"] is True
        assert diag["exception_type"] == "ValueError"
        assert "Corrupted obs" in diag["exception_message"]
        assert diag["step"] == 123

    def test_macro_planning_failure_returns_safe_fallback(self):
        """Failure in macro planner build does not crash."""
        obs = _make_minimal_obs(day=2, hour=0, step=48, num_hands=1)
        with patch("strategy.macro_planner.MacroPlanner.build", side_effect=RuntimeError("Planner bug")):
            action = agent(obs)

        assert action["farmer"] == ["PASS"]
        assert action["hands"] == [["PASS"]]
        assert action["_emergency_fallback"] is True

        diag = get_last_fallback_diagnostic()
        assert diag["exception_type"] == "RuntimeError"

    def test_task_scheduling_failure_returns_safe_fallback(self):
        """Failure in task scheduling does not crash."""
        obs = _make_minimal_obs(day=1, hour=1, step=25, num_hands=3)
        with patch("main.assign_tasks", side_effect=KeyError("Missing unit")):
            action = agent(obs)

        assert action["farmer"] == ["PASS"]
        assert len(action["hands"]) == 3
        assert all(h == ["PASS"] for h in action["hands"])
        assert action["_emergency_fallback"] is True

    def test_market_planning_failure_returns_safe_fallback(self):
        """Failure in OrderBuilder does not crash and does not suppress unit actions."""
        obs = _make_minimal_obs(day=2, hour=0, step=48, num_hands=0)
        with patch("market.order_builder.OrderBuilder.build", side_effect=TypeError("Order failure")):
            action = agent(obs)

        # Domain isolation: purchase failure empties market orders but does not suppress unit actions
        assert isinstance(action["farmer"], list) and len(action["farmer"]) > 0
        assert action["farmer"] != ["PASS"], "Market failure must not suppress unit actions"
        assert action["hands"] == []
        assert action["market"] == []
        assert action.get("_emergency_fallback") is None

    def test_emergency_fallback_distinguishable_from_intentional_pass(self):
        """Emergency fallback has distinct diagnostics while normal decision does not."""
        obs = _make_minimal_obs(day=0, hour=5, step=5)
        normal_action = agent(obs)
        assert normal_action.get("_emergency_fallback") is None
        assert get_last_fallback_diagnostic() is None

        with patch("main._agent_decision", side_effect=ZeroDivisionError("Math error")):
            fallback_action = agent(obs)
        assert fallback_action.get("_emergency_fallback") is True
        assert get_last_fallback_diagnostic() is not None

    def test_one_turn_failure_does_not_corrupt_subsequent_turns(self):
        """Turn T failure falls back safely; Turn T+1 recovers normally."""
        obs_t = _make_minimal_obs(day=1, hour=5, step=29)
        with patch("main.assign_tasks", side_effect=Exception("Transient glitch")):
            action_t = agent(obs_t)
        assert action_t["_emergency_fallback"] is True

        obs_t1 = _make_minimal_obs(day=1, hour=6, step=30)
        action_t1 = agent(obs_t1)
        assert action_t1.get("_emergency_fallback") is None
        assert get_last_fallback_diagnostic() is None

    def test_persistent_failure_remains_operational(self):
        """Multiple consecutive failures do not crash the agent."""
        obs = _make_minimal_obs(day=3, hour=0, step=72, num_hands=2)
        with patch("main._agent_decision", side_effect=Exception("Persistent broken state")):
            for _ in range(10):
                act = agent(obs)
                assert act["farmer"] == ["PASS"]
                assert len(act["hands"]) == 2
                assert act["_emergency_fallback"] is True

    def test_fallback_is_deterministic(self):
        """Repeated fallback calls on the same observation produce identical actions."""
        obs = _make_minimal_obs(day=2, hour=4, step=52, num_hands=4)
        with patch("main._agent_decision", side_effect=Exception("Deterministic error")):
            act1 = agent(obs)
            act2 = agent(obs)
        assert act1 == act2


# ==============================================================================
# BUG 3 TESTS — Hour-23 survival watering safeguard
# ==============================================================================
class TestBug3Hour23SurvivalWatering:
    def _create_ctx(self, hour=23, consecutive_unwatered=1, watered_today=False, planted_day=0, day=2):
        obs = _make_minimal_obs(day=day, hour=hour, step=day * 24 + hour)
        obs["farms"][0]["tiles"][0][0] = {
            "kind": "PLANT",
            "crop": "MELON",
            "planted_day": planted_day,
            "yield_units": 1,
            "watered_today": watered_today,
            "consecutive_unwatered": consecutive_unwatered,
            "fertilized_until_day": -1,
        }
        return parse_observation(obs)

    def test_endangered_plant_generates_water_at_hour_23(self):
        """Plant with consecutive_unwatered == 1 at Hour 23 MUST generate WATER with survival priority."""
        ctx = self._create_ctx(hour=23, consecutive_unwatered=1, watered_today=False)
        macro = MacroPlan(day=ctx["day"])
        tasks = build_tasks(ctx, macro)

        water_tasks = [t for t in tasks if t["op"] == "WATER" and t["target"] == (0, 0)]
        assert len(water_tasks) == 1
        assert water_tasks[0]["priority"] == PRIORITY_URGENT_SURVIVAL

    def test_planting_day_unwatered_plant_generates_water_at_hour_23(self):
        """Planting-day unwatered plant at Hour 23 MUST generate survival WATER."""
        ctx = self._create_ctx(hour=23, consecutive_unwatered=0, watered_today=False, planted_day=2, day=2)
        macro = MacroPlan(day=ctx["day"])
        tasks = build_tasks(ctx, macro)

        water_tasks = [t for t in tasks if t["op"] == "WATER" and t["target"] == (0, 0)]
        assert len(water_tasks) == 1
        assert water_tasks[0]["priority"] == PRIORITY_URGENT_SURVIVAL

    def test_already_watered_plant_no_duplicate_water_at_hour_23(self):
        """Plant already watered today generates NO water task at Hour 23."""
        ctx = self._create_ctx(hour=23, consecutive_unwatered=0, watered_today=True)
        macro = MacroPlan(day=ctx["day"])
        tasks = build_tasks(ctx, macro)

        water_tasks = [t for t in tasks if t["op"] == "WATER" and t["target"] == (0, 0)]
        assert len(water_tasks) == 0

    def test_non_endangered_plant_no_water_at_hour_23(self):
        """Plant with consecutive_unwatered == 0 and planted before today generates NO water at Hour 23."""
        ctx = self._create_ctx(hour=23, consecutive_unwatered=0, watered_today=False, planted_day=0, day=2)
        macro = MacroPlan(day=ctx["day"])
        tasks = build_tasks(ctx, macro)

        water_tasks = [t for t in tasks if t["op"] == "WATER" and t["target"] == (0, 0)]
        assert len(water_tasks) == 0

    def test_multiple_endangered_plants_respect_worker_constraints(self):
        """Multiple endangered plants at Hour 23 respect 1-action-per-unit constraint."""
        obs = _make_minimal_obs(day=2, hour=23, step=71, num_hands=1)
        for i in range(4):
            obs["farms"][0]["tiles"][i][0] = {
                "kind": "PLANT", "crop": "MELON", "planted_day": 0,
                "yield_units": 1, "watered_today": False, "consecutive_unwatered": 1,
                "fertilized_until_day": -1,
            }
        ctx = parse_observation(obs)
        macro = MacroPlan(day=2)
        tasks = build_tasks(ctx, macro)
        water_tasks = [t for t in tasks if t["op"] == "WATER"]
        assert len(water_tasks) == 4

        asg = assign_tasks(tasks, ctx)
        assert len(asg["assignment"]) <= 2

    def test_plant_saved_by_hour_23_watering_survives_engine_refresh(self):
        """Verification against Kaggle engine mechanics: plant watered at Hour 23 does not turn into WEED."""
        from kaggle_environments import make
        env = make("kaggriculture")
        env.reset()
        for _ in range(23):
            env.step(["PASS", "PASS"])

        farm = env.steps[-1][0]["observation"]["farms"][0]
        assert env.steps[-1][0]["observation"]["hour"] == 23
        farm["tiles"][4][4] = {
            "kind": "PLANT", "crop": "WHEAT", "planted_day": 0,
            "yield_units": 1, "watered_today": False, "consecutive_unwatered": 1,
            "fertilized_until_day": -1, "max_lifespan_step": 720
        }
        action = {"farmer": ["WATER"], "hands": [], "market": []}
        env.step([action, "PASS"])

        new_farm = env.steps[-1][0]["observation"]["farms"][0]
        tile = new_farm["tiles"][4][4]
        assert tile.get("kind") == "PLANT"
        assert tile.get("consecutive_unwatered") == 0

    def test_existing_hours_0_to_22_behavior_preserved(self):
        """Normal bonus and routine watering still generates at Hours 0-22."""
        ctx = self._create_ctx(hour=10, consecutive_unwatered=0, watered_today=False, planted_day=0, day=2)
        macro = MacroPlan(day=ctx["day"])
        tasks = build_tasks(ctx, macro)

        water_tasks = [t for t in tasks if t["op"] == "WATER" and t["target"] == (0, 0)]
        assert len(water_tasks) == 1
        assert water_tasks[0]["kind"] == "water"
