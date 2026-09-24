# Kaggriculture — Gate 1 Forensic Calibration Report

## 1. Executive Summary

Following the completion of the Formal Gate 1 100-Game SHADOW Divergence Audit, a critical diagnostic paradox was identified:
- **Baseline Behavior:** Purchased Southwest (SW) land in 100/100 games on Day 5 or Day 6 with 0 unfed animals, 0 dead crops, and 15.5%–36.2% idle worker actions.
- **SHADOW Evaluator Behavior:** Recommended SW in 0/100 games, reporting a Core Service Certificate pass rate of only **3.77%** and citing `WORKER_HOURS` as the binding bottleneck on essentially all turns, despite positive whole-farm candidate economics.

This calibration pass conducted a forensic root-cause analysis comparing engine reality against certificate predictions, calibrated the `ServiceCertificate` and `WholeFarmPlanner` to eliminate artificial false-positive vetoes while preserving genuine overcommitment safety, and verified the results across:
1. The full unit test suite (1,141/1,141 tests passing, 100%).
2. Offline replay of 10 representative Gate 1 configurations (10/10 invariance, core pass rate increasing from 3.77% to 63.44%).
3. A fresh 100-configuration diagnostic panel on unused seeds `96511–96520` (200 matches, 100/100 invariance, 63.19% core pass rate, 26.67ms p50 latency).

---

## 2. Forensic Investigation & Root Causes

Using the empirical script `scripts/forensic_cert_vs_reality.py`, we traced agent execution at Days 0, 2, 3, and 5 of Seed 96501. The audit revealed that the low certificate pass rate (3.77%) was caused by four compounding artifacts in the capacity model rather than physical labor exhaustion:

### Root Cause 1: Deadline Clumping & Single-Hour Slicing
In the initial implementation, `WholeFarmPlanner` assigned an artificial deadline of `hour_deadline = 20` to all animal feeding tasks, ledger in-ground wheat harvests, and plant queue obligations.
Because the service certificate checks hourly slack as:
$$\text{slack}(d, h) = \text{budget}(d, h) - \text{demand}(d, h)$$
placing 6 animal feeds, 4 wheat harvests, and 6 plant tasks into Hour 20 generated an instantaneous demand of 16–22 actions in a single hour where a 3-worker farm only has a budget of 3 worker-actions. The certificate demanded that all daily tasks execute inside Hour 20, triggering immediate `WORKER_HOURS` failure even though workers could service them across Hours 4–20.

### Root Cause 2: Compounded Travel Inflation on Low-Density Tasks
A flat 1.35x travel factor was applied across all tasks regardless of task density. Even isolated tasks (e.g. 1 plant task taking 1 tick) were inflated, compounding with the deadline clumping to artificially inflate demand by 35% across all hours.

### Root Cause 3: Past-Hour Evaluation Trap
On evaluations occurring midday (e.g. Day 5 Hour 12), static morning deadlines (e.g. Hour 4 or 6) generated tasks with deadlines in the past relative to `current_hour`. The certificate evaluator correctly flags any task with deadline in the past as failed, creating an immediate artificial failure on midday replans.

### Root Cause 4: Candidate Portfolio Fallback Inversion
When no candidate portfolio was admitted, the planner evaluated fallback portfolios for telemetry. An inversion in candidate selection selected economically negative compact portfolios over profitable oversized portfolios, skewing the telemetry towards `core_cert` fallback instead of reporting the binding labor bottleneck of the profitable proposal.

---

## 3. Calibration Implementation

### A. Temporal Staggering & Dynamic Task Windows
In `agent/strategy/whole_farm_planner.py` (and mirrored in `submission/`):
- **Animal Feeding:** Staggered into the morning window:
  $$\text{feed\_h} = 4 + (\text{idx} \pmod 6)$$
  with a dynamic lower bound ensuring $\text{hour\_deadline} \ge \text{snapshot.hour} + 1$ on the current day.
- **Wheat Harvesting:** Ledger harvests staggered across morning hours:
  $$\text{harvest\_h} = 6 + (\text{idx} \pmod 8)$$
- **Crop Watering & Harvests:** Distributed across afternoon hours (Hours 14–19) and evening (Hours 18–22).
- **Plant Queue:** Staggered across midday hours:
  $$\text{plant\_h} = 12 + (\text{idx} \pmod 6)$$

### B. Calibrated Spatial Travel Factor
In `agent/strategy/service_certificate.py` (and mirrored in `submission/`):
- Adjusted travel overhead to calibrated multipliers:
  - Day 0–1 (Hour < 24): $1.15\times$ for clustered tasks ($>2$ tasks/hour), $1.0\times$ for isolated tasks.
  - Day 1–2 (Hour 24–48): $1.15\times$.
  - Future Days (Hour 48+): $1.10\times$.

### C. Guarantee Safety Tiers
Added formal classification to `CertificateResult.guarantee_tier`:
- `CERTIFIED_SAFE`: $\text{minimum\_slack} \ge 3$ worker-actions.
- `TIGHT_BUT_SERVICEABLE`: $0 \le \text{minimum\_slack} < 3$ worker-actions.
- `INFEASIBLE`: $\text{minimum\_slack} < 0$ or any hard task failed.
- `UNCERTAIN`: Horizon bounds exceeded or missing context.

### D. Representative Candidate Telemetry Selection
When no portfolio is admitted, the planner selects the best candidate with $\Delta \text{FC} > 0$ to serve as the telemetry exemplar, ensuring that telemetry accurately reflects why profitable SW expansions were delayed or downsized by the labor certificate.

---

## 4. Verification & Validation Evidence

### A. Full Pytest Suite (Unit & System Tests)
All unit and architectural tests pass 100%:
- `pytest agent/tests/test_sw_forward_architecture.py`: **58/58 passed (100%)**
- `pytest agent/tests/test_submission_package.py`: **4/4 passed (100%)**
- `pytest agent/tests/`: **1,141/1,141 passed (100%)**

### B. Offline Replay on Gate 1 Representative Configurations (10 Pairs)
Replaying the 10 Gate 1 configurations through the calibrated planner:

| Metric | Gate 1 Baseline (Uncalibrated) | Calibrated Planner Replay | Change |
| :--- | :---: | :---: | :---: |
| **Action & Cash Invariance** | 100.0% | **100.0% (10/10)** | Preserved |
| **Mean Core Cert Pass Rate** | 3.77% | **63.44%** | **+59.67% (16.8x)** |
| **Mean Combined Pass Rate** | ~0.0% | **31.35%** | **+31.35%** |
| **P50 Decision Latency** | 24.3ms | **20.1ms** | Sub-30ms |

### C. Fresh 100-Configuration Diagnostic Panel (Seeds 96511–96520)
Executed 100 game configurations (200 matches) under `scripts/run_fresh_diagnostic_panel.py`:

| Parameter / Metric | Diagnostic Panel Value |
| :--- | :--- |
| **Seeds Evaluated** | `96511, 96512, 96513, 96514, 96515, 96516, 96517, 96518, 96519, 96520` (10 fresh seeds) |
| **Opponents** | `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent` (All 5) |
| **Seats** | Seat 0 and Seat 1 (Both seats) |
| **Total Matches** | 100 pairs = 200 matches |
| **Action & Cash Invariance** | **100/100 (100.0%)** |
| **Runtime Errors / Exceptions** | **0** |
| **Mean Core Cert Pass Rate** | **63.19%** (vs 3.77% in Gate 1) |
| **Mean Combined Pass Rate** | **29.64%** |
| **Mean Lifecycle Pass Rate** | **6.53%** |
| **Safety Tier Distribution (All Turns)** | `CERTIFIED_SAFE`: 6,334 \| `TIGHT_BUT_SERVICEABLE`: 14,979 \| `INFEASIBLE`: 50,587 |
| **Latency P50 Mean** | **26.67 ms** |
| **Total Wall Clock Time** | 1,420.67s (~23.6 minutes across 7 workers) |

---

## 5. Architectural Insight: Why Baseline Rushes SW and Shadow Delays

A key finding from this calibration pass explains why SW purchase recommendations remained 0 in SHADOW mode even after calibration:
1. **The Production Baseline Policy:** The existing production agent triggers SW land purchase immediately once cash reaches \$2,000 (typically on Day 5 or Day 6) with 2–3 workers and minimal liquidity buffer, without verifying whether upcoming crop watering or harvest obligations will cause labor congestion.
2. **The SW-Forward Architecture Policy:** The calibrated SW-forward planner requires:
   - Target SW day $\ge 8$ (or `SW_READY` state).
   - Cash buffer $\ge \$2,200$ (\$2,000 land cost + \$200 liquidity buffer).
   - Workforce capacity certified safe or tight-but-serviceable for the combined farm.
3. **The SHADOW Interaction Effect:** Because the production baseline retains 100% control of actions in SHADOW mode, the baseline buys SW on Day 5 at \$2,000. The moment the baseline buys SW, Southwest is unlocked in the engine. Once unlocked, pre-purchase SW recommendation logic is bypassed (`is_sw_unlocked = True`), and the planner transitions to post-unlock quadrant management.
4. **Conclusion:** The divergence on Day 5 is a **genuine policy disagreement**, not a capacity certificate bug. The baseline agent rushes SW aggressively before it is certified safe; the SW-forward architecture intentionally delays until workforce and liquidity buffers are verified.

---

## 6. Integrity & Quarantine Confirmation

- **Protected Seeds [98001–98050]:** Zero calls or references. Strict quarantine maintained.
- **Default Mode:** `SW_FORWARD_ARCHITECTURE_MODE = "OFF"` verified as default in `agent/config.py`.
- **Packaging Parity:** Byte-for-byte synchronization verified between `agent/` and `submission/`.
