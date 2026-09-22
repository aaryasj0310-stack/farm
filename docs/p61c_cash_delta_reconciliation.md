# P6.1-C Cash Delta Reconciliation

## Executive Summary

This document establishes the exact, zero-residual cash waterfall reconciliation for the P6.1 experiment across the 100 discovery scenario pairs (seeds `96,411`–`96,420`, 5 opponents, both seats). 

In P6.1, the reported final cash advantage was **+$1,439.86/game**. P6.1 attributed **+$661.70** to net direct product sales and labeled the remaining **+$778.16** as *"Early Liquidity Compounding"*.

Forensic accounting via transaction-level interception across all 200 live simulation runs proves that:
1. **The single-game accounting residual error is exactly $\epsilon = 0.000000$ across all 100 matched pairs.**
2. The unexplained **+$778.16** is **NOT** compounding yield or return on invested capital. It is **AN EXPENDITURE SAVINGS OF EXACTLY +$778.16**, driven overwhelmingly by **$749.18 in reduced feed wheat purchases from town**.
3. Feed wheat purchase savings ($+\$749.18$) almost exactly mirror the reduction in wheat sales revenue ($-\$731.49$). Treatment held 24.24 fewer units of wheat in shed market dumps, thereby avoiding the purchase of 23.16 units of feed wheat at an unfavorable town retail spread.
4. The remaining **+$1,393.19** of final cash delta is driven by high-value product sales increases (Milk +$799.35, Melon +$535.48, Strawberry +$115.62, Carrot +$49.40, Tomato +$39.15, less Wool -$137.40 and Fertilizer -$8.41), offset by minor non-wheat expenditure deltas.

---

## 1. Zero-Residual Cash Waterfall Ledger

All values represent the per-game arithmetic mean across the 100 matched pairs (Treatment minus Control).

$$\text{Final Cash Delta} = \Delta \text{Revenue} - \Delta \text{Expenditures}$$

| Line Item | Control Mean | Treatment Mean | Net Delta (T - C) | Economic Classification |
| :--- | :---: | :---: | :---: | :--- |
| **Gross Product Sales Revenue** | **$113,873.34** | **$114,535.04** | **+$661.70** | **Total Revenue Inflow Delta** |
| • Wheat Sales | $36,066.82 (1023.42u) | $35,335.33 (999.18u) | -$731.49 (-24.24u) | Reduced wheat dumping (buffer) |
| • Milk Sales | $33,433.55 (139.94u) | $34,232.90 (141.91u) | +$799.35 (+1.97u) | Preserved production & minor discard save |
| • Melon Sales | $11,922.95 (54.58u) | $12,458.43 (57.03u) | +$535.48 (+2.45u) | Salvaged 1.05u discards + field timing |
| • Strawberry Sales | $7,725.12 (45.38u) | $7,840.74 (46.06u) | +$115.62 (+0.68u) | Harvest yield variation |
| • Carrot Sales | $4,855.94 (53.30u) | $4,905.34 (53.84u) | +$49.40 (+0.54u) | Minor yield / price timing |
| • Tomato Sales | $4,589.90 (52.68u) | $4,629.05 (53.13u) | +$39.15 (+0.45u) | Minor yield / price timing |
| • Wool Sales | $16,278.92 (73.22u) | $16,141.52 (73.16u) | -$137.40 (-0.06u) | Market price degradation in FPA matches |
| • Fertilizer Sales | $15,273.06 (187.74u) | $15,264.65 (187.52u) | -$8.41 (-0.22u) | Negligible variation |
| • Egg Sales | $0.00 (0.00u) | $0.00 (0.00u) | $0.00 (0.00u) | Chickens disabled in baseline |
| **Gross Cash Expenditures** | **$48,912.40** | **$48,134.24** | **-$778.16** | **Total Expenditure Outflow Delta (Savings)** |
| • Feed Wheat Purchases | $30,780.44 (877.70u) | $30,031.26 (854.54u) | -$749.18 (-23.16u) | **Avoided store feed purchases (+Savings)** |
| • Seed Purchases | $4,685.40 | $4,680.50 | -$4.90 | Minor planting schedule difference |
| • Animal Purchases | $4,903.00 | $4,889.00 | -$14.00 | Minor purchase timing difference |
| • Worker Wages (Hires) | $7,543.56 | $7,533.48 | -$10.08 | Minor hire step offset |
| • Land Expansion | $1,000.00 | $1,000.00 | $0.00 | Identical expansion policy |
| • Fertilizer Purchases | $0.00 | $0.00 | $0.00 | Never purchased from town |
| **Reconciled Net Delta** | — | — | **+$1,439.86** | **$\Delta \text{Revenue} - \Delta \text{Expenditures}$** |
| **Actual Cash Delta** | $99,890.78 | $101,330.64 | **+$1,439.86** | **Exact match ($\epsilon = 0.000000$)** |

---

## 2. Deconstruction of the "+$778.16 Unexplained Compounding"

In the P6.1 report, the author assumed that because direct sales revenue only grew by +$661.70, the remaining +$778.16 must have been generated through economic multiplier effects ("early liquidity compounding").

The forensic accounting ledger disproves this hypothesis completely:
1. **$749.18 of the $778.16 (96.3%) is simply lower feed wheat expenditure.**
2. Why did Treatment spend $749.18 less on feed wheat?
   - Treatment implemented `feed_safety_buffer = ceil(daily_feed_demand * 1.5) = 48 units`.
   - Control routinely allowed its shed wheat to fall or sold wheat during daytime market sell cycles, leaving the shed with insufficient feed wheat when morning feeding occurred (Day H0).
   - When shed feed wheat is deficient, the engine agent purchases feed wheat from the town store at retail buy prices (~$35.00–$35.80/unit).
   - In Treatment, the hygiene routine explicitly blocked the sale of shed wheat below the 48-unit buffer.
   - Consequently, Treatment sold **24.24 fewer units of wheat** ($-\$731.49$, sold at ~\$30.18/unit town wholesale price).
   - Because Treatment retained this wheat in the shed, it **avoided purchasing 23.16 units of feed wheat** from the store at retail prices ($+\$749.18$ savings).
3. **Net Arbitrage Gain**:
   $$\text{Avoided Retail Buy Cost} - \text{Forfeited Wholesale Sell Revenue} = \$749.18 - \$731.49 = +\$17.69$$
   The wheat retention buffer provided an internal transfer pricing benefit of only **+$17.69/game**. It was not a compounding growth engine.

---

## 3. Residual Verification

Every single game satisfies:
$$\text{Starting Money} + \sum \text{Sales Revenue} - \sum \text{Purchase Costs} \equiv \text{Final Money}$$
Across all 100 scenario pairs (200 live games), the maximum discrepancy was:
$$\max |\text{Cash Delta} - (\Delta \text{Sales} - \Delta \text{Expenditures})| = 0.000000$$

The reconciliation is mathematically closed and absolute.
