# P5.0 Tomato Lifecycle & Input Destruction Audit

## Lifecycle Profile

Tomato is an ongoing multi-flush crop:
- **First Yield**: Day $D+7$ (if watered daily).
- **Yield Interval**: Every 3 days thereafter ($D+10, D+13, D+16$).
- **Maximum Flushes**: 4 harvest flushes.
- **Base Yield**: 1 unit per flush (2 units if fertilized).
- **Market Dynamics**: Moderate base value ($60), moderate price support.

---

## Empirical Core Allocation & Input Valuation

Across 100 games:
- **Total Tile-Days Occupied**: 5,364 tile-days (3.6% of core).
- **Fertilizer Applications**: 464 applications on Tomatoes.
- **Marginal Classification Breakdown**:
  - **F1 (Strongly Positive)**: 77 applications (16.6%)
  - **F2 (Marginally Positive)**: 273 applications (58.8%)
  - **F4 (Negative vs Selling Spot)**: **114 applications (24.6%)**!
- **Mean Net Marginal Value**: **+$4.01** per application (compared to +$65.28 on Strawberries).

---

## Root Cause of Tomato Input Destruction

In 24.6% of tomato fertilizer applications, applying fertilizer actually **destroyed value** compared to simply selling the fertilizer bag at the town spot price:
1. **Low Spot Value Spread**: Tomato base price is $60. With town market inventories, marginal realized revenue per extra unit is often only $40–$48.
2. **High Fertilizer Spot Price**: When fertilizer spot price is $60–$90, spending a $75 bag + $15 labor opportunity cost to gain a $45 tomato produces a net loss of **-$45.00**!
3. **Policy Defect**: The baseline hardcoded rule fertilizes Tomatoes at ages 7–8 and 10–11 regardless of the spot price of fertilizer.

### Remedy (T2 Opportunity)
Enforce an economic gate: never fertilize Tomatoes unless the spot price of fertilizer is below $45.00 and the projected tomato price exceeds $55.00.
