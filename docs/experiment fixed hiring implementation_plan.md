# Implementation Plan: Fixed Hiring Schedule + Labor-Centric Dynamic Policy (v5.9)

## 1. Goal & Context
Leaderboard analysis of top competitors demonstrates that an intensive farming model on 75 tiles (3 quadrants) with a fixed, aggressive hiring schedule (scaling to 12 hands) outperforms our **current** dynamic hiring policy — specifically because we have not yet discovered the optimal dynamic hiring strategy. 

This plan details the full implementation of **v5.9**, replacing the current dynamic hiring logic with this proven fixed schedule as a stable benchmark, locking land purchases strictly to 3 quadrants (permanently blocking Quadrant 4 / SE), and restructuring the action-budget allocator and crop/animal policy to maximize throughput across 75 tiles with zero wasted worker actions.

---

## 2. Hard Constraints & Core Rules

1. **Fixed Hiring Schedule (`DAY_TO_HANDS`)**:
   - **Days 0–5**: 4 hands ($5\text{ units} \times 24 = 120\text{ actions/day}$)
   - **Days 6, 7, 8**: 8 hands ($9\text{ units} \times 24 = 216\text{ actions/day}$)
   - **Day 9**: 10 hands ($11\text{ units} \times 24 = 264\text{ actions/day}$)
   - **Days 10–29**: 12 hands ($13\text{ units} \times 24 = 312\text{ actions/day}$)
   - **Day 30**: 0 hands ($1\text{ unit} \times 24 = 24\text{ actions/day}$)
   - *Constraint*: Hands are hired at start of each day to reach target count. Never override with money/market conditions.

2. **Land Purchase Policy**:
   - **Quadrant 2 (NE, \$1k)**: Buy on Day 6 if money $\ge \$2,000$ (safety buffer).
   - **Quadrant 3 (SW, \$2k)**: Buy on Day 9 if money $\ge \$4,000$.
   - **Quadrant 4 (SE, \$4k)**: **HARD-BLOCKED PERMANENTLY**. Enforced via strict assertion guard in `OrderBuilder` and `MacroPlanner`.

3. **Selling Batch Size Rules**:
   - **Phase 1 (Days 0–5)**: 10–20 units per order
   - **Phase 2 (Days 6–8)**: 5–10 units per order
   - **Phase 3+ (Days 9+)**: 3–5 units per order (preserves premium goods: milk, wool, strawberry, melon from glut price collapse)

---

## 3. Proposed Changes Grouped by Component

### A. Configuration Layer (`agent/config.py` & `submission/config.py`)
- Define `DAY_TO_HANDS = {0: 4, 6: 8, 9: 10, 10: 12, 30: 0}` and `get_target_hands(day)`.
- Define `QUADRANT_UNLOCK_DAYS = {2: 6, 3: 9}`, `QUADRANT_MONEY_THRESHOLDS = {2: 2000, 3: 4000}`, and `QUADRANT_HARD_BLOCK = {4}`.
- Define `ANIMAL_SCALING = {4: (4, 0, 0), 8: (8, 2, 0), 10: (10, 3, 1), 12: (12, 4, 2)}` for target animal progression (Geese $\longrightarrow$ Cows $\longrightarrow$ Sheep).
- Define `SELL_BATCH_SIZES = {"phase1": 15, "phase2": 7, "phase3": 4}`.

### B. Strategic Macro Planner (`agent/strategy/macro_planner.py` & `submission/strategy/macro_planner.py`)
- **Fixed Hiring**: Retrieve target hands directly from `get_target_hands(day)`.
- **Mandatory Labor Budget Priority**: Deduct hire cost before computing seed/animal budgets so labor is guaranteed.
- **Land Expansion Guard**: Check `QUADRANT_UNLOCK_DAYS` and `QUADRANT_MONEY_THRESHOLDS`; assert that next quadrant $\ne 4$.
- **Day 0 Wheat-First Strategy**: Plant all available starting tiles with Wheat and queue immediate watering.
- **Animal Target Progression**: Scale targets according to `get_animal_targets(target_hands)` with cash-flow and labor guards.
- **Endgame Rules (Phase 5)**:
  - After Day 25: Halt all seed purchases (`_crop_allowed_today` returns `False` for new seeds).
  - Days 26–28: Prioritize watering and harvesting existing crops.
  - Day 29: Trigger full liquidation and harvest all mature crops.

### C. Execution & Action-Budget Allocator (`agent/execution/task_scheduler.py` & `submission/execution/task_scheduler.py`)
- **Action-Budget Allocator**:
  - Global priority hierarchy:
    $$\text{HARVEST} > \text{WATER} > \text{FEED\_ANIMALS} > \text{COLLECT\_FERTILIZER} > \text{SELL} > \text{PLANT} > \text{FERTILIZE\_CROPS} > \text{BUY}$$
  - Fallback tasks if queue empties: `COLLECT_FERTILIZER` $\longrightarrow$ `SELL_SURPLUS` $\longrightarrow$ `WATER_MATURE` to ensure $<5\%$ idle actions.
- **Fertilizer Application**:
  - Collect daily from all producing animals.
  - Apply to **Strawberry** and **Tomato** first (doubles strawberry yield from 4 to 8).
  - Never apply to Wheat or Melon.
- **Utilization Logging**:
  - Log `actions_available`, `actions_used`, `idle_actions`, `idle_cause`, `shed_occupancy`, `quadrant_ownership`, `daily_hires`, `hire_cost`.

### D. Market Brain & Order Builder (`agent/market/` & `submission/market/`)
- **`order_builder.py`**:
  - Make `TIER_HIRES` absolute #1 priority with 100% money claim.
  - Add hard assertion `assert next_quadrant != 4` on `BUY_LAND`.
- **`market_brain.py`**:
  - Enforce phase-specific batch sizes (`batch_target` = 15, 7, or 4).
  - Spread sales across the day to prevent market depression.

---

## 4. Verification Plan

### Automated Tests
1. **Pytest Suite**: Run `pytest` across all 379 test cases to verify 100% compatibility.
2. **Assertion Verification**:
   - Assert Q4 is never purchased across all 720 steps.
   - Assert daily hires exactly match `DAY_TO_HANDS` schedule on every single day.
   - Assert average idle action rate $< 5\%$.
   - Assert zero shed overflow discard events.

### 5-Game A/B Simulation vs. v5.8 Baseline
- Run 5 full games with seeds `[101, 202, 303, 404, 505]` in `kaggle_environments`.
- Compare v5.9 final scores vs. v5.8 baseline (`scripts/five_games_log.json`):
  - v5.8 Baseline: Mean \$11,655 (Game 1: \$9.9k, Game 2: \$10.2k, Game 3: \$14.7k, Game 4: \$12.5k, Game 5: \$10.6k).
  - Target v5.9: Maintain high stability and test if fixed 12-hand labor engine scales revenue further.
- Produce a detailed comparison report with daily utilization and money curves.
