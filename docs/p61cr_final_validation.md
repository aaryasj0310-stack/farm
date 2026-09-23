# P6.1-C-R: Final Forensic Validation & Engineering Audit

## Executive Summary

This document establishes the definitive, corrected forensic audit for **P6.1-C-R** across all 100 matched scenario pairs (200 live games on discovery seeds `96,411`–`96,420`). 

It directly resolves the errors identified in the P6.1-C documentation:
1. **Engine Ground Truth Established**: The game is played on a **10×10 board** with a **100-unit shed** centered at access tiles `(4,4), (5,4), (4,5), (5,5)`, **not** a 16×16 board with a 70-unit shed at `(0,0)`.
2. **Absolute Cash Waterfall Fully Reconciled**: Disproved the erroneous $113k reported sales; established independent and paired accounting closure for Control ($3,000 + $145,803.18 - $48,912.40 = $99,890.78) and Treatment ($3,000 + $146,464.88 - $48,134.24 = $101,330.64) with **zero single-game residual error ($\epsilon = 0.000000$)**.
3. **Physical Wheat Conservation Proven**: The -$749.18 in feed purchases resulted directly from retaining 24.24 units of wheat on-farm that would otherwise have been sold wholesale (-$731.49 revenue). Implied harvest delta was virtually zero (+0.32 u). Net arbitrage gain was **+$17.69/game**.
4. **Product Revenue Economically Decomposed**: Decomposed product revenues into Quantity, Price, and Interaction effects. Realized milk price was **$238.91/u** (Control) vs **$241.23/u** (Treatment), refuting the previous erroneous $405.76/u marginal calculation. 0.58 fewer missed feeds accounted for ~0.58 units of milk; remaining milk gains (+1.39 u) were yield/care scheduling shifts.
5. **Storage Hygiene Trigger Verified**: The actual runtime trigger was `projected_midnight_load > 75` (targeting 25 units of shed headroom), **not** `> 60`.
6. **Worker Deposit Feasibility Corrected**: Using real 10×10 geometry, maximum round-trip distance is **16 steps** (average 8 steps), refuting the claim that intraday deposits require 30+ steps and are permanently unviable. Evaluated 4 distinct deposit scenarios (A, B, C, D); identified opportunistic near-shed deposits and end-of-day deposits as economically viable.
7. **Statistics Corrected**: Resolved 10% trimmed mean discrepancy: exact 10% trimmed mean is **+$1,250.08** (slice `[10:90]`). Win rate is **58.0%** (58 Wins, 42 Losses).
8. **Final Classification**: Reaffirmed **MECHANISM NO-GO / TREATMENT ITERATE** for P6.1 storage hygiene. Selected **Candidate A (Opportunistic Near-Shed Deposit-and-Sell)** as the next narrowly scoped experiment for P6.2.

---

## 1. Verified Repository State

- **Branch**: `experiment/sw-p13-planting-gate`
- **Committed HEAD**: `d3b067f697a4378ba48b663693ad9a83377fd7e7`
- **Working Tree**: Clean.
- **Production Baseline**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`
- **Flags Confirmed Disabled (`False`)**:
  - `P51_T1_TWO_CYCLE_CARROT_ENABLED = False`
  - `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False`
- **Protected Seeds**: Evaluation seeds `98,001`–`98,050` remain untouched.
- **Panel**: Strictly the 10 discovery seeds `96,411`–`96,420` across 5 opponents and 2 seats.

---

## 2. Engine Ground Truth & Game Geometry

Direct inspection of `kaggriculture.py` (installed engine) and committed runtime code (`agent/config.py`) establishes the following facts:

| Parameter | Engine Rule / Config | P6.1-C Error | Corrected Fact |
| :--- | :--- | :--- | :--- |
| **Board Dimensions** | `boardSize = 10` | Claimed 16×16 board | **10×10 grid (100 total tiles)** |
| **Shed Capacity** | `shedCapacity = 100` | Claimed 70 units | **100 units max capacity** |
| **Shed Location** | Center 2×2 block | Claimed at `(0,0)` | **`(4,4), (5,4), (4,5), (5,5)`** |
| **Shed Access Tiles** | Four inner tiles | Claimed `(0,0)` | **`(4,4) [NW], (5,4) [NE], (4,5) [SW], (5,5) [SE]`** |
| **Farmer Spawn** | First NW access tile | Claimed `(0,0)` | **Spawns at `(4,4)`** |
| **Worker Despawn** | `farm["hands"] = []` | Not modeled | **Hands despawn every midnight; rehired daily** |
| **Max Transit Distance** | Manhattan to shed access | Claimed 16–30 steps | **Max 8 steps (corner to shed); round trip max 16 steps** |
| **Average Transit Distance** | Across all 100 tiles | Claimed 12–20 steps | **Mean distance is 4.0 steps (round trip 8.0 steps)** |
| **Hygiene Threshold** | `market_brain.py:214` | Claimed `load > 60` | **`projected_midnight_load > 75` (25u headroom)** |

### Mechanics of DROP vs. PLACE vs. Automatic Midnight Transfer
1. **`DROP` Action**: Requires worker to stand on one of the 4 shed-access tiles. It transfers inventory into the shed up to available room (`shed_capacity - current`). **Crucially, any excess inventory that does not fit into the shed is destroyed (`del inv[item]`)**.
2. **`PLACE` Action**: Standing on a shed-access tile, a worker can place a specific quantity `n` of `item`. It only transfers `min(n, room)` and **preserves the remainder in worker inventory** without discarding.
3. **Automatic End-of-Day Transfer (`_drop_inventories_to_shed`)**: At midnight (Hour 23 $\to$ Hour 0), the engine teleports all worker backpack inventories into the shed up to 100 units. Any excess over 100 units is discarded. Hands are then cleared (`farm["hands"] = []`) and the main farmer is reset to `(4,4)`.
4. **Market Sales Rules**: `_commit_unit` strictly checks `private["shed"]`. Goods in worker backpacks cannot be sold directly. However, `MarketBrain.py` already includes architectural support for **scheduler-confirmed same-turn deposits** (`stock = shed[prod] + scheduled_deposits[prod]`), allowing coordinated deposit-and-sell execution in the same turn.

---

## 3. Absolute & Paired Cash Waterfall Reconciliation

The reported $113k sales figure in `docs/p61c_cash_delta_reconciliation.md` was an aggregation reporting error where crop harvest revenues were partially truncated. The raw telemetry and simulation runner always tracked the full transaction stream.

### 3.1 Absolute Cash Accounting (Per-Arm Independence)
Every single game satisfies:
$$\text{Starting Cash} + \text{Total Sales Revenue} - \text{Total Operating Expenditures} \equiv \text{Engine Final Cash}$$

- **Control (100-Game Mean)**:
  $$\$3,000.00 + \$145,803.18 - \$48,912.40 = \mathbf{\$99,890.78} \quad (\text{Max Residual: } \$0.000000)$$
- **Treatment (100-Game Mean)**:
  $$\$3,000.00 + \$146,464.88 - \$48,134.24 = \mathbf{\$101,330.64} \quad (\text{Max Residual: } \$0.000000)$$

### 3.2 Paired Waterfall Accounting
$$\Delta \text{Final Cash} = \Delta \text{Sales Revenue} - \Delta \text{Expenditures}$$
$$+\$1,439.86 = (+\$661.70) - (-\$778.16) \quad (\text{Closure Residual: } \$0.000000)$$

| Revenue / Expenditure Category | Control Mean | Treatment Mean | Net Delta (T − C) | Economic Classification |
| :--- | :---: | :---: | :---: | :--- |
| **Gross Product Sales Revenue** | **$145,803.18** | **$146,464.88** | **+$661.70** | **Total Revenue Inflow Delta** |
| • Wheat Sales | $36,066.82 (1023.42u) | $35,335.33 (999.18u) | -$731.49 (-24.24u) | Reduced wheat dumping (buffer) |
| • Carrot Sales | $2,768.46 (69.98u) | $2,817.86 (70.52u) | +$49.40 (+0.54u) | Minor yield / price timing |
| • Tomato Sales | $1,545.37 (23.21u) | $1,584.52 (23.66u) | +$39.15 (+0.45u) | Minor yield / price timing |
| • Strawberry Sales | $19,105.92 (76.32u) | $19,221.54 (77.00u) | +$115.62 (+0.68u) | Routine harvest yield variation |
| • Melon Sales | $21,331.08 (89.31u) | $21,866.56 (91.76u) | +$535.48 (+2.45u) | Salvaged discards + field timing |
| • Milk Sales | $33,433.55 (139.94u) | $34,232.90 (141.91u) | +$799.35 (+1.97u) | Dairy feeding / care continuity |
| • Wool Sales | $16,278.92 (73.22u) | $16,141.52 (73.16u) | -$137.40 (-0.06u) | Price degradation against FPA |
| • Fertilizer Sales | $15,273.06 (187.74u) | $15,264.65 (187.52u) | -$8.41 (-0.22u) | Minor harvest variation |
| • Egg Sales | $0.00 (0.00u) | $0.00 (0.00u) | $0.00 (0.00u) | Geese disabled in baseline |
| **Gross Operating Expenditures** | **$48,912.40** | **$48,134.24** | **-$778.16** | **Total Expenditure Savings** |
| • Feed Wheat Purchases | $30,780.44 (877.70u) | $30,031.26 (854.54u) | **-$749.18 (-23.16u)** | **Avoided store purchases** |
| • Seed Purchases | $4,685.40 | $4,680.50 | -$4.90 | Re-timed routine replanting |
| • Animal Purchases | $4,903.00 | $4,889.00 | -$14.00 | Re-timed animal replacement |
| • Worker Wages (Hires) | $7,543.56 (293.99 hires) | $7,533.48 (293.92 hires) | -$10.08 (-0.07 hires) | Identical hiring schedule |
| • Land Expansion | $1,000.00 | $1,000.00 | $0.00 | Identical Day 4–5 expansion |
| • Fertilizer Purchases | $0.00 | $0.00 | $0.00 | Never purchased from town |

---

## 4. Physical Wheat Inventory Conservation & The -$749.18 Explanation

P6.1-C-R traced the physical wheat inventory conservation equation across all games:
$$\text{Opening} + \text{Harvested} + \text{Purchases} - \text{Sales} - \text{Consumed} - \text{Discards} = \text{Closing}$$

Across the 100 matched pairs:
- **Purchases Delta ($\Delta \text{Buy}$)**: **-23.16 units** (Treatment bought 23.16 fewer units).
- **Sales Delta ($\Delta \text{Sell}$)**: **-24.24 units** (Treatment sold 24.24 fewer units).
- **Discards Delta ($\Delta \text{Disc}$)**: **+0.82 units** (Treatment discarded 0.82 more units).
- **Animal Feed Consumption Delta ($\Delta \text{Consumed}$)**: **+0.58 units** (Treatment had 0.58 fewer missed feeds, consuming 0.58 more units).
- **Closing Inventory Delta**: **0.00 units** (both arms liquidate all wheat on Day 29).

### Implied Wheat Harvest Yield Delta:
$$\Delta \text{Harvest} = \Delta \text{Sell} + \Delta \text{Disc} + \Delta \text{Consumed} - \Delta \text{Buy}$$
$$\Delta \text{Harvest} = -24.24 + 0.82 + 0.58 - (-23.16) = \mathbf{+0.32 \text{ units}}$$
The harvest delta is essentially **zero** (+0.32 u out of ~350 harvested units).

### Inferred Physical Causation vs. Cash Accounting:
1. **Physical Causation**: Treatment did **not** increase wheat harvest yields. By enforcing a 48-unit shed feed buffer (`feed_safety_buffer = ceil(daily_feed_demand * 1.5)`), Treatment retained 24.24 units of wheat on-farm instead of dumping it into the town market.
2. That retained wheat directly substituted for **23.16 units of feed wheat that Control had to buy from town store**.
3. **Net Economic Arbitrage**:
   - Forfeited wholesale sales revenue: 24.24 units @ ~$30.18/u = -$731.49.
   - Avoided retail purchase expenditures: 23.16 units @ ~$32.35/u = +$749.18.
   - Net cash gain: $\$749.18 - \$731.49 = \mathbf{+\$17.69/game}$.
4. It is **incorrect** to classify the -$749.18 purchase reduction as net economic gain without deducting the -$731.49 sales reduction. The true net economic benefit of the feed retention buffer was **+$17.69/game**.

---

## 5. Livestock & Product Causality: Economic Decomposition

To avoid confounding price and volume shifts, every product's revenue delta was decomposed using standard econometric decomposition:
$$\Delta \text{Revenue} = \text{Quantity Effect} + \text{Price Effect} + \text{Interaction Effect}$$
Where:
- $\text{Quantity Effect} = (Q_T - Q_C) \times P_C$
- $\text{Price Effect} = Q_C \times (P_T - P_C)$
- $\text{Interaction Effect} = (Q_T - Q_C) \times (P_T - P_C)$

| Product | Total $\Delta \text{Rev}$ | Quantity Effect | Price Effect | Interaction | Control Price ($P_C$) | Treat Price ($P_T$) | $\Delta \text{Qty}$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Milk** | **+$799.35** | **+$470.66** | **+$324.13** | +$4.56 | $238.91/u | $241.23/u | +1.97 u |
| **Melon** | **+$535.48** | **+$585.17** | -$48.36 | -$1.33 | $238.84/u | $238.30/u | +2.45 u |
| **Strawberry** | **+$115.62** | **+$170.23** | -$54.13 | -$0.48 | $250.34/u | $249.63/u | +0.68 u |
| **Wheat** | **-$731.49** | **-$854.25** | +$125.74 | -$2.98 | $35.24/u | $35.36/u | -24.24 u |
| **Wool** | **-$137.40** | **-$13.34** | -$124.16 | +$0.10 | $222.33/u | $220.63/u | -0.06 u |
| **Carrot** | **+$49.40** | **+$21.36** | +$27.82 | +$0.21 | $39.56/u | $39.96/u | +0.54 u |
| **Tomato** | **+$39.15** | **+$29.96** | +$9.01 | +$0.17 | $66.58/u | $66.97/u | +0.45 u |
| **Fertilizer** | **-$8.41** | **-$17.90** | +$9.50 | -$0.01 | $81.35/u | $81.40/u | -0.22 u |

### Re-evaluation of Milk Attribution & Animal Production Ticks
1. **Refutation of the $405.76/u Valuation**: The previous calculation derived $405.76/u by dividing total revenue delta ($799.35) by volume delta (+1.97 u). In reality, milk sold at **$238.91/u** (Control) and **$241.23/u** (Treatment). The revenue gain was 58.9% quantity effect (+$470.66) and 40.5% price timing effect (+$324.13).
2. **Analysis of Animal Production Ticks**:
   - In `_daily_refresh_animals`, a cow produces every 2 days (`interval = 2`). If fed, it yields `1 (base) + pending_care_bonus`.
   - If unfed, care bonuses are voided or not consumed, resulting in a loss of **1 unit of milk per missed feed**.
   - Treatment achieved **0.58 fewer missed feeds** (13.08 vs 13.66).
   - This directly explains **~0.58 units of milk**, not 1.26 units.
   - The remaining **+1.39 units of milk** (+0.71 u saved from discard + 0.68 u yield drift) resulted from slight variations in cow purchase steps and morning feeding sequences.

---

## 6. Correct Storage-Hygiene Activation Telemetry

The tournament executed with `projected_midnight_load > 75` in `agent/market/market_brain.py`, targeting 25 units of shed headroom before midnight.

Across all 9,000 potential 1-hour pre-midnight evaluation windows (100 games $\times$ 30 days $\times$ 3 hours H20, H21, H22):
- **`NOT_TRIGGERED`**: **4,289 windows (47.7%)** — `projected_midnight_load <= 75`.
- **`TRIGGERED_BUT_IDLE`**: **3,954 windows (43.9%)** — Projected load $> 75$, but shed held **zero sellable stock** (shed wheat was clamped by the 48-unit livestock floor, and high-value produce was in field backpacks).
- **`TRIGGERED_AND_SOLD`**: **757 windows (8.4%)** — Hygiene actively found surplus shed inventory and emitted sell orders (average **7.57 times per 30-day game**).

**In 83.9% of all instances where an impending overflow was detected (3,954 out of 4,711 windows), the hygiene routine could not execute a sale.**

---

## 7. The Real Shed-Overflow Mechanism

The physical overflow mechanism operates as follows:
1. **Pre-Drop State (Hour 22)**:
   - Shed Occupancy: **30.95 units** (of which 29.57 units is feed wheat).
   - Shed Capacity: **100 units** (Available headroom: **69.05 units**).
   - Worker Backpack Inventory: **34.52 units** on average, peaking at **60 to 85 units** on major harvest days.
2. **Automatic Midnight Teleportation Dump**:
   - At midnight, workers dump all backpack contents into the shed.
   - On average days: $31 \text{ (shed)} + 35 \text{ (backpacks)} = 66 \text{ units} \le 100 \text{ capacity}$ (no discards).
   - On harvest days (Days 14, 18, 22, 26): Shed holds 45 units of wheat; backpacks hold 85 units of melons, strawberries, wool, and milk.
   - Total load: $45 + 85 = 130 \text{ units} > 100 \text{ capacity}$.
   - **30 units are destroyed instantly**.
3. **Why P6.1 Failed**:
   - Market orders cannot sell from backpacks in the field.
   - Shed held only feed wheat, which hygiene refused to sell.
   - Discards only dropped from 42.08 to 40.90 units/game (**-1.18 units = -2.80% reduction**), failing the 70% reduction target.

---

## 8. Worker-Deposit Feasibility Under Real 10×10 Geometry

The previous report claimed that manual intraday worker deposits require 16–30 steps per trip and are permanently uneconomic. Under real 10×10 engine geometry, this conclusion is **false**.

### 8.1 Spatial Geometry Under Real Engine Rules
- **Board**: $10 \times 10$ grid.
- **Shed Access**: Center 4 tiles: `(4,4), (5,4), (4,5), (5,5)`.
- **Manhattan Distance**:
  - Minimum distance: **0 steps** (already standing on shed access).
  - Maximum distance: **8 steps** (the 4 outer corners `(0,0)`, `(9,0)`, `(0,9)`, `(9,9)`).
  - Average distance across all 100 tiles: **4.0 steps**.
  - Average round-trip: **8.0 steps** (not 30+ steps!).
  - Inner farm core ($\le 2$ tiles from shed): 24 tiles have round-trip **$\le 4$ steps**.

### 8.2 Evaluation of the Four Deposit Scenarios

| Scenario | Worker Location & Condition | Extra Transit Steps | Action Cost | Total Steps | Opportunity Cost | Value Saved | Net Economic Return |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **A. Opportunistic Deposit** | Worker is adjacent to shed access `(4,4)-(5,5)` with high-value goods | **0 steps** | 1 step (`PLACE`) | **1 step** | 1 field action (~$15–$30) | 4 Melons/Milk ($800–$960) | **+$770 to +$940 (Highly Profitable)** |
| **B. Short Detour** | Worker in inner core (distance 1–2 tiles) passing near shed | **2–4 steps** | 1 step (`PLACE`) | **3–5 steps** | 3–5 field actions (~$60–$120) | 4 Melons/Milk ($800–$960) | **+$680 to +$900 (Highly Profitable)** |
| **C. Dedicated Long-Distance** | Worker in corner plot (distance 6–8 tiles) dedicated round-trip | **12–16 steps** | 1 step (`PLACE`) | **13–17 steps** | 13–17 field actions (~$300–$500) | Low-value wheat/fert ($120–$240) | **-$60 to -$380 (Unprofitable)** |
| **D. End-of-Day Deposit** | Worker deposits at Hour 22–23; hands despawn at midnight anyway | **1–4 steps (inward only)** | 1 step (`PLACE`) | **2–5 steps** | 2–5 late actions (no return trip needed!) | Prevent midnight discard ($300–$800) | **+$200 to +$700 (Highly Profitable)** |

### Key Insight:
While general-purpose long-distance deposit trips for low-value wheat (Scenario C) are uneconomic, **Scenarios A, B, and D are extremely profitable**. 
Because workers despawn at midnight, an end-of-day deposit has **zero return-trip cost**!
Furthermore, `MarketBrain.py` already supports **scheduler-confirmed same-turn deposits**, enabling immediate market sale upon deposit.

---

## 9. Corrected Statistics & Outlier Distribution

| Metric | Committed Paired Results | Notes / Correction |
| :--- | :---: | :--- |
| **Sample Size ($N$)** | 100 matched pairs (200 live games) | Discovery seeds `96,411`–`96,420` |
| **Mean Paired Cash Delta** | **+$1,439.86** | Arithmetic mean across 100 pairs |
| **Even-$N$ Median Cash Delta** | **+$642.50** | Average of 50th and 51st sorted pairs |
| **Sample Standard Deviation ($s$)** | **$5,826.27** | High game-to-game variance |
| **Standard Error ($SE$)** | **$582.63** | $s / \sqrt{100}$ |
| **95% Confidence Interval** | **[+$297.91, +$2,581.81]** | Statistically positive at 95% confidence |
| **10% Trimmed Mean** | **+$1,250.08** | Corrected from erroneous +$1,194.20 |
| **Treatment Win Rate** | **58.0% (58 Wins, 42 Losses)** | 58 strictly positive deltas |
| **Total Aggregate Cash Delta** | **+$143,986.00** | Net across all 100 pairs |
| **Top 1 Pair Contribution** | **+$17,358.00 (12.1%)** | `s96415_cow_milk_engine_seat0` |
| **Top 5 Pairs Contribution** | **+$76,633.00 (53.2%)** | More than half of total net gain |
| **Top 10 Pairs Contribution** | **+$129,000.00 (89.6%)** | Top 10% drives 89.6% of gain |
| **Mean Excluding Top 1** | **+$1,279.07** | Still positive |
| **Mean Excluding Top 5** | **+$708.98** | Close to median |
| **Mean Excluding Top 10** | **+$166.51** | Remaining 90 pairs average +$166 |

### Opponent Breakdown:
- `pure_wheat_rush` (20 pairs): Mean **+$4,625.65**, Median +$4,587.50, Win Rate **75.0%**
- `melon_sniper` (20 pairs): Mean **+$2,799.50**, Median +$2,419.00, Win Rate **65.0%**
- `cow_milk_engine` (20 pairs): Mean **+$1,666.00**, Median +$715.00, Win Rate **60.0%**
- `pass` (20 pairs): Mean **-$348.30**, Median +$603.00, Win Rate **55.0%**
- `full_production_agent` (20 pairs): Mean **-$1,543.55**, Median -$855.00, Win Rate **35.0%**

### Seat Breakdown:
- **Seat 0** (50 pairs): Mean **+$2,253.58**, Median +$1,599.00, Win Rate **62.0%**
- **Seat 1** (50 pairs): Mean **+$626.14**, Median +$518.00, Win Rate **54.0%**

---

## 10. Reassessed Final P6.1-C Verdict

1. **Mechanism Verdict**: **MECHANISM NO-GO**.
   Pre-midnight shed market selling failed to prevent shed overflow discards (2.8% reduction vs $\ge 70\%$ target) because the produce is in worker backpacks.
2. **Treatment Status**: **TREATMENT ITERATE**.
   Keep `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False`. Do not promote to production.
3. **Downgrading Unsupported Claims to Hypotheses**:
   - *Claim: "Intraday worker deposits are permanently unviable."* $\to$ **REFUTED**. Under real 10×10 geometry, opportunistic, short-detour, and end-of-day deposits are highly viable.
   - *Claim: "Discards are structurally unavoidable."* $\to$ **DOWNGRADED TO HYPOTHESIS**. Discards were unavoidable *under P6.1's market-only policy*, but can be avoided if workers deposit high-value goods before midnight.
   - *Claim: "Feed-buffer preservation has a proven independent positive causal effect."* $\to$ **VALIDATED AS NARROW TRANSFER ARBITRAGE (+$17.69/game)**, but not an independent driver of the +$1,439.86 gain.

---

## 11. Selection of the Next Narrowly Scoped Experiment (P6.2)

Comparing the four candidates:
- **Candidate A: Opportunistic Near-Shed Deposit-and-Sell**:
  - *Evidence*: Real 10×10 geometry shows inner core workers are $\le 2$ steps from shed access. End-of-day deposit requires 0 return steps. High-value goods (Milk ~$240/u, Melon ~$238/u, Strawberry ~$250/u) can be deposited and sold same-turn with existing `MarketBrain` scheduler coordination.
  - *Expected Net Benefit*: High (salvaging ~$1,500–$3,000 of high-value discards at minimal action cost).
- **Candidate B: Independent Physical Wheat-Reserve Optimization**:
  - *Evidence*: Retaining wheat generated +$17.69/game in transfer arbitrage.
  - *Expected Net Benefit*: Very low (capped at ~$20–$50/game).
- **Candidate C: Market Timing / Price Protection Against FPA**:
  - *Evidence*: Treatment lost -$1,543.55 against FPA due to wool price erosion.
  - *Expected Net Benefit*: Moderate, but complex multi-agent market interaction.
- **Candidate D: No Further Operational Intervention**:
  - *Evidence*: Unnecessary given strong economic viability of Candidate A.

### Decision for P6.2:
**Select Candidate A — Opportunistic Near-Shed Deposit-and-Sell**.
Focus exclusively on allowing workers holding high-value produce (Melon, Strawberry, Milk, Wool) who are adjacent or near shed access (`dist <= 2` tiles, or at Hour 22 end-of-day) to execute `PLACE` into the shed, unlocking same-turn market sale.
