"""
Unit tests for Phase M0-L-C-R2 Evidence Reconciliation.
Tests statistical calculation correctness, release gate integrity, failure mode enforcement,
and evidence provenance.
"""

import os
import sys
import json
import hashlib
import copy
import numpy as np
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.reconcile_phase_m0_l_c_r_evidence import (
    validate_pair_record,
    evaluate_gate_5,
    evaluate_gate_6,
    evaluate_overall_disposition,
    compute_sha256,
    EXPECTED_PAIRED_HASH,
    CONFIRMATION_DIR,
    RELEASE_DIR,
)

def test_raw_confirmation_data_integrity():
    """Verify raw confirmation dataset hash remains unchanged."""
    paired_path = os.path.join(CONFIRMATION_DIR, "paired_results.json")
    assert os.path.exists(paired_path), f"Missing {paired_path}"
    actual_hash = compute_sha256(paired_path)
    assert actual_hash == EXPECTED_PAIRED_HASH, f"Raw confirmation hash mismatch! Got {actual_hash}"

def test_official_submission_zip_hash():
    """Verify official submission zip exists and retains canonical SHA-256."""
    zip_path = os.path.join("dist", "submission.zip")
    assert os.path.exists(zip_path), f"Missing {zip_path}"
    expected_hash = "e7ff7c5a4b91364c10898cb8a22e4680c9330f1e30171593da2d1eed7dd4ed41"
    actual_hash = compute_sha256(zip_path)
    assert actual_hash == expected_hash, f"Submission ZIP hash mismatch! Got {actual_hash}"

def test_paired_delta_percentile_calculation_synthetic():
    """
    Verify that paired percentiles must be calculated on deltas directly.
    Demonstrates that subtracting arm percentiles produces mathematical distortion.
    """
    c0 = np.array([100.0, 200.0, 300.0, 400.0])
    c1 = np.array([250.0, 150.0, 450.0, 350.0])
    deltas = c1 - c0  # [+150, -50, +150, -50]
    
    # Subtraction of arm percentiles:
    subtracted_p75 = np.percentile(c1, 75) - np.percentile(c0, 75)  # 375.0 - 325.0 = 50.0
    # True empirical percentile of paired differences:
    empirical_p75 = np.percentile(deltas, 75)  # 150.0
    
    # Assert strict discrepancy demonstrating the mathematical error
    assert subtracted_p75 != empirical_p75, "Quantile subtraction should NOT equal empirical quantile on non-comonotonic data"
    assert empirical_p75 == 150.0
    assert subtracted_p75 == 50.0
    assert abs(empirical_p75 - subtracted_p75) == 100.0

def test_reconciled_distribution_extrema():
    """Verify all recomputed distribution extrema match exact raw confirmation values."""
    agg_path = os.path.join(CONFIRMATION_DIR, "aggregate_statistics.json")
    with open(agg_path, "r", encoding="utf-8") as f:
        stats = json.load(f)
    
    extrema = stats["extrema"]
    assert extrema["c0_min"] == 74459.0
    assert extrema["c0_max"] == 127585.0
    assert extrema["c1_min"] == 78965.0
    assert extrema["c1_max"] == 141462.0
    assert extrema["maximum_paired_gain"] == 32164.0
    assert extrema["worst_paired_loss"] == -18097.0
    assert extrema["smallest_negative_delta"] == -70.0
    
    # Empirical delta percentiles
    p_deltas = stats["paired_gain_percentiles"]
    assert abs(p_deltas["p10"] - 89.30) < 1e-2
    assert abs(p_deltas["p25"] - 2852.25) < 1e-2
    assert p_deltas["p50"] == 6003.0
    assert abs(p_deltas["p75"] - 10426.25) < 1e-2
    assert abs(p_deltas["p90"] - 15806.40) < 1e-2

def test_missing_mandatory_telemetry_fails_validation():
    """Verify that validate_pair_record raises KeyError/ValueError on missing or None fields."""
    sample_pair = {
        "cell": {"seed": 96541, "opponent": "pass", "seat": 0},
        "c0": {
            "final_cash": 100000.0,
            "move_count": 4500,
            "confirmed_animal_escapes": 0,
            "max_consecutive_unfed": 1,
            "starvation_events": 200,
            "min_wheat_in_shed": 5,
            "max_market_orders": 8,
        },
        "c1": {
            "final_cash": 105000.0,
            "move_count": 4200,
            "confirmed_animal_escapes": 0,
            "max_consecutive_unfed": 1,
            "starvation_events": 200,
            "min_wheat_in_shed": 5,
            "max_market_orders": 8,
        }
    }
    # Clean pair passes
    validate_pair_record(sample_pair, 0)
    
    # Missing field raises KeyError
    bad_pair_1 = copy.deepcopy(sample_pair)
    del bad_pair_1["c1"]["confirmed_animal_escapes"]
    with pytest.raises(KeyError, match="confirmed_animal_escapes"):
        validate_pair_record(bad_pair_1, 0)
        
    bad_pair_2 = copy.deepcopy(sample_pair)
    del bad_pair_2["c0"]["move_count"]
    with pytest.raises(KeyError, match="move_count"):
        validate_pair_record(bad_pair_2, 0)
        
    # None field raises ValueError
    bad_pair_3 = copy.deepcopy(sample_pair)
    bad_pair_3["c1"]["max_consecutive_unfed"] = None
    with pytest.raises(ValueError, match="max_consecutive_unfed"):
        validate_pair_record(bad_pair_3, 0)

def test_nonzero_treatment_escapes_fail_gate_5():
    """Verify that any confirmed treatment escape causes Gate 5 to FAIL."""
    sample_pairs = [
        {
            "c0": {"confirmed_animal_escapes": 0},
            "c1": {"confirmed_animal_escapes": 0}
        },
        {
            "c0": {"confirmed_animal_escapes": 0},
            "c1": {"confirmed_animal_escapes": 1}  # One escape in treatment!
        }
    ]
    res = evaluate_gate_5(sample_pairs)
    assert res["passed"] is False
    assert res["disposition"] == "FAIL"
    assert res["treatment_total_escapes"] == 1

def test_feed_safety_violations_fail_gate_6():
    """Verify that engine feed-safety violations cause Gate 6 to FAIL."""
    # Scenario A: max_consecutive_unfed reaches engine escape threshold (2)
    pairs_violating_unfed = [
        {
            "c1": {
                "confirmed_animal_escapes": 0,
                "max_consecutive_unfed": 2,  # Fatal threshold reached
                "min_wheat_in_shed": 0,
                "starvation_events": 500,
            }
        }
    ]
    res_a = evaluate_gate_6(pairs_violating_unfed)
    assert res_a["passed"] is False
    assert res_a["disposition"] == "FAIL"
    assert res_a["engine_survival_invariant_verified"] is False
    
    # Scenario B: confirmed animal escape observed
    pairs_violating_escapes = [
        {
            "c1": {
                "confirmed_animal_escapes": 1,  # Animal died/escaped
                "max_consecutive_unfed": 1,
                "min_wheat_in_shed": 0,
                "starvation_events": 500,
            }
        }
    ]
    res_b = evaluate_gate_6(pairs_violating_escapes)
    assert res_b["passed"] is False
    assert res_b["disposition"] == "FAIL"

def test_unverified_feed_floor_produces_unverified_disposition():
    """Verify that when survival invariant passes but feed buffer floor is 0, Gate 6 is UNVERIFIED."""
    pairs = [
        {
            "c1": {
                "confirmed_animal_escapes": 0,
                "max_consecutive_unfed": 1,
                "min_wheat_in_shed": 0,  # Buffer reached 0
                "starvation_events": 300,
            }
        }
    ]
    res = evaluate_gate_6(pairs)
    assert res["passed"] is False
    assert res["disposition"] == "UNVERIFIED"
    assert res["engine_survival_invariant_verified"] is True
    assert "UNVERIFIED" in res["audit_notes"]

def test_failed_or_unverified_gate_prevents_unconditional_certification():
    """Verify evaluate_overall_disposition handles FAIL, UNVERIFIED, and PASS appropriately."""
    mock_gates = {
        "gate_1": {"disposition": "VERIFIED PASS"},
        "gate_2": {"disposition": "VERIFIED PASS"},
        "gate_3": {"disposition": "VERIFIED PASS"},
        "gate_4": {"disposition": "VERIFIED PASS"},
        "gate_5": {"disposition": "VERIFIED PASS"},
        "gate_6": {"disposition": "VERIFIED PASS"},
        "gate_7": {"disposition": "VERIFIED PASS"},
        "gate_8": {"disposition": "VERIFIED PASS"},
    }
    # All 8 pass
    all_pass = evaluate_overall_disposition(mock_gates)
    assert all_pass["certification_status"] == "CERTIFIED"
    assert all_pass["audited_release_disposition"] == "UNCONDITIONALLY_CERTIFIED"
    assert all_pass["gates_verified_pass_count"] == 8
    
    # One UNVERIFIED gate
    one_unverified = copy.deepcopy(mock_gates)
    one_unverified["gate_6"]["disposition"] = "UNVERIFIED"
    res_unv = evaluate_overall_disposition(one_unverified)
    assert res_unv["certification_status"] == "UNCONDITIONAL_CERTIFICATION_WITHHELD"
    assert res_unv["audited_release_disposition"] == "PROVISIONAL_PASS_UNVERIFIED_GATES"
    assert res_unv["gates_verified_pass_count"] == 7
    assert "gate_6" in res_unv["unverified_gates"]
    
    # One FAILED gate
    one_failed = copy.deepcopy(mock_gates)
    one_failed["gate_5"]["disposition"] = "FAIL"
    res_fail = evaluate_overall_disposition(one_failed)
    assert res_fail["certification_status"] == "REJECTED"
    assert res_fail["audited_release_disposition"] == "REJECTED_VERIFIED_FAIL"
    assert "gate_5" in res_fail["failed_gates"]

def test_downside_movement_telemetry_uses_move_count():
    """Verify downside forensics uses true 'move_count' and matches audit targets."""
    downside_path = os.path.join(CONFIRMATION_DIR, "downside_forensics.json")
    with open(downside_path, "r", encoding="utf-8") as f:
        downside = json.load(f)
    
    assert downside["total_losses"] == 20
    assert abs(downside["mean_loss"] - (-4882.80)) < 1e-2
    assert abs(downside["median_loss"] - (-4065.00)) < 1e-2
    assert abs(downside["worst_loss"] - (-18097.00)) < 1e-2
    assert abs(downside["smallest_negative_delta"] - (-70.00)) < 1e-2
    assert abs(downside["mean_moves_saved"] - 172.55) < 1e-2
    assert downside["losses_with_reduced_movement"] == "17 / 20"
    
    # Verify every loss record contains nonzero movement telemetry
    for rec in downside["all_20_loss_records"]:
        assert rec["c0_move_count"] > 3000
        assert rec["c1_move_count"] > 3000
        assert rec["moves_saved"] == rec["c0_move_count"] - rec["c1_move_count"]

def test_all_20_loss_records_match_raw_pairs():
    """Verify that all 20 loss records strictly match the original paired_results.json."""
    paired_path = os.path.join(CONFIRMATION_DIR, "paired_results.json")
    with open(paired_path, "r", encoding="utf-8") as f:
        pairs = json.load(f)
        
    downside_path = os.path.join(CONFIRMATION_DIR, "downside_forensics.json")
    with open(downside_path, "r", encoding="utf-8") as f:
        downside = json.load(f)
        
    raw_losses = [p for p in pairs if p["c1"]["final_cash"] < p["c0"]["final_cash"]]
    assert len(raw_losses) == 20
    
    # Map raw losses by (seed, opponent, seat)
    raw_loss_map = {
        (p["cell"]["seed"], p["cell"]["opponent"], p["cell"]["seat"]): p
        for p in raw_losses
    }
    
    for rec in downside["all_20_loss_records"]:
        key = (rec["cell"]["seed"], rec["cell"]["opponent"], rec["cell"]["seat"])
        assert key in raw_loss_map, f"Loss record {key} not found in raw losses"
        raw_p = raw_loss_map[key]
        assert rec["c0_cash"] == raw_p["c0"]["final_cash"]
        assert rec["c1_cash"] == raw_p["c1"]["final_cash"]
        assert rec["loss_delta"] == raw_p["c1"]["final_cash"] - raw_p["c0"]["final_cash"]
        assert rec["c0_move_count"] == raw_p["c0"]["move_count"]
        assert rec["c1_move_count"] == raw_p["c1"]["move_count"]
        assert rec["c0_confirmed_escapes"] == raw_p["c0"]["confirmed_animal_escapes"]
        assert rec["c1_confirmed_escapes"] == raw_p["c1"]["confirmed_animal_escapes"]

def test_reconciliation_manifest_r2_integrity():
    """Verify reconciliation_manifest_r2.json exists and all listed hashes match files on disk."""
    manifest_path = os.path.join(CONFIRMATION_DIR, "reconciliation_manifest_r2.json")
    assert os.path.exists(manifest_path), f"Missing {manifest_path}"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    assert manifest["phase"] == "M0-L-C-R2-FINAL-INTEGRITY"
    assert manifest["provenance"]["source_promotion_commit"] == "faa6cb99f66b2066e639806d0eabc72a0c7d7982"
    
    verified_hashes = manifest["verified_file_hashes"]
    for file_key, file_info in verified_hashes.items():
        path = file_info["path"]
        expected_hash = file_info["sha256"]
        if expected_hash is not None and os.path.exists(path):
            actual_hash = compute_sha256(path)
            assert actual_hash == expected_hash, f"Hash mismatch for {file_key} ({path}): expected {expected_hash}, got {actual_hash}"
