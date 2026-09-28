# Phase SW-C2: P0 Diagnostic Integrity Report

**Date:** 2026-09-28  
**Branch:** `experiment/sw-c2-workforce-coordinator`  
**Starting Commit:** `ec16d96fa19efc5f7f7f33bb416ff9778bccb0d7`  
**Protected Production Baseline:** `faa6cb99f66b2066e639806d0eabc72a0c7d7982`  
**Protected Submission SHA-256:** `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41`  

---

## 1. Executive Summary

Phase P0-B repaired the diagnostic problems identified in the SW-C2 implementation specification without modifying gameplay decisions or altering action streams.

### Key Repairs Implemented & Verified:

1. **Separation of CARE and COLLECT_FERTILIZER**:
   - Previously in SW-C1: `self.action_counts['care_actions']` was incremented on `COLLECT_FERTILIZER`, and `CARE` was uncounted.
   - Now in SW-C2: `care_actions` and `collect_fertilizer_actions` are strictly separated counters. On match `97013_pass_0`:
     - Arm A: 215 CARE actions, 221 COLLECT_FERTILIZER actions.
     - Arm B: 216 CARE actions, 240 COLLECT_FERTILIZER actions.
     - Arm C: 216 CARE actions, 240 COLLECT_FERTILIZER actions.

2. **HARD Obligation Completion Path Repaired**:
   - Previously in SW-C1: `core_hard_completion_rate` was reported as `0.0` across 100% of matches because `record_hard_obligation_executed` was never invoked from the execution interceptor.
   - Now in SW-C2: `record_executed_action` accepts `step` and propagates engine-confirmed state outcomes directly to `record_hard_obligation_executed()`.
   - On match `97013_pass_0`:
     - Arm A: 371 completed out of 399 due (93.0% completion).
     - Arm B: 508 completed out of 549 due (92.5% completion).
     - Arm C: 508 completed out of 549 due (92.5% completion).

3. **PLANT Outcome & Seed Lot Attribution**:
   - Previously in SW-C1: `audited_unit_action` did not populate `outcome` for `PLANT`, resulting in `seed_ledger` recording zero core/SW plants.
   - Now in SW-C2: Tile transition from `None -> {"kind": "PLANT", "crop": c}` generates `outcome = {"planted": True, "crop": c}`, accurately updating `planted_core`, `planted_sw`, and tracking coordinates and timing.

4. **100% Exact Cash & Mass Balance Reconciliation**:
   - Zero cash residual ($\Delta = \$0.0000$) verified turn-by-turn against the engine wallet.
   - Reconciled cash: $\text{Starting} + \text{Inflows} - \text{Outflows} = \text{Final Cash}$.

5. **Bit-for-Bit Reference Parity**:
   - Match `97013_pass_0`:
     - Arm A final cash: **$107,571.00** (bit-exact match to historical SW-C1: $107,571.00).
     - Arm B final cash: **$102,960.00** (bit-exact match to historical SW-C1: $102,960.00).
     - Arm C final cash: **$102,960.00** (bit-exact match to historical SW-C1: $102,960.00).
     - Arm C vs Arm B delta: **$0.0000** (100% exact parity).

---

## 2. Gate P0-B Verdict

- Reference action parity: **VERIFIED**.
- Reference final-cash parity: **VERIFIED**.
- Deterministic telemetry: **VERIFIED**.
- Exact cash closure ($0.0000 residual): **VERIFIED**.
- **P0-B Gate Status:** **PASSED**. Authorized to proceed.
