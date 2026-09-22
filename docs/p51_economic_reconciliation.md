# Kaggriculture P5.1 — Economic Reconciliation Report
*(Updated with Definitive P5.1-C Empirical Telemetry)*

## 1. Executive Summary & Epistemic Evolution

In P5.0-R, offline counterfactual modeling identified an estimated **shadow opportunity of +$655.25 / game** by substituting surplus late-season wheat plantings (Days 21–23) on core NW+NE tiles with two consecutive 3-day carrot cycles.

However, when tested in the full, unconstrained 100-pair (200-game) live discovery replay against all 5 benchmark opponents:
- **Modeled Shadow Opportunity**: **+$655.25 / game** [MODELED ESTIMATE — FLAWED]
- **Empirical Live Discovery Delta**: **−$1,020.68 / game** [MEASURED FACT]
- **Net Divergence (Delta Gap)**: **−$1,675.93 / game**

Prior to telemetry instrumentation, four hypothetical drag mechanisms were proposed. The subsequent **P5.1-C Causal Delta Reconciliation** instrumented all 200 games at the game engine level, achieving **0.000000 cash accounting closure**. 

This document contrasts the preliminary hypotheses with the empirical ground truth.

---

## 2. Hypothesis vs. Empirical Reality Matrix

The table below directly evaluates the preliminary hypotheses against empirical telemetry:

| Preliminary Proposed Mechanism | Preliminary Estimate | Empirical Reality (P5.1-C Telemetry) | Epistemic Status |
| :--- | :---: | :--- | :---: |
| **1. Extra Watering Labor Displacement** | −$950 to −$1,200 | **Total crop waterings actually decreased by −4.68 / game**. Baseline already watered late wheat ~4 times. Labor was not displaced by watering; rather, extra movement (+14.54 steps) increased transit time. | **[REJECTED]** |
| **2. Town Shop Carrot Price Depletion** | −$300 to −$450 | **Realized carrot prices were $42.09 / unit** in Treatment vs $40.65 in Control (both well above the $35 base price). Zero price collapse occurred. | **[REJECTED]** |
| **3. Market Order Slot Cap Squeezes** | −$150 to −$250 | **The engine limit is 10 orders per turn**, not 10 per day. Exactly **0.00 orders were dropped** due to caps across 144,000 game turns. | **[REJECTED]** |
| **4. Unsold Endgame Inventory Haircut** | −$100 to −$200 | **Endgame shed and worker inventory was 0.00** across all 200 games. Zero unsold inventory remained. | **[REJECTED]** |
| **TRUE CAUSE A: Net Wheat & Feed Deficit** | — | **−$1,382.51 / game**: Lost wheat sales (−$931.43) + wheat seed saved (+$108.80) + forced market feed wheat buys (−$559.88). | **[MEASURED FACT]** |
| **TRUE CAUSE B: Livestock Production Loss** | — | **−$985.32 / game**: Grain stockouts caused −3.24 missed feeds, voiding care bonuses and destroying 2.50 milk units and 1.91 wool units. | **[MEASURED FACT]** |

---

## 3. The Definitive Cash Accounting Identity

The exact financial delta of P5.1 is governed by the following mathematical identity ($\epsilon = 0.000000$):

$$\begin{aligned}
\Delta \text{Cash} &= \text{Net Carrot Margin} \\
&\quad - \text{Net Wheat Revenue Lost} - \text{Market Feed Purchases} \\
&\quad - \text{Livestock Revenue Lost} + \text{Minor Categories} \\
&= +\$1,269.96 - \$822.63 - \$559.88 - \$985.32 + \$77.19 \\
&= \mathbf{-\$1,020.68 \text{ / game}}
\end{aligned}$$

### Detailed Categorical Breakdown:
1. **Direct Carrot Enterprise**: **+$1,269.96**
   - Gross Revenue: +$1,516.36 (+33.66 units @ $42.09 avg)
   - Seed Costs: −$246.40 (+12.32 seeds @ $20)
2. **Crop Wheat Impact**: **−$822.63**
   - Lost Wheat Revenue: −$931.43 (−34.98 units @ $36.56 avg)
   - Wheat Seed Savings: +$108.80 (−10.88 seeds @ $10)
3. **Purchased Feed Wheat**: **−$559.88**
   - Extra feed wheat bought on open market to prevent animal starvation.
4. **Livestock Revenue Destruction**: **−$985.32**
   - Milk Revenue Lost: −$404.58 (−1.49 units @ $244.08 avg)
   - Wool Revenue Lost: −$545.65 (−2.48 units @ $214.82 avg)
   - Fertilizer Revenue Lost: −$35.09 (−0.61 units @ $81.10 avg)
5. **Minor Financial Categories**: **+$77.19**
   - Labor Hires saved: +$20.16
   - Net Strawberry / Tomato / Melon variance: +$57.03

---

## 4. Key Strategic Insights & Future Directives

1. **Grain Security is Fundamental**:
   - Wheat on the core farm is not a low-value cash crop; it is **internal critical infrastructure**. 
   - Converting core wheat tiles to cash crops starves the dairy and sheep herds of physical intraday grain, forcing expensive spot-market purchases and triggering missed feedings.
2. **Asymmetric Livestock Economics**:
   - A cow produces ~$244/unit in milk; a sheep produces ~$215/unit in wool.
   - Forfeiting just 4 units of livestock production obliterates the entire profit of 30+ carrots.
   - Any proposed modification that risks livestock feeding regularity by even 1% must be rejected immediately.
3. **P5.1 Permanently Closed**:
   - `P51_T1_TWO_CYCLE_CARROT_ENABLED = False` is permanently locked.
   - No P5.2 or related variants will be pursued.
