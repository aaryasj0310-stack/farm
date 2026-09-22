# Kaggriculture P4.1 Implementation Plan — Late-Season Isolated SW Zonal Acreage Expansion

## 1. Executive Summary & Problem Formulation

In Phase P4.0, the authoritative economic audit established that:
1. The Promoted P2.3 Production Baseline (`536f1e7`) achieves a mean final score of **$101,836.36** across 100 games, leaving a remaining gap of **-$28,163.64** against the $130,000 project target.
2. The 2-quadrant core (NW+NE, 46 usable tiles) is **90–96% saturated** from Day 14 to Day 26 (only 1.8 to 4.7 empty tiles).
3. The farm amasses **$17,721 in cash by Day 13** and **$50,849 by Day 22**, with 13 active workers (1 farmer + 12 hands).
4. Micro-execution within the 46 tiles is exhausted (P3.1, P3.2, P3.3-A, P3.3-B, P3.4 rejected).
5. **The Sole Structural Frontier is Physical Acreage Expansion**: Reaching $130k physically requires more cultivating tiles.

This document presents the complete research, architectural, safety, and evaluation plan for **P4.1: Late-Season Isolated SW Zonal Acreage Expansion**.

---

## 2. Theoretical Hypothesis & Causal Pathway

### Hypothesis
If the farm unlocks the Southwest (SW) quadrant strictly on **Day 14 Hour 0** (contingent on liquid cash $\ge \$15,000$ and core saturation $\ge 90\%$), and restricts cultivation to an isolated **8-tile shed-adjacent zone** tended exclusively by a **dedicated 2-worker cohort (Hands 11 & 12)** while strictly walling off core workers from entering SW, then:
1. The $2,000 land cost and seed capex will be easily absorbed without impacting early bootstrapping or herd purchases.
2. The 8 dedicated SW tiles will produce additional high-value strawberry/wheat crops yielding **+$8,000 to +$14,000 in net realized cash**.
3. The 2-quadrant core farm ($101.8k baseline value) will suffer zero spatial contagion or watering drops because core workers are hard-blocked from crossing into SW.
4. Net season score will increase significantly above $101.8k toward the $115k–$120k frontier.

### Causal Pathway
$$\begin{aligned}
\text{Day 14 Gate (\$17k Cash, 2Q 94\% Full)} & \longrightarrow \text{Emit BUY\_LAND SW (\$2,000 cost)} \\
& \longrightarrow \text{Assign Hands 11 \& 12 Exclusively to SW Shed-Adjacent Zone (8 tiles)} \\
& \longrightarrow \text{Till \& Plant 8 Strawberry/Wheat Tiles (Zero Core Labor Displaced)} \\
& \longrightarrow \text{Harvest +96 Strawberries / +144 Wheat Directly into Center Shed} \\
& \longrightarrow \text{Sell into Dynamic Market @ Realized Prices (\$245 / \$36)} \\
& \longrightarrow \mathbf{+\$8,000\text{ to }+\$14,000\text{ Incremental Net Cash (Final Score)}}
\end{aligned}$$

---

## 3. Difference from Previously Failed Experiments (P1 / P1.3-C)

| Architectural Dimension | Failed P1 / P1.3-C Policy | Promoted P2.3 Baseline (`536f1e7`) | Proposed P4.1 Treatment |
| :--- | :--- | :--- | :--- |
| **SW Unlock Day** | Day 6–9 (Premature) | Never (`QUADRANT_HARD_BLOCK = {4}`) | **Day 14 Hour 0 Hard Gate** |
| **Cash Trigger** | Unconstrained / $400 cash | N/A | **Cash $\ge \$15,000$ Required** |
| **Core Saturation Trigger** | None (Unlocked before NE full) | N/A | **Core Tiles $\ge 90\%$ Full Required** |
| **Cultivated Acreage** | All 25 tiles of SW (Sprawl) | 0 tiles | **Exactly 8 Tiles Max** `(x: 3-4, y: 5-8)` |
| **Livestock in SW** | Moved cows/pastures to SW | All in NW+NE | **Zero Livestock in SW** (Crops Only) |
| **Worker Dispatch** | Farm-wide unconstrained routing | NW+NE routing | **Strict Zonal Cohort**: Hands 11 & 12 dedicated to SW; Hands 1–10 hard-blocked from SW |
| **Early Capex Impact** | Starved herd purchases (-$30k) | Herd 100% funded | **Zero Impact** (Herd fully bought by Day 12) |
| **Past Outcome** | **-$13,420/game (Disastrous)** | **$101,836.36 (Baseline)** | **Target: +$8,000 to +$14,000/game** |

---

## 4. Proposed Code Changes & Implementation Isolation

### 1. `agent/config.py`
- Add feature flag:
  ```python
  P41_SW_ZONAL_EXPANSION_ENABLED: bool = False

  def set_p41_sw_zonal_expansion_enabled(enabled: bool) -> None:
      global P41_SW_ZONAL_EXPANSION_ENABLED
      P41_SW_ZONAL_EXPANSION_ENABLED = bool(enabled)

  def get_p41_sw_zonal_expansion_enabled() -> bool:
      return P41_SW_ZONAL_EXPANSION_ENABLED
  ```
- Add activation parameters:
  ```python
  P41_SW_MIN_DAY = 14
  P41_SW_MIN_CASH = 15000.0
  P41_SW_MIN_CORE_OCCUPANCY = 0.90
  P41_SW_MAX_TILES = 8
  P41_SW_ZONE_COORDS = [(3, 5), (3, 6), (3, 7), (3, 8), (4, 6), (4, 7), (4, 8), (4, 9)]
  P41_SW_DEDICATED_WORKER_INDICES = [11, 12]  # Hands 11 and 12
  ```

### 2. `agent/strategy/macro_planner.py`
- Modify `plan_land_expansion()`:
  - If `P41_SW_ZONAL_EXPANSION_ENABLED` is `True`:
    - On Day $\ge 14$, if SW is locked and `farm.money >= P41_SW_MIN_CASH` and `core_occupancy >= P41_SW_MIN_CORE_OCCUPANCY`:
      - Remove SW from hard block and emit `BUY_LAND` order.
  - If `False`: Retain baseline `QUADRANT_HARD_BLOCK = {4}`.

### 3. `agent/strategy/central_planner.py` & `agent/execution/task_scheduler.py`
- Add strict **Zonal Cohort Dispatch**:
  - For workers with index $\in \{11, 12\}$:
    - If SW is unlocked, prioritize tasks in `P41_SW_ZONE_COORDS` (clearing weeds, tilling, planting, watering).
  - For workers with index $\in \{0, 1, 2, ..., 10\}$ (Farmer + Hands 1–10):
    - **Hard Zonal Boundary**: Task eligibility explicitly returns `False` for any tile with $y \ge 5, x < 5$ (SW quadrant). Core workers NEVER cross into SW.

### 4. Zero Regression Guarantee
- When `P41_SW_ZONAL_EXPANSION_ENABLED = False`, all new codepaths are bypassed. The agent behaves 100% identically to commit `536f1e7`.

---

## 5. Safety Invariants & Mechanism Telemetry

### Mandatory Safety Invariants (Evaluated Every Turn):
1. **Solvency Invariant**: `farm["money"] >= 0` on every step (zero negative cash steps allowed).
2. **Core Herd Invariant**: Zero animal starvation days. Feed logistics remain 100% intact.
3. **Core Farm Invariant**: 2Q core crop watering compliance must remain $\ge 98.0\%$.
4. **Boundary Invariant**: Zero worker steps by Farmer or Hands 1–10 into SW tiles.
5. **Acreage Ceiling Invariant**: Total cultivated SW tiles must never exceed 8.

### Mechanism Telemetry Captured:
- Day & hour of SW unlock.
- Actual cash balance at moment of SW unlock.
- Number of SW tiles tilled, planted, watered, and harvested.
- Gross revenue from SW crops sold.
- Worker turns spent in SW vs Core.

---

## 6. Verification & A/B Evaluation Protocol

### 1. Offline Unit Tests
- `test_p41_isolation.py`:
  - Verify that when `P41_SW_ZONAL_EXPANSION_ENABLED = False`, agent output is byte-identical to `536f1e7`.
  - Verify that when enabled, SW cannot unlock prior to Day 14 or if cash $< \$15,000$.
- `test_p41_zonal_confinement.py`:
  - Verify that Hands 1–10 are never assigned tasks in SW.
  - Verify that Hands 11–12 do not accept tasks in NE.

### 2. Smoke Test Gate
- 5 matched pairs (10 games) on smoke seeds `92,991–92,995` against `pass` and `full_production_agent`.
- Assert 0 errors, 0 negative cash, exact cash reconciliation.

### 3. Formal A/B Tournament Protocol
- **Evaluation Seed Block**: **94,001–94,050** (Strictly fresh, held-out, 50 pairs $\times$ 2 seats = 100 matched cases = 200 live games).
- **Opponent Distribution**: 20 games each against the 5 standard opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`).
- **Balanced Seats**: Exactly 50 games in Seat 0 and 50 games in Seat 1 per arm.
- **Arm Isolation**: Subprocess pool with independent clean Python processes.

---

## 7. Promotion & Rejection Criteria

### Promotion Criteria (All Must Pass):
1. **Statistically Significant Score Delta**: Paired mean delta $\Delta \ge +\$3,500.00$ with $p < 0.05$.
2. **Confidence Interval**: 95% confidence interval lower bound $> +\$500.00$.
3. **Zero Solvency Failures**: 0 games with negative cash steps.
4. **Zero Herd Regressions**: 0 starvation animal-days.
5. **Core Farm Preservation**: 2Q Core gross crop revenue must remain within $\pm \$500$ of Control.

### Rejection Criteria (Any Triggers Immediate Rejection):
1. Paired mean delta $\Delta \le 0$, or $p \ge 0.05$ with CI crossing zero.
2. Any negative cash step.
3. 2Q Core crop watering compliance falls below 95%.
4. SW cultivation causes net score destruction.

---

## 8. Final Status & Hold

Per instructions:
- **P4.0 investigation and measurement phase is now complete.**
- **All 8 required P4.0 audit reports have been compiled and verified.**
- **P4.1 implementation plan is complete and held.**
- **DO NOT implement production code changes until the plan is reviewed and approved by the user.**
