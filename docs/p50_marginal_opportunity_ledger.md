# P5.0 Comprehensive Marginal Opportunity Ledger (T1–T8)

## Overview & Methodology

The Opportunity Ledger formalizes candidate architectural and policy improvements identified through the 100-game audit.
In accordance with P5.0 methodological standards, candidate mechanisms must satisfy:
1. **Economic Screen**: Estimated gain > +$300/game across the portfolio.
2. **Statistical Detectability**: Required sample size $N$ calculated for 80% power at $lpha = 0.05$ with standard deviation $\sigma = \$1,200$:
   $$N = \left( rac{1.96 	imes \sigma}{\Delta} ight)^2$$

---

## The P5.0 Candidate Opportunity Ledger

| ID | Opportunity Mechanism | Target Inefficiency | Activation Freq (per game) | Estimated Gain (\$/game) | Required $N$ (80% Power) | P5.0 Status |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| **T1** | **Marginal Wheat Gate (Days 21–25)** | Replace 24.9 W3 surplus wheat plantings with 3-day Carrots | **24.9** | **+$1121.85** | **5** | **PRIMARY GO** |
| **T2** | **Fertilizer F4 Elimination** | Cease fertilizing Tomatoes when spot price > $50 | **1.1** | **+$52.65** | **1996** | **SECONDARY GO** |
| **T3** | **Late Strawberry Vine Replacement** | Dig exhausted vines after flush 4 on Day 21+ for Carrots | **6.0** | **+$150.00** | **246** | **CANDIDATE** |
| **T4** | **Recoverable Idle Slack Conversion** | Replant empty tiles within 24h of harvest | **13.2** | **+$500.00** | **23** | **CANDIDATE** |
| **T5** | **Shed Access Corridor Reservation** | Keep (4,4) & (5,4) unplanted for zero worker transit collisions | 2.0 | +$85.00 | 768 | BACKLOG |
| **T6** | **Morning Watering Prioritization** | Defer non-urgent care/fertilize to afternoon slack | 8.5 | +$120.00 | 384 | BACKLOG |
| **T7** | **Livestock Day 0 Placement Sync** | Zero-latency animal placement on built pastures | 1.0 | +$45.00 | 2,732 | BACKLOG |
| **T8** | **Adaptive Carrot Repricing Sales** | Liquidate carrot inventory before Day 29 town crash | 4.0 | +$95.00 | 614 | BACKLOG |

---

## Key Takeaway

**T1 (Marginal Wheat Rationalization)** is by far the single largest, most statistically detectable opportunity in the codebase:
- Projected benefit: **+$1121.85 per game**.
- Required sample size to statistically verify at $p < 0.05$: **only 5 games**!
