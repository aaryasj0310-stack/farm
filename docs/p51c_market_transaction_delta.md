# Kaggriculture P5.1-C — Market Transaction & Price Absorption Delta

## 1. Executive Summary

This report analyzes the market side of the P5.1-C reconciliation, tracking every single `SELL`, `BUY_PRODUCT`, `BUY_SEED`, `BUY_ANIMAL`, `HIRE`, and `BUY_LAND` order executed across all 100 matched pairs (200 live games).

### Core Discoveries:
1. **The "Carrot Market Saturation" Hypothesis is Completely Disproven**:
   - Treatment sold **+33.66 additional carrots per game** (69.01 $\rightarrow$ 102.67).
   - The average settlement price for carrots in Treatment was **$42.09 / unit**, which was actually **higher** than Control's **$40.65 / unit** (and well above the $35 base price).
   - Town shops absorbed all extra carrots without any price collapse or demand saturation.
2. **Gross Crop Revenue Did Increase (+ $641.96)**:
   - Extra Carrot Revenue: **+$1,516.36**
   - Lost Wheat Revenue: **−$931.43**
   - Melon / Straw / Tomato Net: **+$57.03**
   - Total Gross Crop Revenue Delta: **+$641.96**
3. **Purchased Feed Wheat Wiped Out Crop Gains**:
   - Treatment was forced to buy additional wheat on the market to feed livestock, spending **+$559.88** more on purchased feed wheat.
   - Combined with net seed cost deltas (−$137.60 net), the entire crop+feed enterprise was **net negative by −$55.52**.
4. **Livestock Realized Prices Remained Steady, But Volume Slipped**:
   - Realized milk prices: $244.36 (Ctrl) vs $244.08 (Treat).
   - Realized wool prices: $214.99 (Ctrl) vs $214.82 (Treat).
   - The $950+ livestock loss was purely **volume destruction** (−1.49 milk units, −2.48 wool units sold), not price degradation.

---

## 2. Comprehensive Commodity Sales & Price Realization Table

The table below compiles panel-wide mean sales units, gross revenues, and volume-weighted average realized prices across all 100 matched pairs:

| Commodity | Metric | Control Mean | Treatment Mean | Treatment − Control ($\Delta$) |
| :--- | :--- | :---: | :---: | :---: |
| **WHEAT** | Units Sold | 1,031.00 | 996.02 | **−34.98** |
| | Gross Revenue | $37,694.69 | $36,763.26 | **−$931.43** |
| | Avg Realized Price | $36.56 | $36.91 | **+$0.35** |
| :--- | :--- | :---: | :---: | :---: |
| **CARROT** | Units Sold | 69.01 | 102.67 | **+33.66** |
| | Gross Revenue | $2,805.51 | $4,321.87 | **+$1,516.36** |
| | Avg Realized Price | $40.65 | $42.09 | **+$1.44** |
| :--- | :--- | :---: | :---: | :---: |
| **MILK** | Units Sold | 145.31 | 143.82 | **−1.49** |
| | Gross Revenue | $35,507.47 | $35,102.89 | **−$404.58** |
| | Avg Realized Price | $244.36 | $244.08 | **−$0.28** |
| :--- | :--- | :---: | :---: | :---: |
| **WOOL** | Units Sold | 71.67 | 69.19 | **−2.48** |
| | Gross Revenue | $15,409.04 | $14,863.39 | **−$545.65** |
| | Avg Realized Price | $214.99 | $214.82 | **−$0.17** |
| :--- | :--- | :---: | :---: | :---: |
| **FERTILIZER**| Units Sold | 191.17 | 190.56 | **−0.61** |
| | Gross Revenue | $15,490.28 | $15,455.19 | **−$35.09** |
| | Avg Realized Price | $81.03 | $81.10 | **+$0.07** |
| :--- | :--- | :---: | :---: | :---: |
| **MELON** | Units Sold | 91.73 | 91.60 | **−0.13** |
| | Gross Revenue | $21,856.18 | $21,829.18 | **−$27.00** |
| | Avg Realized Price | $238.27 | $238.31 | **+$0.04** |
| :--- | :--- | :---: | :---: | :---: |
| **STRAWBERRY**| Units Sold | 77.23 | 77.42 | **+0.19** |
| | Gross Revenue | $19,264.95 | $19,325.05 | **+$60.10** |
| | Avg Realized Price | $249.45 | $249.61 | **+$0.16** |
| :--- | :--- | :---: | :---: | :---: |
| **TOMATO** | Units Sold | 23.05 | 23.29 | **+0.24** |
| | Gross Revenue | $1,568.24 | $1,592.17 | **+$23.93** |
| | Avg Realized Price | $68.04 | $68.36 | **+$0.32** |
| :--- | :--- | :---: | :---: | :---: |
| **EGG** | Units Sold | 0.00 | 0.00 | **0.00** |
| | Gross Revenue | $0.00 | $0.00 | **$0.00** |

---

## 3. Expense Breakdown Table

| Expenditure Category | Control Mean ($) | Treatment Mean ($) | Delta ($\Delta$) | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **Carrot Seed Purchases** | $840.40 | $1,086.80 | **−$246.40** | +12.32 seeds @ $20 |
| **Wheat Seed Purchases** | $2,374.80 | $2,266.00 | **+$108.80** | −10.88 seeds @ $10 |
| **Purchased Feed Wheat** | $32,122.59 | $32,682.47 | **−$559.88** | Forced market feed buys |
| **Other Seeds (Mel/Str/Tom)** | $1,475.00 | $1,475.00 | **$0.00** | Invariant |
| **Fertilizer Purchases** | $0.00 | $0.00 | **$0.00** | Self-produced only |
| **Animal Purchases** | $5,300.00 | $5,300.00 | **$0.00** | Invariant |
| **Farm Hand Hire Costs** | $7,545.00 | $7,524.84 | **+$20.16** | Minor scheduling shift |
| **Land Expansion Costs** | $1,000.00 | $1,000.00 | **$0.00** | Invariant |
| **Total Expenses** | **$50,657.79** | **$51,335.11** | **−$677.32** | Net cost increase |

---

## 4. Synthesis: The Fallacy of Isolated Crop Margin

A standalone evaluation of the carrot rotation showed:
$$\text{Carrot Rev } (+\$1,516.36) - \text{Carrot Seed } (\$246.40) = \mathbf{+\$1,269.96 \text{ gross profit}}$$
However, this paper profit ignored the general equilibrium of the farm:
1. Every carrot planted occupied a core tile that would have grown wheat.
2. The lost wheat forfeited **$931.43** in direct crop sales (net **$822.63** after seed savings).
3. The livestock engine, starved of homegrown wheat, purchased **$559.88** in market feed wheat to survive.
4. Total direct crop+feed impact:
   $$+\$1,269.96 - \$822.63 - \$559.88 = \mathbf{-\$112.55}$$
5. And the intraday stockouts caused during this substitution forfeited another **$985.32** in milk and wool.
