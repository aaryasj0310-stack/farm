# Opponent Modeling System — Complete Design & Implementation Plan

## Context

Phase E.1 from [analysis_results.md](file:///d:/website%20project/kaggri%20ox/docs/analysis_results.md) calls for opponent modeling that predicts their sales, undercuts them, and diversifies away from their products. Currently [opponent_model.py](file:///d:/website%20project/kaggri%20ox/agent/state/opponent_model.py) has two scaffolded but **never-called** functions, and `record_our_sale()` in [state_tracker.py](file:///d:/website%20project/kaggri%20ox/agent/state/state_tracker.py) is never invoked — making the drain ledger's opponent attribution inaccurate.

This plan builds a **comprehensive, tested opponent modeling system** before wiring it into the main agent pipeline.

---

## Information Asymmetry: What We Can See vs. What's Hidden

Understanding the exact observability boundary is critical for designing what the model CAN and CANNOT infer.

### ✅ PUBLIC (both farms visible every turn)

| Data Point | Source | Precision |
|---|---|---|
| Opponent's **money** | `farms[1-player].money` | Exact, real-time |
| Opponent's **full 10×10 tile grid** | `farms[1-player].tiles` | Every tile — plants, animals, structures, weeds |
| Each plant's **crop type, planted_day, watered_today, consecutive_unwatered, yield_units, fertilized_until_day** | tile dict | Exact |
| Each animal's **type, placed_day, fed_today, cared_today, consecutive_unfed, fertilizer_available, pending_care_bonus, yield_units** | tile dict | Exact |
| Farmer + hand **positions** | `farms[1-player].farmer`, `.hands` | Exact (x, y) |
| **Unlocked quadrants** | `farms[1-player].unlocked_quadrants` | Exact |
| **Hires today** | `farms[1-player].hires_today` | Exact |
| **Market inventory & prices** (shared) | `obs.market` | Exact, post-order |
| **Town shops** (shared) | `obs.town.unlocked_shops` | Exact |

### 🔒 HIDDEN (private per-player)

| Data Point | Why It Matters |
|---|---|
| Opponent's **shed contents** | Don't know what they're holding to sell |
| Opponent's **seed inventory** | Don't know what they plan to plant |
| Opponent's **unit inventories** (carried items) | Don't know if they picked up harvest |
| Opponent's **market orders** (until they execute) | Don't know their buy/sell plan for this turn |

---

## The Five Pillars of Opponent Modeling

### Pillar 1: Production Forecast (What they WILL produce)

Since we can see **every tile's crop type, planted_day, fertilized_until_day**, we can compute exact future harvests:

```
For each opponent plant tile:
  age = current_day - planted_day
  crop_data = CROPS[crop]
  
  One-time crops (Wheat, Carrot, Melon):
    harvest_day = planted_day + max_yield_day
    yield = base_yield + bonus_window_days_watered  (observable from yield_units)
    
  Ongoing crops (Tomato, Strawberry):
    next_yield_day = planted_day + first_yield_day + k * interval
    yield_per_cycle = 1 (unfertilized) or 2 (fertilized — check fertilized_until_day)

For each opponent animal tile:
  next_production_day = placed_day + first_yield_day + k * interval
  product = ANIMALS[animal].product
  held_units = yield_units  (visible — tells us if they're harvesting or not)
```

**Key Outputs:**
- `opp_harvest_schedule[product][day]` → expected units arriving in opponent's shed
- `opp_imminent_harvest[product]` → units harvestable RIGHT NOW (ripe, not yet picked)
- `opp_crop_commitment` → which crops they're invested in (guides our diversification)

### Pillar 2: Shed Inference (What they're HOLDING to sell)

Their shed is private, but we can **reconstruct it** via:

$$\text{shed}_{t} = \text{shed}_{t-1} + \text{harvests}_{t} - \text{sales}_{t} - \text{feed\_consumed}_{t}$$

- **Harvests**: From Pillar 1 (we see the tiles change when they harvest — `yield_units` drops)
- **Sales**: From the drain ledger (Δmarket_inventory − town_consumption − our_own_sales)
- **Feed consumed**: 1 wheat/animal/day (we see their animal count)

> [!IMPORTANT]
> **Harvest detection**: When a one-time crop tile's `yield_units` drops to 0 or the tile becomes EMPTY/WEED, they harvested. For ongoing crops, we track `yield_units` decrements. For animals, `yield_units` dropping means they collected product.

**Key Outputs:**
- `opp_estimated_shed[product]` → inferred current holdings (probabilistic range)
- `opp_shed_pressure` → estimated total shed utilization (approaching 100 = desperate sell incoming)

### Pillar 3: Sell Timing Prediction (WHEN they'll dump)

Combining Pillar 1 + 2 to predict sell timing:

**Signals for "opponent is about to sell product X":**

| Signal | Weight | How to Detect |
|---|---|---|
| Ripe crops visible on farm | HIGH | `age >= max_yield_day` AND `yield_units > 0` |
| Farmer/hand moving toward shed | MEDIUM | Manhattan distance to (4,4)/(5,4)/(4,5)/(5,5) decreasing |
| Recent money increase | HIGH | `Δmoney > 0` without visible market buy = they sold something |
| Inferred shed nearing 100 | HIGH | `opp_estimated_shed_total >= 80` → panic sell coming |
| Animal product accumulating | MEDIUM | `yield_units` on animal tiles growing without pickup |
| End-of-day approaching | LOW | Hours 20-23 → may rush to sell before day change |

**Money delta analysis** is the most powerful signal:

```
Δmoney = opp_money_now - opp_money_prev
If Δmoney > 0:
  # They earned money — from selling (market orders are the only income source)
  # Cross-reference with Δmarket_inventory to identify WHAT they sold
  
If Δmoney < 0 and no visible HIRE/BUY_LAND/BUY_SEED/BUY_ANIMAL:
  # Unexplained spending — they bought something from market (wheat/fertilizer)
```

> [!TIP]
> **Money is observable every turn.** By tracking `Δmoney` per step alongside `Δmarket_inventory`, we can often determine **exactly** what the opponent bought or sold on the previous turn, even though their orders are private.

**Key Outputs:**
- `opp_sell_probability[product]` → 0.0–1.0 likelihood they sell THIS turn
- `opp_sell_volume_estimate[product]` → expected units they might dump
- `opp_recent_sales[product]` → confirmed sales from money/inventory delta

### Pillar 4: Strategy Classification (HOW they play)

Over the first 5–8 days, classify the opponent's archetype:

| Archetype | Detection Signal |
|---|---|
| **Wheat Rusher** | >60% tiles are wheat, few/no animals by day 5 |
| **Animal Farmer** | 3+ animals placed by day 6, coops/pastures visible |
| **Melon Sniper** | Melon seeds planted days 0–2, waiting for day 10 payoff |
| **Diversified** | Mix of crops + animals, no dominant single strategy |
| **Passive/Starter** | Few tiles planted, money not spent, likely a weak bot |

**Classification logic:**

```python
def classify_opponent(opp_farm, day):
    crop_counts = count_crops(opp_farm)
    animal_count = count_animals(opp_farm)
    money_spent = 3000 - opp_farm.money  # relative to start
    tiles_used = count_used_tiles(opp_farm)
    
    wheat_ratio = crop_counts.get("WHEAT", 0) / max(tiles_used, 1)
    has_melons = crop_counts.get("MELON", 0) > 0
    
    if tiles_used < 3 and day > 3:
        return "PASSIVE"
    if wheat_ratio > 0.6:
        return "WHEAT_RUSHER"
    if animal_count >= 3 and day <= 8:
        return "ANIMAL_FARMER"
    if has_melons and day <= 3:
        return "MELON_SNIPER"
    return "DIVERSIFIED"
```

**Key Output:**
- `opp_archetype` → string classification, updated as new evidence arrives
- `opp_dominant_products` → ranked list of their primary output channels

### Pillar 5: Tactical Responses (What WE should do about it)

This is where the model outputs become **actionable decisions**:

#### 5a. Anti-Glut Diversification (→ MacroPlanner)

When the opponent is heavily invested in a product, our own production of that product faces double the supply pressure:

```
effective_own_supply[product] += opp_estimated_production[product]
```

This shifts `_crop_score()` downward for products the opponent also produces, naturally steering the MacroPlanner toward under-supplied products.

#### 5b. Pre-emptive Selling (→ MarketBrain)

If we detect the opponent is about to sell product X (ripe crops, farmer heading to shed):

```
If opp_sell_probability[X] > 0.7 AND we also hold X:
  → SELL X NOW (even outside normal sell windows)
  → Sell BEFORE them to get the higher pre-dump price
```

#### 5c. Sell Delay / Avoidance (→ MarketBrain)

If the opponent just dumped product X (detected via `Δmoney` and `Δinventory`):

```
If opp just sold X AND price[X] dropped significantly:
  → HOLD X (wait for town drain to recover the price)
  → Carry check horizon extended for X
```

#### 5d. Opponent Shed Pressure Exploitation (→ MarketBrain)

If the opponent's inferred shed is near 100:

```
They MUST sell soon or lose goods to overflow.
→ We can HOLD our competing products and let them crash the price
→ Then sell after the crash + recovery
```

#### 5e. Counter-Picking (→ MacroPlanner)

```
If opponent produces ZERO of product Y AND shop demand for Y exists:
  → Y has ZERO competition → monopoly pricing
  → Prioritize Y in crop scoring
```

---

## Implementation Architecture

### Module Structure

```
agent/state/
  opponent_model.py          # REWRITE — the core OpponentModel class
  state_tracker.py           # MODIFY — wire record_our_sale, improve drain ledger

agent/strategy/
  opponent_advisor.py        # NEW — translates model outputs → strategic advice
```

### OpponentModel Class Design

```python
class OpponentModel:
    """Persistent cross-turn opponent state tracker and predictor."""
    
    def __init__(self):
        self.prev_tiles = None          # snapshot for delta detection
        self.prev_money = None
        self.estimated_shed = {}        # product → estimated count
        self.confirmed_sales = {}       # product → cumulative confirmed sold
        self.harvest_schedule = {}      # product → {day: expected_units}
        self.archetype = "UNKNOWN"
        self.dominant_products = []
        self.sell_probability = {}      # product → 0.0-1.0
    
    def update(self, ctx, mem):
        """Call every turn with the new observation."""
        opp = ctx["opponent_farm"]
        self._detect_harvests(opp)      # Pillar 2: tile delta → shed inference
        self._infer_sales(ctx, mem)     # Pillar 3: money + inventory delta
        self._forecast_production(opp, ctx["day"])  # Pillar 1
        self._classify(opp, ctx["day"]) # Pillar 4
        self._compute_sell_probability(ctx)  # Pillar 3
        self.prev_tiles = snapshot(opp)
        self.prev_money = opp.money
    
    def advise(self, ctx, mem):
        """Returns OpponentAdvice consumed by MacroPlanner and MarketBrain."""
        return OpponentAdvice(
            supply_adjustment={...},     # Pillar 5a
            preempt_sell=[...],          # Pillar 5b
            delay_sell=[...],            # Pillar 5c
            counter_pick=[...],          # Pillar 5e
            archetype=self.archetype,
        )
```

### OpponentAdvice Dataclass

```python
@dataclass
class OpponentAdvice:
    # For MacroPlanner: additional supply to factor into crop scoring
    supply_adjustment: Dict[str, float]   # product → extra units to add
    
    # For MarketBrain: products to rush-sell before opponent dumps
    preempt_sell: List[str]
    
    # For MarketBrain: products to hold (opponent just crashed the price)
    delay_sell: List[str]
    
    # For MacroPlanner: products opponent doesn't produce (monopoly opportunity)
    counter_pick: List[str]
    
    # Metadata
    archetype: str
    opp_shed_pressure: float  # 0.0-1.0
    opp_dominant_products: List[str]
```

---

## Phased Implementation Plan

### Phase 1: Foundation — Accurate Data Collection *(fix what exists)*

#### [MODIFY] [state_tracker.py](file:///d:/website%20project/kaggri%20ox/agent/state/state_tracker.py)
- Wire `record_our_sale()` to be called after every SELL order is composed (track our own sales accurately)
- Add `prev_opp_money` tracking to persistent `_STATE`
- Add `opp_money_deltas` history (last N turns of Δmoney)
- Fix drain ledger attribution: subtract our confirmed sales before attributing remainder to opponent

#### [MODIFY] [opponent_model.py](file:///d:/website%20project/kaggri%20ox/agent/state/opponent_model.py)
- Add `_snapshot_tiles(opp_farm)` → compact tile state for delta comparison
- Add `_detect_harvests(opp_farm, prev_snapshot)` → detect `yield_units` decrements and tile clearing
- Add `_track_money_delta(current_money, prev_money, market_delta)` → infer buys/sells from money changes

**Tests:** 8–10 unit tests covering delta detection, money inference, harvest identification

---

### Phase 2: Production Forecasting *(Pillar 1)*

#### [MODIFY] [opponent_model.py](file:///d:/website%20project/kaggri%20ox/agent/state/opponent_model.py)
- Add `forecast_production(opp_farm, current_day)` → builds day-by-day harvest schedule for all visible crops/animals
- Handle one-time vs. ongoing crops with exact engine math
- Track fertilization status (visible) for yield predictions
- Track animal placement days and production intervals
- Account for death risk: `consecutive_unwatered >= 2` → plant will die tonight

**Tests:** 6–8 tests covering wheat cycles, melon timing, ongoing tomato/strawberry, animal production schedules

---

### Phase 3: Shed Inference & Sell Prediction *(Pillars 2 + 3)*

#### [MODIFY] [opponent_model.py](file:///d:/website%20project/kaggri%20ox/agent/state/opponent_model.py)
- Add `estimate_shed(harvest_events, inferred_sales, animal_feed)` → running estimate of opponent's shed
- Add `compute_sell_probability(product, shed_estimate, farm_state)` → probability scoring with signal weights
- Track opponent farmer/hand movement patterns relative to shed tiles

**Tests:** 8–10 tests for shed reconstruction accuracy, sell probability calibration

---

### Phase 4: Strategy Classification *(Pillar 4)*

#### [MODIFY] [opponent_model.py](file:///d:/website%20project/kaggri%20ox/agent/state/opponent_model.py)
- Add `classify_archetype(opp_farm, day, money_history)` → archetype enum
- Bayesian update: initial classification at day 3, refined through day 10
- Track capital allocation pattern: % spent on seeds vs. animals vs. land vs. hires

**Tests:** 4–6 tests covering each archetype detection from synthetic farm states

---

### Phase 5: Tactical Advisor *(Pillar 5)*

#### [NEW] [opponent_advisor.py](file:///d:/website%20project/kaggri%20ox/agent/strategy/opponent_advisor.py)
- `OpponentAdvice` dataclass
- `build_advice(model, ctx, forecast)` → translates raw model state into planner/brain-compatible adjustments
- Supply adjustment calculator: `opp_production * glut_weight` per product
- Pre-empt/delay logic with configurable thresholds
- Counter-pick identification: products with zero opponent investment + nonzero shop demand

**Tests:** 6–8 tests covering each tactical response pathway

---

### Phase 6: Comprehensive Integration Tests

#### [NEW] [test_opponent_model.py](file:///d:/website%20project/kaggri%20ox/agent/tests/test_opponent_model.py)
- End-to-end multi-turn scenarios with synthetic observations
- Validate shed inference converges to ground truth over 5–10 turns
- Validate archetype classification accuracy on Agent Zoo archetypes
- Validate sell-probability signals fire correctly before major opponent dumps
- Test against real engine replays (if available from tournament runner)

---

## Open Questions

> [!IMPORTANT]
> **Q1: Shed inference accuracy tolerance.** The estimated shed will drift from reality due to unobservable seed purchases and partial harvest pickups. Should we maintain a **confidence interval** (min/max bounds) rather than a point estimate? This adds complexity but prevents false-positive pre-emptive sells.

> [!IMPORTANT]
> **Q2: How aggressively should pre-emptive selling override normal sell windows?** Currently MarketBrain only sells on `hour % 4 == 1`. If we detect an imminent opponent dump, should we sell on ANY hour, or only expand to the next available window?

> [!IMPORTANT]
> **Q3: Should the archetype classifier influence crop selection directly (hard switch) or as a soft multiplier on existing crop scores?** Hard switching ("they're a Wheat Rusher, so plant zero wheat") is risky if classification is wrong. A soft penalty multiplier (e.g., 0.7× score for their dominant product) is safer.

## Verification Plan

### Automated Tests
- `pytest agent/tests/test_opponent_model.py -v` — all new unit tests for Pillars 1–5
- `pytest agent/tests/ -v` — full agent test suite regression (185+ tests passing)
- Synthetic multi-turn scenario tests validating shed inference convergence

### Manual Verification
- Run tournament matches (via `simulations/experiments/tournament_runner.py`) against Agent Zoo bots **with opponent model enabled vs disabled** and compare win rates across 50+ seeds
- Inspect diagnostic logs showing archetype classification, shed estimates, and sell-probability signals during replays
