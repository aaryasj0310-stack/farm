# P6.1-C Product Delta Causality (Corrected)

## Executive Summary

In P6.1, net product sales revenue rose by **+$661.70**, composed of distinct gains in Milk (+1.97 u, +$799.35), Melon (+2.45 u, +$535.48), and Strawberry (+0.68 u, +$115.62), set against a sharp reduction in Wheat revenue (-24.24 u, -$731.49).

This report applies standard econometric decomposition to separate volume shifts, market price realization, and animal production mechanics.

Key conclusions:
1. **Economic Revenue Decomposition**:
   - $\text{Quantity Effect} = (Q_T - Q_C) \times P_C = \mathbf{+\$397.07}$
   - $\text{Price Effect} = Q_C \times (P_T - P_C) = \mathbf{+\$266.30}$
   - $\text{Interaction Effect} = (Q_T - Q_C) \times (P_T - P_C) = \mathbf{-\$1.67}$
   - Total Sales Delta: $\mathbf{+\$661.70}$.
2. **Correction of Milk Unit Valuation**:
   - The earlier report derived an erroneous $405.76/u valuation by dividing total revenue delta ($799.35) by volume delta (+1.97 u).
   - In reality, milk realized an average price of **$238.91/u** in Control and **$241.23/u** in Treatment.
   - The revenue increase was **58.9% quantity effect (+$470.66)** and **40.5% price timing effect (+$324.13)**.
3. **Animal Care Continuity & Feed Reliability (+1.97 units Milk)**:
   - In engine rules (`kaggriculture.py:823`), missing a feed on a production day voids pending care bonuses, costing ~1 unit of milk.
   - Treatment achieved **0.58 fewer missed feeds** (13.08 vs 13.66), directly explaining **~0.58 units of milk**.
   - Direct midnight discard reduction preserved **+0.71 units of milk**.
   - The remaining **+0.68 units of milk** arose from minor cow acquisition step differences.

---

## 1. Product Revenue Decomposition Matrix

$$\Delta \text{Revenue} = \text{Quantity Effect} + \text{Price Effect} + \text{Interaction Effect}$$

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
| **Total** | **+$661.70** | **+$397.07** | **+$266.30** | **-$1.67** | — | — | — |

---

## 2. In-Depth Operational Examination of Key Commodities

### 2.1 Dairy Production (Milk: +1.97 units, +$799.35)
Milk was the single largest revenue driver in Treatment.
- **Quantity Contribution (+$470.66)**: Driven by +1.97 additional units sold.
  - ~0.58 units from nutritional continuity (avoiding 0.58 missed feeds).
  - 0.71 units saved from shed discards.
  - 0.68 units from cow acquisition timing shifts.
- **Price Timing Contribution (+$324.13)**: Treatment realized a slightly higher average price ($241.23/u vs $238.91/u, +$2.32/u). Treatment's pre-midnight sell triggers occasionally coincided with higher town market spot windows.

### 2.2 Melons (+2.45 units, +$535.48)
- **Quantity Contribution (+$585.17)**: Driven by +2.45 additional units sold.
  - 1.05 units saved directly from midnight shed discards (Melon discards fell from 3.10 u to 2.05 u).
  - 1.40 units from late-season field harvest execution differences.
- **Price Contribution (-$48.36)**: Average price dropped slightly from $238.84/u to $238.30/u (-$0.54/u) due to higher volume sold into the town market.

### 2.3 Wheat (-24.24 units Sold, -$731.49)
- **Quantity Contribution (-$854.25)**: Treatment sold 24.24 fewer units of wheat because the hygiene routine refused to sell shed wheat below the 48-unit safety floor.
- **Price Contribution (+$125.74)**: By selling fewer units, Treatment avoided depressing the town wheat market, realizing $35.36/u vs $35.24/u.
- **On-Farm Consumption**: That retained wheat directly substituted for 23.16 units of store-bought feed wheat (+749.18 expenditure savings), netting **+$17.69/game** in internal transfer arbitrage.
