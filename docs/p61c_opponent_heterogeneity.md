# P6.1-C Opponent Heterogeneity & The Full-Production Deficit

## Executive Summary

This report evaluates performance heterogeneity across the five benchmark opponents in the 100 discovery scenario pairs.

The evaluation uncovers marked divergence across opponent types:
1. **Strong Outperformance against Single-Crop / Rigid Bots**:
   - `pure_wheat_rush`: **+$4,625.65/game** (75.0% win rate)
   - `melon_sniper`: **+$2,799.50/game** (65.0% win rate)
   - `cow_milk_engine`: **+$1,666.00/game** (60.0% win rate)
2. **Deficit Against Dynamic, Multi-Product Competitors**:
   - `pass`: **-$348.30/game** (55.0% win rate)
   - `full_production_agent`: **-$1,543.55/game** (**35.0% win rate** — severe underperformance)

---

## 1. Opponent Performance Matrix

Each benchmark opponent was evaluated over 20 paired matches (10 seeds $\times$ 2 seats).

| Opponent Benchmark | Paired Games | Mean Cash Delta | Median Cash Delta | Treatment Win Rate | Mean Sales Delta | Mean Expenditure Delta | Mean Discard Delta |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`pure_wheat_rush`** | 20 | **+$4,625.65** | +$4,587.50 | **75.0%** (15/20) | +$4,109.25 | -$516.40 | +10.95 u |
| **`melon_sniper`** | 20 | **+$2,799.50** | +$2,419.00 | **65.0%** (13/20) | +$346.70 | -$2,452.80 | -0.65 u |
| **`cow_milk_engine`** | 20 | **+$1,666.00** | +$715.00 | **60.0%** (12/20) | +$677.90 | -$988.10 | -2.70 u |
| **`pass`** | 20 | **-$348.30** | +$603.00 | **55.0%** (11/20) | -$336.20 | +$12.10 | +3.20 u |
| **`full_production_agent`** | 20 | **-$1,543.55** | -$855.00 | **35.0%** (7/20) | -$1,489.15 | +$54.40 | -4.90 u |
| **Overall** | **100** | **+$1,439.86** | **+$642.50** | **57.0%** (57/100) | **+$661.70** | **-$778.16** | **-1.18 u** |

*(Note: In the Discard Delta column, negative values indicate Treatment discarded fewer units than Control; positive values indicate Treatment discarded more).*

---

## 2. Forensic Investigation of the `full_production_agent` Deficit

Against the strongest benchmark bot, `full_production_agent` (FPA), Treatment experienced a substantial loss of **-$1,543.55/game** and a losing win rate of **35.0%**.

### 2.1 Product Sales Revenue Breakdown Against FPA

| Product | Control Sales Rev | Treatment Sales Rev | Revenue Delta (T - C) | Quantity Delta (T - C) | Price Realization Impact |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Wool** | $17,741.45 | $15,587.50 | **-$2,153.95** | -3.05 u (74.7u vs 71.7u) | **-$19.95/unit price collapse** |
| **Strawberry** | $8,245.10 | $7,485.90 | **-$759.20** | -4.20 u | Lower harvest clearance |
| **Melon** | $12,410.20 | $12,164.80 | **-$245.40** | -1.15 u | Minor yield timing |
| **Wheat** | $34,980.50 | $34,940.90 | -$39.60 | -1.20 u | Negligible change |
| **Fertilizer** | $14,980.20 | $15,024.70 | +$44.50 | +0.55 u | Negligible change |
| **Carrot** | $4,810.30 | $4,864.35 | +$54.05 | +0.60 u | Minor gain |
| **Tomato** | $4,512.40 | $4,673.95 | +$161.55 | +1.85 u | Minor gain |
| **Milk** | $32,150.20 | $33,599.10 | **+$1,448.90** | +1.50 u | Preserved dairy yield |
| **Total Sales** | **$129,830.35** | **$128,341.20** | **-$1,489.15** | — | **Severe Deficit** |

### 2.2 Mechanism of the Wool Collapse
The primary driver of the deficit against FPA is the **-$2,153.95 drop in Wool revenue**:
- Control realized an average sell price of **$237.50/unit** on 74.7 units of wool.
- Treatment realized an average sell price of only **$217.55/unit** on 71.7 units of wool.
- This represents an average price loss of **-$19.95 per unit** across the entire wool harvest.

#### Why Did Treatment Suffer Price Depreciation Against FPA?
1. **Shared Town Shop Saturation**:
   - `full_production_agent` produces both dairy and fiber, actively selling wool and milk to town stores.
   - Town store purchase prices decrease dynamically as products are sold into the store.
2. **Pre-Midnight Sales Distort Market State**:
   - In Treatment, when hygiene executes small pre-midnight sales at H21, it alters the inventory and liquidity balance.
   - In several seeds (e.g. `96415`, `96416`, `96417`), this triggered downstream planner shifts where our agent delayed wool sales until after FPA had already sold into the town market, receiving the post-depreciation price.
3. **Control's Bulk Timing Superiority**:
   - In Control, goods accumulated and were sold in deliberate, coordinated bulk batches that effectively beat or matched FPA's market timing.

---

## 3. Discard Paradox in `pure_wheat_rush`

In `pure_wheat_rush`, Treatment achieved its largest cash gain (**+$4,625.65/game**), yet suffered **+10.95 MORE discard units** than Control!
- Control discarded 38.10 units; Treatment discarded 49.05 units.
- Despite throwing away 11 more units of produce, Treatment earned $4,625 more money.
- Why? Against `pure_wheat_rush`, the opponent floods the market with wheat, driving wheat prices down. Treatment's wheat buffer prevented it from selling wheat into a cratered market, preserving feed wheat and allowing it to harvest and sell high-value livestock produce.

---

## 4. Strategic Implications for Future Iterations

Any strategy that claims to improve performance by managing storage must be robust against the most competitive agent in the field (`full_production_agent`):
- P6.1 failed against FPA because uncoordinated, rule-based H21 selling disrupted delicate market timing against an opponent that actively competes for town market capacity.
- Future improvements must incorporate market depth and opponent activity before triggering early sales.
