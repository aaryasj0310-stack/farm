# Phase SW-C2: P5 — Exploratory Pilot Contrast & Release Evaluation Report

**Date:** 2026-09-29  
**Branch:** `experiment/sw-c2-workforce-coordinator`  
**Status:** Technical Gate PASSED / Economic Release Gate FAILED — REJECTED FOR PROMOTION  

---

## 1. Executive Summary

Phase P5 evaluates the complete **SW-C2 Architecture** (Phases P0 through P4) under the experimental protocol defined in Section 11 of `docs/SW_C2_Implementation_Plan.md`.

Testing evaluated Candidate configuration `ARM_F` (8-tile cap with P1 Mission Ownership, P2 Coordinated Dispatch, and P3 Transactional Whole-Farm Capacity Reservations active) against:
1. **`ARM_A`**: Protected Canonical Production baseline (SW OFF, benchmark reference).
2. **`ARM_B`**: Frozen B3C historical 8-tile reference (SW historical control).

### Critical Findings & Disposition:
1. **Release Gate Status: FAILED / NOT PROMOTED.** Across the 12 matched evaluation cells, `ARM_F` averaged **$102,999.42**, which is lower than both historical SW control `ARM_B` ($104,580.25, **-$1,580.83**) and canonical production `ARM_A` ($106,862.33, **-$3,862.91**). Under the preregistered release gate criteria, `ARM_F` is **not economically successful and must NOT be promoted to production**.
2. **Technical & Invariant Gates: PASSED.** 100% of matches closed with exact **$0.0000 cash residual reconciliation**. Zero animal deaths, zero starvations, and zero escapes occurred across all 36 matches. P95 latency (210.9ms) remained well within the 1000ms engine budget.
3. **Pilot Sample Distinction:** The evaluated 36 matches (12 per arm across 2 seeds, 3 opponents, 2 seats) represent an initial **exploratory pilot contrast**, not the formal 10-seed × 5-opponent × 2-seat (100 cells/arm) independent confirmation panel required for production release.

---

## 2. Experimental Pilot Results

| Metric | ARM_A (Canonical SW OFF) | ARM_B (Frozen B3C Control) | ARM_F (SW-C2 Candidate) | Contrast (F vs B) | Contrast (F vs A) |
|---|---|---|---|---|---|
| **Matches Evaluated** | 12 | 12 | 12 | — | — |
| **Mean Final Cash** | $106,862.33 | $104,580.25 | **$102,999.42** | -$1,580.83 (-1.5%) | -$3,862.91 (-3.6%) |
| **Median Final Cash** | $106,788.50 | $106,174.00 | **$101,884.50** | -$4,289.50 | -$4,904.00 |
| **Worst-Case Tail (Min Cash)** | $85,543.00 | $79,553.00 | **$83,961.00** | **+$4,408.00 (+5.5%)** | -$1,582.00 |
| **Max Final Cash** | $119,335.00 | $117,399.00 | **$116,110.00** | -$1,289.00 | -$3,225.00 |
| **Win Rate** | 100% (1.0) | 100% (1.0) | **100% (1.0)** | 0.0 | 0.0 |
| **Cash Residual Reconciled** | 100% ($0.0000) | 100% ($0.0000) | **100% ($0.0000)** | Parity | Parity |
| **Mean Core Crop Revenue** | $79,478.33 | $74,251.64 | **$76,184.90** | **+$1,933.27 (+2.6%)** | -$3,293.43 |
| **Mean Core Livestock Revenue** | $71,104.17 | $69,366.83 | **$70,307.08** | **+$940.25 (+1.4%)** | -$797.08 |
| **Mean SW Crop Revenue** | $0.00 | $6,321.70 | **$6,017.60** | -$304.10 | +$6,017.60 |
| **Mean SW Net Margin** | $0.00 | $5,628.36 | **$5,344.26** | -$284.10 | +$5,344.26 |
| **Animal Deaths / Escapes** | 0 / 0 | 0 / 0 | **0 / 0** | Clean | Clean |
| **SW Land Purchase Rate** | 0.0% | 66.7% | **66.7%** | Parity | +66.7% |

---

## 3. Matched B → F Cash and Inventory Decomposition

An audit was conducted to resolve why `ARM_F` generates **+$2,569.42 more product sales revenue than `ARM_B` while finishing -$1,580.83 lower in final cash**.

Every dollar of the $4,150.25 difference between sales gains and final cash was decomposed to exact mathematical closure ($0.000000 residual) across all 12 matched cells:

$$\text{Final Cash} = \text{Opening Cash (\$3,000)} + \text{Product Sales} - (\text{Feed} + \text{Animals} + \text{Land} + \text{Seeds} + \text{Wages})$$

### Matched 12-Cell Mean Outflow Reconciliation:

| Ledger Category | ARM_B (Control) | ARM_F (Candidate) | Delta (F - B) | Economic Analysis |
|---|---|---|---|---|
| **Product Sales Revenue** | **$149,940.17** | **$152,509.58** | **+$2,569.42** | Higher gross revenue from core protection and SW crops |
| **Feed Purchases Spend** | $27,944.92 | $31,945.00 | **+$4,000.08** | **Additional market feed purchases due to feeding prioritization** |
| **Animal Purchases Spend** | $5,533.33 | $5,833.33 | **+$300.00** | Minor timing variation in animal acquisitions |
| **Land Purchases Spend** | $2,333.33 | $2,333.33 | **$0.00** | Identical 8-tile expansion decisions |
| **Seed Purchases Spend** | $5,003.33 | $4,877.50 | **-$125.83** | Minor seed purchasing savings |
| **Hiring Wages Spend** | $7,545.00 | $7,521.00 | **-$24.00** | Equivalent worker wages paid |
| **Total Outflows** | **$48,359.92** | **$52,510.17** | **+$4,150.25** | **Net +$4,150.25 in additional cash outflows** |
| **Reconciled Net Cash Delta** | **$104,580.25** | **$102,999.42** | **-$1,580.83** | **+$2,569.42 Sales - $4,150.25 Outflows = -$1,580.83** |
| **Mathematical Residual** | **$0.000000** | **$0.000000** | **$0.000000** | **Exact $0.000000 closure across all 12 cells** |

### Physical Wheat Inventory Flows:
- **Core Wheat Harvested:** ARM_B = 404.8 units vs ARM_F = 400.8 units (-4.0 units).
- **Market Feed Wheat Purchased:** ARM_B = 850.0 units vs ARM_F = 924.4 units (**+74.4 units purchased from market**).
- **Wheat Consumed as Feed:** ARM_B = 224.7 units vs ARM_F = 234.4 units (+9.8 units fed).
- **Harvest Wheat Sold to Market:** ARM_B = 1022.2 units vs ARM_F = 1084.1 units (+61.9 units sold).
- **Ending Unsold Wheat in Shed:** ARM_B = 1.5 units vs ARM_F = 1.4 units (-0.1 units).

---

## 4. Causal Attribution of Feed Spending Across Treatment Arms

A causal audit across treatments (`ARM_B` → `ARM_D` → `ARM_E` → `ARM_F`) on seed 97013 pass 0 revealed the exact origin of feed spending differences:

| Metric | ARM_B (Control) | ARM_D (P1 Ownership) | ARM_E (P2 Dispatch) | ARM_F (P3 Reservations) |
|---|---|---|---|---|
| **Feed Purchase Spend** | $33,573.00 | $32,557.00 (-$1,016) | **$38,613.00 (+$6,056)** | **$38,613.00 ($0.00 vs E)** |
| **Feed Actions Executed**| 229 | 198 | **238 (+40 vs D)** | **238 ($0.00 vs E)** |
| **Core Wheat Harvested** | 400 | 385 | **369 (-16 vs D)** | **369 ($0.00 vs E)** |
| **Market Wheat Purchased**| 872 units | 959 units | **1,008 units (+49 vs D)**| **1,008 units ($0.00 vs E)**|
| **Final Cash** | $102,960.00 | $102,308.00 | **$100,079.00** | **$100,079.00 ($0.00 vs E)** |

### Causal Attribution Conclusions:
1. **P3 Transactional Reservations Did NOT Increase Feed Spend:** ARM_F and ARM_E have **bit-for-bit identical** feed spend ($38,613.00), identical wheat purchased (1,008 units), identical feed actions (238), and identical final cash ($100,079.00). P3 introduced zero additional feed expenditures.
2. **The Shift Originated in Phase P2 (Coordinated Dispatch):** In Phase P2, Stage 1 (Deadline Feasibility Protection) prioritized survival feeding ahead of discretionary work. Total animal feedings increased from 198 (ARM_D) to 238 (ARM_E). 
3. **Upstream Market Controller Feedback:** Feeding animals 238 times drew down shed wheat reserves faster. The upstream `feed_feasibility` module and `OrderBuilder` observed lower shed inventory and scheduled 49 additional units of spot wheat purchases, escalating feed spend to $38,613.00.

---

## 5. Preregistered Design for Future Discovery and Confirmation

To ensure experimental rigor and avoid post-hoc data fitting:
1. **Candidate Configuration (Frozen):**
   `ARM_F` (8-tile cap, `SW_P1_MISSION_OWNERSHIP_ENABLED = True`, `SW_P2_COORDINATED_DISPATCH_ENABLED = True`, `SW_P3_TRANSACTIONAL_RESERVATIONS_ENABLED = True`).
2. **Controls:**
   `ARM_A` (Canonical production, SW OFF), `ARM_B` (Frozen B3C historical 8-tile control).
3. **Preregistered Discovery Panel:**
   - 10 Unused Seeds: `97001, 97002, 97003, 97004, 97005, 97006, 97007, 97008, 97009, 97010`.
   - 5 Canonical Opponents: `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`.
   - 2 Seats: Player 0 and Player 1.
   - Total: 100 matched cells per arm (300 matches total).
4. **Preregistered Confirmation Panel (Untouched):**
   - 10 Separate Untouched Seeds: `97021, 97022, 97023, 97024, 97025, 97026, 97027, 97028, 97029, 97030`.
   - Tested strictly once without iterative retuning.
5. **Protected Validation Distribution:**
   - Seeds `98001–98050` remain strictly unread, untouched, and sequestered until final release validation is explicitly authorized.

---

## 6. Phase P5 Exit Gate Disposition

```text
================================================================================
PHASE P5 GATE DISPOSITION
================================================================================
Technical Verification Gate:              PASSED (Exact $0.0000 closure, 0 losses)
Pilot Screening Classification:          EXPLORATORY PILOT CONTRAST (12 cells/arm)
Economic / Production Release Gate:       FAILED (Mean cash inferior to ARM_B and ARM_A)
Production Promotion Decision:            REJECTED — ARM_F NOT PROMOTED
Architecture State:                       PRESERVED AS EXPERIMENTAL FOUNDATION
================================================================================
```

All behavior-changing feature flags remain strictly `OFF` (`False`) by default in `agent/config.py`. The canonical production submission `dist/submission.zip` SHA-256 (`E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41`) remains authoritative.
