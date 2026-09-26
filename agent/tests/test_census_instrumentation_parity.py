"""Regression test verifying census instrumentation non-invasiveness and bitwise parity.
"""
from __future__ import annotations

import copy
import pytest
import kaggle_environments as ke
try:
    from main import agent, reset_agent_state
except ImportError:
    from agent.main import agent, reset_agent_state
import config
from execution.midnight_storage_controller import reset_midnight_storage_telemetry
from strategy.sw_tranche_controller import reset_sw_tranche_controller
from simulations.experiments.agent_zoo import get_agent
from simulations.census.engine_instrumentation import CensusSession


def test_census_instrumentation_zero_side_effects():
    """Verify that CensusSession produces 0 side-effects on actions and terminal cash."""
    seed = 97013
    opp_name = "pass"
    seat = 0

    def run_match(instrumented: bool):
        config.set_midnight_storage_dump_mode("RESCUE")
        config.set_same_turn_crop_pipeline_mode("OFF")
        config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
        config.SOFT_WORKER_LOCALITY_MODE = "OFF"
        config.set_same_turn_deposit_sell_mode("BASELINE")
        config.set_animal_service_economics_mode("OFF")

        reset_agent_state()
        reset_midnight_storage_telemetry()
        reset_sw_tranche_controller()

        env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
        env.reset()
        opp_agent = get_agent(opp_name)

        session = CensusSession(seat) if instrumented else None
        if session:
            session.install_hooks(env)

        actions = []
        try:
            while not env.done:
                obs_pre = env.state[seat].observation
                if session:
                    session.attach_env_state(env.state)
                act = agent(obs_pre, env.configuration)
                actions.append(copy.deepcopy(act))
                try:
                    opp_act = opp_agent(env.state[1 - seat].observation, env.configuration)
                except TypeError:
                    opp_act = opp_agent(env.state[1 - seat].observation)
                env.step([act, opp_act])
        finally:
            if session:
                session.remove_hooks()

        return float(env.state[seat].observation.farms[seat].money), actions

    cash_uninst, actions_uninst = run_match(False)
    cash_inst, actions_inst = run_match(True)

    assert cash_uninst == cash_inst
    assert len(actions_uninst) == len(actions_inst) == 719
    for s in range(719):
        assert actions_uninst[s] == actions_inst[s], f"Mismatch at step {s}"
