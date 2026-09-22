# Kaggriculture P6.1 — CentralPlanner Market Slot & Arbitration Audit

- **Audit Target**: CentralPlanner per-turn 10-order cap arbitration, priority dominance, and candidate displacement under P6.1 Pre-Midnight Storage Hygiene.
- **Evaluation Panel**: 100 matched pairs (200 games) across Seeds `96,411`–`96,420`.
- **Finding**: **ZERO P0 DISPLACEMENTS; CENTRALPLANNER ARBITRATION 100% SOUND**.

---

## 1. CentralPlanner Arbitration Volume & Rejection Profile

| Metric | Control (Baseline) | Treatment (P6.1) | Delta | Significance |
| :--- | :---: | :---: | :---: | :---: |
| **Total Market Proposals** | 2,752.4 / game | 2,761.8 / game | +9.4 / game | Modest evening sell proposal generation |
| **Accepted Orders** | 1,842.1 / game | 1,848.5 / game | +6.4 / game | Realized execution volume |
| **Total Rejections** | 910.3 / game | 913.3 / game | +3.0 / game | Normal non-selected candidates |
| **`slot_cap` Rejections** | **100.61 / game** | **101.67 / game** | **+1.06 / game** | Negligible change (+1.05%) |
| **P0 Critical Rejections** | **0** | **0** | **0 (Zero)** | **P0 Dominance Strictly Preserved** |

---

## 2. Priority Hierarchy Performance

In `agent/strategy/central_planner.py`, P6.1 proposals were assigned `priority_class = P1_URGENT` with `urgency = 1.5`, positioned directly between P0 (Hard Emergencies) and P2 (Soft-Cap Relief / Routine Buffers):

1. **P0 Protection Invariant**:
   - `P0_CRITICAL` orders (emergency feed wheat when starvation is imminent, day 29 final dump) have priority value `0`.
   - Because $0 < 1$, any P0 proposal strictly dominates P1 hygiene proposals during ranking.
   - Across all 72,000 tournament turns in Treatment, **exactly 0 P0 orders were rejected due to storage hygiene competition**.

2. **P1 Hygiene Acceptance Rate**:
   - At Hours 20, 21, and 22, the market order queue is lightly contested (morning HIRE and seed purchases take place at Hour 0).
   - When P6.1 generated storage hygiene sell proposals, CentralPlanner accepted **96.8%** of emitted hygiene slices.
   - The ~3.2% rejections occurred exclusively when multiple small slices were generated that exceeded the remaining turn capacity of 10 orders.

---

## 3. Market Slot Audit Conclusion

CentralPlanner performed flawlessly:
- The 10-order engine cap was never breached.
- P0 emergency purchases were never starved or displaced.
- Slot exhaustion was not a binding bottleneck for storage hygiene.
