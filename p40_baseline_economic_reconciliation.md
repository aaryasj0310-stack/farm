# Kaggriculture P4.0 — Baseline Economic Reconciliation Report

## 1. Executive Summary & Audit Verification

This report establishes the authoritative, mathematically exact economic ledger for the Promoted P2.3 Production Baseline across 100 representative games. Every penny entering or leaving the farm was intercepted at the engine transaction level (`_commit_unit`, `_do_hire`, `_do_buy_land`) and reconciled against the final game reward.

- **Authoritative Baseline SHA**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`
- **Agent Tree Hash**: `2847f8df5608b564ef47ec695fadb4bdc40704f8` (100% clean worktree, 0 diffs)
- **Engine Version**: `1.32.7` (Kaggle Environments `kaggriculture`)
- **Diagnostic Sample**: 100 matched games (50 seeds 96,001–96,050 $\times$ 2 balanced seats)
- **Opponent Archetypes**: 5 standard opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent` — 20 games each)
- **Mathematical Cash Flow Identity**:
  $$\text{Starting Cash } (\$3,000.00) + \text{Realized Inflows } - \text{Realized Outflows } = \text{Final Cash } \equiv \text{Final Reward}$$
- **Reconciliation Pass Rate**: **100.0% (100 / 100 games)**
- **Maximum Reconciliation Discrepancy**: **$0.000000** across all 100 games.

---

## 2. Final Score Distribution

Across the 100 diagnostic games, the promoted P2.3 production baseline achieved:

| Metric | Value | 95% Confidence Interval |
| :--- | :---: | :---: |
| **Mean Final Score** | **$101,836.36** | **[$100,006.20, $103,666.52]** |
| **Median Final Score** | **$103,048.00** | — |
| **Standard Deviation** | $9,224.61 | — |
| **Minimum Score** | $74,180.00 | — |
| **Maximum Score** | $126,894.00 | — |
| **Distance to $130k Target** | **-$28,163.64** | — |

### Per-Opponent Breakdown (20 games each, balanced seats)

| Opponent Archetype | Games | Mean Score | Median Score | 95% CI |
| :--- | :---: | :---: | :---: | :---: |
| `cow_milk_engine` | 20 | $105,654.60 | $106,394.50 | [$101,754.82, $109,554.38] |
| `pass` | 20 | $102,578.85 | $103,754.00 | [$99,770.89, $105,386.81] |
| `melon_sniper` | 20 | $100,622.00 | $102,722.00 | [$95,436.51, $105,807.49] |
| `pure_wheat_rush` | 20 | $100,365.65 | $100,641.50 | [$95,871.78, $104,859.52] |
| `full_production_agent` | 20 | $99,960.70 | $101,423.50 | [$95,357.93, $104,563.47] |

### Seat Bias Verification (50 games per seat)
- **Seat 0 Mean**: $101,481.52 (95% CI: [$98,918.67, $104,044.37])
- **Seat 1 Mean**: $102,191.20 (95% CI: [$99,491.39, $104,891.01])
- **Seat Delta (Seat 1 - Seat 0)**: **+$709.68** (statistically negligible, confirming seat parity).

---

## 3. The Authoritative Macro Cash Flow Ledger

The mean macro cash flow per game reconciles exactly as follows:

$$\begin{aligned}
\text{Starting Cash} & = +\$3,000.00 \\
\text{Gross Realized Inflows (Revenue)} & = +\$147,890.11 \\
\text{Gross Realized Outflows (Expenses)} & = -\$49,053.75 \\
\hline
\text{Net Cash Generated} & = +\$98,836.36 \\
\mathbf{\text{Final Cash (Final Score)}} & = \mathbf{\$101,836.36}
\end{aligned}$$

Discrepancy: **$0.000000** (Engine exact).

---

## 4. Itemized Revenue Breakdown (Inflows)

All revenue was generated via engine `SELL` transactions from the shed into the dynamic market.

| Product | Mean Revenue | Share (%) | Mean Units Sold | Avg Realized Price | 95% Confidence Interval |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **WHEAT** | $36,708.63 | 24.82% | 1,003.0 | $36.60 / unit | [$35,349, $38,069] |
| **MILK** | $34,304.92 | 23.20% | 141.6 | $242.32 / unit | [$31,061, $37,548] |
| **MELON** | $21,469.81 | 14.52% | 89.9 | $238.71 / unit | [$21,061, $21,879] |
| **STRAWBERRY** | $19,538.28 | 13.21% | 79.6 | $245.58 / unit | [$18,787, $20,290] |
| **WOOL** | $16,395.77 | 11.09% | 72.7 | $225.68 / unit | [$13,981, $18,811] |
| **FERTILIZER** | $15,198.97 | 10.28% | 186.5 | $81.51 / unit | [$15,011, $15,387] |
| **CARROT** | $2,599.76 | 1.76% | 67.2 | $38.67 / unit | [$2,426, $2,773] |
| **TOMATO** | $1,673.97 | 1.13% | 24.2 | $69.17 / unit | [$1,575, $1,773] |
| **EGG** | $0.00 | 0.00% | 0.0 | $0.00 | $0.00 |
| **Total Inflows** | **$147,890.11** | **100.00%** | **1,664.7** | — | **[$144,385, $151,395]** |

### Sector-Level Revenue Aggregation
- **Crops (Wheat, Melon, Strawberry, Carrot, Tomato)**: **$81,990.45** (55.44% of total revenue)
- **Livestock Products (Milk, Wool)**: **$50,700.69** (34.28% of total revenue)
- **By-Products (Fertilizer from Cow/Sheep manure)**: **$15,198.97** (10.28% of total revenue)
- Total Livestock Sector Contribution (Products + Manure): **$65,899.66** (44.56% of total revenue)

---

## 5. Itemized Expense Breakdown (Outflows)

All outflows were recorded directly from cash deductions for seeds, animals, feed, labor, and land.

| Expense Category | Mean Cost | Share (%) | Mean Units / Events | 95% Confidence Interval |
| :--- | :---: | :---: | :---: | :---: |
| **BUY_PRODUCT WHEAT (Feed)** | $30,932.05 | 63.06% | 849.8 units | [$29,730, $32,134] |
| **HIRE (Farm Hands)** | $7,537.80 | 15.37% | 293.9 hire-turns | [$7,532, $7,544] |
| **BUY_ANIMAL COW** | $2,676.00 | 5.46% | 6.7 cows | [$2,446, $2,906] |
| **BUY_ANIMAL SHEEP** | $2,225.00 | 4.54% | 4.5 sheep | [$1,929, $2,521] |
| **BUY_SEED STRAWBERRY** | $1,502.00 | 3.06% | 15.0 seeds | [$1,481, $1,523] |
| **BUY_SEED MELON** | $1,278.40 | 2.61% | 16.0 seeds | [$1,255, $1,302] |
| **BUY_SEED WHEAT** | $1,032.40 | 2.10% | 103.2 seeds | [$1,023, $1,042] |
| **BUY_LAND (NE Quadrant)** | $1,000.00 | 2.04% | 1.0 quadrant | [$1,000, $1,000] |
| **BUY_SEED CARROT** | $605.60 | 1.23% | 30.3 seeds | [$592, $619] |
| **BUY_SEED TOMATO** | $264.50 | 0.54% | 5.3 seeds | [$257, $272] |
| **Total Outflows** | **$49,053.75** | **100.00%** | — | **[$47,485, $50,622]** |

### Functional Expense Aggregation
- **Animal Feed (Market Wheat Purchases)**: **$30,932.05** (63.06% of all farm expenditures)
- **Workforce Expansion (Hiring Costs)**: **$7,537.80** (15.37% of all farm expenditures)
- **Livestock Capital Investment (Animals)**: **$4,901.00** (9.99% of all farm expenditures)
- **Crop Working Capital (Seed Purchases)**: **$4,682.90** (9.55% of all farm expenditures)
- **Land Acquisition (NE Quadrant Unlock)**: **$1,000.00** (2.04% of all farm expenditures)

---

## 6. Net Sector Margin Analysis

| Economic Sector | Inflows ($) | Outflows ($) | Net Margin ($) | Net Profit Margin (%) |
| :--- | :---: | :---: | :---: | :---: |
| **Crop Production Sector** | $81,990.45 | -$4,682.90 | **+$77,307.55** | **94.29%** |
| **Livestock Sector (Milk+Wool+Fert)** | $65,899.66 | -$35,833.05 | **+$30,066.61** | **45.63%** |
| **Farm Overhead (Labor + Land)** | $0.00 | -$8,537.80 | **-$8,537.80** | — |
| **Starting Cash** | +$3,000.00 | $0.00 | **+$3,000.00** | — |
| **Total Net Economic Value** | **$150,890.11** | **-$49,053.75** | **+$101,836.36** | — |

> [!IMPORTANT]
> The crop sector is an ultra-high margin cash engine (94.3% gross margin on seed investment, yielding +$77.3k net). The livestock sector generates substantial gross revenue ($65.9k), but consumes $30.9k in purchased wheat feed, yielding a net margin of +$30.1k.

---

## 7. Unconverted Resources at Season End (Day 29 Hour 23)

At the final tick of the game (Day 29 Hour 23, post-interpreter), all assets and inventories were audited:

| Asset Class | Units Remaining | Estimated Liquid Realizable Value | Engine Scoring Realization |
| :--- | :---: | :---: | :---: |
| **Unsold Shed Inventory** | **0.00 units** | $0.00 | $0.00 |
| **Unsold Worker Hands Inventory** | **0.00 units** | $0.00 | $0.00 |
| **Unharvested Crop Yield on Tiles** | **0.00 units** | $0.00 | $0.00 |
| **Unused Seed Inventory** | **0.00 units** | $0.00 | $0.00 |
| **Uncollected Fertilizer on Tiles** | **0.00 units** | $0.00 | $0.00 |
| **Living Cows** | 6.7 cows | $0.00 (engine provides $0 terminal asset salvage) | $0.00 |
| **Living Sheep** | 4.5 sheep | $0.00 (engine provides $0 terminal asset salvage) | $0.00 |
| **Unlocked Land (NW + NE)** | 50 tiles | $0.00 (engine provides $0 terminal asset salvage) | $0.00 |

### Key Takeaway:
**The production baseline achieves 100% terminal liquidation.** There is ZERO unsold inventory in the shed, ZERO inventory stranded in worker hands, and ZERO unharvested ripe crops left on tiles at season end. Every single dollar of potential harvest value produced during the season was successfully converted to cash.
