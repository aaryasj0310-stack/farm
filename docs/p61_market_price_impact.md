# Kaggriculture P6.1 — Market Price Impact & Pricing Curve Analysis

- **Target Metric**: Price depression analysis for pre-midnight liquidation sales
- **Core Question**: Did selling goods in late-evening windows (Hours 20–22) depress town shop market prices?
- **Finding**: **NO MATERIAL PRICE DEPRESSION**. Average realized selling prices remained within $\pm 1\%$ of baseline across all 8 products.

---

## 1. Product Price Realization Comparison

The table below contrasts realized selling prices across all 100 matched pairs (100 Control games vs 100 Treatment games):

| Product | Base Catalog Price | Control Realized Price | Treatment Realized Price | Absolute Price Delta | % Price Impact | Pricing Drip Protection Active |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **STRAWBERRY**| \$120.00 | \$250.34 | \$249.63 | **-\$0.71** | -0.28% | Yes (`keep_frac` = 0.88) |
| **MELON** | \$250.00 | \$238.84 | \$238.30 | **-\$0.54** | -0.23% | Yes (`keep_frac` = 0.90) |
| **MILK** | \$160.00 | \$238.91 | \$241.23 | **+\$2.32** | +0.97% | Yes (`keep_frac` = 0.85) |
| **WOOL** | \$200.00 | \$222.33 | \$220.63 | **-\$1.70** | -0.76% | Yes (`keep_frac` = 0.90) |
| **WHEAT** | \$25.00 | \$35.24 | \$35.36 | **+\$0.12** | +0.34% | Yes (`keep_frac` = 0.95) |
| **CARROT** | \$35.00 | \$39.56 | \$39.96 | **+\$0.40** | +1.01% | Yes (`keep_frac` = 0.95) |
| **TOMATO** | \$60.00 | \$66.58 | \$66.97 | **+\$0.39** | +0.59% | Yes (`keep_frac` = 0.93) |
| **FERTILIZER**| \$100.00 | \$81.35 | \$81.40 | **+\$0.05** | +0.06% | Yes (`keep_frac` = 0.90) |

---

## 2. Market Dynamics & Elasticity Mechanics

1. **Why Prices Did Not Collapse**:
   - P6.1 strictly retained `MarketBrain._safe_drip_qty()` and `DRIP_PRICE_KEEP_FRAC` bounds.
   - Slices were clamped so that each transaction kept the quoted price at $\ge 85\%\text{--}90\%$ of the initial spot price.
   - Furthermore, the town shops drain at global steps $t \equiv 0 \pmod 4$ and $t \equiv 0 \pmod{24}$, restoring town demand before the next morning's selling windows.

2. **Floor Protection Invariant**:
   - `HOLD_AT_FLOOR_PRODUCTS` ($1 floor holds for Melon, Strawberry, Milk, Wool) remained active (`is_floor_exception = False`).
   - Treatment never dumped high-value inventory at the $1 floor during Hours 20–22.

3. **Conclusion**:
   - The economic failure of P6.1 was **not** caused by market price depression.
   - Town demand was fully sufficient to absorb additional sales at premium prices.
   - The bottleneck was strictly physical inventory availability in the shed.
