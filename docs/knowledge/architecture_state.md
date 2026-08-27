# Kaggriculture Current Architecture & Milestone Status

**Status Date**: 2026-08-27  
**Test Suite**: **377/377 Passing (`pytest`)** across full test suite in ~38s  
**State**: Decision, Execution, Market Layer, Opponent Modeling & Full 100-Tile Farm Expansion Active

---

## 1. Complete Architecture Chain

$$\begin{aligned}
\text{16.7M Exhaustive Census} &\longrightarrow \text{Validated Reference} \longrightarrow \text{PriceForecast (W1)} \\
&\longrightarrow \text{Distributional Profitability (W4)} \longrightarrow \text{MacroPlanner (W2)} \\
&\longrightarrow \begin{cases}
\text{Task Scheduler} \longrightarrow \text{Unit Controller} \longrightarrow \text{Unit Actions} \\
\text{Order Builder} + \text{Market Brain} + \text{Liquidator} \longrightarrow \text{Market Orders}
\end{cases} \\
\text{Opponent Observation} &\longrightarrow \text{StateTracker (Delta/Money/Attribution)} \\
&\longrightarrow \text{OpponentModel (Forecast/Shed/SellProbs)} \longrightarrow \text{OpponentAdvisor} \\
&\longrightarrow \text{Injected into MacroPlanner (Supply/ROI) \& MarketBrain (Delay/Preempt)} \\
&\longrightarrow \text{REAL Game Engine (720-step season walk proven: \$7,105 vs baseline)}
\end{aligned}$$

---

## 2. Opponent Modeling System — Current Status

### Implemented Pillars & Modules

1. **Pillar 1: Production Forecasting (`agent/state/opponent_model.py`)** [Active]
   - `forecast_opponent_production(opp_farm, current_day, horizon=30)`: Exact forward schedule for all visible opponent crops (one-time vs. ongoing interval) and animals (daily eggs, 2-day milk, 3-day wool).
   - `get_imminent_harvests(opp_farm, current_day)`: Real-time scan of ripe unharvested crops and animal yields on the field.
   - `summarize_opponent_commitments(opp_farm)`: Portfolio allocation breakdown (crops, animals, structures, empty/locked tiles).
   - Mortality detection: Unwatered crops (`consecutive_unwatered >= 1`) excluded from future harvest projections.

2. **Pillar 2: Shed Reconstruction & State Tracking (`agent/state/opponent_model.py` & `state_tracker.py`)** [Active]
   - `snapshot_opponent_farm(opp_farm)`: Compact tile signature snapshot.
   - `detect_tile_deltas(current_farm, prev_snapshot)`: Identifies harvest events, plantings, animal collections, animal placements, and deaths across consecutive turns.
   - `update_opponent_shed_estimate(prev_shed, harvest_events, inferred_sales, n_animals, day, hour)`: Probabilistic shed reconstruction:
     $$\text{shed}_t = \text{shed}_{t-1} + \text{harvests}_t - \text{sales}_t - \text{feed\_consumed}_t$$
   - Clamped non-negative with proportional $\le 100$ capacity scaling.
   - `opp_shed_pressure`: Tracks capacity utilization ($\ge 0.80$ flags panic dumping).

3. **Pillar 3: Sell Probability Prediction (`agent/state/opponent_model.py`)** [Active]
   - `compute_opponent_sell_probabilities(opp_farm, estimated_shed, ctx, mem)`: 5-signal weighted heuristic:
     - Shed stock weight (0.35)
     - Imminent / unharvested units (0.25)
     - Shed distance / movement signal (0.20 — distance to `(4,4),(5,4),(4,5),(5,5)`)
     - Global shed pressure (0.15)
     - Timing window boost (0.05 — $h \equiv 1 \pmod 4$ or end-of-day)
   - `predict_imminent_dumps(opp_farm, estimated_shed, sell_probs, threshold=0.60)`: Volume and urgency estimation.

4. **Pillar 5: Tactical Advisor (`agent/strategy/opponent_advisor.py`)** [Active]
   - `OpponentAdvice` dataclass translating model signals into structured planner/market inputs.
   - `build_opponent_advice(opp_state, ctx, forecast, boosts)`: Computes supply adjustments, preempt sells, delay sells, and counter-picks.

---

## 3. Opponent Strategy Implementation — Active Plays vs. Reserved Items

### ✅ Currently Implemented & Wired (Phase 6 Complete)

| Play | Module | Description & Mechanics |
|---|---|---|
| **Play 6: Sale Attribution Feedback Loop** | `state/state_tracker.py` + `main.py` | Finalized turn `SELL` orders call `record_our_sale(product, qty)`. `_update_drain_ledger` subtracts our sales from net market inventory delta before attributing residual sales to `opp_sales_inferred`. Prevents self-sale misattribution. Memory resets cleanly on new episodes. |
| **Play 1: Anti-Glut Crop Steering** | `strategy/opponent_advisor.py` + `strategy/macro_planner.py` | `_compute_supply_adjustment` scales opponent forward harvest schedule by $0.50$ over a 12-day window. Injected into `MacroPlanner._crop_score()` via $\text{inv\_eff} = I_0 - \text{town\_drain} + \text{own\_prod} + \text{opp\_supply}$. Depresses expected ROI of crowded crops, redirecting farm capital to uncontested commodities. |
| **Play 3: Post-Crash Patience (Delay Sell)** | `strategy/opponent_advisor.py` + `market/market_brain.py` | `_compute_delay_sell` identifies commodities recently dumped by opponent whose spot price has dropped $< 80\%$ of expected benchmark. `MarketBrain.sell_orders()` enforces a temporary carry hold ($day < 28$), allowing town shops to drain and restore profitable quotes before we sell. |

---

### ⏳ Reserved for Future Phases

The following components were intentionally deferred during this iteration and remain documented for future optimization:

1. **Pillar 4: Strategy Classification & Archetype Profiling (`agent/state/opponent_model.py`)**
   - *Deferred*: Online Bayesian/rule-based categorization of opponents into archetypes (`WHEAT_RUSHER`, `ANIMAL_FARMER`, `MELON_SNIPER`, `DIVERSIFIED`, `PASSIVE`).
   - *Rationale*: Direct tile scanning and exact production forecasting provide higher-fidelity data without risking hard misclassification biases.

2. **Play 2: Out-of-Window Emergency Pre-emptive Selling (`market/market_brain.py`)**
   - *Current Status*: Preempt sell urgency ($0.99$) prioritizes product slots within standard sell windows ($h \equiv 1 \pmod 4$).
   - *Reserved*: Allowing emergency out-of-window selling on *any* hour when $\text{sell\_prob} \ge 0.90$ to beat an immediate turn dump.

3. **Play 4: Continuous / Dynamic Monopoly Counter-Picking (`strategy/macro_planner.py`)**
   - *Current Status*: Binary counter-pick (+15% boost if opponent has exactly 0 tiles).
   - *Reserved*: Sliding-scale continuous multiplier based on opponent tile share and shop consumption velocity.

4. **Play 5: Multi-Turn Shed Pressure Exploitation & Game-Theoretic Trapping**
   - *Current Status*: Shed pressure $\ge 0.80$ tracked and surfaced as warning signal.
   - *Reserved*: Dynamic pricing traps (e.g. intentionally withholding supply to force opponent to dump at floor, then sweeping post-dump recovery).

5. **Heuristic Calibration via Tournament Logs**
   - *Reserved*: Tuning the 5 sell-probability weights (0.35/0.25/0.20/0.15/0.05) and supply weight (0.50) using empirical data from 100+ game tournament replays.

---

## 4. Farm Strategy & Anti-Monoculture Engine (7-Point Optimization)

| # | Component | Location | Mechanism & Impact |
|---|---|---|---|
| **1** | **Labor Demand Accuracy** | `execution/task_scheduler.py` | Accurate `estimate_daily_load` formula eliminating phantom tile counting, ensuring labor demand matches true active work. |
| **2** | **Wheat-First Baseline** | `strategy/macro_planner.py` | Automatically plants feed base ($\min(4, \text{empty})$) before general scoring. Unlocks $\text{wheat\_cap} > 0$ to open the sustainable animal purchasing gate. |
| **3** | **Portfolio-Aware Glut Model** | `strategy/macro_planner.py` | Evaluates dynamic effective inventory in `_crop_score` accounting for real planned tile allocations, correctly capturing price depression. |
| **4** | **Per-Crop Static Safety Caps** | `config.py` + `strategy/macro_planner.py` | Enforces hard ceilings (`MELON: 4, STRAWBERRY: 4, TOMATO: 6, CARROT: 10`), preventing budget-draining monoculture. |
| **5** | **Land-Buy Window Unlocking** | `config.py` + `strategy/macro_planner.py` | Removed restrictive `day <= 6` gate on NE land. The agent now expands across all 4 quadrants (NE, SW, SE) whenever cash permits, scaling from 25 to 100 tiles. |
| **6** | **Tiered Budget Reservation** | `strategy/macro_planner.py` | Prioritizes labor costs (`hire_total_cost`) and expansion reserves before allocating seed capital, preventing expensive seeds from crowding out land. |
| **7** | **Dynamic Labor Scaling** | `config.py` + `strategy/macro_planner.py` | Realistic labor capacity divisor ($12$ actions/worker/day accounting for movement) and sustained hand floor covering days 0–25, keeping all 100 tiles watered with zero weed decay. |

---

## 5. Verification & Submission Status

- **Automated Tests**: **377/377 passing** (`pytest --basetemp=.pytest_tmp`) in ~38s.
- **Gameplay Verification**:
  - Full quadrant expansion verified: Day 1 unlocks NE (50 tiles), Day 20 unlocks all 4 quadrants (100 tiles).
  - Multi-commodity production verified (Wheat feed base + Melon + Carrot + diversified assets).
  - Head-to-head 720-step matches consistently beat baseline with 100% win-rate.
- **Standalone Submission Packages**:
  - **`dist/submission.py`** (Standalone single-file bundle, 720-step validated at **\$30,512.00–\$37,075.00**).
  - **`dist/submission.zip`** (Multi-file archive with `/kaggle_simulations/agent` path injection).
