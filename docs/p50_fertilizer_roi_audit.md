# P5.0 Fertilizer ROI & Counterfactual Valuation Audit

## Overview of Fertilizer Decisions

Across 100 games, the baseline agent executed **2,428 fertilizer applications** (24.3/game).
Every application was evaluated using the exact counterfactual engine pricing model:
$$\Delta Y = Y_{\text{fertilized}} - Y_{\text{unfertilized}}$$
$$\Delta R = R(M + \Delta Y) - R(M)$$
$$\text{Net Marginal Value} = \Delta R - \text{Spot Price} - \text{Labor Opportunity Cost}$$

---

## Fertilizer ROI Classification Table

| Class | Definition | Applications | Per Game | Primary Crop | Mean Net Value ($) |
| :--- | :--- | :---: | :---: | :--- | :---: |
| **F1: Strongly Positive** | Net Marginal Value > +$20.00 | **1,589** | **15.9** | Strawberry (95.2%) | +$68.40 |
| **F2: Marginally Positive** | $0.00 ≤ Net Marginal Value ≤ +$20.00 | **725** | **7.2** | Tomato / Strawberry | +$11.80 |
| **F3: Neutral** | -$20.00 ≤ Net Marginal Value < $0.00 | **0** | **0.0** | - | $0.00 |
| **F4: Value-Destroying** | Net Marginal Value < -$20.00 (worse than selling) | **114** | **1.1** | Tomato (100.0%) | -$46.18 |

---

## Key Strategic Takeaways

1. **Strawberry Fertilizer is Elite**:
   Strawberry fertilizer generates an average of **+$65.28 net value per application**. It should never be skipped.
2. **Tomato Fertilizer is Frequently Harmful**:
   114 tomato fertilizer events (1.1 per game) destroyed an average of **-$46.18** compared to selling the fertilizer on the market. Eliminating these 114 events saves **+$52.65 per game**.
3. **Wheat / Carrot Gating is Well-Calibrated**:
   The baseline's thresholds (<$50 for wheat, <$35 for carrot) resulted in 0 wasteful applications, correctly preserving fertilizer for Strawberries.
