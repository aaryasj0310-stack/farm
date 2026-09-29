# Phase SW-C2-R2: Acquisition, Executable Capacity, & Reservation Telemetry Report

**Date:** 2026-09-29  
**Branch:** `experiment/sw-c2-r2-early-acquisition`  
**Base Commit:** `af08690153efbd988a00bb3ccfbee8ae434cfec6`  
**Adjudication Commit:** `d571eb4`  
**Verification Gates:** Experimental Correctness Gate (PASSED) | Production Release Gate (PRESERVED)

---

## 1. Executive Summary

Phase SW-C2-R2 delivers the full architecture for dynamic SW acquisition preference (Day 8–10), executable workforce availability modeling, shared reservation integration into the `ServiceObligationLedger`, and settlement/utilization telemetry.

All 6 authorized deliverables have been implemented and verified:
1. **Dynamic D8–D10 SW Acquisition Preference:** Earlier acquisition (D8, D9, D10) is prioritized when economically justified, verifying treasury buffer ($2,500+), seed costs, 3-day feed buffer, and service capacity.
2. **Settlement & Utilization Telemetry:** Replaced placeholder telemetry with exact engine step/day/hour of purchase, pre- and post-purchase cash, first productive planting turn/crop/coordinates, and clear distinction between purchase emission and settlement.
3. **Executable Workforce Availability:** Expansion planning and capacity forecasting strictly rely on physically present workers (`1 + len(farm.hands)`), honor `release_step` and task prerequisites, and decrement carried/shed resources upon assignment.
4. **Shared Reservation & Dispatch Capacity:** SW crop cycle reservations register active unit obligations (`PLANT`, `WATER`, `HARVEST`) into the centralized `ServiceObligationLedger`.
5. **Reservation Lifecycle:** Atomic lifecycle transitions (`TRIAL` -> `COMMITTED` -> `CANCELLED`/`FULFILLED`) release or clean up obligations in both the reservation manager and shared ledger upon acquisition withdrawal or market rejection.
6. **Preserved Acreage Ladder:** The 8 -> 12 -> 16 -> 20 -> 24 incremental expansion ladder option is fully preserved with executable worker checks.

---

## 2. Deliverable Verification Details

### Deliverable 1: Dynamic D8–D10 SW Acquisition Preference
- **Configuration & Gate Control:** `SW_R2_DYNAMIC_ACQUISITION_ENABLED` added to `agent/config.py` (defaults to `False`).
- **Dynamic Unlock Day:** `get_effective_quadrant_unlock_day(3)` returns Day 8 when enabled, allowing the planner to evaluate Day 8 and Day 9 purchases without artificial Day 9/12 locks.
- **Economic Justification:** Governed by `evaluate_candidate_crop_economics`, `evaluate_sw_timing`, and 5-point certificate verification.

### Deliverable 2: Settlement and Utilization Telemetry
- **Settlement Fields Added to `SWLandLifecycleTelemetry`:**
  - `exact_purchase_step`, `exact_purchase_day`, `exact_purchase_hour`
  - `cash_before_purchase`, `cash_after_purchase`
  - `purchase_settled` (boolean)
  - `purchase_attempt_steps` (list of engine steps where market order was emitted)
  - `first_productive_plant_step`, `first_productive_plant_day`, `first_productive_plant_crop`, `first_productive_plant_pos`
- **Distinction Between Attempt and Settlement:** Emitted purchase orders log to `purchase_attempt_steps`; engine confirmation in `observe_engine_step` sets `purchase_settled = True` and computes exact cash delta.

### Deliverable 3: Executable Workforce Availability
- **Physical Workforce Count:** `SWTrancheController.maybe_evaluate_adaptive_expansion` computes `active_workers = 1 + len(getattr(farm, "hands", []) or [])`.
- **Forecast Capacity Decrement:** `WorkforceCapacityForecaster` decrements carried items (`WHEAT` for feeding, seeds for planting) and shed inventory during forward simulation.
- **Prerequisite & Release Step Adherence:** Workers cannot start an obligation until `max(step, obl.release_step)` and all prerequisite tasks complete.

### Deliverable 4: Shared Reservation and Dispatch Capacity
- **Shared Registration:** `CropCycleReservationManager.commit_reservation` pushes all tranche obligations directly into `ServiceObligationLedger`.
- **Global Coordination:** Worker dispatch in `GlobalWorkforceCoordinator` and `WorkforceCapacityForecaster` inspects shared obligations across NW, NE, and SW.

### Deliverable 5: Clean Reservation Lifecycle & Cancellation
- **Atomic Cancellation:** `CropCycleReservationManager.cancel_reservation(res_id, reason)` marks the reservation `ReservationState.CANCELLED` and marks all registered obligations `ObligationLifecycle.CANCELLED` in the ledger.
- **Fail-Closed Cleanup:** If a land order fails (`notify_land_order_failed`), pending reservations are immediately cancelled.

### Deliverable 6: Preserved Acreage Ladder
- The 4-tile increment blocks (`12`, `16`, `20`, `24`) in `AdaptiveAcreagePlanner` remain intact, respecting shed port `(4, 5)` invariants, safety cash reserves, and feed buffers.

---

## 3. Verification Gate Results

### Experimental Correctness Gate
1. **Isolated Build & Execution Gate:**
   - Script: `scripts/verify_experimental_package.py`
   - Test: `agent/tests/test_experimental_package_gate.py`
   - Result: Temp package built in isolated directory; verified all 57 runtime modules synced. Executed 720-step match on seed 11:
     `{"passed": true, "steps": 720, "statuses": ["DONE", "DONE"], "final_cash": [127124.0, 0.0], "protected_files_unchanged": true}`
2. **Dedicated R2 Test Suite:**
   - Test file: `agent/tests/test_sw_c2_r2_early_acquisition.py`
   - Result: 8 passed in 0.37s.
3. **SW-C2 Phase Suite:**
   - Tests: P0, P1, P2, P3, R1, R2 suites (43 items).
   - Result: 43 passed in 3.64s.
4. **Real-Engine Discovery Verification:**
   - Command: `python scripts/run_phase_sw_c2_experiment.py --arms ARM_R2 --seeds 97013 --opponents pure_wheat_rush --seats 0 --workers 1 --tag r2_test`
   - Match ID: `97013_pure_wheat_rush_0_ARM_R2`
   - Final Cash: $100,089.00
   - Cash Residual: Exact $0.0000
   - Animal Losses: 0 (0 starvation deaths, 0 escapes)
   - SW Net Crop Margin: +$8,656.56 (414 actions executed in SW)
   - Latency: p95 = 75.15 ms, max = 555.86 ms (strict < 1000ms engine limit)

### Production Release Gate
- Canonical Production Commit: `faa6cb99f66b2066e639806d0eabc72a0c7d7982` (UNTOUCHED)
- Canonical `dist/submission.zip` SHA-256: `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41` (UNTOUCHED)
- Protected Evaluation Seeds: 98001–98050 remain sequestered and unread.
- Default Feature Flags: All default to `OFF` (`False`).
