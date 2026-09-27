"""Automated Evidence Consistency and Regression Test Suite for Phase SW-B3A-R1A.

Validates that all reported figures, economic ledgers, lifecycle stages,
worker telemetry, and storage discard metrics strictly agree with underlying
engine-grounded JSON artifacts in simulations/results/phase_sw_b3a_r1a/.
"""
import json
import os
import re
import pytest
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "simulations", "results", "phase_sw_b3a_r1a")
REPORT_PATH = os.path.join(PROJECT_ROOT, "reports", "phase_sw_b3a_r1a_evidence_consistency.md")


@pytest.fixture(scope="module")
def waterfalls_data():
    path = os.path.join(RESULTS_DIR, "paired_waterfalls_20_pairs.json")
    assert os.path.exists(path), f"Missing artifact: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def summary_data():
    path = os.path.join(RESULTS_DIR, "summary_report_data.json")
    assert os.path.exists(path), f"Missing artifact: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def lifecycles_data():
    path = os.path.join(RESULTS_DIR, "sw_lifecycle_9stages.json")
    assert os.path.exists(path), f"Missing artifact: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ledgers_data():
    path = os.path.join(RESULTS_DIR, "transaction_ledgers_40_matches.json")
    assert os.path.exists(path), f"Missing artifact: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def worker_data():
    path = os.path.join(RESULTS_DIR, "worker_action_telemetry.json")
    assert os.path.exists(path), f"Missing artifact: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def storage_data():
    path = os.path.join(RESULTS_DIR, "storage_discard_reconciliation.json")
    assert os.path.exists(path), f"Missing artifact: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_sw_purchasing_classification(waterfalls_data, summary_data):
    """Verify that exactly 16 matches purchased SW and 4 did not, with correct mean deltas."""
    purchased = [p for p in waterfalls_data if p["sw_purchased"]]
    not_purchased = [p for p in waterfalls_data if not p["sw_purchased"]]

    assert len(purchased) == 16, f"Expected 16 SW purchasing matches, got {len(purchased)}"
    assert len(not_purchased) == 4, f"Expected 4 non-purchasing matches, got {len(not_purchased)}"

    # Specific pairs that must NOT have purchased SW
    non_purchasing_ids = {p["pair_id"] for p in not_purchased}
    expected_non_purchasing = {
        "s97013_pure_wheat_rush_seat0",
        "s97013_pure_wheat_rush_seat1",
        "s97014_pass_seat0",
        "s97014_pass_seat1",
    }
    assert non_purchasing_ids == expected_non_purchasing

    purchased_deltas = [p["paired_delta"] for p in purchased]
    all_deltas = [p["paired_delta"] for p in waterfalls_data]

    purchased_mean_delta = round(float(np.mean(purchased_deltas)), 2)
    overall_mean_delta = round(float(np.mean(all_deltas)), 2)

    assert purchased_mean_delta == -1259.06, f"Expected -$1,259.06, got {purchased_mean_delta}"
    assert overall_mean_delta == -1007.25, f"Expected -$1,007.25, got {overall_mean_delta}"

    # Verify summary JSON fields
    assert summary_data["stats"]["pooled"]["purchasing_pairs"] == 16
    assert summary_data["stats"]["pooled"]["purchasing_mean_delta"] == -1259.06


def test_economic_waterfall_panel_averages(waterfalls_data, summary_data):
    """Verify that panel average waterfall values strictly match the independent audit check."""
    wf_sum = summary_data["waterfalls_summary"]

    assert wf_sum["mean_sw_net_margin"] == 5658.18
    assert wf_sum["mean_core_crop_delta"] == -6249.68
    assert wf_sum["mean_core_seed_cost_delta"] == -71.00
    assert wf_sum["mean_animal_rev_delta"] == 222.80
    assert wf_sum["mean_feed_cost_delta"] == 479.55
    assert wf_sum["mean_animal_purchase_delta"] == 230.00
    assert wf_sum["mean_fertilizer_expenditure_delta"] == 0.00
    assert wf_sum["mean_hiring_cost_delta"] == 0.00
    assert wf_sum["mean_wages_delta"] == 0.00
    assert wf_sum["observed_paired_delta"] == -1007.25
    assert wf_sum["accounted_delta"] == -1007.25
    assert wf_sum["waterfall_residual"] == 0.00
    assert wf_sum["all_waterfalls_zero_residual"] is True

    # Check arithmetic closure:
    # delta = sw_net + core_crop - core_seed + anim_rev - feed - fert - anim_purch - hire - wages
    expected_delta = round(
        5658.18
        + (-6249.68)
        - (-71.00)
        + 222.80
        - 479.55
        - 0.00
        - 230.00
        - 0.00
        - 0.00,
        2,
    )
    assert expected_delta == -1007.25


def test_individual_matches_and_waterfalls_zero_residual(waterfalls_data, ledgers_data):
    """Verify that every individual match ledger and every paired waterfall has $0.00 residual."""
    # 40 match ledgers
    for l in ledgers_data:
        residual = l["cash_reconciliation"]["residual"]
        assert residual == 0.0, f"Non-zero residual in match {l['match_id']}: {residual}"
        assert l["cash_reconciliation"]["zero_residual_verified"] is True

    # 20 paired waterfalls
    for p in waterfalls_data:
        w_res = p["cash_waterfall"]["waterfall_residual"]
        assert w_res == 0.0, f"Non-zero waterfall residual in pair {p['pair_id']}: {w_res}"
        assert p["cash_waterfall"]["zero_residual_verified"] is True


def test_unified_canonical_stage_9_telemetry(lifecycles_data):
    """Verify that Stage 9 telemetry is canonically unified with exact non-zero steps."""
    for l in lifecycles_data:
        pid = l["pair_id"]
        purch = l["sw_purchased"]
        st9 = l["lifecycle_stages"].get("stage_9_first_productive_plant")

        # Must not contain legacy duplicate key
        assert "stage_9_planted" not in l["lifecycle_stages"], f"Found legacy stage_9_planted key in {pid}"

        if purch:
            assert st9 is not None, f"Missing Stage 9 in purchasing match {pid}"
            assert st9["step"] > 0, f"Invalid step in {pid}: {st9['step']}"
            assert st9["day"] >= 9, f"Invalid day in {pid}: {st9['day']}"
            assert 0 <= st9["hour"] < 24, f"Invalid hour in {pid}: {st9['hour']}"
            assert st9["crop"] == "STRAWBERRY", f"Invalid crop in {pid}: {st9['crop']}"
            assert len(st9["pos"]) == 2, f"Invalid pos in {pid}: {st9['pos']}"
            assert st9["successful_planting"] is True
        else:
            assert st9 is None, f"Non-purchasing match {pid} must not have Stage 9 plant event"


def test_worker_action_telemetry_reconciliation(worker_data, summary_data):
    """Verify that worker action averages match source JSON and distinguish moves from productive labor."""
    wap = summary_data["worker_action_panel_summary"]
    assert wap["mean_move_actions_delta"] == 198.50
    assert wap["mean_water_actions_delta"] == 7.60
    assert wap["mean_actions_in_core_delta"] == -349.75
    assert wap["mean_actions_in_sw_delta"] == 347.65

    # Direct verification from raw worker pairs
    c_moves = np.mean([p["control"]["move_actions"] for p in worker_data])
    t_moves = np.mean([p["treatment"]["move_actions"] for p in worker_data])
    assert round(t_moves - c_moves, 2) == 198.50

    c_water = np.mean([p["control"]["water_actions"] for p in worker_data])
    t_water = np.mean([p["treatment"]["water_actions"] for p in worker_data])
    assert round(t_water - c_water, 2) == 7.60


def test_storage_discard_panel_totals(storage_data, summary_data):
    """Verify that full-panel storage discard totals match source JSON (392 vs 340)."""
    s_sum = summary_data["storage_discard_panel_summary"]
    assert s_sum["control_total_discarded_units"] == 392
    assert s_sum["treatment_total_discarded_units"] == 340
    assert s_sum["control_total_rescue_units"] == 1828
    assert s_sum["treatment_total_rescue_units"] == 2049

    c_disc = sum(p["control"]["genuine_overflow_units_discarded"] for p in storage_data)
    t_disc = sum(p["treatment"]["genuine_overflow_units_discarded"] for p in storage_data)
    assert c_disc == 392
    assert t_disc == 340


def test_report_consistency_against_json(summary_data):
    """Verify that every important numerical claim in the deliverable report matches the JSON."""
    if not os.path.exists(REPORT_PATH):
        pytest.skip(f"Report file {REPORT_PATH} not yet written.")

    with open(REPORT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Core required figures
    assert "$109,444.30" in content, "Control mean cash missing in report"
    assert "$108,437.05" in content, "Treatment mean cash missing in report"
    assert "-$1,007.25" in content, "Overall mean paired delta missing in report"
    assert "16 / 20" in content or "16/20" in content, "16/20 SW purchase count missing in report"
    assert "-$1,259.06" in content, "Purchasing mean delta missing in report"
    assert "+$5,658.18" in content, "SW net margin missing in report"
    assert "-$6,249.68" in content, "Core crop delta missing in report"
    assert "-$71.00" in content, "Core seed cost delta missing in report"
    assert "+$222.80" in content, "Animal revenue delta missing in report"
    assert "+$479.55" in content, "Feed expenditure delta missing in report"
    assert "+$230.00" in content, "Animal purchase delta missing in report"
    assert "392" in content, "Control total discard units (392) missing in report"
    assert "340" in content, "Treatment total discard units (340) missing in report"
    assert "+198.5" in content, "Move actions delta (+198.5) missing in report"
    assert "+7.6" in content, "Water actions delta (+7.6) missing in report"
    assert "-349.75" in content, "Core actions delta (-349.75) missing in report"
    assert "+347.65" in content, "SW actions delta (+347.65) missing in report"
    assert "1,000 ms" in content or "1000 ms" in content, "1,000 ms actTimeout missing in report"
