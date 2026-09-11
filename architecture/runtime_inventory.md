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

### `ARCH-CORE-01`: Central Configuration & Policy Constants
- **File / Module**: [submission/config.py](file:///d:/website%20project/kaggri%20ox/submission/config.py)
- **Symbol**: Global engine constants (`LAND_PRICES`, `QUADRANT_UNLOCK_DAYS`, `QUADRANT_HARD_BLOCK`, `DAY_TO_HANDS`, `CROP_TILE_CAPS`, `C4_LIVESTOCK_CUTOFF_DAY`, `FEED_WHEAT_BUFFER_DAYS`, `SELL_WINDOWS`, `SHED_SOFT_CAP`, `SHED_RESUME_CAP`, `MELON_SEASON_SALE_CAP`, `C6_PRIORITY_BAND`, `C6_TRAVEL_WEIGHT`), `get_target_hands()`, `get_sw_seed_targets()`.
- **Purpose**: Master configuration module establishing deterministic game parameters, static thresholds, spatial quadrant limits, hiring targets, priority tiers, and whitelist rules across all subsystems.
- **Inputs**: Static python configuration.
- **Outputs**: Constant definitions, threshold parameters, schedule mappings.
- **Status**: **ACTIVE CORE CONFIGURATION**.

---

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
- **Downstream Systems Affected**: Opponent model, strategic crop scoring, land ROI valuation.

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
  - Opponent global shed pressure: `shed_pressure = min(1.0, sum(estimated_shed.values()) / 100.0)` (`FORM-OPP-01`)
  - Multi-signal sell probability: `P_sell_score = 0.35 * shed_stock_score + 0.25 * imminent_harvest_score + 0.20 * movement_score + 0.15 * pressure_score + 0.05 * timing_score` (`FORM-OPP-02`)
- **Static Constants Used**: `SHED_CAPACITY = 100`, `ANIMALS`, `CROPS`.
- **Fallback Behavior**: Wrapped in broad try/except in `_build_opp_advice`; records diagnostics in `_OPPONENT_MODEL_DIAGNOSTICS` and returns empty advice on failure.
- **Downstream Systems Affected**: Tactical opponent advice, crop scoring supply penalties, rush selling, hold delays.

---

### `ARCH-STRAT-01`: Price Forecasting Engine
- **File / Module**: [submission/strategy/price_forecast.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/price_forecast.py)
- **Symbol**: `PriceForecast`
- **Purpose**: Decision-grade query interface over the exhaustive $8^8$ ($16,777,216$ paths) shop-sequence enumeration reference pre-calculated in `baked_price_table.py` (not a random Monte Carlo sample).
- **Inputs**: Product, day, price thresholds, quantiles.
- **Outputs**: $E[P \mid \text{day}]$, tail probabilities $P(P > \text{thresh} \mid \text{day})$, floor probabilities $P(P = \$1 \mid \text{day})$, quantiles.
- **Calls**: Queries `baked_price_table.PRICE_TABLE`.
- **Called By**: `MacroPlanner` (crop scoring), `ExpansionPlanner` (land ROI valuation), `OpponentAdvisor` (tactical price thresholds). *(Note: Injected into `MarketBrain.__init__` and `EndgameLiquidator`, but runtime `sell_orders()` does not query `PriceForecast` and `should_liquidate_now()` is dormant/unreached).*
- **Lookup vs Interpolation**:
  - `expected_price(prod, day)`, `std_price(prod, day)`, and `prob_floor(prod, day)` are **direct $O(1)$ table lookups**.
  - `prob_above(prod, day, thresh)` and `quantile(prod, day, q)` use **piecewise linear interpolation** across baked price anchors and quantile knots (`FORM-FC-01`).
- **Static Constants Used**: `QUANTILE_LEVELS`, `TABLE_VERSION = 1`.
- **Downstream Systems Affected**: Crop marginal profit ranking (MacroPlanner), land valuation ROI (ExpansionPlanner), tactical opponent counter-picking (OpponentAdvisor). Live sell execution (MarketBrain / EndgameLiquidator) does not query PriceForecast.

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
- **Symbol**: `MacroPlanner`, `MacroPlan`, `sw_plant_decision()`
- **Purpose**: Daily high-level strategic governor. Allocates land between crops, pastures, and coops; evaluates land purchase viability; schedules dynamic animal acquisition; balances feed wheat buffering; ranks candidate crop tiles via portfolio-wide marginal profit modeling; partitions SW soil tiles for dedicated Wheat/Carrot allocation; outputs queues and intents.
- **Inputs**: `ctx`, `boosts`, `opp_advice`.
- **Outputs**: `MacroPlan` object consumed by `TaskScheduler` (`plant_queue`, `build_queue`, `place_queue`, `feeding_enabled`, `watering_enabled`) and `OrderBuilder` (`intents`).
- **Calls**: `get_target_hands()`, `get_animal_targets()`, `compute_land_roi()`, `opportunity_window_factor()`, `compute_land_urgency()`, `should_buy_land()`, `_crop_score()`, `sw_plant_decision()`, `get_committed_crop_counts()`, `get_strawberry_cap()`, `get_sw_tile_breakdown()`.
- **Called By**: `main._agent_decision()`.
- **Dynamic Formulas Used**: 
  - Farm-wide committed crop accounting (`FORM-CROP-01`)
  - Multi-harvest portfolio-aware crop score (`FORM-CROP-02`)
  - Town-only implied cumulative drain via forecast inversion (`FORM-CROP-DRAIN-01`)
  - Effective market inventory accounting (`FORM-CROP-INVENTORY-01`)
  - Sustainable herd capacity from wheat projection (`FORM-HERD-01`)
  - Operational wheat buffer purchase need (`FORM-FEED-01`)
  - Effective cash reservation for animal purchasing (`FORM-ANIM-BUDGET-01`)
  - Dedicated SW soil Wheat tile allocation (`FORM-SW-WHEAT-01`)
  - Travel-aware workload estimation (`FORM-LOAD-01`, uncoupled diagnostic)
- **Static Constants Used**: `CROP_TILE_CAPS`, `CROP_DIVERSIFICATION_FACTOR`, `FEED_WHEAT_BUFFER_DAYS`, `SW_PASTURE_TILES`, `SW_SOIL_TILES`, `PORT_SW`.
- **Downstream Systems Affected**: `TaskScheduler` work queue, `OrderBuilder` purchase commitments.

---

### `ARCH-STRAT-04`: Expansion & Land Planner
- **File / Module**: [submission/strategy/expansion_planner.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py)
- **Symbol**: `compute_land_roi()`, `opportunity_window_factor()`, `compute_land_urgency()`, `should_buy_land()`, `expansion_seed_targets()`
- **Purpose**: Economics-driven quadrant acquisition governor. Computes incremental profit of adding 25 tiles against land price; evaluates seasonal opportunity windows; enforces non-negotiable treasury safety gates.
- **Inputs**: `next_quadrant`, `day`, `money`, `farm`, `forecast`, commitments, reserve.
- **Outputs**: `(buy_land: bool, reason: str, diagnostics: dict)`.
- **Calls**: `_allocate_portfolio_profit()`, `_estimate_crop_revenue_per_tile()`, `evaluate_sw_timing()`.
- **Called By**: `MacroPlanner.build()`.
- **Dynamic Formulas Used**:
  - Incremental Marginal ROI: $\text{ROI} = \frac{(P_{\text{with}} - P_{\text{without}}) - \text{Price}}{\text{Price}}$ (`FORM-LAND-01`)
  - Adjusted ROI: $\text{ROI}_{\text{adj}} = \text{ROI} \times \text{OW\_Factor}$ (`FORM-LAND-02`)
  - Treasury Safety Requirement: $\text{Req} = \text{Price} + \text{hire\_cost} + \text{feed\_cost} + \text{animal\_cost} + \text{seed\_cost} + \text{reserve}$ (`FORM-LAND-03`)
- **Model-Policy Mismatch**:
  - `compute_land_roi()` models all 25 tiles as crop-capable ground planted with high-margin crops (up to 20 Strawberries, Melons, Tomatoes).
  - Runtime SW geometry partitions the 25 tiles into **15 soil tiles** (`SW_SOIL_TILES`), **9 pasture tiles** (`SW_PASTURE_TILES`), and **1 shed portal tile** (`PORT_SW`).
  - Runtime SW policy strictly whitelists only Wheat and Carrots on SW soil tiles.
  - The planning ROI is structurally optimistic relative to actual SW execution.
- **Static Constants Used**: `QUADRANT_UNLOCK_DAYS`, `QUADRANT_MONEY_THRESHOLDS`, `QUADRANT_HARD_BLOCK = {4}`, `LAND_PRICES = [1000, 2000]`, `current_day > 13` (active SW hard blocker).
- **Dormant Constants**: `LAND_ROI_THRESHOLD = 1.5` (`RULE-LAND-04`, unused; code checks `adjusted_roi > 0`), `LAND_BUY_LAST_DAY = 20` (`RULE-LAND-05`, unused).
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
- **Purpose**: Days 28–29 liquidation manager. Delegates directly to `MarketBrain.sell_orders()` in its aggressive endgame mode to ensure shed inventory is monetized before Day 30 scoring cutoff.
- **Inputs**: `ctx`, `opp_advice`, `max_slots`.
- **Outputs**: `(orders, details)`.
- **Calls**: `MarketBrain.sell_orders()`.
- **Called By**: `main._agent_decision()`.
- **Dormant Helpers**: `should_liquidate_now()` and `harvest_priorities()` are implemented in the class but **never called** in runtime execution.
- **Static Constants Used**: `ENDGAME_START_DAY = 28`, `MAX_MARKET_ORDERS = 10`.
- **Dormant Constants**: `FINAL_DUMP_DAYS = {28: 0.75, 29: 0.25}` (`RULE-MKT-04`, imported but unreferenced).
- **Downstream Systems Affected**: Final turn market sell orders.

---

### `ARCH-STRAT-07`: Town Shop Demand Adapter
- **File / Module**: [submission/strategy/shop_adapter.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/shop_adapter.py)
- **Symbol**: `demand_boosts(known_shops)`
- **Purpose**: Translates observed unlocked town shops into crop demand multipliers for `MacroPlanner._crop_score()`.
- **Inputs**: List of unlocked shop strings from `obs["town"]["unlocked_shops"]`.
- **Outputs**: Dictionary `{crop: boost_float}`.
- **Called By**: `main._agent_decision()`.
- **Static Constants Used**: `SHOP_BOOSTS = {"BAKERY": {"WHEAT": 0.3}, "JUICE_BAR": {"STRAWBERRY": 0.25, "CARROT": 0.25}, ...}`.
- **Downstream Systems Affected**: `MacroPlanner._crop_score()`.

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

### `ARCH-MKT-02`: Sell-Side Market Brain (Sell Windows, Shed Pressure, Melon Floor Hold/Drip, Non-Melon Phase Batches)
- **File / Module**: [submission/market/market_brain.py](file:///d:/website%20project/kaggri%20ox/submission/market/market_brain.py)
- **Symbol**: `MarketBrain`
- **Purpose**: Decides which products to sell, in what batch sizes, and at what hours. Implements 3-tier urgency shedding, Melon price floor holds, Melon-specific analytical drip sizing, and emergency liquidation priority.
- **Inputs**: `ctx`, `opp_advice`, `max_slots`.
- **Outputs**: `(sell_orders, details)` where each order is `["SELL", product, qty]`.
- **Calls**: `market_price()`, `inventory_for_price_at_least()`, `total_revenue_estimate()`, `_get_season_units_sold()`.
- **Called By**: `main._agent_decision()`, `EndgameLiquidator`.
- **Dynamic Formulas Used**: 
  - Melon analytical drip volume calculation: `_drip_budget()` (`FORM-DRIP-01`, active strictly for `MELON`).
- **Dormant Logic**:
  - `MarketBrain` receives `PriceForecast` through `__init__`, but `sell_orders()` does not query it (`PriceForecast` carry edge is dormant). `_reason()` receives precomputed `carry` parameter and compares `carry <= MIN_CARRY_GAIN` (`FORM-CARRY-01`, Status: **DORMANT DESIGN / HISTORICAL POLICY**).
- **Floor Behavior**:
  - For `MELON`: If `spot <= 1` and not in floor exception (`endgame or urgency == 2`), Melon is held (`stock = 0`).
  - For non-Melon commodities: If `spot <= 1`, candidate `urgency_score` is raised to `0.95` to prioritize selling in the candidate queue. It does **not** activate emergency mode (`pressure` requires `shed_total >= 65`) and does **not** bypass the sell-window check (`hour in SELL_HOUR_SET`).
- **Shed Pressure Semantics**:
  - Recomputed independently each turn: `pressure = shed_total >= 65`. When active, urgency-1 selling attempts to reduce shed inventory toward 55 during that turn (`to_shed = shed_total - 55`). No stored hysteresis latch.
- **Static Constants Used**: 
  - `SELL_WINDOWS = [1, 5, 9, 13, 17, 21]`, `SHED_SOFT_CAP = 65`, `SHED_RESUME_CAP = 55`, `MELON_SEASON_SALE_CAP = 150`, `DRIP_PRICE_KEEP_FRAC["MELON"] = 0.90`.
- **Batch Sizing**: Non-Melon products sell in phase-determined batch targets:
  - $\text{batch\_target} = 15 \text{ (Day } \le 5), \quad 7 \text{ (Day 6–8)}, \quad 4 \text{ (Day } \ge 9)$.
  - Normal: $\min(\text{stock}, \text{batch\_target})$.
  - Urgency 1: $\min(\text{stock}, \max(\text{batch\_target}, 10), \text{to\_shed})$.
  - Urgency 2 / Endgame / $\text{days\_left} \le 2$ / Fertilizer: $\min(\text{stock}, 20)$.
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
  - OrderBuilder discretionary budget: `FORM-BUDGET-01`
- **Static Constants Used**: `MAX_MARKET_ORDERS = 10`, `MIN_HANDS_BASE = 4`, `MONEY_RESERVE_DEFAULT = 300`, `TIER_HIRES = 0`, `TIER_FEED_WHEAT = 1`, `TIER_LAND = 2`, `TIER_SEEDS = 3`, `TIER_ANIMALS = 4`.
- **Downstream Systems Affected**: Dispatched market purchase orders, farm treasury, worker roster, land unlock state.

---

### `ARCH-EXEC-01`: Task Scheduler & Dispatcher
- **File / Module**: [submission/execution/task_scheduler.py](file:///d:/website%20project/kaggri%20ox/submission/execution/task_scheduler.py)
- **Symbol**: `build_tasks()`, `assign_tasks()`, `get_daily_log()`, `reset_daily_log()`, `emit()`
- **Purpose**: Generates prioritized per-tile tasks (survival, harvest, feed staging, production feed, crop fertilization, care, planting, pasture building) and solves the multi-unit spatial assignment problem. Implements persistent sticky missions, Manhattan/BFS movement, C2 zonal boundaries, and C6 clustered dispatch.
- **Inputs**: `ctx`, `plan` (`MacroPlan`).
- **Outputs**: Action assignment dictionary `{"actions": {unit_id: [action]}, "assignment": {...}}`.
- **Calls**: `bfs_first_step()`, `crop_age()`, `in_bonus_window()`, `needs_water_today()`, `turns_until_decay()`, `emit()`.
- **Called By**: `main._agent_decision()`, `_survival_fallback_from_ctx()`.
- **Persistent State Read/Written**: `_daily_log`, `_daily_accum`, `_ACTIVE_MISSIONS` (`STATE-STICKY`), `_BLOCKED_TASK_TRACKER` (`STATE-BLOCK`), `_SW_SEASONAL_TRACKER` (`STATE-SW-TRACK`).
- **Dynamic Formulas Used**:
  - Clustered dispatch score: `effective_score = -prio + spill_penalty + C6_TRAVEL_WEIGHT * (d - cluster_bonus)` (`FORM-EXEC-01`)
  - Tile Manhattan Distance: $|x_1 - x_2| + |y_1 - y_2|$ (`FORM-DIST-01`)
- **Static Constants Used**: Priority levels 100 down to 20 (`RULE-EXEC-01`), `C2_MAX_SPILLOVER_DIST = 12`, `C6_CLUSTER_RADIUS = 1`, `C6_CLUSTER_BONUS = 2`, `C6_TRAVEL_WEIGHT = 3`, `C6_PRIORITY_BAND = 20`.
- **Downstream Systems Affected**: Farmer action, hired hands actions, daily work completion, crop survival.

---

### `ARCH-EXEC-02`: Pathfinding & Navigation
- **File / Module**: [submission/execution/pathfinding.py](file:///d:/website%20project/kaggri%20ox/submission/execution/pathfinding.py)
- **Symbol**: `bfs_first_step(start, target, board_size)`
- **Purpose**: Computes the optimal single-step cardinal move (`"NORTH"`, `"SOUTH"`, `"EAST"`, `"WEST"`) to reach target $(x, y)$ on the 10x10 torus-free grid using Breadth-First Search.
- **Inputs**: Start coordinate tuple, target coordinate tuple, board size integer.
- **Outputs**: Direction string (`"NORTH"`, `"SOUTH"`, `"EAST"`, `"WEST"`) or `None` if already at target.
- **Downstream Systems Affected**: Unit movement actions.

---

### `ARCH-EXEC-03`: Unit Controller Helpers
- **File / Module**: [submission/execution/unit_controller.py](file:///d:/website%20project/kaggri%20ox/submission/execution/unit_controller.py)
- **Symbol**: `emit_action()`, `step_toward()`, `reroute_to_shed_access()`
- **Purpose**: Historical unit action formatting helpers.
- **Status**: **DORMANT / HELPER** (Exported in `execution/__init__.py` but superseded in live execution by `task_scheduler.emit()` and `pathfinding.bfs_first_step()`).

---

### `ARCH-DATA-01`: Baked Crop Economics Data
- **File / Module**: [submission/strategy/baked_economics.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/baked_economics.py)
- **Symbol**: `CROP_ECONOMICS`, `CROP_CYCLE_LEN`
- **Purpose**: Precalculated cycle lengths, fertilizer applications, and yield parameters for crops.
- **Status**: **ACTIVE DATA ARTIFACT**.

---

### `ARCH-DATA-02`: Baked Exhaustive Price Distribution Table
- **File / Module**: [submission/strategy/baked_price_table.py](file:///d:/website%20project/kaggri%20ox/submission/strategy/baked_price_table.py)
- **Symbol**: `PRICE_TABLE`
- **Purpose**: Exhaustive $8^8$ shop-sequence enumeration statistics table containing population-exact daily means, standard deviations, floor probabilities, and quantiles.
- **Status**: **ACTIVE DATA ARTIFACT**.

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

### 3. Dynamic Decision Formulas (`FORM-*`)

### `FORM-LAND-01`: Incremental Marginal Land ROI
- **Expression**:
  $$\Delta P = P_{\text{with\_land}} - P_{\text{without\_land}}$$
  $$\text{Expected Profit} = \Delta P - \text{Land Price}$$
  $$\text{ROI} = \frac{\text{Expected Profit}}{\max(1, \text{Land Price})}$$
- **Location**: [expansion_planner.py:L306-L309](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py#L306-L309)
- **Status**: **ACTIVE** (Model-Policy Mismatch: evaluates 25 crop tiles with high-margin crops; SW execution only provides 15 crop tiles restricted to Wheat/Carrots).

### `FORM-LAND-02`: Adjusted Land ROI
- **Expression**:
  $$\text{ROI}_{\text{adj}} = \text{ROI} \times \text{opportunity\_window\_factor}(Q, \text{day})$$
- **Location**: [expansion_planner.py:L512](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py#L512)
- **Status**: **ACTIVE** (Evaluates 1.0 for Day $\le 25$; 0.0 for Day $> 25$).

### `FORM-LAND-03`: Land Treasury Requirement Gate
- **Expression**:
  $$\text{Total Required} = \text{Land Price} + \text{hire\_cost} + \text{feed\_cost} + \text{animal\_cost} + \text{seed\_cost} + \text{reserve}$$
  $$\text{Shortfall} = \text{Total Required} - \text{Money}$$
- **Location**: [expansion_planner.py:L500-L503](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py#L500-L503)
- **Status**: **ACTIVE** (Seed cost is dynamically evaluated from `expansion_seed_targets` minus owned seeds; animal cost is included).

### `FORM-SLOT-01`: OrderBuilder Hour 0 Hire Allocation
- **Expression**:
  $$\text{non\_hire\_needed} = \sum [1 \text{ for item in kept if item} \in (\text{"wheat"}, \text{"land"}, \text{"seed"})]$$
  $$\text{max\_hire\_slots} = \max(\text{MIN\_HANDS\_BASE}, \text{slots} - \text{non\_hire\_needed})$$
- **Location**: [order_builder.py:L247-L248](file:///d:/website%20project/kaggri%20ox/submission/market/order_builder.py#L247-L248)
- **Status**: **ACTIVE** (Protects non-hire orders from slot starvation; defers remaining hires to Hour 1).

### `FORM-CROP-01`: Farm-Wide Committed Crop Accounting
- **Expression**:
  `get_committed_crop_counts(farm, planned)` returns live un-decayed tiles plus supplied planned counts. Within the planting loop, `committed_counts` is mutated after every accepted crop. Candidate evaluation passes:
  $$\text{own\_for\_this} = \text{current\_committed\_count} + 1$$
- **Location**: [macro_planner.py:L236-L254](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L236-L254), [macro_planner.py:L705-L770](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L705-L770)
- **Status**: **ACTIVE** (Evaluates live un-decayed tiles, iteratively tracks queued plantings today, and tests the candidate tile increment).

### `FORM-CROP-02`: Multi-Harvest Portfolio-Aware Crop Marginal Score
- **Expression**:
  $$\text{DiversificationFactor} = \text{CROP\_DIVERSIFICATION\_FACTOR.get}(C, 0.60)$$
  $$\text{EffectiveOwnTiles} = \text{CommittedCandidateTiles} \times \text{DiversificationFactor} \quad (\text{if } \text{CommittedCandidateTiles} > 0 \text{ else } 0)$$
  $$\text{CumOwnProduction} = \text{\_cum\_own\_production}(C, \text{EffectiveOwnTiles}, \text{harvest\_index}, \text{feed\_wheat\_per\_day}, h, \text{plant\_day}, n_{\text{animals}})$$
  $$\text{and for Wheat: } \text{AvgHerd} = \text{\_project\_avg\_herd}(n_{\text{animals}}, \text{plant\_day}), \quad \text{DaysElapsed} = \max(0, h - \text{plant\_day})$$
  $$\text{CumOwnWheat} = \max(0.0, \text{RawOwnWheat} - \text{AvgHerd} \times \text{DaysElapsed})$$
  $$P_h = \text{market\_price}(C, I_{\text{eff}}(C, h))$$
  $$\text{ShopFactor} = \min(1.0 + \text{SHOP\_BOOST\_WEIGHT} \times \text{boosts}[C], \text{BOOST\_CAP})$$
  $$\text{CounterFactor} = 1.15 \text{ if } C \in \text{opp\_advice.counter\_pick else } 1.0$$
  $$\text{Revenue} = \sum_{h \in \text{hdays}} (\text{CycleYield} \times P_h \times \text{ShopFactor} \times \text{CounterFactor})$$
  $$\text{LifecycleCost} = \text{cycles\_for\_cost} \times (\text{seed\_cost} + \text{fert\_applications} \times 25.0)$$
  $$\text{Net} = \text{Revenue} - \text{LifecycleCost}$$
  $$\text{Score}(C) = \frac{\text{Net}}{\max(1, 30 - \text{day})}$$
  $$\text{where } I_{\text{eff}}(C, h) = \text{MARKET\_I0} - \text{CumTownDrain}(C, h) + \text{CumOwnProduction}(C, h) + \text{OppSupplyAdjustment}(C)$$
- **Location**: [macro_planner.py:L257-L310](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L257-L310)
- **Status**: **ACTIVE** (Scales committed tiles by heuristic `CROP_DIVERSIFICATION_FACTOR`; loops through every harvest day; applies shop/counter boosts to revenue before costs; feed wheat consumption deducted internally via projected average herd).

### `FORM-CROP-DRAIN-01`: Town-Only Implied Cumulative Drain (Forecast Inversion)
- **Expression**:
  $$P_{\text{expected}} = \text{PriceForecast.expected\_price}(C, h)$$
  $$I_{\text{implied}} = \text{inventory\_at\_price}(C, P_{\text{expected}})$$
  $$\text{CumTownDrain} = \max(0.0, \text{MARKET\_I0} - I_{\text{implied}})$$
- **Location**: [macro_planner.py:L182-L201](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L182-L201)
- **Status**: **ACTIVE** (The source implementation uses this deterministic point-estimate approximation for $O(1)$ planning efficiency. The source comment asserts that its monotonic error preserves relative crop ROI ranking, but this is not formally guaranteed for nonlinear pricing functions and should be treated as an implementation assumption rather than a proven property).

### `FORM-CROP-INVENTORY-01`: Effective Market Inventory Accounting
- **Expression**:
  $$I_{\text{eff}}(C, h) = \text{MARKET\_I0} - \text{CumTownDrain}(C, h) + \text{CumOwnProduction}(C, h) + \text{OppSupplyAdjustment}(C)$$
- **Location**: [macro_planner.py:L296](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L296)
- **Status**: **ACTIVE** (Starts strictly from `MARKET_I0 = 10000`, subtracting cumulative implied town drain and adding own production and opponent supply adjustment).

### `FORM-DRIP-01`: Melon Analytical Drip Sizing
- **Expression**:
  $$P_{\text{keep}} = \max(2, \lfloor P_{\text{spot}} \times \text{keep\_frac} \rfloor) \quad (\text{keep\_frac} = 0.90)$$
  $$I_{\text{target}} = \text{inventory\_for\_price\_at\_least}(\text{MELON}, P_{\text{keep}})$$
  $$Q_{\text{turn\_budget}} = \max(0, \lfloor I_{\text{target}} - I_{\text{market}} \rfloor)$$
- **Location**: [market_brain.py:L337-L341](file:///d:/website%20project/kaggri%20ox/submission/market/market_brain.py#L337-L341)
- **Status**: **ACTIVE (MELON ONLY)** (Non-Melon commodities bypass drip sizing and sell in phase-indexed batch targets).

### `FORM-MATH-01`: Engine Market Pricing Curve
- **Expression**:
  $$\text{Scarcity: } \text{price} = \text{base} + \text{amp}_{\text{below}} \times \text{shape}(bf, I_0 - \text{inv}, T)$$
  $$\text{Glut: } \text{price} = \text{base} - \text{amp}_{\text{above}} \times \text{shape}(af, \text{inv} - I_0, T)$$
  $$\text{Quote: } \max(P_{\text{floor}}(1), \text{int}(\text{round}(\text{price})))$$
- **Location**: [price_math.py:L34-L48](file:///d:/website%20project/kaggri%20ox/submission/market/price_math.py#L34-L48)
- **Status**: **ACTIVE**.

### `FORM-DIST-01`: Spatial Manhattan Distance
- **Expression**:
  $$\text{dist}((x_1, y_1), (x_2, y_2)) = |x_1 - x_2| + |y_1 - y_2|$$
- **Location**: [pathfinding.py](file:///d:/website%20project/kaggri%20ox/submission/execution/pathfinding.py), [task_scheduler.py:L996](file:///d:/website%20project/kaggri%20ox/submission/execution/task_scheduler.py#L996)
- **Status**: **ACTIVE** (Used in `task_scheduler.assign_tasks()`, `C2_MAX_SPILLOVER_DIST`, and dispatch scoring).

### `FORM-EXEC-01`: Clustered Spatial Dispatch Scoring (Minimization)
- **Expression**:
  $$\text{EffectiveScore} = -\text{Priority} + \text{SpillPenalty} + 3 \times (\text{Distance} - \text{ClusterBonus})$$
  $$\text{Choose candidate assignment }(u, t)\text{ with MINIMUM EffectiveScore}$$
  $$\text{where SpillPenalty} = 10 \text{ if spillover else } 0, \quad \text{ClusterBonus} = 4 \text{ if dist}=0 \text{ else } (2 \text{ if dist} \le 1 \text{ else } 0)$$
- **Location**: [task_scheduler.py:L997-L1007](file:///d:/website%20project/kaggri%20ox/submission/execution/task_scheduler.py#L997-L1007)
- **Status**: **ACTIVE** (Greedy minimization matching tasks to workers).

### `FORM-HIRE-01`: Fibonacci Incremental Hire Cost
- **Expression**:
  $$\text{HireCost}(k) = \sum_{i=0}^{k-1} \text{fib}(\text{hires\_today} + i)$$
- **Location**: [order_builder.py:L37-L49](file:///d:/website%20project/kaggri%20ox/submission/market/order_builder.py#L37-L49)
- **Status**: **ACTIVE** (One-time acquisition capital cost, not a recurring daily wage).

### `FORM-CAPACITY-01`: Theoretical Maximum Engine Capacity
- **Expression**:
  $$\text{Theoretical Engine Actions} = 24 \times (1 + \text{current\_hands})$$
- **Location**: Engine Specification / Reference
- **Status**: **THEORETICAL ENGINE CAPACITY / REFERENCE** (Upper bound on daily unit execution bandwidth).

### `FORM-PLANNING-CAPACITY-01`: Effective Planning Action Capacity
- **Expression**:
  $$\text{PlanningCapacity} = (1 + \text{current\_hands} + \text{hires}) \times \text{EFFECTIVE\_ACTIONS\_PER\_UNIT}$$
  $$\text{where local runtime defines } \text{EFFECTIVE\_ACTIONS\_PER\_UNIT} = 18 \quad (\text{shadowing config value } 12)$$
  $$\text{water\_budget\_exceeded} = (\text{estimate\_daily\_load}(\text{ctx}) + \text{len}(\text{plant\_queue})) > \text{PlanningCapacity}$$
- **Location**: [macro_planner.py:L455](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L455), [macro_planner.py:L900-L902](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L900-L902)
- **Status**: **ACTIVE CALCULATION / CURRENTLY UNCOUPLED** (`water_budget_exceeded` is written into `MacroPlan` but does not alter `DAY_TO_HANDS` or any active hiring gate).

### `FORM-LOAD-01`: Travel-Aware Workload Burden
- **Expression**:
  $$\text{Load} = \text{BaseLoad} + \text{ShedTrips} + \text{DispersionBurden} + \text{SWBurden}$$
  $$\text{where BaseLoad} = \text{unwatered} + \text{harvestable} + \text{unfed} + \text{fert} + \text{uncared} + \text{empty\_with\_seeds}$$
  $$\text{ShedTrips} = \text{shed\_animals} \times 3 + 3 \times 1_{\text{wheat}>0} + 3 \times 1_{\text{fert}>0}$$
  $$\text{Dispersion} = (\text{active\_quads} - 1) \times 4 + 4 \times 1_{\text{SW} \land \text{NE}}$$
  $$\text{SWBurden} = 6 + \min(8, \text{sw\_tiles} // 3)$$
- **Location**: [macro_planner.py:L1035-L1112](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L1035-L1112)
- **Status**: **ACTIVE CALCULATION / UNCOUPLED DIAGNOSTIC** (Calculated in `estimate_daily_load()`, but its output `water_budget_exceeded` does not govern hiring or decision gating. Function body is duplicated verbatim in `task_scheduler.py:L1305`, where it is uncalled dead code).

### `FORM-ANIM-01`: Cow Lifetime Production Profit
- **Expression**:
  $$\text{CowProfit} = 160 \times M + \text{FertNet} - 400 \quad \text{where } M = \text{FORM-ANIM-COW-YIELD-01}, \text{ FertNet} = \text{FORM-ANIM-03}$$
- **Location**: [animal_planner.py:L61-L70](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L61-L70)
- **Status**: **ACTIVE**.

### `FORM-ANIM-02`: Sheep Lifetime Production Profit
- **Expression**:
  $$\text{SheepProfit} = 200 \times W + \text{FertNet} - 500 \quad \text{where } W = \text{FORM-ANIM-SHEEP-YIELD-01}, \text{ FertNet} = \text{FORM-ANIM-03}$$
- **Location**: [animal_planner.py:L63-L75](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L63-L75)
- **Status**: **ACTIVE**.

### `FORM-ANIM-03`: Net Fertilizer Contribution
- **Expression**:
  $$\text{FertNet} = (100 - \text{FEED\_PRICE}(25)) \times (29 - \text{day})$$
- **Location**: [animal_planner.py:L9](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L9)
- **Status**: **ACTIVE**.

### `FORM-ANIM-COW-YIELD-01`: Cow Lifetime Milk Yield Units
- **Expression**:
  $$\text{Cow Milk Units} = \begin{cases} 6 + 3 \times \lfloor \frac{R - 8}{2} \rfloor & \text{if } R \ge 8 \\ 0 & \text{otherwise} \end{cases} \quad (R = \max(0, 29 - \text{day}))$$
- **Location**: [animal_planner.py:L61](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L61)
- **Status**: **ACTIVE**.

### `FORM-ANIM-SHEEP-YIELD-01`: Sheep Lifetime Wool Yield Units
- **Expression**:
  $$\text{Sheep Wool Units} = \begin{cases} 6 + 4 \times \lfloor \frac{R - 6}{3} \rfloor & \text{if } R \ge 6 \\ 0 & \text{otherwise} \end{cases} \quad (R = \max(0, 29 - \text{day}))$$
- **Location**: [animal_planner.py:L63](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L63)
- **Status**: **ACTIVE**.

### `FORM-HERD-01`: Sustainable Animal Count from Projected Wheat Capacity
- **Expression**:
  $$\text{SustainableAnimals} = \left\lfloor \frac{\text{ProjectedWheatSupply}}{\text{FeedingDaysLeft}} \right\rfloor \quad (\text{from authoritative feed capacity projection})$$
- **Location**: [macro_planner.py:L352-L425](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L352-L425), [animal_planner.py:L142-L175](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L142-L175)
- **Status**: **ACTIVE & ENFORCED** (Authoritative projected feed supply strictly couples to `get_animal_targets()` via `max_sustainable`, clamping livestock targets and exposing 5 diagnostics fields; ungrounded early-game geese exception eliminated).

### `FORM-BUDGET-01`: OrderBuilder Discretionary Purchase Budget
- **Expression**:
  $$\text{AvailableForPurchases} = \max(0.0, \text{Money} - \text{MandatoryHireBudget} - \text{Reserve})$$
  $$\text{SurvivalFeedBudget} = \text{WheatBuyable} \times \lceil P_{\text{wheat}} \times 1.10 \rceil$$
  $$\text{DiscretionaryBudget} = \max(0.0, \text{AvailableForPurchases} - \text{SurvivalFeedBudget})$$
- **Location**: [order_builder.py:L109-L119](file:///d:/website%20project/kaggri%20ox/submission/market/order_builder.py#L109-L119)
- **Status**: **ACTIVE** (Discretionary purchases — Land, Seeds, Animals — draw sequentially strictly from DiscretionaryBudget).

### `FORM-ANIM-BUDGET-01`: MacroPlanner Cash Reservation for Animal Purchasing
- **Expression**:
  $$\text{cash\_for\_animals} = \max(0.0, \text{Money} - \text{future\_hire\_cost} - \text{reserve} - \text{seed\_reserve} - \text{land\_reserve} - \text{day\_0\_seed\_reserve} - \text{ne\_fund\_reserve})$$
- **Location**: [macro_planner.py:L475-L484](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L475-L484)
- **Status**: **ACTIVE** (Protects forward hiring schedule, seed escrow, and NE/SW land purchase funds from animal over-spending).

### `FORM-FEED-01`: Operational Wheat Buffer Purchase Need with Treasury Protection
- **Expression**:
  $$\text{wheat\_buffer\_target} = \begin{cases} 5 & \text{if } (\text{day} \le 5 \lor (\text{next\_quadrant} == 2 \land \text{day} \le 8)) \land (n_{\text{animals}} > 0 \lor \text{buy\_animal}) \\ 4 & \text{otherwise (FEED\_WHEAT\_BUFFER\_DAYS)} \end{cases}$$
  $$\text{wheat\_needed} = (n_{\text{animals}} + \sum \text{buy\_animal.values()}) \times \text{wheat\_buffer\_target}$$
  $$\text{if trigger: } \text{wheat\_needed} = \max(\text{wheat\_needed}, \text{deficit})$$
  $$\text{ne\_protect} = 1000.0 \text{ if } (\text{next\_quadrant} == 2 \land 5 \le \text{day} \le 6 \land \neg \text{buy\_land}) \text{ else } 0.0$$
  $$\text{max\_wheat\_budget} = \max(0.0, \text{available\_before\_seeds} - \text{ne\_protect})$$
  $$\text{survival\_floor} = \max(0, (n_{\text{animals}} \times 2) - \text{wheat\_have}) \times 25.0$$
  $$\text{max\_wheat\_budget} = \max(\text{max\_wheat\_budget}, \min(\text{available\_before\_seeds}, \text{survival\_floor}))$$
  $$\text{BuyWheat} = \min(\text{wheat\_needed} - \text{wheat\_have}, \lfloor \text{max\_wheat\_budget} / 25 \rfloor)$$
- **Location**: [macro_planner.py:L623-L638](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L623-L638)
- **Status**: **ACTIVE** (Calculates wheat needed to sustain planned animals across buffer window, protecting NE fund when pending and prioritizing funding up to a 2-day emergency Wheat floor, subject to available capital).

### `FORM-WHEAT-01`: Buffered Feed Wheat Purchase Quote
- **Expression**:
  $$\text{Buffered Price} = \lceil P_{\text{wheat}} \times \text{WHEAT\_BUY\_PRICE\_BUFFER}(1.10) \rceil$$
- **Location**: [order_builder.py:L111](file:///d:/website%20project/kaggri%20ox/submission/market/order_builder.py#L111)
- **Status**: **ACTIVE**.

### `FORM-SW-WHEAT-01`: Dedicated SW Wheat Tile Allocation
- **Expression**:
  $$\text{feed\_need} = \text{herd\_size} \times (29 - \text{day} + 1)$$
  $$n_{\text{wheat}} = \min(\text{free\_tiles}, (\text{deficit} + 4) // 5) \quad \text{if day} \le 25 \land \text{wheat\_stock} < \text{feed\_need else } 0$$
  $$n_{\text{carrot}} = \max(0, \text{free\_tiles} - n_{\text{wheat}})$$
- **Location**: [macro_planner.py:L366-L386](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L366-L386)
- **Status**: **ACTIVE** (Runtime implementation uses effective divisor 5).

### `FORM-DRAIN-01`: StateTracker Market Ledger Net Player Sales
- **Expression**:
  $$\text{net\_player\_sales} = (I_{\text{now}} - I_{\text{prev}}) + \text{expected\_town\_consumption}$$
- **Location**: [state_tracker.py:L104](file:///d:/website%20project/kaggri%20ox/submission/state/state_tracker.py#L104)
- **Status**: **ACTIVE**.

### `FORM-DRAIN-02`: StateTracker Opponent Sales Inferred
- **Expression**:
  $$\text{opp\_sales\_inferred} += \max(0.0, \text{net\_player\_sales} - \text{our\_units\_sold\_last\_step})$$
- **Location**: [state_tracker.py:L106-L109](file:///d:/website%20project/kaggri%20ox/submission/state/state_tracker.py#L106-L109)
- **Status**: **ACTIVE**.

### `FORM-OPP-01`: Opponent Estimated Shed Pressure
- **Expression**:
  $$\text{shed\_pressure} = \min\left(1.0, \frac{\sum \text{estimated\_shed.values()}}{100.0}\right)$$
- **Location**: [opponent_model.py:L551](file:///d:/website%20project/kaggri%20ox/submission/state/opponent_model.py#L551)
- **Status**: **ACTIVE**.

### `FORM-OPP-02`: Opponent Multi-Signal Sell Probability Scoring
- **Expression**:
  $$P_{\text{sell\_score}} = 0.35 \times S_{\text{shed}} + 0.25 \times S_{\text{imminent}} + 0.20 \times S_{\text{movement}} + 0.15 \times S_{\text{pressure}} + 0.05 \times S_{\text{timing}}$$
- **Location**: [opponent_model.py:L564-L579](file:///d:/website%20project/kaggri%20ox/submission/state/opponent_model.py#L564-L579)
- **Status**: **ACTIVE**.

### `FORM-FC-01`: Price Table Continuous Query Interpolation
- **Expression**:
  $$P(P > \text{thresh}) = T_0 + \frac{\text{thresh} - G_0}{G_1 - G_0} \times (T_1 - T_0)$$
- **Location**: [price_forecast.py:L177-L192](file:///d:/website%20project/kaggri%20ox/submission/strategy/price_forecast.py#L177-L192)
- **Status**: **ACTIVE** (Used for threshold and quantile queries; mean/std/floor are direct $O(1)$ table lookups).

### `FORM-CARRY-01`: Forecast Carry Gain Evaluation
- **Expression**:
  $$\text{carry} \le \text{MIN\_CARRY\_GAIN}(0.02)$$
- **Location**: [market_brain.py:L351](file:///d:/website%20project/kaggri%20ox/submission/market/market_brain.py#L351)
- **Status**: **DORMANT DESIGN / HISTORICAL POLICY** (Evaluated inside uncalled helper `_reason()`; `sell_orders()` does not query `PriceForecast`).

---

## 4. Static Policy Rules & System Constraints (`RULE-*`)

| Rule ID | Parameter / Constant | Value | Location | Status | Description |
|---|---|---|---|:---:|---|
| `RULE-LAND-01` | `QUADRANT_UNLOCK_DAYS` | `{2: 3, 3: 9}` | [config.py:L207](file:///d:/website%20project/kaggri%20ox/submission/config.py#L207) | **ACTIVE** | Earliest permitted days to evaluate NE (Q2) and SW (Q3). |
| `RULE-LAND-02` | `QUADRANT_HARD_BLOCK` | `{4}` | [config.py:L218](file:///d:/website%20project/kaggri%20ox/submission/config.py#L218) | **ACTIVE** | Quadrant 4 (SE) is permanently hard-blocked; farm capped at 75 tiles. |
| `RULE-LAND-03` | `LAND_PRICES` | `[1000, 2000]` | [config.py:L60](file:///d:/website%20project/kaggri%20ox/submission/config.py#L60) | **ACTIVE** | Price for 2nd quadrant (\$1,000) and 3rd quadrant (\$2,000). |
| `RULE-LAND-04` | `LAND_ROI_THRESHOLD` | `1.5` | [config.py:L124](file:///d:/website%20project/kaggri%20ox/submission/config.py#L124) | **DORMANT / DEAD** | Imported in macro_planner but never used; gate enforces `adjusted_roi > 0.0`. |
| `RULE-LAND-05` | `LAND_BUY_LAST_DAY` | `20` | [config.py:L125](file:///d:/website%20project/kaggri%20ox/submission/config.py#L125) | **DORMANT / DEAD** | Config cutoff Day 20, superseded by active SW hard cutoff Day 13. |
| `RULE-LAND-06` | SW Hard Cutoff Day | `current_day > 13` | [expansion_planner.py:L471](file:///d:/website%20project/kaggri%20ox/submission/strategy/expansion_planner.py#L471) | **REMOVED** | Hard Day-13 cutoff eliminated; replaced by dynamic economic payback, labor serviceability, adjusted ROI, and treasury feasibility. |
| `RULE-HIRE-01` | `DAY_TO_HANDS` | `{0:4, 6:8, 9:8, 10:10, 11:12, 30:0}` | [config.py:L181](file:///d:/website%20project/kaggri%20ox/submission/config.py#L181) | **ACTIVE** | Deterministic hiring schedule. Prevents execution variability. |
| `RULE-HIRE-02` | `MIN_HANDS_BASE` | `4` | [config.py:L196](file:///d:/website%20project/kaggri%20ox/submission/config.py#L196) | **ACTIVE** | Minimum Hour-0 hire-slot allowance used by OrderBuilder slot budgeting. It does not guarantee four successful hires or a four-hand workforce. |
| `RULE-CROP-01` | `CROP_TILE_CAPS` | `WHEAT: 99, CARROT: 16, TOMATO: 16, STRAWBERRY: 20, MELON: 12` | [config.py:L129](file:///d:/website%20project/kaggri%20ox/submission/config.py#L129) | **ACTIVE** | Portfolio tile caps preventing market self-glut. |
| `RULE-CROP-02` | `STRAWBERRY_PLANT_DEADLINE` | `13` | [config.py:L225](file:///d:/website%20project/kaggri%20ox/submission/config.py#L225) | **ACTIVE** | Final valid day to plant strawberries for full 3-harvest lifecycle. |
| `RULE-CROP-03A` | `MELON_PLANT_LAST_DAY_FERT` | `17` | [config.py:L103](file:///d:/website%20project/kaggri%20ox/submission/config.py#L103) | **ACTIVE** | Runtime planner Melon cutoff used by `_crop_allowed_today()`; enables harvest by Day 29 assuming timely watering and fertilizer application. |
| `RULE-CROP-03B` | `MELON_PLANT_LAST_DAY` | `19` | [config.py:L104](file:///d:/website%20project/kaggri%20ox/submission/config.py#L104) | **CONFIGURED / UNUSED** | Unfertilized theoretical/engine feasibility cutoff; imported nowhere, not used by planner. |
| `RULE-CROP-04` | SW Runtime Planting Policy | `sw_plant_decision()` | [macro_planner.py:L366](file:///d:/website%20project/kaggri%20ox/submission/strategy/macro_planner.py#L366) | **ACTIVE** | Days 0–27: allocate free SW soil tiles to Wheat when feed deficit requires it; allocate ALL remaining free SW soil tiles to Carrot. Day 28+: no new SW planting ($n_{\text{wheat}} = 0, n_{\text{carrot}} = 0$). |
| `RULE-CROP-05` | Pre-Buy SW Seed Targets | `get_sw_seed_targets()` | [config.py:L278](file:///d:/website%20project/kaggri%20ox/submission/config.py#L278) | **ACTIVE** | Expansion seed target whitelist: D $\le$ 24 target 15 Wheat seeds; D25–27 target 15 Carrot seeds. *(Expansion pre-buy targeting, not live SW tile allocation).* |
| `RULE-ANIM-01` | `C4_LIVESTOCK_CUTOFF_DAY` | `12` | [config.py:L304](file:///d:/website%20project/kaggri%20ox/submission/config.py#L304) | **ACTIVE** | Cutoff begins Day 12: Day 11 is final permitted purchase day, Day 12+ blocked; pasture construction uses same `< 12` boundary. |
| `RULE-ANIM-02` | Herd Drainage Caps | `HERD_CAP=20, SHEEP_CAP=12, COW_CAP=19` | [animal_planner.py:L16](file:///d:/website%20project/kaggri%20ox/submission/strategy/animal_planner.py#L16) | **ACTIVE** | Town consumption saturation limits for livestock output. |
| `RULE-ANIM-03` | `FEED_WHEAT_BUFFER_DAYS` | `4` | [config.py:L96](file:///d:/website%20project/kaggri%20ox/submission/config.py#L96) | **ACTIVE** | Mandatory feed buffer days required per animal. |
| `RULE-ANIM-FEED-01` | Animal Feed Consumption | `1 Wheat / head / day` | Engine Rule | **ACTIVE** | Baseline biological feed burn rate for Cows, Sheep, and Geese. |
| `RULE-MKT-01` | `SELL_WINDOWS` | `[1, 5, 9, 13, 17, 21]` | [config.py:L85](file:///d:/website%20project/kaggri%20ox/submission/config.py#L85) | **ACTIVE** | Post-town-drain trading hours ($t \equiv 1 \pmod 4$) quoting boosted prices. |
| `RULE-MKT-02` | Shed Relief Triggers | `SHED_SOFT_CAP = 65`, `Midnight: H >= 22 & Shed > 88` | [config.py:L155](file:///d:/website%20project/kaggri%20ox/submission/config.py#L155) | **ACTIVE** | Emergency inventory liquidation triggers; Urgency 1 reduces toward 55 that turn. |
| `RULE-MKT-03` | `MELON_SEASON_SALE_CAP` | `150` | [config.py:L157](file:///d:/website%20project/kaggri%20ox/submission/config.py#L157) | **ACTIVE** | Cumulative melon sales cap to avoid steep quadratic penalty. |
| `RULE-MKT-04` | `FINAL_DUMP_DAYS` | `{28: 0.75, 29: 0.25}` | [config.py:L136](file:///d:/website%20project/kaggri%20ox/submission/config.py#L136) | **DORMANT / DEAD** | Imported in market_brain but never referenced in decision logic. |
| `RULE-EXEC-01` | Task Priority Tiers | `P100 (Survival) down to P20 (Dig)` | [config.py:L63-L75](file:///d:/website%20project/kaggri%20ox/submission/config.py#L63-L75) | **ACTIVE** | Priority hierarchy including P60 (Fertilize Crop) and P87 (Fertilizer Staging). |
| `RULE-EXEC-02` | Zonal Spillover Boundary | `C2_MAX_SPILLOVER_DIST = 12` | [config.py:L107](file:///d:/website%20project/kaggri%20ox/submission/config.py#L107) | **ACTIVE** | Maximum Manhattan distance a unit may travel across quadrant boundaries. |
| `RULE-EXEC-03` | Dispatch Priority Band & Cluster | `C6_PRIORITY_BAND = 20, ClusterBonus=2/4` | [config.py:L113-L117](file:///d:/website%20project/kaggri%20ox/submission/config.py#L113-L117) | **ACTIVE** | Task prioritization band (20) and cluster bonuses for unit assignment. |
| `RULE-ADV-01` | `SUPPLY_ADJUSTMENT_WEIGHT` | `0.50` | [opponent_advisor.py:L26](file:///d:/website%20project/kaggri%20ox/submission/strategy/opponent_advisor.py#L26) | **ACTIVE** | Weight applied to inferred opponent supply flood in crop scoring. |
| `RULE-ADV-02` | `SUPPLY_PROJECTION_DAYS` | `12` | [opponent_advisor.py:L27](file:///d:/website%20project/kaggri%20ox/submission/strategy/opponent_advisor.py#L27) | **ACTIVE** | Forward planning horizon for opponent harvest schedule projection. |
| `RULE-ADV-03` | `PREEMPT_SELL_THRESHOLD` | `0.65` | [opponent_advisor.py:L28](file:///d:/website%20project/kaggri%20ox/submission/strategy/opponent_advisor.py#L28) | **ACTIVE** | Opponent sell probability threshold triggering preemptive sell prioritization. |
| `RULE-ADV-04` | `DELAY_PRICE_DEPRESSION_PCT` | `0.80` | [opponent_advisor.py:L29](file:///d:/website%20project/kaggri%20ox/submission/strategy/opponent_advisor.py#L29) | **ACTIVE** | Spot price depression threshold relative to expected price triggering delay hold. |

---

## 5. Potential Issues & Codebase Anomalies Discovered

1. **Documentation Convention on Code-Doc Drift & Stale Source Comments**:
   When source code comments conflict with executable Python branches, architecture documents represent executable behavior as ground truth and separately flag stale comments as **CODE-DOC DRIFT**. For example, `macro_planner.py:L717` contains a stale comment claiming: `# Whitelist: strictly WHEAT (D9-24) or CARROT (D25-27), 0 strawberries/melons/tomatoes`, whereas the actual executable function `sw_plant_decision()` dynamically allocates free SW soil tiles to Wheat to satisfy net feed deficits, and dedicates all remaining free SW soil tiles to Carrot starting from early days (Days 0–27).
2. **Active Hard Cutoff Blocker in `expansion_planner.py` (CORRECTED)**:
   The former hard check `current_day > 13` was removed and replaced with a dynamic economic payback gate (`expected_remaining_profit_from_SW > land_price + incremental_support_costs`), labor serviceability verification, adjusted ROI check, and opportunity window factor through Day 25.
3. **SW Land ROI Valuation vs SW Planting Policy Mismatch**:
   `compute_land_roi()` assumes 25 crop-capable tiles. Runtime SW provides 15 crop-capable soil tiles (`SW_SOIL_TILES`), 9 pasture tiles (`SW_PASTURE_TILES`), and 1 shed portal tile (`PORT_SW = (4, 5)`). This is 10 extra assumed crop tiles:
   - 40% of the full 25-tile quadrant is incorrectly treated as crop land, and
   - Modeled crop capacity is 66.7% higher than actual crop capacity (25 vs 15).
   Furthermore, `compute_land_roi()` evaluates profitability assuming the additional tiles will be planted with high-margin strawberry/melon/tomato cycles, whereas runtime SW planting policy (`sw_plant_decision()`) strictly enforces `RULE-CROP-04`, dedicating SW exclusively to Wheat (feed deficit) and Carrots (remainder).
4. **Projected Wheat Sustainability Constraint (`FORM-HERD-01`) (CORRECTED)**:
   `macro_planner.py` now computes an authoritative feed capacity calculation (`compute_authoritative_feed_capacity`) combining shed wheat, worker inventories, maturing planted wheat ($\le$ Day 28), planned predictable wheat, and affordable emergency wheat. The ungrounded `PHASE1_GEESE_DAY0_2` early-game floor exception was eliminated. The sustainable herd size is passed directly into `get_animal_targets(..., max_sustainable=sustainable)` and strictly clamps livestock expansion, exposing 5 feed diagnostic metrics on `MacroPlan`.
5. **Workload Load Estimation Duplication & Shadowing (`FORM-PLANNING-CAPACITY-01`)**:
   `estimate_daily_load()` is duplicated verbatim (all 79 lines of executable function body match) between `macro_planner.py:L1035` (called at line 900) and `task_scheduler.py:L1305` (defined but never called internally). Furthermore, when evaluating `water_budget_exceeded = load > (units_now + hires) * EFFECTIVE_ACTIONS_PER_UNIT`, `macro_planner.py:L455` locally defines `EFFECTIVE_ACTIONS_PER_UNIT = 18`, shadowing `config.py:L116` (`EFFECTIVE_ACTIONS_PER_UNIT = 12`). The resulting `water_budget_exceeded` flag is stored in `MacroPlan` but never read by any decision gate or hiring schedule.
6. **Dormant `BUY_WHEAT_TRIGGER_DAYS` Constant**:
   `config.py:L97` defines `BUY_WHEAT_TRIGGER_DAYS = 2.0`, but this constant is never imported or referenced in runtime execution. The actual live survival floor in `macro_planner.py:L635` is hardcoded directly as `(n_animals * 2) - wheat_have`.
7. **Generalized Price-Protected Drip Selling & Floor Logic (CORRECTED)**:
   Marginal price protection is generalized across all fragile products (`DRIP_PROTECTED_PRODUCTS = ("MELON", "WOOL", "MILK", "STRAWBERRY")`) using `DRIP_PRICE_KEEP_FRAC`. For each protected commodity, `safe_drip_budget()` uses the exact continuous inverse and discrete quotes to guarantee the last sold unit stays $\ge$ keep-fraction of spot price. Live market inventory is updated per slice within multi-slice sell loops. Fragile products are held at the \$1 floor in normal and shed-relief modes (`HOLD_AT_FLOOR_PRODUCTS`), liquidating only during endgame or urgency 2, while respecting the 150 seasonal melon cap.
8. **`main._build_opp_advice` Silent Diagnostic Suppression**:
   Exceptions during opponent modeling are caught and recorded in `_OPPONENT_MODEL_DIAGNOSTICS`, returning an empty advice object. This prevents crashes, but suppresses error visibility unless `DEBUG` is active.
9. **Semantic Duplication in `get_animal_targets`**:
   `config.py:L306` provides a wrapper `get_animal_targets()` delegating to `strategy.animal_planner`, while `macro_planner.py` directly imports `from strategy.animal_planner import get_animal_targets`.
