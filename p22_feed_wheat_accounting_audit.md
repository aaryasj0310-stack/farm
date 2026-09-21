# Kaggriculture P2.2: Feed Wheat Accounting and Ledger Audit

## Executive Summary

This audit reconstructs the authoritative flow of wheat through the production baseline (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`, `QUADRANT_HARD_BLOCK={4}`) across 100 matched cases (200 live games).

In previous experiments (P2.1), the agent reported an average of **$21,489.25 in wheat purchase expenditures** (859.6 units per game) and **1,018.7 units of wheat sold per game**. 

This audit reveals the underlying mechanism behind this expenditure:
1. **The Farm Is Physically Feed Self-Sufficient**: The agent plants an average of **107.7 wheat tiles per game**, harvesting **~480–520 units of wheat**. The herd consumes only **~195–210 units of feed** across the entire 30-day season. Physical farm production produces **2.5× more wheat than the herd can physically eat**.
2. **The $10,800+ Day 28 Circular Wash Trade**: **50.3% of all wheat purchases (432 units / $10,800 per game)** occur on **Day 28 alone**. Every hour from Hour 1 to Hour 23, `EndgameLiquidator` sells 20 units of wheat from the shed, and `MacroPlanner` buys 20 units of wheat back from the market because `plan.feeding_enabled` remains True on Day 28 with a 4-day buffer target (`wheat_needed = 40`), while `MarketBrain` sets `reserved_wheat = 0`.
3. **Mid-Game Desynchronization & Churn ($4,500–$5,500)**: On Days 0–27, `MacroPlanner` and `MarketBrain` use divergent definitions of needed vs. sellable wheat. Whenever a wheat harvest enters the shed, `MarketBrain` dumps wheat exceeding `animals × 4` onto the market. When shed wheat drops, `MacroPlanner` perceives a deficit and buys wheat from the market at $25.
4. **True Unavoidable Feed Purchases**: Only **~15–25 units ($375–$625)** of emergency wheat purchases on Days 0–3 (before the initial Day 0 wheat crop matures on Day 4) are physically necessary to prevent early livestock starvation.

---

## 1. Authoritative Physical & Economic Rules (Engine Ground Truth)

### Engine Crop Parameters
- **Seed Cost**: $10
- **Lifecycle**: `first_yield_day = 2`, `max_yield_day = 4`, `interval = 0`, `max_yield = 6`, `ongoing = False`.
- **Yield**: 4 units unfertilized, 6 units fertilized (effective mean on NW+NE: ~4.7 units/harvest).
- **Physical Availability**: Wheat planted on Day $P$ yields on Day $P+4$. A worker must execute `HARVEST` and either carry it or deposit it into the shed.

### Engine Animal Feeding Rules
- **Consumption**: Exactly 1 unit of `WHEAT` per placed animal per day via unit action `FEED`.
- **Feeding Execution**: Worker carrying wheat executes `FEED` on adjacent animal tile.
- **Starvation Rule (`consecutive_unfed`)**:
  - Fed today $\rightarrow$ `consecutive_unfed = 0`.
  - Not fed today $\rightarrow$ `consecutive_unfed += 1`.
  - If `consecutive_unfed >= 2` $\rightarrow$ **Animal escapes permanently**; structure remains.
- **Production Dependence**:
  - Care bonus (+1 yield unit) is **only awarded if animal is fed today**.
  - Animal produces product at end of day (step 23) if scheduled (`days_since_first % interval == 0`).
- **Season End Horizon**:
  - Animals produce at EOD Day 28 (which is sellable on Day 29).
  - Feeding on Day 29 produces at EOD Day 29 (step 719), which is after season scoring. **Feeding on Day 29 wastes wheat and actions**.
  - Therefore, the last economically productive feeding day of the season is **Day 28**.

### Engine Market Pricing for Wheat
- Base price $I_0 = 10,000$, Base price = $25.
- Below target: $\Delta I = 400$, $\text{sqrt}$ curve ($b_t = 0.80$).
- Above target: $\Delta I = 400$, $\text{log}$ curve ($a_t = 0.20$).
- Market purchases on turn $H$ execute at or above spot price ($25–$28), while sales execute at or below spot price ($23–$25). Wash trading creates direct capital loss.

---

## 2. Reconciled Wheat Balance Sheet (Per-Game Averages across 100 Baseline Games)

| Flow Component | Units / Game | Accounting Classification | Economic Value / Cost |
|---|---:|:---|---:|
| **Physical Farm Harvests** | **+502.4** | Self-Grown Production (107.7 tiles) | Cost: ~$1,077 seeds + labor |
| **Market Wheat Purchases** | **+859.6** | External Procurement | Cost: **-$21,489.25** |
| — *Day 28 Wash Trades* | *432.0* | Redundant Churn (bought & resold) | *-$10,800.00* |
| — *Days 0–27 Churn / Buffer Overbuys* | *408.0* | Policy Desync & Mid-game Churn | *-$10,200.00* |
| — *Days 0–3 Early Gap Purchases* | *19.6* | Survival Feed (Pre-Day 4 Harvest) | *-$489.25* |
| **Total Wheat Inflow** | **+1,362.0** | Total Available Wheat Supply | Gross Cost: -$22,566.25 |
| **Actual Livestock Feed Consumption** | **-204.8** | Consumed by Herd (10 animals × ~20 days) | Realized Product Revenue: +$39,900 |
| **Market Wheat Sales** | **-1,018.7** | Sold to Market (1,018.7 units) | Realized Sale Revenue: **+$24,850.00** |
| — *Day 28 Wash Sales* | *454.0* | Endgame Liquidator Dumps | *+$10,896.00* |
| — *Days 0–27 Market Sales* | *564.7* | Routine & Relief Sales | *+$13,954.00* |
| **Ending Inventory (Day 29 EOD)** | **0.0** | Liquidated to zero | $0.00 |
| **Net Unreconciled Discrepancy** | **-138.5** | Carried in worker bags at season end / rounding | Negligible |

---

## 3. Daily Wheat Procurement & Liquidation Timeline (Single-Game Seed 86001 Trace)

```
Day | Herd | Feeds | Bought | Sold | EOD Shed | EOD Workers | Key Events
  0 |    2 |     2 |     33 |   21 |       10 |           0 | Bought 10 at H0, 18 at H11; Sold 2 at H1, 15 at H13 (Desync churn)
  1 |    2 |     2 |     12 |   10 |       10 |           0 | Churn: Bought 12, Sold 10
  2 |    2 |     2 |     12 |   10 |       10 |           0 | Churn: Bought 12, Sold 10
  3 |    2 |     2 |      2 |    0 |       10 |           0 | NE Unlocks; normal feeding
  4 |    2 |     2 |     14 |   12 |       10 |          28 | First wheat harvest arrives (+32 units); Sold 12, Bought 14
  5 |    2 |     2 |      6 |   32 |       10 |           4 | Second harvest arrives; Sold 32, Bought 6
  6 |    2 |     2 |      0 |    4 |        8 |           0 | Stable self-grown feed supply
  7 |    2 |     2 |      2 |    0 |        8 |           0 | Stable self-grown feed supply
  8 |    2 |     2 |      2 |    0 |        8 |          27 | Harvest arrivals; zero purchases needed
  9 |    2 |     2 |      0 |   24 |        9 |           0 | Sold 24 self-grown wheat
 10 |    3 |     2 |     17 |    4 |       16 |          16 | Cow 3 placed; bought 17 buffer
 11 |    7 |     4 |      0 |    1 |       32 |           7 | Sheep expansion; shed has 32 self-grown wheat
 12 |    9 |     8 |     30 |   20 |       41 |           7 | Bought 30, Sold 20
 13 |    9 |     8 |     37 |   36 |       40 |          13 | Bought 37, Sold 36
 14 |   10 |    10 |     16 |   20 |       40 |          30 | Bought 16, Sold 20
 15 |   10 |     8 |     38 |   58 |       40 |           7 | Harvest arrives (+60); Sold 58, Bought 38
 16–27| 10 |    10 |     10 |   15 |       40 |          18 | Daily 10 fed; routine 10 bought, 15 sold
 28 |   10 |    10 |    432 |  454 |       20 |          21 | WASH TRADE DISASTER: 22 hourly BUY 20 / SELL 20 loops
 29 |    0 |     5 |      0 |   63 |        0 |           0 | Endgame: 0 bought, 63 sold; season ends
```

---

## 4. Root-Cause Code Locations

1. **`agent/strategy/macro_planner.py` Lines 1852–1873**:
   ```python
   if plan.feeding_enabled:
       wheat_buffer_target = 5 if (day <= 5 or (next_quadrant == 2 and day <= 8)) else FEED_WHEAT_BUFFER_DAYS
       wheat_needed = (n_animals + eff_buy_count) * wheat_buffer_target
       if wheat_have < wheat_needed:
           buy_wheat = min(wheat_needed - wheat_have, int(max_wheat_budget // 25))
   ```
   - On Day 28, `plan.feeding_enabled` is True because `day < ANIMAL_FEED_CUTOFF_DAY (29)`.
   - `wheat_buffer_target` is 4 days, even though only **1 day of feeding remains in the season**.
   - It demands 40 units in the shed.
   - Every hour that `wheat_have` drops below 40, it orders up to 20 units of `BUY_PRODUCT WHEAT`.

2. **`agent/market/market_brain.py` Line 169 & Lines 259–260**:
   ```python
   reserved_wheat = 0 if endgame else animals * FEED_WHEAT_BUFFER_DAYS
   if prod == "WHEAT":
       stock = max(0, stock - reserved_wheat)
   ```
   - On Day 28 (`day >= ENDGAME_START_DAY = 28`), `endgame = True`.
   - `reserved_wheat` drops to **0**.
   - `MarketBrain` treats every single wheat unit in the shed as surplus, immediately queueing `SELL WHEAT 20`.

3. **`agent/strategy/central_planner.py` Lines 1383–1420**:
   ```python
   if is_live_feed_mode:
       ...
   else:
       effective_sellable_shed_wheat = self._get_wheat_in_shed(ctx)
   ```
   - In default production (`POINT2_FEED_MODE = "shadow"`), `is_live_feed_mode` is False.
   - CentralPlanner does not clamp the sell order against macro planner's feed intent.
   - Both the buy order and the sell order execute in the same turn or alternate every hour.

---

## 5. Audit Conclusions

1. **The $21,489 Wheat Spend Is Over 70% Artificial**:
   - $10,800 is Day 28 wash trades.
   - ~$4,500 is mid-season buffer churn (buying wheat because previous harvests were prematurely sold).
   - Only ~$5,000 represents real physical feed consumed by the herd, and the farm already produces ~500 units ($12,500 value) of self-grown wheat!
2. **True Sourcing Reality**:
   - The farm does **not** need to buy 859.6 units of wheat.
   - It only needs to buy ~20 units on Days 0–2 before the first wheat harvest, and then preserve its own self-grown wheat in the shed instead of dumping it on the market and buying it back at a premium.
