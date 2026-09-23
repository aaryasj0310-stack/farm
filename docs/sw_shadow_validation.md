# SW Shadow Validation & Historical Failure Replay Report

**Status:** Phase A Verified  
**Date:** 2026-09-23  
**Base Commit SHA:** `975da5e1683f1bb57463cb9478344d0acf379d58`  
**Evidence Freeze Commit:** `f830d41e33c2a0ef881fae3492a90a8a277bcc39`  

---

## 1. Baseline Verification & Research Evidence State

All 7 core research audit documents, the 132-episode saved leader census (`simulations/experiments/results/sw_leader_audit/`), economic models (`artifacts/sw_economics/`), and diagnostic scripts were verified locally, hashed, and frozen in Commit `f830d41e33c2a0ef881fae3492a90a8a277bcc39`.

Key findings confirmed from the evidence:
1. **P4.1 Loss Attribution**: P4.1 lost -$4,819.10/game not because SW is intrinsically unprofitable, but because two productive core workers were exclusively transferred to SW without replacing core capacity or retiring workload.
2. **Workforce Ceiling**: Top-performing leader replays (such as Crop Dusta) consistently operate with **13 total workers** (farmer + 12 hands), identical to our mature baseline.
3. **SW Purchase Timing**: Strong players acquire SW around **Day 8–9**, not Day 6 or Day 14.
4. **Development Velocity**: Once purchased, successful SW development ramps rapidly within 2–4 days across mixed crops (wheat, strawberries, melons).

---

## 2. Historical Scenario Replays: Failure Mechanism Detection

The new architectural substrate was benchmarked against synthetic reconstructions of the four major historical failure modes in `agent/tests/test_sw_historical_failure_scenarios.py`:

| Historical Failure Scenario | Simulated Failure Mode | Certificate Verdict | Diagnostic & Structured Repair Result |
|---|---|:---:|---|
| **P4.1 Core Worker Displacement** | 2 workers partitioned to SW; core has 15 urgent actions on 11 units | **FAILED** (`feasible = False`) | Binding bottleneck identified at Day 14 Hour 18. Structured repairs generated: `DOWNSIZE_TRANCHE` or `DROP_COHORT` to recover core actions. |
| **P1 Purchase-Only Overcommitment** | SW bought on Day 6 with cash above threshold, but forward wage/feed liabilities unfunded | **BLOCKED** (`can_buy = False`) | `ResourceLedger` checks all future liability checkpoints; detects negative cash on Days 7–9 and blocks land purchase. |
| **P1.1 Feed Causality Deficit** | Animals added against in-ground wheat maturing on Day 10 | **FAILED** (`is_feed_safe = False`) | Feed ledger identifies negative balance on Days 8 and 9; enforces strict physical harvest timing. |
| **P6.1 Harvest Wave Storage Congestion** | Concurrent harvest waves exceed shed capacity | **FLAGGED** (`wave > headroom`) | Storage ledger tracks carried units and shed occupancy, flagging headroom exhaustion (headroom = 5 vs wave = 12). |

---

## 3. Computational Budget & Latency Telemetry

In `SHADOW` mode, execution overhead was benchmarked across multi-day evaluation turns:
- **Event-Driven Replanning**: Deep multi-day trajectory search and portfolio evaluation execute exclusively on strategic event turns (day boundaries, land purchase, cohort status changes, shop unlocks).
- **Incremental Turns**: Fast-path tracking on routine turns.
- **Latency Profile**:
  - $p50 < 0.25\text{ ms}$
  - $p95 < 0.85\text{ ms}$
  - $\text{Max} < 2.50\text{ ms}$
- **Package Footprint**: Negligible memory growth ($< 50\text{ KB}$ for plan and ledger state).
- **Time Limits**: Well within Kaggle competition limits (1.0s per turn).

---

## 4. Phase A-R Correctness Hardening Validation

In Phase A-R, four core substrate gaps were hardened and re-verified:
1. **Authoritative Crop Age & Wheat Feed Causality**:
   - Replaced fragile tile age attributes with `crop_age(t, day)` and `t.planted_day`.
   - Explicitly modeled same-day physical chain `Worker -> Wheat -> HARVEST -> Animal -> FEED <= 23`.
   - Verified that unharvested grain maturing in future turns cannot feed animals on earlier turns.
2. **Physically Causal Storage Timeline**:
   - Separated worker backpacks (`WorkerStorageState`) from shed inventory.
   - Enforced rule that `SELL` orders cannot sell goods carried in backpacks.
   - Accurately modeled midnight auto-drop and discard mechanics when inventory exceeds 100 units.
3. **Engine-Exact Sequential Pricing**:
   - Swapped generic pricing with `market/price_math.py` (`market_price` and `total_revenue_estimate`).
   - Eliminated double-deduction of cannibalization in $\Delta FC = \text{WITH} - \text{WITHOUT}$.
4. **Sanity Panel Execution**:
   - Run on discovery seeds 96401, 42, 100 for 72 steps each in both `OFF` and `SHADOW` modes.
   - Results: **0 divergences** between OFF and SHADOW actions; **72 shadow evaluations** logged per game; 0 exceptions.
   - Held-out evaluation seeds 98001–98050 remained strictly untouched.
