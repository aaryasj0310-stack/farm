# Kaggriculture Competition — Deep Analysis & Winning Strategy

## 1. Competition Summary

**Kaggriculture** is a Kaggle two-player competitive farming simulation. Each player manages a 10×10 farm grid over **30 days (720 turns)**, buying seeds/animals, planting, watering, harvesting, and selling on a dynamic market. **Whoever has the most coins at the end wins.**

---

## 2. Core Mechanics Breakdown

### 2.1 Economy & Starting Conditions

| Parameter | Value |
|---|---|
| Starting money | \$3,000 |
| Season length | 30 days × 24 turns/day = **720 turns** |
| Starting land | 1 quadrant (5×5 = 25 tiles) |
| Land costs | \$1k → \$2k → \$4k (cumulative \$7k for full 100 tiles) |
| Shed capacity | 100 non-seed items |
| Max market orders/turn | 10 |

### 2.2 Crop Economics (Detailed)

| Crop | Seed | Base Price | First Yield | Max Yield Day | Yield (unfert) | Yield (fert) | Type | ROI Cycle |
|---|---|---|---|---|---|---|---|---|
| **Wheat** | \$10 | \$25 | Day 2 | Day 4 | 4 | 6 | One-time | 2–4 days |
| **Carrot** | \$20 | \$35 | Day 2 | Day 3 | 3 | 4 | One-time | 2–3 days |
| **Tomato** | \$50 | \$60 | Day 8 | Day 11 | 4 total (4 yields of 1) | Up to 8 (4 yields of 2) | Ongoing | 8–11 days |
| **Strawberry** | \$100 | \$120 | Day 10 | Day 16 | 4 total | Up to 8 | Ongoing | 10–16 days |
| **Melon** | \$80 | \$250 | Day 10 | Day 10 | 6 | 6 | One-time | 10 days |

#### Key Yield Insights

- **Wheat**: Best yield/tile/day at 0.80. Cheap, fast, highly versatile. Also serves as **animal feed**.
- **Carrot**: Decent yield/tile/day at 0.75 but carrot uses **hinge** scarcity pricing — price explodes past \$70 if demand exceeds supply threshold T=450.
- **Tomato**: Low yield/tile/day (0.33) but hinge pricing means scarcity spikes are lucrative. Each yield is only 1 unit though.
- **Strawberry**: Lowest yield/tile/day (0.24) but base price is \$120. Premium pricing with linear above_target=1.60 means gluts crash it to \$1 fast.
- **Melon**: High base price (\$250) but **catastrophic glut behavior** — sq above_target=3.60 drives price to \$1 at I0+T. Only profitable if you sell before the market saturates.

### 2.3 Animal Economics

| Animal | Cost | Structure | Yield | Base Price | Interval | Yield/tile/day | Feed Cost |
|---|---|---|---|---|---|---|---|
| **Goose** | \$300 | Coop (\$10 wheat seed equiv) | Eggs | \$50 | Daily | 1.00 | 1 wheat/day |
| **Cow** | \$400 | Pasture (\$10) | Milk | \$160 | Every 2 days | 0.50 | 1 wheat/day |
| **Sheep** | \$500 | Pasture (\$10) | Wool | \$200 | Every 3 days | 0.33 | 1 wheat/day |

> [!IMPORTANT]
> Animals produce **indefinitely** as long as fed. This is the single most important strategic differentiator — unlike crops that die, animals are perpetual income machines. The `max_held` cap is on unharvested product sitting on the tile, NOT lifetime output.

#### Animal Profitability (Raw, ignoring market dynamics)

- **Goose**: 1 egg/day × \$50 = \$50/day. Feed cost: ~\$25/day (wheat at base). **Net ~\$25/day per goose.** Break-even in ~12 days after setup.
- **Cow**: 0.5 milk/day × \$160 = \$80/day. Feed: ~\$25/day. **Net ~\$55/day per cow.** Break-even in ~8-9 days after first yield.
- **Sheep**: 0.33 wool/day × \$200 = \$66/day. Feed: ~\$25/day. **Net ~\$41/day per sheep.** Break-even in ~12-15 days.

> [!WARNING]
> **Milk and wool have brutal above-market curves.** `linear` with above_target 1.60 for milk and `sq` with above_target 3.20 for wool means even modest oversupply crashes prices to \$1. You must **time sales carefully** and not flood the market.

### 2.4 Market Price Dynamics — The Heart of Strategy

The price function is:
```
price(inv) = base + sign · amp · f(|inv − I0|)
```

**Critical observations:**

1. **Hinge resources (Carrot, Tomato, Egg)** are the most strategically interesting. Below the knee (T units below I0), price rises linearly — manageable. Past the knee, the `8·max(0, u−1)²` quadratic explodes. If town shops consume enough, these prices can skyrocket.

2. **Premium resources (Strawberry, Melon, Milk, Wool)** have `above_target > 1`, meaning selling even T units past I0 crashes the price to \$1. These are **sell-timing games** — you must sell in small batches and watch market inventory.

3. **Wheat is uniquely resilient.** `sqrt` scarcity (rises well under shortage) but `log` glut absorption (barely drops when oversupplied). Wheat is the safest commodity and also serves as animal feed. **Wheat is the backbone of any strategy.**

4. **Fertilizer** has symmetrical linear pricing. At \$100 base, it's only worth buying if the extra yield it produces exceeds its cost.

### 2.5 Town Shop Demand — The Price Driver

Shops unlock every 3 days (days 3, 6, 9, 12, 15, 18, 21, 24, 27 — up to 8 instances, with replacement). Each shop instance consumes product every 4 turns (6× per day). Town center consumes 1 of each non-fertilizer product per day.

**Demand calculation per shop (per day):**
- Each shop instance consumes 1 of each demanded product every 4 turns = **6 units/product/day**
- Single-product shops consume **12 units/product/day** (2× rate)

| Shop | Demands | Units/day per instance |
|---|---|---|
| Bakery | eggs, wheat | 6 eggs, 6 wheat |
| Pizza Shop | milk, tomatoes, wheat | 6 each |
| Brunch Spot | eggs, wheat, strawberries | 6 each |
| Yarn Store | wool (2×) | 12 wool |
| Ice Cream Shop | strawberries, milk, wheat | 6 each |
| Pet Cafe | carrots (2×) | 12 carrots |
| Smoothie Shop | strawberries, milk | 6 each |
| Farmers Market | wheat, carrots, tomatoes, strawberries | 6 each |

> [!TIP]
> **Town shops are drawn with replacement.** Getting 2-3 Pet Cafes means carrot demand explodes (24-36/day), draining market inventory and driving carrot prices through the hinge ceiling. **Monitor `unlocked_shops` every observation and adapt.**

### 2.6 Action Economy

Each farmer/hand gets **1 action per turn**. With 24 turns/day, the main farmer gets 24 actions/day. Farm hands are temporary (hired daily, cost increases per Fibonacci).

**Action cost analysis for a typical tile lifecycle:**
1. Move to tile (1+ turns)
2. PLANT (1 turn)
3. WATER (1 turn/day for duration)
4. HARVEST (1 turn)
5. DROP at shed (1 turn, if needed)

For wheat: ~2 actions to plant, 2-4 actions to water over 2-4 days, 1 to harvest, 1 to drop = **6-8 actions per wheat cycle** on a single tile. With pathing overhead, maybe 8-12. A single farmer can manage roughly **3-5 wheat tiles** efficiently.

### 2.7 The Shed Bottleneck

- 100 item cap (excluding seeds)
- Items overflow at end-of-day → **discarded forever**
- You MUST sell regularly or lose production

---

## 3. Strategic Analysis — How to Win

### 3.1 Phase Planning (30-day season)

#### Phase 1: Days 0–3 (Bootstrap)
- **Goal**: Establish income engine with minimal capital
- Plant wheat on available tiles (cheap, fast ROI)
- Sell first wheat harvest by day 2-3 to recycle capital
- Buy 1-2 animal structures early if capital allows

#### Phase 2: Days 3–10 (Scaling)
- First shop unlocks day 3 — **read the shop type and adapt**
- If Pet Cafe: pivot to carrots (hinge pricing will spike)
- If Bakery/Brunch: invest in geese (egg demand + wheat consumption)
- Buy NE quadrant (\$1k) for more farm space
- Start placing animals (goose first — cheapest, daily production, eggs demanded by 2 shop types)
- Consider melon seeds (day 0-2 planting for day 10 harvest)

#### Phase 3: Days 10–20 (Peak Production)
- Multiple shops unlocked → market demand is high → prices rising for scarce goods
- Animals producing → steady income stream
- Hire farm hands (cost is cheap early: 1, 1, 2, 3...) to scale operations
- **Watch premium prices** — if strawberry/milk/wool prices are elevated, sell; if they've crashed, hold
- Buy more land if needed for animal expansion

#### Phase 4: Days 20–30 (Cash Out)
- **Stop investing, maximize liquidation**
- Sell everything in shed at best prices
- No more seed purchases after ~day 25 (won't mature in time)
- Animals keep producing — harvest and sell daily
- Time final sales to avoid crashing your own prices

### 3.2 Crop Strategy Tier List

| Tier | Crop/Animal | Why |
|---|---|---|
| **S** | Goose (eggs) | Cheapest animal, daily production, hinge pricing on scarcity, 2 shop types demand it |
| **S** | Wheat | Backbone. Fast ROI, resilient pricing, needed as animal feed, demanded by 5/8 shop types |
| **A** | Cow (milk) | High base price, decent production rate, but price crashes on oversupply |
| **A** | Carrot | Great with Pet Cafe (hinge pricing explosion), otherwise decent |
| **A** | Melon | Highest single-harvest value (\$250 × 6 = \$1500), but brutal glut curve |
| **B** | Sheep (wool) | Highest base price but slowest production, very fragile pricing |
| **B** | Tomato | Hinge pricing can spike, but low yield rate |
| **C** | Strawberry | Very slow to mature (day 10), premium but easily crashed |

### 3.3 Critical Strategic Insights

> [!IMPORTANT]
> #### Insight 1: The Opponent's Farm Is Visible
> You can see your opponent's tiles, farmer position, and money. Use this to:
> - Anticipate what they'll sell (if they have 20 wheat ready, expect wheat prices to drop)
> - Sell BEFORE them if you have the same product
> - Counter-pick crops they're NOT growing (less competition on market)

> [!IMPORTANT]
> #### Insight 2: Market Orders Are Processed Concurrently
> When both players sell the same product, orders alternate one unit at a time. Selling first in the order matters less than volume — but if you sell when your opponent is also dumping, prices drop 2× as fast.

> [!TIP]
> #### Insight 3: Fertilizer Is Free From Animals
> Every surviving animal produces 1 fertilizer/day via `COLLECT_FERTILIZER`. This is free and:
> - Can be sold (\$100 base, linear pricing)
> - Can be used to boost crop yields
> - Is an **often-overlooked income source** (~\$100/animal/day at base price)

> [!TIP]
> #### Insight 4: Hiring Is Extremely Cheap Early
> First two hires cost 1 coin each. Third costs 2. Four hires = 7 coins total. That's 4 extra workers for essentially free. **Always hire 2-4 hands per day** for massive action throughput.

> [!TIP]
> #### Insight 5: Day 0 Planting Trap
> A seed planted on day 0 starts with `consecutive_unwatered = 1`. If you don't water it on day 0, it hits 2 at end-of-day and becomes a weed **before it grows**. Always water on the planting day!

---

## 4. Tool-Based Strategy Development Approach

Here's how I'd use available tools to systematically develop a winning agent:

### 4.1 Phase A: Deep Environment Research

**Tools: Web search, URL reading, codebase analysis**

1. **Read the actual game engine source** (`kaggriculture.py`) — the rules doc is a summary but the source code is ground truth
   - Search for the exact price function implementation
   - Verify yield calculations, edge cases, decay mechanics
   - Find any undocumented behaviors or bugs

2. **Study the Kaggle competition page and forums**
   - Web-search for top-scoring notebooks, forum posts, strategy discussions
   - Look for meta-shifts (what the leaderboard is converging on)
   - Read winning agent code from similar past competitions (Halite, Lux AI, etc.)

3. **Analyze the starter agents** — `"random"`, `"starter"`, `"pass"` to understand baseline behavior

### 4.2 Phase B: Mathematical Modeling

**Tools: Python scripting, local execution**

1. **Build a price simulator** — implement the exact price function and simulate:
   - How fast does wheat price recover after dumping 100 units?
   - What's the optimal batch size for selling premium goods?
   - How do different shop unlock combinations affect equilibrium prices?

2. **Build a crop profitability calculator** accounting for:
   - Seed cost amortization
   - Action cost (opportunity cost of turns spent watering vs. planting new)
   - Market price at time of sale (not just base price)
   - Fertilizer ROI analysis per crop type

3. **Monte Carlo town shop simulations** — since shops are random with replacement:
   - What's the probability of getting N Pet Cafes? (each one adds 12 carrot demand/day)
   - Expected demand profiles for each product across 1000+ random shop sequences
   - Identify which products have highest expected scarcity value

### 4.3 Phase C: Agent Architecture Design

**Tools: Code writing, subagent delegation**

Build a **multi-layer agent** with:

1. **Observation Parser** — clean struct mapping of the raw observation
2. **State Tracker** — track across turns: market trends, opponent behavior, shop unlocks, own production pipeline
3. **Planner** — decides high-level strategy each day:
   - What to plant/build this day
   - How many hands to hire
   - What to sell and when
4. **Task Scheduler** — assigns specific actions to farmer + each hand:
   - Pathfinding (BFS on the 10×10 grid)
   - Task priority queue (water > harvest > feed > plant > collect fertilizer)
5. **Market Brain** — optimizes sell/buy timing:
   - Tracks price trends
   - Splits large sells into batches across turns
   - Watches opponent's inventory to anticipate their sales

### 4.4 Phase D: Simulation & Iteration

**Tools: Local testing, replay analysis**

1. **Run 100+ games** against `"random"` and `"starter"` to baseline
2. **Analyze replays** — find turns where money was left on the table
3. **A/B test strategies**:
   - Pure wheat vs. mixed crops
   - Early animals vs. late animals
   - Aggressive land expansion vs. intensive single-quadrant
4. **Track win rates** against increasingly sophisticated self-play opponents

### 4.5 Phase E: Advanced Techniques

1. **Opponent modeling** — since their farm is visible:
   - Predict their next sell based on what's ready to harvest
   - Undercut their sales by selling first
   - Invest in products they're NOT producing

2. **Dynamic adaptation** — adjust strategy based on shop unlocks:
   - Pre-computed response tables for each shop type
   - Recalculate optimal crop mix when a new shop appears

3. **End-game optimization** — stop investing at the right time:
   - No seeds after day ~22-25 (depending on crop)
   - Liquidate entire shed in final 2-3 days
   - Sell animals' structures are pointless to tear down (free production)

---

## 5. Quick-Win Strategy (Minimum Viable Agent)

For an immediate strong baseline, implement this sequence:

```
Day 0, Turn 0:
  - BUY_SEED WHEAT 10
  - HIRE (2 hands)
  
Day 0, Turns 1-23:
  - Farmer + hands: PLANT wheat on tiles around shed, WATER immediately
  
Day 1-2:
  - Continue watering wheat
  - BUY_SEED WHEAT 10 more
  - Start building 1 coop + BUY_ANIMAL GOOSE
  
Day 2+:
  - HARVEST mature wheat → DROP in shed → SELL
  - Replant immediately
  - Feed goose with wheat
  - COLLECT_FERTILIZER from goose → SELL
  
Day 3: First shop unlocks → adapt crop mix
Day 6: Second shop → further adapt
...continue scaling with more animals and adaptive crop selection...
```

---

## 6. Key Numbers to Remember

| Metric | Value |
|---|---|
| Total turns | 720 |
| Starting money | \$3,000 |
| Wheat ROI | \$90-150 per tile per cycle (2-4 days) |
| Goose daily income | ~\$50 eggs + \$100 fertilizer = **~\$150/day** |
| Cow daily income | ~\$80 milk + \$100 fertilizer = **~\$180/every 2 days** |
| Max farm hands affordable day 1 | 4-5 (costs 1+1+2+3+5 = 12 coins) |
| Shed overflow threshold | 100 items — sell before hitting this |
| Shop unlock schedule | Days 3, 6, 9, 12, 15, 18, 21, 24 |
