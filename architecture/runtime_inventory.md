# Kaggriculture Runtime Architecture Inventory

> **Package Source of Truth**: `submission/` (Official Kaggle Competition Deployment Artifact)  
> **Target Environment**: Kaggle Environments `kaggriculture` (Two-Player Turn-Based Farm Sim)  
> **Stable ID Notation**:
> - `ARCH-*`: Architectural modules and component classes
> - `DEC-*`: Strategic, market, and execution decision gates
> - `FORM-*`: Exact dynamic mathematical formulas
> - `RULE-*`: Static engine constants, constraints, and policy parameters
> - `STATE-*`: Persistent module-level and cross-turn state objects
> - `EXEC-*`: Spatial unit dispatch and task scheduling routines
> - `MKT-*`: Order construction, price math, and market clearing
> - `FAIL-*`: Failure modes and hazard states

---

## 1. Top-Level Architectural Modules (`ARCH-*`)

### `ARCH-MAIN-01`: Top-Level Agent Controller
- **File / Module**: [submission/main.py](file:///d:/website%20project/kaggri%20ox/submission/main.py)
- **Symbol**: `agent(obs, config=None)` / `_agent_decision(obs)`
- **Purpose**: Kaggle entry point. Coordinates the 6-phase per-turn lifecycle: state tracking, opponent advice generation, strategic macro-planning, task building/spatial assignment, morning market order compilation, sell-side market composition, action dict formatting, and fail-safe recovery.
- **Inputs**: Raw Kaggle observation dictionary `obs`, optional `config`.
- **Outputs**: Engine action dictionary `{"farmer": [...], "hands": [[...], ...], "market": [[...], ...]}`.
- **Calls**: `get_state()`, `_get_components()`, `reset_daily_log()`, `reset_opponent_model_state()`, `demand_boosts()`, `_build_opp_advice()`, `MacroPlanner.build()`, `build_tasks()`, `assign_tasks()`, `OrderBuilder.build()`, `OrderBuilder.reinvest_livestock()`, `MarketBrain.sell_orders()`, `EndgameLiquidator.plan()`, `MarketBrain.compose()`, `record_our_sale()`, `_emergency_fallback()`.
- **Called By**: Kaggle Environments simulation engine (`kaggle_environments.make("kaggriculture")`).
- **Persistent State Read**: `_STATE`, `_prev_opp_snapshot`, `_estimated_shed`, `_OPPONENT_MODEL_DIAGNOSTICS`, `_LAST_FALLBACK_DIAGNOSTIC`.
- **Persistent State Written**: `_STATE["episode"]`, `_LAST_FALLBACK_DIAGNOSTIC`.
- **Engine State Read**: `day`, `hour`, `step`, `farms`, `market`, `town`, `private`.
- **Engine Actions Produced**: Dispatches unit actions (`MOVE`, `WATER`, `FEED`, `HARVEST`, `CARE`, `PLANT`, `BUILD_PASTURE`, `PICKUP`, `DIG`, `PASS`) and market orders (`HIRE`, `BUY_LAND`, `BUY_SEED`, `BUY_PRODUCT`, `BUY_ANIMAL`, `SELL`).
- **Dynamic Formulas Used**: `n_units = 1 + len(farm.hands)`.
- **Static Constants Used**: `QUADRANT_HARD_BLOCK`, `TURNS_PER_DAY`.
- **Thresholds / Cutoffs**: `ctx["day"] == 0 and ctx["hour"] == 0` (seasonal state reset), `ctx["hour"] in (0, 1)` (morning purchase window / deferred hires), `ctx["day"] >= 28` (endgame liquidation switch).
- **Assumptions**: Interpreter applies unit actions *before* `_process_market()`; newly hired hands on turn $T$ cannot act until turn $T+1$.
- **Side Effects**: Mutates persistent state dictionaries, writes diagnostic traces on fallback.
- **Fallback Behavior**: Calls `_emergency_fallback(obs, exc)` returning a deterministic survival action dict (`_survival_fallback_from_ctx` or `_survival_fallback_raw`).
- **Downstream Systems Affected**: Complete simulation state, game score.
- **Failure Consequences**: Total match disqualification or score drop if unhandled.

---

### `ARCH-STATE-01`: Observation Parser
- **File / Module**: [submission/state/observation_parser.py](file:///d:/website%20project/kaggri%20ox/submission/state/observation_parser.py)
- **Symbol**: `parse_observation(obs)`, `TileView`, `FarmView`, `MarketView`, `TownView`, `PrivateView`
- **Purpose**: Converts unstructured observation dicts or Struct objects into lightweight, strongly-typed, indexed domain views.
- **Inputs**: Raw `obs` dict from engine.
- **Outputs**: Typed `ctx` dictionary containing `FarmView`, `MarketView`, `TownView`, `PrivateView`, coordinate helpers, and temporal step counts.
- **Calls**: `g()` safe attribute accessor.
- **Called By**: `state_tracker.get_state()`, `main._emergency_fallback()`.
- **Persistent State Read/Written**: None (pure functional parsing).
- **Engine State Read**: Full observation tree.
- **Static Constants Used**: `SHED_ACCESS_TILES`, `TURNS_PER_DAY`.
- **Assumptions**: 10x10 farm grid divided into four 5x5 quadrants (`NW`, `NE`, `SW`, `SE`).
- **Fallback Behavior**: Returns `None` if `obs["farms"]` is missing or invalid.
- **Downstream Systems Affected**: Every decision, planning, market, and execution module.

---

### `ARCH-STATE-02`: Persistent State Tracker
- **File / Module**: [submission/state/state_tracker.py](file:///d:/website%20project/kaggri%20ox/submission/state/state_tracker.py)
- **Symbol**: `get_state(obs)`, `reset_memory()`, `record_our_sale()`, `_update_drain_ledger()`, `_update_opp_money()`
- **Purpose**: Maintains cross-turn memory across turns within an episode; detects new episodes; runs drain-ledger accounting to infer opponent sales; tracks town shop consumption.
- **Inputs**: Raw `obs`.
- **Outputs**: `(ctx, mem)` tuple.
- **Calls**: `parse_observation()`, `_update_drain_ledger()`, `_update_opp_money()`, `_update_shop_tracker()`.
- **Called By**: `main._agent_decision()`.
- **Persistent State Read**: `_STATE` (`STATE-MEM-01`).
- **Persistent State Written**: `_STATE["prev_inventory"]`, `_STATE["opp_sales_inferred"]`, `_STATE["our_units_sold"]`, `_STATE["opp_money_deltas"]`, `_STATE["known_shops"]`, `_STATE["days_seen"]`.
- **Dynamic Formulas Used**: 
  - `net_player_sales = (inventory_now - inventory_prev) + expected_town_consumption` (`FORM-DRAIN-01`)
  - `opp_sales_inferred += max(0, net_player_sales - our_sales_last_step)` (`FORM-DRAIN-02`)
- **Static Constants Used**: `PRODUCTS`, `SHOPS`, `TURNS_PER_DAY`, `OPP_MONEY_WINDOW = 24`.
- **Side Effects**: Fires callbacks registered in `_RESET_HOOKS`.
- **Fallback Behavior**: Gracefully ignores missing historical data on turn 0 or post-reset.
- **Downstream Systems Affected**: Opponent model, market brain drip sizing, price forecasting.

---

### `ARCH-STATE-03`: Opponent Modeling Engine
- **File / Module**: [submission/state/opponent_model.py](file:///d:/website%20project/kaggri%20ox/submission/state/opponent_model.py)
- **Symbol**: `snapshot_opponent_farm()`, `detect_tile_deltas()`, `forecast_opponent_production()`, `update_opponent_shed_estimate()`, `compute_opponent_sell_probabilities()`
- **Purpose**: Non-intrusive opponent behavioral tracking: creates compact tile signatures, detects field deltas (harvests, plantings, animal placements), projects forward harvest schedules, reconstructs opponent shed inventory via Bayesian balance, and scores opponent dump probabilities.
- **Inputs**: `opp_farm` (`FarmView`), historical deltas, market sales inferred.
- **Outputs**: State dict with `estimated_shed`, `sell_probs`, `forecast`, `shed_pressure`, `commitments`.
- **Calls**: `_tile_signature()`, `crop_age()`, `market_price()`.
- **Called By**: `main._build_opp_advice()`.
- **Persistent State Read/Written**: `_prev_opp_snapshot` (`STATE-OPP-SNAP`), `_estimated_shed` (`STATE-OPP-SHED`).
- **Dynamic Formulas Used**: 
  - `shed_pressure = min(1.0, sum(estimated_shed.values()) / 100.0)` (`FORM-OPP-01`)
  - Multi-factor sell scoring: `P_sell = w_mat * score_maturity + w_shed * score_pressure + w_drain * score_drain` (`FORM-OPP-02`)
- **Static Constants Used**: `SHED_CAPACITY = 100`, `ANIMALS`, `CROPS`.
- **Fallback Behavior**: Wrapped in broad try/except in `_build_opp_advice`; records diagnostics in `_OPPONENT_MODEL_DIAGNOSTICS` and returns empty advice on failure.
- **Downstream Systems Affected**: Tactical opponent advice, crop scoring supply penalties, rush selling, hold delays.

---

### `ARCH-STRAT-01`: Price Forecasting Engine
- **File / Module**: [submission/strategy/price_forecast.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/price_forecast.py)
- **Symbol**: `PriceForecast`
- **Purpose**: Decision-grade query interface over population-exact Monte Carlo price distributions (all $8^8$ shop sequence paths) pre-calculated in `baked_price_table.py`.
- **Inputs**: Product, day, price thresholds, quantiles.
- **Outputs**: $E[P \mid \text{day}]$, tail probabilities $P(P > \text{thresh} \mid \text{day})$, floor probabilities $P(P = \$1 \mid \text{day})$, quantiles.
- **Calls**: Queries `baked_price_table.PRICE_TABLE`.
- **Called By**: `MacroPlanner`, `MarketBrain`, `EndgameLiquidator`, `ExpansionPlanner`.
- **Dynamic Formulas Used**: Continuous interpolation between price grid anchor points (`FORM-FC-01`).
- **Static Constants Used**: `QUANTILE_LEVELS`, `TABLE_VERSION = 1`.
- **Downstream Systems Affected**: Crop marginal profit ranking, animal lifetime profitability, land ROI, market hold/drip/dump decisions.

---

### `ARCH-STRAT-02`: Tactical Opponent Advisor
- **File / Module**: [submission/strategy/opponent_advisor.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/opponent_advisor.py)
- **Symbol**: `build_opponent_advice()`, `OpponentAdvice`
- **Purpose**: Translates probabilistic opponent state into concrete strategic penalties and market trading recommendations.
- **Inputs**: `opp_state`, `ctx`, `forecast`, `boosts`.
- **Outputs**: `OpponentAdvice(supply_adjustment, preempt_sell, delay_sell, counter_pick, opp_shed_pressure)`.
- **Calls**: `_compute_supply_adjustment()`, `_compute_preempt_sell()`, `_compute_delay_sell()`, `_compute_counter_pick()`.
- **Called By**: `main._build_opp_advice()`.
- **Static Constants Used**: 
  - `SUPPLY_ADJUSTMENT_WEIGHT = 0.50` (`RULE-ADV-01`)
  - `SUPPLY_PROJECTION_DAYS = 12` (`RULE-ADV-02`)
  - `PREEMPT_SELL_THRESHOLD = 0.65` (`RULE-ADV-03`)
  - `DELAY_PRICE_DEPRESSION_PCT = 0.80` (`RULE-ADV-04`)
- **Downstream Systems Affected**: `MacroPlanner._crop_score()` glut penalty, `MarketBrain.sell_orders()` urgency override and delay holds.

---

### `ARCH-STRAT-03`: Strategic Macro Planner
- **File / Module**: [submission/strategy/macro_planner.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py)
- **Symbol**: `MacroPlanner`, `MacroPlan`
- **Purpose**: Daily high-level strategic governor. Allocates land between crops, pastures, and coops; evaluates land purchase viability; schedules dynamic animal acquisition; balances feed wheat buffering; ranks candidate crop tiles via portfolio-wide marginal profit modeling; outputs queues and intents.
- **Inputs**: `ctx`, `boosts`, `opp_advice`.
- **Outputs**: `MacroPlan` object consumed by `TaskScheduler` (`plant_queue`, `build_queue`, `place_queue`, `feeding_enabled`, `watering_enabled`) and `OrderBuilder` (`intents`).
- **Calls**: `get_target_hands()`, `get_animal_targets()`, `compute_land_roi()`, `opportunity_window_factor()`, `compute_land_urgency()`, `should_buy_land()`, `_crop_score()`, `get_committed_crop_counts()`, `get_strawberry_cap()`, `get_sw_tile_breakdown()`.
- **Called By**: `main._agent_decision()`.
- **Dynamic Formulas Used**: 
  - Farm-wide committed crop accounting (`FORM-CROP-01`)
  - Marginal revenue delta with own-supply glut depression (`FORM-CROP-02`)
  - Sustainable herd capacity from wheat projection (`FORM-HERD-01`)
  - Effective cash reservation for land/seed/feed/labor (`FORM-BUDGET-01`)
- **Static Constants Used**: `CROP_TILE_CAPS`, `CROP_DIVERSIFICATION_FACTOR`, `FEED_WHEAT_BUFFER_DAYS`, `SW_PASTURE_TILES`, `EARLY_PASTURE_TILES`.
- **Downstream Systems Affected**: `TaskScheduler` work queue, `OrderBuilder` purchase commitments.

---

### `ARCH-STRAT-04`: Expansion & Land Planner
- **File / Module**: [submission/strategy/expansion_planner.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py)
- **Symbol**: `compute_land_roi()`, `opportunity_window_factor()`, `compute_land_urgency()`, `should_buy_land()`, `expansion_seed_targets()`
- **Purpose**: Economics-driven quadrant acquisition governor. Computes exact incremental profit of adding 25 tiles against land price; evaluates seasonal opportunity windows; enforces non-negotiable treasury safety gates.
- **Inputs**: `next_quadrant`, `day`, `money`, `farm`, `forecast`, commitments, reserve.
- **Outputs**: `(buy_land: bool, reason: str, diagnostics: dict)`.
- **Calls**: `_allocate_portfolio_profit()`, `_estimate_crop_revenue_per_tile()`, `evaluate_sw_timing()`.
- **Called By**: `MacroPlanner.build()`.
- **Dynamic Formulas Used**:
  - Incremental Marginal ROI: $\text{ROI} = \frac{(P_{\text{with}} - P_{\text{without}}) - \text{Price}}{\text{Price}}$ (`FORM-LAND-01`)
  - Adjusted ROI: $\text{ROI}_{\text{adj}} = \text{ROI} \times \text{OW\_Factor}$ (`FORM-LAND-02`)
  - Treasury Safety Requirement: $\text{Req} = \text{Price} + \text{Mandatory W\_Cost} + \text{Seed Tranche} + \text{Reserve}$ (`FORM-LAND-03`)
- **Static Constants Used**: `QUADRANT_UNLOCK_DAYS`, `QUADRANT_MONEY_THRESHOLDS`, `QUADRANT_HARD_BLOCK = {4}`, `LAND_PRICES = [1000, 2000]`, `LAND_BUY_LAST_DAY = 20`.
- **Downstream Systems Affected**: `MacroPlan.intents["buy_land"]`, `OrderBuilder` slot allocation, total tile capacity.

---

### `ARCH-STRAT-05`: Livestock Target Planner
- **File / Module**: [submission/strategy/animal_planner.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py)
- **Symbol**: `get_animal_targets()`
- **Purpose**: Optimizes terminal herd composition (Cow vs Sheep) by maximizing modeled net lifetime profit under spatial housing, feed replacement, and town drainage limits.
- **Inputs**: `day`, `money`, `shed_wheat`, `current_animals`, `max_pastures`, `cutoff_day`.
- **Outputs**: Dictionary `{"COW": count, "SHEEP": count, "GOOSE": 0}`.
- **Dynamic Formulas Used**:
  - Cow lifetime profit with care bonus and gestation lag (`FORM-ANIM-01`)
  - Sheep lifetime profit with care bonus and gestation lag (`FORM-ANIM-02`)
  - Net fertilizer revenue: $(100 - \text{FEED\_PRICE}) \times (29 - \text{day})$ (`FORM-ANIM-03`)
- **Static Constants Used**: `HERD_CAP = 20`, `SHEEP_CAP = 12`, `COW_CAP = 19`, `C4_LIVESTOCK_CUTOFF_DAY = 12`, `FEED_PRICE = 25`, `FEED_BUFFER_DAYS = 3`.
- **Downstream Systems Affected**: `MacroPlanner` pasture build targets, animal purchase intents.

---

### `ARCH-STRAT-06`: Endgame Liquidator
- **File / Module**: [submission/strategy/endgame_liquidator.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/endgame_liquidator.py)
- **Symbol**: `EndgameLiquidator`
- **Purpose**: Days 28–29 liquidation manager. Bypasses normal hold rules to ensure all shed products are sold before Day 30 scoring cutoff (unsold inventory scores 0).
- **Inputs**: `ctx`, `opp_advice`, `max_slots`.
- **Outputs**: `(orders, details)`.
- **Calls**: `MarketBrain.sell_orders()`, `PriceForecast.prob_floor()`, `PriceForecast.expected_price()`.
- **Called By**: `main._agent_decision()`.
- **Dynamic Formulas Used**: Uplift vs Floor Probability check (`FORM-LIQ-01`).
- **Static Constants Used**: `ENDGAME_START_DAY = 28`, `FINAL_DUMP_DAYS = {28: 0.75, 29: 0.25}`.
- **Downstream Systems Affected**: Final turn market sell orders.

---

### `ARCH-MKT-01`: Engine-Exact Price Math
- **File / Module**: [submission/market/price_math.py](file:///d:/website%20project/kaggri%20ox/submission/market/price_math.py)
- **Symbol**: `market_price()`, `inventory_for_price_at_least()`, `inventory_at_price()`, `total_revenue_estimate()`
- **Purpose**: Exact pure-Python mirror of the Kaggriculture market price curves ($I_0 = 10,000$, scarcity below $I_0$, glut above $I_0$, custom shape functions: linear, sqrt, sq, log, hinge). Provides analytical inverses to calculate maximum safe sell quantities.
- **Inputs**: Product, inventory level, target prices.
- **Outputs**: Integer price quote, floating continuous inventory levels.
- **Calls**: `_shape()`, `_solve_shape()`, `amplitude()`.
- **Called By**: `MarketBrain`, `OrderBuilder`, `MacroPlanner`, `ExpansionPlanner`.
- **Dynamic Formulas Used**: Engine piecewise market pricing formula (`FORM-MATH-01`).
- **Static Constants Used**: `MARKET_I0 = 10000`, `PRICE_FLOOR = 1`, `MARKET_PARAMS`.
- **Downstream Systems Affected**: All pricing, revenue estimates, and drip sizing.

---

### `ARCH-MKT-02`: Sell-Side Market Brain
- **File / Module**: [submission/market/market_brain.py](file:///d:/website%20project/kaggri%20ox/submission/market/market_brain.py)
- **Symbol**: `MarketBrain`
- **Purpose**: Decides which products to sell, in what batch sizes, and at what hours. Implements 3-tier urgency shedding, floor price holds, forecast carry evaluation, self-glut drip slicing, and special melon drip limits.
- **Inputs**: `ctx`, `opp_advice`, `max_slots`.
- **Outputs**: `(sell_orders, details)` where each order is `["SELL", product, qty]`.
- **Calls**: `market_price()`, `inventory_for_price_at_least()`, `total_revenue_estimate()`, `_get_season_units_sold()`.
- **Called By**: `main._agent_decision()`, `EndgameLiquidator`.
- **Dynamic Formulas Used**: 
  - Turn drip volume calculation: $Q = \text{inv\_for\_price\_at\_least}(P \times \text{keep\_frac}) - I_{\text{market}}$ (`FORM-DRIP-01`)
  - Carry gain evaluation: $E[P \mid \text{day} + H] / P_{\text{spot}} - 1.0 > \text{MIN\_CARRY\_GAIN}$ (`FORM-CARRY-01`)
- **Static Constants Used**: 
  - `SELL_WINDOWS = [1, 5, 9, 13, 17, 21]`, `SHED_SOFT_CAP = 65`, `SHED_RESUME_CAP = 55`, `MELON_SEASON_SALE_CAP = 150`, `DRIP_PRICE_KEEP_FRAC`.
- **Downstream Systems Affected**: Outgoing market sell orders, shed levels, treasury growth.

---

### `ARCH-MKT-03`: Purchase Order Builder
- **File / Module**: [submission/market/order_builder.py](file:///d:/website%20project/kaggri%20ox/submission/market/order_builder.py)
- **Symbol**: `OrderBuilder`, `hire_total_cost()`, `_fib()`
- **Purpose**: Compiles high-level `MacroPlan.intents` into engine-compliant market orders (`HIRE`, `BUY_LAND`, `BUY_SEED`, `BUY_PRODUCT`, `BUY_ANIMAL`). Enforces 10-order turn caps, reserves cash for mandatory labor and survival feed, and protects critical non-hire orders from slot starvation.
- **Inputs**: `ctx`, `intents`.
- **Outputs**: `(orders, ledger)`.
- **Calls**: `_fib()`, `hire_total_cost()`, `market_price()`.
- **Called By**: `main._agent_decision()`.
- **Dynamic Formulas Used**:
  - Fibonacci cumulative hire cost: $\sum_{i=0}^{k-1} \text{fib}(\text{start} + i)$ (`FORM-HIRE-01`)
  - Hour 0 Hire Slot Budget: $\text{max\_hire\_slots} = \max(\text{MIN\_HANDS\_BASE}, \text{slots} - \text{non\_hire\_slots\_needed})$ (`FORM-SLOT-01`)
  - Buffered wheat purchase price: $\lceil P_{\text{wheat}} \times 1.10 \rceil$ (`FORM-WHEAT-01`)
- **Static Constants Used**: `MAX_MARKET_ORDERS = 10`, `MIN_HANDS_BASE = 4`, `MONEY_RESERVE_DEFAULT = 300`, `TIER_HIRES = 0`, `TIER_FEED_WHEAT = 1`, `TIER_LAND = 2`, `TIER_SEEDS = 3`, `TIER_ANIMALS = 4`.
- **Downstream Systems Affected**: Dispatched market purchase orders, farm treasury, worker roster, land unlock state.

---

### `ARCH-EXEC-01`: Task Scheduler & Dispatcher
- **File / Module**: [submission/execution/task_scheduler.py](file:///d:/website%20project/kaggri%20ox/submission/execution/task_scheduler.py)
- **Symbol**: `build_tasks()`, `assign_tasks()`, `get_daily_log()`, `reset_daily_log()`
- **Purpose**: Generates prioritized per-tile tasks (survival, harvest, feed staging, production feed, care, planting, pasture building) and solves the multi-unit spatial assignment problem. Implements persistent sticky missions, Manhattan/BFS movement, C2 zonal boundaries, and C6 clustered dispatch.
- **Inputs**: `ctx`, `plan` (`MacroPlan`).
- **Outputs**: Action assignment dictionary `{"actions": {unit_id: [action]}, "assignment": {...}}`.
- **Calls**: `bfs_first_step()`, `crop_age()`, `in_bonus_window()`, `needs_water_today()`, `turns_until_decay()`.
- **Called By**: `main._agent_decision()`, `_survival_fallback_from_ctx()`.
- **Persistent State Read/Written**: `_daily_log`, `_daily_accum`, `_ACTIVE_MISSIONS` (`STATE-STICKY`), `_BLOCKED_TASK_TRACKER` (`STATE-BLOCK`), `_SW_SEASONAL_TRACKER` (`STATE-SW-TRACK`).
- **Dynamic Formulas Used**:
  - Effective dispatch cost: $\text{score} = \text{priority} - (\text{dist} \times C6\_TRAVEL\_WEIGHT) + \text{cluster\_bonus}$ (`FORM-EXEC-01`)
  - Tile Manhattan Distance: $|x_1 - x_2| + |y_1 - y_2|$ (`FORM-DIST-01`)
- **Static Constants Used**: Priority levels 100 down to 20 (`RULE-PRIO-01` to `RULE-PRIO-12`), `C2_MAX_SPILLOVER_DIST = 12`, `C6_CLUSTER_RADIUS = 1`, `C6_CLUSTER_BONUS = 2`.
- **Downstream Systems Affected**: Farmer action, hired hands actions, daily work completion, crop survival.

---

### `ARCH-EXEC-02`: Pathfinding & Navigation
- **File / Module**: [submission/execution/pathfinding.py](file:///d:/website%20project/kaggri%20ox/submission/execution/pathfinding.py)
- **Symbol**: `bfs_first_step(start, target, board_size)`
- **Purpose**: Computes the optimal single-step cardinal move (`MOVE_NORTH`, `MOVE_SOUTH`, `MOVE_EAST`, `MOVE_WEST`) to reach target $(x, y)$ on the 10x10 torus-free grid using Breadth-First Search.
- **Inputs**: Start coordinate tuple, target coordinate tuple, board size integer.
- **Outputs**: Direction string or `None` if already at target.
- **Downstream Systems Affected**: Unit movement actions.

---

## 2. Persistent & Cross-Turn State Objects (`STATE-*`)

| State ID | Symbol / Location | Lifetime / Reset Trigger | Reader Modules | Writer Modules | Failure Consequences if Corrupted |
|---|---|---|---|---|---|
| `STATE-MEM-01` | `state_tracker._STATE` | Reset on new episode (Day 0 Step 0 or backwards day) | `state_tracker`, `main`, `opponent_model` | `state_tracker.get_state`, `record_our_sale` | False opponent sales inference; stale shop lists; drain ledger desync. |
| `STATE-OPP-SNAP` | `main._prev_opp_snapshot` | Reset on Day 0 H0 in `main._agent_decision` or hook | `main._build_opp_advice`, `opponent_model` | `main._build_opp_advice` | Delta detection hallucination; incorrect harvest/placement detection. |
| `STATE-OPP-SHED` | `main._estimated_shed` | Reset on Day 0 H0 in `main._agent_decision` or hook | `main._build_opp_advice`, `opponent_model` | `main._build_opp_advice` | Opponent shed inventory explosion; phantom dump predictions. |
| `STATE-STICKY` | `task_scheduler._ACTIVE_MISSIONS` | Cross-turn; unit cleared on mission complete/timeout | `task_scheduler.assign_tasks` | `task_scheduler.assign_tasks` | Worker lock-up / task churn; units oscillating or stranded on distant tiles. |
| `STATE-BLOCK` | `task_scheduler._BLOCKED_TASK_TRACKER` | Reset on day transition or via reset hook | `task_scheduler.assign_tasks` | `task_scheduler.assign_tasks` | Valid tasks permanently ignored if falsely marked unreachable. |
| `STATE-DAILY-LOG` | `task_scheduler._daily_log` | Reset on Day 0 H0 via `reset_daily_log()` | Benchmarks, telemetry exporters | `task_scheduler.assign_tasks` | Telemetry accumulation error across multi-game evaluations. |
| `STATE-SW-TRACK` | `task_scheduler._SW_SEASONAL_TRACKER`| Season-long accumulator | `get_sw_season_summary()`, `MacroPlanner` | `task_scheduler.assign_tasks` | Inaccurate SW occupancy and utilization telemetry reporting. |
| `STATE-DIAG-FALL` | `main._LAST_FALLBACK_DIAGNOSTIC` | Updated on any caught planner/scheduler crash | `get_last_fallback_diagnostic()` | `main._emergency_fallback`, `main._agent_decision` | Undetected silent fallbacks during live tournament play. |

---

## 3. Dynamic Decision Formulas (`FORM-*`)

### `FORM-LAND-01`: Incremental Marginal Land ROI
- **Expression**:
  $$\Delta P = P_{\text{with\_land}} - P_{\text{without\_land}}$$
  $$\text{Expected Profit} = \Delta P - \text{Land Price}$$
  $$\text{ROI} = \frac{\text{Expected Profit}}{\max(1, \text{Land Price})}$$
- **Location**: [expansion_planner.py:L306-L309](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py#L306-L309)
- **Description**: Compares optimal crop allocation profit on $(N_{\text{current}} + 25)$ tiles against $N_{\text{current}}$ tiles over remaining days $(29 - \text{day})$.

### `FORM-LAND-02`: Adjusted Land ROI
- **Expression**:
  $$\text{ROI}_{\text{adj}} = \text{ROI} \times \text{opportunity\_window\_factor}(Q, \text{day})$$
- **Location**: [expansion_planner.py:L512](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py#L512)
- **Description**: Multiplies ROI by opportunity window factor (1.0 for Day $\le 25$; 0.0 for Day $> 25$).

### `FORM-LAND-03`: Land Treasury Requirement Gate
- **Expression**:
  $$\text{Total Required} = \text{Land Price} + \text{Mandatory Labor} + \text{Survival Feed} + \text{Seed Tranche} + \text{Reserve}$$
  $$\text{Shortfall} = \text{Total Required} - \text{Money}$$
- **Location**: [expansion_planner.py:L503-L546](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py#L503-L546)
- **Description**: Non-negotiable treasury safety check. Purchase approved if $\text{Money} \ge \text{Total Required}$ and $\text{ROI}_{\text{adj}} > 0$.

### `FORM-SLOT-01`: OrderBuilder Hour 0 Hire Allocation
- **Expression**:
  $$\text{non\_hire\_needed} = \sum [1 \text{ for item in kept if item} \in (\text{"wheat"}, \text{"land"}, \text{"seed"})]$$
  $$\text{max\_hire\_slots} = \max(\text{MIN\_HANDS\_BASE}, \text{slots} - \text{non\_hire\_needed})$$
- **Location**: [order_builder.py:L245-L248](file:///d:/website%20project/kaggri%20ox/submission/market/order_builder.py#L245-L248)
- **Description**: Guarantees that kept non-hire orders (such as `BUY_LAND` and seeds) are never starved by 10 HIRE orders. Remaining hires are deferred to Hour 1.

### `FORM-CROP-01`: Farm-Wide Committed Crop Accounting
- **Expression**:
  $$\text{Committed}(C) = \text{LiveTiles}(C) + \text{PlannedToday}(C) + 1_{\text{candidate}}$$
- **Location**: [macro_planner.py:L142-L170](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L142-L170)
- **Description**: Accurately accounts for live field tiles, queued daily plantings, and the candidate tile to evaluate self-supply glut.

### `FORM-CROP-02`: Portfolio-Aware Marginal Crop Score
- **Expression**:
  $$I_{\text{eff}} = I_{\text{market}} + (\text{Committed}(C) \times \text{YieldPerTile} \times \text{DiversificationFactor}) + \text{OpponentAdjustment}$$
  $$P_{\text{exp}} = \text{market\_price}(C, I_{\text{eff}})$$
  $$\text{Marginal Score} = \frac{\text{YieldPerTile} \times P_{\text{exp}} - \text{SeedCost} - \text{FertCost}}{\text{CycleDays}} \times \text{ShopMultiplier}$$
- **Location**: [macro_planner.py:L218-L345](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L218-L345)
- **Description**: Evaluates expected revenue against effective market price depressed by our own projected supply.

### `FORM-DRIP-01`: Drip Sell Volume Calculation
- **Expression**:
  $$P_{\text{floor}} = \max(1, \lfloor P_{\text{spot}} \times \text{keep\_frac} \rfloor)$$
  $$I_{\text{target}} = \text{inventory\_for\_price\_at\_least}(C, P_{\text{floor}})$$
  $$Q_{\text{safe}} = \max(0, \lfloor I_{\text{target}} - I_{\text{current}} \rfloor)$$
  $$Q_{\text{sell}} = \min(Q_{\text{safe}}, \text{ShedStock})$$
- **Location**: [market_brain.py:L200-L240](file:///d:/website%20project/kaggri%20ox/submission/market/market_brain.py#L200-L240)
- **Description**: Limits sell volume per window so the marginal sale unit does not depress the realized spot price below `keep_frac` (85%–97%).

### `FORM-EXEC-01`: Clustered Spatial Dispatch Scoring
- **Expression**:
  $$\text{Score} = \text{TaskPriority} - (\text{ManhattanDist} \times C6\_TRAVEL\_WEIGHT) + \text{ClusterBonus}$$
  $$\text{where ClusterBonus} = C6\_CLUSTER\_BONUS \times 2 \text{ if dist}=0 \text{ else } C6\_CLUSTER\_BONUS \text{ if dist} \le 1 \text{ else } 0$$
- **Location**: [task_scheduler.py:L470-L510](file:///d:/website%20project/kaggri%20ox/submission/execution/task_scheduler.py#L470-L510)
- **Description**: Prevents worker travel thrashing by awarding proximity bonuses to adjacent tasks.

---

## 4. Static Policy Rules & System Constraints (`RULE-*`)

| Rule ID | Constant / Parameter | Value | Location | Description |
|---|---|---|---|---|
| `RULE-LAND-01` | `QUADRANT_UNLOCK_DAYS` | `{2: 3, 3: 9}` | [config.py:L207](file:///d:/website%20project/kaggri%20ox/submission/config.py#L207) | Earliest permitted days to evaluate NE (Q2) and SW (Q3). |
| `RULE-LAND-02` | `QUADRANT_HARD_BLOCK` | `{4}` | [config.py:L218](file:///d:/website%20project/kaggri%20ox/submission/config.py#L218) | Quadrant 4 (SE) is permanently hard-blocked; farming capped at 75 tiles. |
| `RULE-LAND-03` | `LAND_PRICES` | `[1000, 2000]` | [config.py:L60](file:///d:/website%20project/kaggri%20ox/submission/config.py#L60) | Cost to unlock 2nd quadrant (\$1,000) and 3rd quadrant (\$2,000). |
| `RULE-LAND-04` | `LAND_ROI_THRESHOLD` | `1.5` | [config.py:L124](file:///d:/website%20project/kaggri%20ox/submission/config.py#L124) | Baseline lifetime profit-to-cost hurdle ratio. |
| `RULE-LAND-05` | `LAND_BUY_LAST_DAY` | `20` | [config.py:L125](file:///d:/website%20project/kaggri%20ox/submission/config.py#L125) | Absolute latest day to buy land; purchases after Day 20 cannot amortize. |
| `RULE-HIRE-01` | `DAY_TO_HANDS` | `{0:4, 6:8, 9:8, 10:10, 11:12, 30:0}` | [config.py:L181](file:///d:/website%20project/kaggri%20ox/submission/config.py#L181) | Leader-calibrated fixed hiring schedule. Never overridden by cash. |
| `RULE-CROP-01` | `CROP_TILE_CAPS` | `WHEAT: 99, CARROT: 16, TOMATO: 16, STRAWBERRY: 20, MELON: 12` | [config.py:L129](file:///d:/website%20project/kaggri%20ox/submission/config.py#L129) | Farm-wide portfolio safety caps preventing monoculture over-allocation. |
| `RULE-CROP-02` | `STRAWBERRY_PLANT_DEADLINE` | `13` | [config.py:L225](file:///d:/website%20project/kaggri%20ox/submission/config.py#L225) | Final valid day to plant strawberries for full 3-harvest lifecycle. |
| `RULE-CROP-03` | `MELON_PLANT_DEADLINE` | `17` (fert), `19` (unfert) | [config.py:L103](file:///d:/website%20project/kaggri%20ox/submission/config.py#L103) | Last day to plant melons to mature before Day 30. |
| `RULE-CROP-04` | `get_sw_seed_targets` | D9–24: `WHEAT: 15`; D25–27: `CARROT: 15` | [config.py:L278](file:///d:/website%20project/kaggri%20ox/submission/config.py#L278) | Rule P5 SW Whitelist: strictly Wheat or late Carrot. |
| `RULE-ANIM-01` | `C4_LIVESTOCK_CUTOFF_DAY` | `12` | [config.py:L304](file:///d:/website%20project/kaggri%20ox/submission/config.py#L304) | Absolute cutoff for purchasing livestock or building new pastures. |
| `RULE-ANIM-02` | `HERD_CAP` / `SHEEP_CAP` / `COW_CAP` | `20 / 12 / 19` | [animal_planner.py:L16](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L16) | Town drainage capacity limits for wool, milk, and daily fertilizer. |
| `RULE-ANIM-03` | `FEED_WHEAT_BUFFER_DAYS` | `4` | [config.py:L96](file:///d:/website%20project/kaggri%20ox/submission/config.py#L96) | Emergency buffer days of wheat required per animal to bridge crop cycles. |
| `RULE-MKT-01` | `SELL_WINDOWS` | `[1, 5, 9, 13, 17, 21]` | [config.py:L85](file:///d:/website%20project/kaggri%20ox/submission/config.py#L85) | Post-town-drain trading hours ($t \equiv 1 \pmod 4$) quoting boosted prices. |
| `RULE-MKT-02` | `SHED_SOFT_CAP` / `RESUME` | `65 / 55` | [config.py:L155](file:///d:/website%20project/kaggri%20ox/submission/config.py#L155) | Emergency inventory liquidation triggers overriding normal trading hours. |
| `RULE-MKT-03` | `MELON_SEASON_SALE_CAP` | `150` | [config.py:L157](file:///d:/website%20project/kaggri%20ox/submission/config.py#L157) | Cumulative melon sales limit to avoid steep quadratic market price penalty. |
| `RULE-EXEC-01` | `PRIORITY_URGENT_SURVIVAL` | `100` | [config.py:L63](file:///d:/website%20project/kaggri%20ox/submission/config.py#L63) | Rescue feed for starving animals and emergency watering for dying plants. |
| `RULE-EXEC-02` | `C2_MAX_SPILLOVER_DIST` | `12` | [config.py:L107](file:///d:/website%20project/kaggri%20ox/submission/config.py#L107) | Maximum Manhattan distance a worker may travel across quadrant boundaries. |

---

## 5. Potential Issues Discovered (Integrity Audit)

1. **Unreachable Code in `expansion_planner.py:L471`**:
   The check `if next_quadrant == 3 and current_day > 13: return False, "sw_window_closed_after_day_13"` is redundant when SW is purchased on Day 10–11, but acts as a fatal dead-end if cash is delayed past Day 13 even if alternative crops (Tomatoes/Carrots) still exhibit strong positive ROI (+8.50).
2. **`main._build_opp_advice` Fallback Telemetry Leakage Risk**:
   If an exception occurs during opponent modeling, `_OPPONENT_MODEL_DIAGNOSTICS` records the exception and returns an empty advice object. This safely protects execution but suppresses diagnostic error logging in Kaggle standard output unless `DEBUG` is active.
3. **Double Call to `get_animal_targets` in `config.py` vs `macro_planner.py`**:
   `config.py:L306` provides a wrapper `get_animal_targets()` that delegates to `strategy.animal_planner`, while `macro_planner.py` directly imports `from strategy.animal_planner import get_animal_targets`. Both share identical signatures and defaults, creating no divergence but slight semantic duplication.
