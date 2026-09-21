# Kaggriculture P2.1 — Strawberry Policy & Lifecycle Audit

**Author**: Antigravity  
**Commit Baseline**: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`  
**Current HEAD**: `18740e0e6b2c02bd547b411eb08214edb03acbd4`  
**Target Scope**: Phases A & B (Authoritative Engine Lifecycle & Agent Policy Inventory)

---

## 1. Authoritative Engine Lifecycle Ground Truth

From the official Kaggle simulation engine (`kaggle_environments.envs.kaggriculture.kaggriculture`):

```python
CROPS['STRAWBERRY'] = {
    'seed': 100,
    'first_yield_day': 10,
    'interval': 2,
    'max_yield': 4,
    'max_yield_day': 10,
    'ongoing': True,
}

MARKET_PARAMS['STRAWBERRY'] = {
    'base': 120,
    'I0': 10000,
    'T': 100,
    'below_func': 'sqrt',
    'below_target': 0.70,
    'above_func': 'linear',
    'above_target': 1.60,
}
```

### Production Mechanics (`_daily_refresh_plants` & `_decay_plants`)
1. **First Production**: Occurs when plant age reaches `first_yield_day = 10`. That is at the end of Day $P+9$ (during the transition into Day $P+10$).
2. **Subsequent Production Events**: Occur every `interval = 2` days, up to `max_yield = 4` production events:
   - Event 1: Age 10 $\rightarrow$ Day $P + 10$
   - Event 2: Age 12 $\rightarrow$ Day $P + 12$
   - Event 3: Age 14 $\rightarrow$ Day $P + 14$
   - Event 4: Age 16 $\rightarrow$ Day $P + 16$
3. **Event-Level Quantities**:
   - Base yield: **1 unit** per production event.
   - Bonus yield: **+1 unit** (total 2 units) if watered and fertilized on that production day.
   - Cumulative lifetime yield: **4 units** unfertilized, up to **8 units** fully fertilized and watered.
4. **Decay into Weed**:
   - When the plant completes its 4th production event on Day $P+16$, its lifespan is set to `(P + 17) * turns_per_day`.
   - Starting at Day $P+17$, `_decay_plants` reduces `yield_units` by 1 every 2 steps until it reaches 0 and converts the tile to a `WEED`.
5. **Watering & Maintenance Requirement**:
   - The plant must be watered every day. If consecutive unwatered days reach 2, the plant immediately dies and turns into a weed (`consecutive_unwatered >= 2`).
   - Therefore, a plant active from Day $P$ to Day $D_{\text{end}}$ requires **1 watering action per calendar day**.

---

## 2. Planting-Day Specific Lifecycle Table (Season Days 0–29)

The game consists of 30 days (Day 0 through Day 29, ending at Step 719).

| Plant Day ($P$) | Event 1 (Age 10) | Event 2 (Age 12) | Event 3 (Age 14) | Event 4 (Age 16) | Attainable Events ($h$) | Decay Day | Calendar Days Occupied | Total Watering Actions Required | Potential Yield Units |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **0** | Day 10 | Day 12 | Day 14 | Day 16 | **4** | Day 17 | 17 (D0–16) | 17 | 4–8 |
| **1** | Day 11 | Day 13 | Day 15 | Day 17 | **4** | Day 18 | 17 (D1–17) | 17 | 4–8 |
| **2** | Day 12 | Day 14 | Day 16 | Day 18 | **4** | Day 19 | 17 (D2–18) | 17 | 4–8 |
| **3** | Day 13 | Day 15 | Day 17 | Day 19 | **4** | Day 20 | 17 (D3–19) | 17 | 4–8 |
| **4** | Day 14 | Day 16 | Day 18 | Day 20 | **4** | Day 21 | 17 (D4–20) | 17 | 4–8 |
| **5** | Day 15 | Day 17 | Day 19 | Day 21 | **4** | Day 22 | 17 (D5–21) | 17 | 4–8 |
| **6** | Day 16 | Day 18 | Day 20 | Day 22 | **4** | Day 23 | 17 (D6–22) | 17 | 4–8 |
| **7** | Day 17 | Day 19 | Day 21 | Day 23 | **4** | Day 24 | 17 (D7–23) | 17 | 4–8 |
| **8** | Day 18 | Day 20 | Day 22 | Day 24 | **4** | Day 25 | 17 (D8–24) | 17 | 4–8 |
| **9** | Day 19 | Day 21 | Day 23 | Day 25 | **4** | Day 26 | 17 (D9–25) | 17 | 4–8 |
| **10** | Day 20 | Day 22 | Day 24 | Day 26 | **4** | Day 27 | 17 (D10–26) | 17 | 4–8 |
| **11** | Day 21 | Day 23 | Day 25 | Day 27 | **4** | Day 28 | 17 (D11–27) | 17 | 4–8 |
| **12** | Day 22 | Day 24 | Day 26 | Day 28 | **4** | Day 29 | 17 (D12–28) | 17 | 4–8 |
| **13** | Day 23 | Day 25 | Day 27 | Day 29 | **4** | Day 30* | 17 (D13–29) | 17 | 4–8 |
| **14** | Day 24 | Day 26 | Day 28 | *(Day 30)* | **3** | Day 31* | 16 (D14–29) | 16 | 3–6 |
| **15** | Day 25 | Day 27 | Day 29 | *(Day 31)* | **3** | Day 32* | 15 (D15–29) | 15 | 3–6 |
| **16** | Day 26 | Day 28 | *(Day 30)* | *(Day 32)* | **2** | Day 33* | 14 (D16–29) | 14 | 2–4 |
| **17** | Day 27 | Day 29 | *(Day 31)* | *(Day 33)* | **2** | Day 34* | 13 (D17–29) | 13 | 2–4 |
| **18** | Day 28 | *(Day 30)* | *(Day 32)* | *(Day 34)* | **1** | Day 35* | 12 (D18–29) | 12 | 1–2 |
| **19** | Day 29 | *(Day 31)* | *(Day 33)* | *(Day 35)* | **1** | Day 36* | 11 (D19–29) | 11 | 1–2 |
| **20+**| *(Day 30)*| *(Day 32)* | *(Day 34)* | *(Day 36)* | **0** | — | — | — | 0 |

*\*Note: Decay events past Day 29 never execute because the game ends at Day 29, Hour 23.*

### Key Takeaways from the Engine Truth
1. **Day 13 is the absolute mathematical deadline for full 4-event yield realization**.
2. **Planting Day 13 requires 17 consecutive daily watering operations** (Day 13 through Day 29). Modeling only $h(D) + 10 = 14$ operations understates watering labor by 3 actions per tile! Across 20 tiles, that is an unmodeled deficit of 60 worker actions.
3. **Plantings on Day 14+ suffer steep cliff decay**:
   - Day 14 loses 25% of yield.
   - Day 16 loses 50% of yield.
   - Day 18 loses 75% of yield.
   - Day 20+ loses 100% of yield.

---

## 3. Current Agent Strawberry Policy Inventory

### A. Cap Progression (`agent/config.py`, lines 336–356)
```python
def get_strawberry_cap(day, strawberry_eligible=False, land_purchased=None):
    eligible = strawberry_eligible if land_purchased is None else land_purchased
    if not eligible:
        return 0
    if day <= 8:
        return 16
    elif day <= 12:
        return 18
    elif day == 13:
        return 20
    else:
        return 0
```
- Days 0–2: Not planted because dedicated wave requires `day >= 3`.
- Days 3–8: Cap is **16 tiles**.
- Days 9–12: Cap is **18 tiles**.
- Day 13: Cap is **20 tiles**.
- Day 14+: Cap is **0** (`STRAWBERRY_PLANT_DEADLINE = 13`).

### B. The Dedicated Strawberry Wave (`agent/strategy/macro_planner.py`, lines 2358–2382)
- **Execution Condition**: `3 <= day <= STRAWBERRY_PLANT_DEADLINE and "NE" in farm.unlocked`.
- **Precedence**: Executes **after** the continuous wheat replanting loop (which targets 8 wheat tiles on Days 0–9 and 20 wheat tiles on Days 10–13).
- **Target Calculation**: `want_s = max(0, s_cap - committed_counts.get("STRAWBERRY", 0))`.
- **Tile Selection**:
  1. `NE` empty tiles first.
  2. `NW` empty fallow tiles next (excluding shed/worker spawn tiles `(4, 4)` and `(4, 5)`).
  3. `SW` is strictly excluded.
- **Flaw in Dedicated Wave**:
  - It **forces** planting up to `s_cap` without evaluating market prices, town shop demand, opponent strawberry supply, or alternative crop opportunity costs.
  - If money is available, it buys strawberry seeds ($100 each) and queues them unconditionally.

### C. The General Crop Scoring Fallback Loop (`agent/strategy/macro_planner.py`, lines 2390–2456)
- Executes on any empty tiles remaining after the dedicated strawberry wave.
- Contains two strawberry evaluation paths:
  1. **Expansion-priority path** (line 2406): Checks `if forced_crop == "STRAWBERRY": cap = get_strawberry_cap(day, "NE" in farm.unlocked)`.
  2. **Standard scoring path** (line 2429): Checks `if crop == "STRAWBERRY": cap = get_strawberry_cap(day, "NE" in farm.unlocked)`.
- **Flaw in Dual-Path Implementation**:
  - If a treatment modifies only the dedicated wave's target, any unfilled strawberry quota up to `get_strawberry_cap(day, True)` will be considered by Phase 2b and can be planted anyway, bypassing the intended limit!
  - **P2.1 Mandate**: A single unified dynamic budget $S^*$ must govern **both** the dedicated wave and Phase 2b fallback paths.

### D. Selling Policy (`agent/market/market_brain.py`)
- Strawberry is listed in `DRIP_PROTECTED_PRODUCTS = ("MELON", "WOOL", "MILK", "STRAWBERRY")`.
- `DRIP_PRICE_KEEP_FRAC["STRAWBERRY"] = 0.88`.
- Sells in small batches to prevent spot price from dropping below 88% of spot within a single turn.
- However, if market inventory exceeds $I_0 = 10,000$, the linear above-target curve drops price rapidly:
  $$P = 120 \times \left(1 - 1.60 \times \frac{I - 10000}{100}\right) = 120 - 1.92 \times (I - 10000)$$
  At $I = 10,063$, price crashes to the absolute floor of **$1.00**.
  Dumping 80–160 strawberries without town consumption crashes the strawberry market completely.
