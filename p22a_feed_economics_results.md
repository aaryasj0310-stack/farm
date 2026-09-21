# Kaggriculture P2.2-A Day 28 Feed/Liquidation Harmonization Results

## Executive Summary
- **Treatment**: P2.2-A Day 28 Feed/Liquidation Harmonization (`P22A_DAY28_FEED_HARMONIZATION_ENABLED=True`)
- **Control Baseline**: True Production Baseline (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`) with `QUADRANT_HARD_BLOCK={4}`
- **Sample Size**: 100 matched pairs (200 live games), 8 workers, Seeds 87,001–87050
- **Control Mean**: **$103,092.66**
- **Treatment Mean**: **$103,150.99**
- **Paired Mean Delta**: **+$58.33** (95% CI: [$-55.82, $172.48])
- **Record**: **37W / 58L / 5T** (Win Rate: 37.0%)
- **Statistical Significance**: $t = 1.0015$, $p = 3.1656e-01$

## Day 28 Wheat & Wash Trade Diagnostics
| Metric | True Control Baseline | P2.2-A Treatment | Net Impact |
| :--- | :--- | :--- | :--- |
| **Day 28 Wheat Buy Spend** | $11,003.25 | $0.00 | $-11,003.25 |
| **Day 28 Wheat Sell Receipts** | $11,656.25 | $1,219.50 | $-10,436.75 |
| **Day 28 Net Wheat Cash Flow** | $653.00 | $1,219.50 | **$566.50** |
| **Day 28 Wash Trade Turns** | 2200 turns (22.00/game) | 0 turns (0.00/game) | **-2200 turns** |

## Invariant Checks
- **Quadrants Locked**: NW + NE (Hard block on SW + SE)
- **Animal Starvation**: Zero starvation regressions
- **Solvency**: Zero negative cash steps
