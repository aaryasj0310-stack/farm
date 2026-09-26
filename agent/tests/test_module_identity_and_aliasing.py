"""Unit tests verifying Python module identity and bidirectional aliasing.

Guarantees that regardless of whether a caller imports bare (e.g. `execution.midnight_storage_controller`)
or package-prefixed (e.g. `agent.execution.midnight_storage_controller`), the exact same module object,
telemetry dictionaries, and singleton states are shared and mutated in lockstep.
"""
from __future__ import annotations

import subprocess
import sys
import agent.main


def test_midnight_storage_controller_identity():
    """Verify execution.midnight_storage_controller and agent.execution.midnight_storage_controller are identical."""
    import execution.midnight_storage_controller as msc_bare
    import agent.execution.midnight_storage_controller as msc_agent

    assert msc_bare is msc_agent, "Module objects must be identical singletons"
    assert msc_bare._TELEMETRY is msc_agent._TELEMETRY, "Telemetry dict must be identical object"

    # Reset
    msc_bare.reset_midnight_storage_telemetry()
    assert msc_agent.get_midnight_storage_telemetry()["rescue_events"] == 0

    # Mutate from bare
    msc_bare.record_rescue_sale("WHEAT", 15)
    assert msc_agent.get_midnight_storage_telemetry()["rescue_events"] == 1
    assert msc_agent.get_midnight_storage_telemetry()["rescue_units_sold"] == 15

    # Reset from agent
    msc_agent.reset_midnight_storage_telemetry()
    assert msc_bare.get_midnight_storage_telemetry()["rescue_events"] == 0


def test_farm_plan_identity():
    """Verify strategy.farm_plan and agent.strategy.farm_plan are identical singletons."""
    import strategy.farm_plan as fp_bare
    import agent.strategy.farm_plan as fp_agent

    assert fp_bare is fp_agent, "Module objects must be identical singletons"
    assert fp_bare.StrategicState is fp_agent.StrategicState, "StrategicState enum must be identical"

    fp_bare.reset_farm_plan()
    plan_bare = fp_bare.get_farm_plan()
    plan_agent = fp_agent.get_farm_plan()
    assert plan_bare is plan_agent, "get_farm_plan() must return identical instance"

    plan_bare.record_transition(fp_bare.StrategicState.SW_READY, reason="Test transition")
    assert plan_agent.state == fp_agent.StrategicState.SW_READY

    fp_agent.reset_farm_plan()
    assert fp_bare.get_farm_plan().state == fp_bare.StrategicState.SW_NOT_COMMITTED


def test_whole_farm_planner_identity():
    """Verify strategy.whole_farm_planner and agent.strategy.whole_farm_planner are identical singletons."""
    import strategy.whole_farm_planner as wfp_bare
    import agent.strategy.whole_farm_planner as wfp_agent

    assert wfp_bare is wfp_agent, "Module objects must be identical singletons"
    wfp_bare.reset_whole_farm_planner()
    p_bare = wfp_bare.get_whole_farm_planner()
    p_agent = wfp_agent.get_whole_farm_planner()
    assert p_bare is p_agent, "get_whole_farm_planner() must return identical instance"


def test_resource_ledger_identity():
    """Verify strategy.resource_ledger and agent.strategy.resource_ledger are identical."""
    import strategy.resource_ledger as rl_bare
    import agent.strategy.resource_ledger as rl_agent

    assert rl_bare is rl_agent, "Module objects must be identical singletons"
    assert rl_bare.InflowConfidence is rl_agent.InflowConfidence


def test_animal_tracker_identity():
    """Verify diagnostics.animal_tracker and agent.diagnostics.animal_tracker are identical."""
    import diagnostics.animal_tracker as at_bare
    import agent.diagnostics.animal_tracker as at_agent

    assert at_bare is at_agent, "Module objects must be identical singletons"
    assert at_bare.AnimalSurvivalTracker is at_agent.AnimalSurvivalTracker


def test_reverse_import_order_subprocess():
    """Verify in a clean process that importing agent.* first yields identical modules."""
    script = """
import sys, os
import agent.main

# Import agent prefix first
import agent.execution.midnight_storage_controller as msc_ag
import execution.midnight_storage_controller as msc_bare
assert msc_ag is msc_bare, "Subprocess: msc modules not identical"

import agent.strategy.farm_plan as fp_ag
import strategy.farm_plan as fp_bare
assert fp_ag is fp_bare, "Subprocess: farm_plan modules not identical"

import agent.strategy.whole_farm_planner as wfp_ag
import strategy.whole_farm_planner as wfp_bare
assert wfp_ag is wfp_bare, "Subprocess: whole_farm_planner modules not identical"

print("ALL_SUBPROCESS_ASSERTIONS_PASSED")
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert "ALL_SUBPROCESS_ASSERTIONS_PASSED" in result.stdout
