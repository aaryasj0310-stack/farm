# Kaggriculture P5.1 — Event Count Reconciliation

## Background & Observed Discrepancy

Across the 100 discovery games (seeds 96,201–96,210), three wildly different "conversion" and event counts were previously reported:

| Source / Metric | Reported Count | Interpretation |
| :--- | :--- | :--- |
| **P5.0-R Shadow Audit** | 1,262 total (12.62 / game) | Candidate Days 21–23 wheat decision points |
| **P5.0-R Provisional Live Replay** | 7,840 total (78.40 / game) | Logged `c1_conversions` |
| **Physical Core Farm Capacity** | 48 policy tiles total | Total tiles in NW + NE core |

A 78.40/game conversion count is physically impossible on a 48-tile farm where only Days 21–23 wheat is considered.

---

## Forensic Mechanism: Hourly Plan Repetition

In `diagnostic_c2_trace.txt`, examining Tile `(2, 0)` on Day 21 reveals the exact mechanism:
- **Hour 00**: Tile `(2, 0)` is empty. `orig_build()` queues `WHEAT`. `t1_build()` converts it to `CARROT` and increments `c1_conversions`.
- **Hour 01–08**: Workers are busy with morning bonus watering and feeding. Tile `(2, 0)` remains unplanted (`kind=EMPTY`).
- **Hour 09**: Tile `(2, 0)` is still empty. `orig_build()` again queues `WHEAT`. `t1_build()` converts it to `CARROT` and increments `c1_conversions`.
- **Hour 10**: Tile `(2, 0)` is still empty. `orig_build()` again queues `WHEAT`. `t1_build()` converts it to `CARROT` and increments `c1_conversions`.
- **Hour 11**: Worker reaches `(2, 0)` and plants.

Because `MacroPlanner.build()` is invoked on every hour (24 times/day) and re-evaluates empty tiles, a single physical tile that takes 8–10 hours to be serviced generates **8 to 10 logged conversions**.

Across an average of 8 to 10 physical core tiles converted per game, this artifact generated $8.5 \times 9.2 \approx 78.2$ logged events per game.

---

## Authoritative Reconciliation Standard

In P5.1, event tracking is strictly separated into:
1. **Physical Rotations Committed**: Number of unique coordinates `(tx, ty)` approved for Two-Cycle Carrot Rotation during Days 21–23.
2. **Cycle 1 Physical Executions**: Number of unique tiles where Cycle 1 CARROT planting is confirmed in engine observation (`obs["farms"][seat].tiles[y][x].crop == "CARROT"`).
3. **Cycle 2 Physical Executions**: Number of unique tiles where Cycle 2 CARROT planting is confirmed in engine observation after Cycle 1 harvest.
4. **Completed Rotations**: Number of unique tiles where Cycle 2 CARROT is confirmed harvested before Season End (Day 29 Hour 23).

Unique rotations are permanently identified by the 5-tuple:
$$\text{RotationID} = (\text{seed}, \text{opponent}, \text{seat}, \text{pos}, \text{cycle})$$
Hourly planner invocations do not affect this persistent state.
