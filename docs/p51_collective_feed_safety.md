# Kaggriculture P5.1 — Collective Feed Safety Architecture

## Rejection of Simplified Formulas

In early design discussions, a static formula of the form:
$$\text{ProjectedWheat} - 4 \times (\text{ApprovedRotations} + 1) \ge \text{TotalFeedNeeded}$$
was considered. This formula was rejected due to three critical flaws:
1. **Double Counting**: An already approved rotation has already been diverted away from wheat. Re-subtracting it from a static in-ground inventory double-counts the deduction.
2. **Timing Insensitivity**: Wheat harvested on Day 27 cannot prevent animal starvation on Day 22. A total season sum obscures intraday and multi-day feed deficits.
3. **Unplanted Baseline Commitments**: Other wheat tiles planned by the baseline have not yet been planted and do not appear in the in-ground tile array.

---

## The Engine-Exact Sequential Day-by-Day Supply Ledger

The `TwoCycleRotationManager` implements a state-based, sequential supply ledger:

### 1. State Reconstruction at Decision Time (Day $D \in \{21, 22, 23\}$)
- **Initial Stock ($B$)**:
  $$B = \text{ShedWheat} + \sum_{\text{workers}} \text{InventoryWheat}$$
- **Herd Demand ($F_d$)**:
  $$F_d = \begin{cases} \text{UnfedCowsAndSheep}_{\text{today}}, & d = D \\ \text{HerdSize}, & D < d \le 28 \end{cases}$$
  Animals are not fed on Day 29 (season ends at Day 29 Hour 23; Day 30 produces no yield).
- **Existing In-Ground Wheat Harvests ($H_d$)**:
  For each in-ground wheat tile with planted day $P$:
  - Harvest day: $P + 4$.
  - Realizable yield: 4 units (unfertilized, watered) or up to 6 units (fertilized).
- **Baseline Proposed Wheat Commitments**:
  Baseline `MacroPlanner` proposes $K$ wheat plantings today on Day $D$. If kept, each delivers 4 units on Day $D+4$.

### 2. Sequential Candidate Admission Algorithm

```python
# Initial future harvest timeline
future_harvests = dict(existing_inground_harvests)
future_harvests[D + 4] += len(proposed_wheat_tiles) * 4.0

admitted_tiles = []
for candidate_pos in proposed_wheat_tiles:
    # Hypothetically remove 1 wheat planting (4 units from Day D+4)
    trial_harvests = dict(future_harvests)
    trial_harvests[D + 4] -= 4.0

    # Simulate timeline through Day 28
    is_safe = True
    b = initial_stock
    safety_buffer = herd_size * 2.0  # 2 full days of herd reserve

    for d in range(D, 29):
        b += trial_harvests.get(d, 0.0)
        demand = unfed_today if d == D else herd_size
        b -= demand
        if b < safety_buffer:
            is_safe = False
            break

    if is_safe:
        admitted_tiles.append(candidate_pos)
        future_harvests = trial_harvests  # Commit removal from ledger
    else:
        # Buffer floor hit; immediately halt admission
        break
```

---

## Safety Guarantees

1. **Zero Starvation**: No candidate is approved unless every future day $d \in [D, 28]$ maintains a positive balance above the 2-day safety buffer.
2. **Conservative Yield Assumption**: In-ground wheat is credited with at most 4 units (never assuming unverified future fertilizer bonuses).
3. **Fail-Closed Principle**: If herd feed is tight, `admitted_tiles` is empty, and the agent executes 100% standard baseline wheat replanting.
