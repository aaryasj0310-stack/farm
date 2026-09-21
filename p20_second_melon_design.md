# P2.0: Dynamic Second Melon Tranche Design Document
## Architecture, Mathematical Formulation, and Isolation Specification

---

## 1. Baseline Audit: Why a Second Melon Wave Currently Cannot Occur

In True Production Control (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`), an audit of `macro_planner.py` reveals that a second melon wave is completely blocked by four compounding mechanisms:

1. **Static Melon Cap (`CROP_TILE_CAPS["MELON"] = 12`)**:
   During Days 0–10, the 12 Day-0 melon tiles are physically growing on the farm. `committed_counts["MELON"]` equals 12. Any general planting loop immediately skips Melon because `committed_counts["MELON"] >= CROP_TILE_CAPS["MELON"]`.

2. **Day-10 Wheat Target Surge (`quadrant_wheat_target`)**:
   In `macro_planner.py` lines 2278–2284:
   ```python
   quadrant_wheat_target = (
       8 if (n_quads == 1 or day <= 9)
       else (20 if (n_quads == 2 or day <= 13) else 30)
   )
   ```
   At the exact moment Day-0 melons are harvested on Day 10 and become empty tiles, `day <= 9` becomes `False`. The wheat target immediately surges from 8 to **20 tiles**. The planner calculates `wheat_needed = 20 - 8 = 12 tiles`. All 12 newly cleared melon tiles are immediately seized by `wheat_to_plant = min(wheat_needed, len(empty_tiles))`!

3. **Dedicated Strawberry Wave Override**:
   Immediately following the wheat replant loop, lines 2309–2332 enforce a hard override:
   ```python
   if 3 <= day <= STRAWBERRY_PLANT_DEADLINE and "NE" in farm.unlocked:
       s_cap = get_strawberry_cap(day, True)  # 18 on Days 9-12; 20 on Day 13
   ```
   Any remaining empty tiles on the farm are claimed for Strawberry.

4. **Execution Priority Ordering**:
   The macro planner executes planting in this rigid order:
   - Step 1: SW dedicated planting (none on 2Q farm)
   - Step 2: Wheat target fulfillment (up to 20 tiles)
   - Step 3: Strawberry wave override (up to 18–20 tiles)
   - Step 4: Fallback dynamic crop scoring (lines 2341–2406)
   
   On a 49-tile farm with 20 wheat, 18 strawberry, and 8–12 animal pastures, **zero empty tiles ever reach Step 4**. Even though Melon scores **$211.90 / day** in `_crop_score` (vs $31.60 for Wheat and $35.20 for Carrot), Step 4 never executes.

**Conclusion**: The second melon wave cannot occur due to the combination of the Day-10 wheat target surge, the dedicated strawberry wave override, and execution priority ordering.

---

## 2. P2.0 Treatment Specification

### 2.1 Feature Flag & Zero-Impact Invariant
In `agent/config.py`:
```python
P20_SECOND_MELON_TRANCHE_ENABLED: bool = False

def get_p20_second_melon_tranche_enabled() -> bool:
    return P20_SECOND_MELON_TRANCHE_ENABLED

def set_p20_second_melon_tranche_enabled(enabled: bool) -> None:
    global P20_SECOND_MELON_TRANCHE_ENABLED
    P20_SECOND_MELON_TRANCHE_ENABLED = bool(enabled)
```
When `P20_SECOND_MELON_TRANCHE_ENABLED is False`, the agent executes 100% byte-for-byte identical logic to True Production Control.

### 2.2 Admission Logic: `evaluate_second_melon_tranche(...)`
Located in `agent/strategy/second_melon_evaluator.py`, this function evaluates candidate tranche sizes $k \in \{0, 4, 6, 8, 10\}$ against seven quantitative gates:

#### Gate 1: Timing & Season Horizon
- Second tranche is considered strictly on **Days 10, 11, or 12**.
- Melon takes 10 days to mature (`first_yield_day = 10`, `max_yield = 6`).
  - Planted Day 10 $\rightarrow$ Matures Day 20 (9 days left in season).
  - Planted Day 11 $\rightarrow$ Matures Day 21 (8 days left).
  - Planted Day 12 $\rightarrow$ Matures Day 22 (7 days left).
- Plants after Day 12 leave insufficient margin for harvest and endgame liquidation.

#### Gate 2: Existing Melon Commitment
The evaluator tracks total melon volume:
- Live growing melon tiles on farm: $M_{\text{live}}$
- Planned melon plantings this turn: $M_{\text{planned}}$
- Melons currently held in shed + worker inventories: $M_{\text{held}}$
- Estimated melons already sold to market: $M_{\text{sold}}$
- Cumulative melon production: $M_{\text{total}} = M_{\text{live}} \times 6 + M_{\text{held}} + M_{\text{sold}}$
- Hard boundary: Cumulative production must not exceed **140 units** (to protect against the quadratic market price cliff at $T=300$).

#### Gate 3: Endogenous Market Headroom & Realized Price
Melon market parameters: $base = 250$, $T = 300$, $above\_func = sq$, $above\_target = 3.60$.
$$amp = \frac{3.60 \times 250}{300^2} = 0.01$$
For an incremental tranche of $k$ tiles yielding $6k$ melons sold into inventory $I$:
$$\Delta inv = \max(0, I + 6k - I_0)$$
$$P_{\text{marginal}} = \max(1, 250 - 0.01 \times (\Delta inv)^2)$$
$$\text{Expected Melon Revenue} = \sum_{i=1}^{6k} P(I + i)$$
A candidate $k$ is rejected if the projected marginal selling price falls below **$140 / unit**.

#### Gate 4: Seed Capital & Solvency
- Seed cost: $80 \times \max(0, k - \text{owned\_seeds})$.
- The treasury must retain `MONEY_RESERVE` ($300) plus essential daily hire costs and protected land capital before seed expenditure is authorized.

#### Gate 5: Labor Serviceability & Core Protection
The second melon tranche must not steal labor from essential core farm operations:
- Unwatered crops at start of day must be $\le 2$ tiles.
- Available action points ($24 \times (1 + \text{hands})$) must have at least $15\%$ headroom above projected core workload (watering existing crops + scheduled harvests + feed tasks).
- If worker capacity is constrained, $k$ is throttled or rejected.

#### Gate 6: Opportunity Cost vs Alternative Crops
For each candidate $k$ tiles, compare projected melon net profit against the next-best crop that would occupy those tiles over the same 10-day window:
- Alternative: 2 cycles of Carrot ($2 \times 3 \text{ units} \times \$35 - 2 \times \$20 = \$170$ net per tile) or 2 cycles of Wheat ($2 \times 4 \times \$25 - 2 \times \$10 = \$180$ net per tile).
- Incremental Value = $\text{Net Melon Profit} - (k \times \$180.00)$.
- The tranche is admitted only if **$\text{Incremental Value} > 0$**.

#### Gate 7: Dynamic Tranche Selection
Among all feasible candidate sizes $k \in \{0, 4, 6, 8, 10\}$ bounded by available empty tiles, choose:
$$k^* = \arg\max_{k} \text{Incremental Value}(k)$$
If $\max_k \text{Incremental Value} \le 0$, $k^* = 0$.

---

## 3. Placement & Macro Planner Integration

In `macro_planner.py`:
On Days 10–12, when `P20_SECOND_MELON_TRANCHE_ENABLED` is active:
1. `evaluate_second_melon_tranche(...)` is called after live melon harvest.
2. If $k^* > 0$, $k^*$ empty NW/NE tiles are allocated to `MELON` in `plant_queue` and seeds are queued in `buy_seed["MELON"]`.
3. The remaining empty tiles are passed to the standard wheat replant and strawberry loops.
4. When `P20_SECOND_MELON_TRANCHE_ENABLED` is False, this block is completely skipped, preserving exact Control behavior.

---

## 4. Telemetry Specification

The experiment runner records:
- Decision telemetry: checks, day/hour, candidate evaluations, selected $k$, rejections.
- Actual production: planted tiles, confirmed plants, watering completion, harvests, units, revenue, average selling price.
- Core impact: unwatered EOD, productive operations, scheduler travel, mature crop backlog.
- Crop displacement: tiles displaced from Wheat, Carrot, Tomato, Strawberry, Empty.
