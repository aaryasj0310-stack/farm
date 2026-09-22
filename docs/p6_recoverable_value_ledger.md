# P6 Mutually Exclusive Recoverable-Value Ledger

## 1. Accounting Principles & Epistemic Standards

To ensure absolute scientific rigor and avoid double-counting, every potential opportunity identified in the P6 Audit is strictly classified under four epistemic definitions:

1. **`MEASURED FACT`**: Direct physical observation from simulation telemetry across 100 baseline games (exact units, cash spent, cash realized).
2. **`INFERRED RECOVERABLE VALUE`**: Conservative, causal estimate of net cash that can be captured by modifying a specific mechanism, accounting for market price slippage, worker opportunity costs, and downstream interactions.
3. **`THEORETICAL UPPER BOUND`**: Mathematical maximum value assuming zero friction, zero price elasticity, zero transit time, and infinite shed capacity.
4. **`NOT A REAL OPPORTUNITY`**: Apparent paper gains that cannot be physically harvested without causing equal or greater systemic regressions (e.g. forced rapid harvesting leading to shed discards, or crop replanting cannibalizing livestock feed as seen in P5.1).

---

## 2. Mutually Exclusive Recoverable Ledger

| Ledger Item | Primary Root Cause | Measured Fact (Telemetry Data) | Theoretical Upper Bound | Inferred Recoverable Value | Epistemic Classification |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **1. Shed Overflow Discards** | Shed 100-cap overflow at Day-End drop-off | 46.31 units/game destroyed (\$6,026.53/game) | \$6,026.53 | **+\$3,800.00 – \$4,600.00** | `MEASURED FACT` / `INFERRED RECOVERABLE` |
| **2. Unharvested Day-29 Assets** | Harvest dispatch terminates early on Day 29 | 11.50 mature units left on tiles at Turn 720 | \$1,456.30 | **+\$900.00 – \$1,250.00** | `MEASURED FACT` / `INFERRED RECOVERABLE` |
| **3. Livestock Missed Care Bonus** | Worker transit delays causing missed daily cares | 24.69 missed cares/game (17.1 Cow, 7.6 Sheep) | \$5,681.00 | **+\$1,200.00 – \$1,800.00** | `INFERRED RECOVERABLE VALUE` |
| **4. Fertilizer Disposal Backlog** | Market order slot exhaustion bumps fertilizer | 33.47 units produced but unsold/unliquidated | \$2,723.49 | **+\$800.00 – \$1,400.00** | `INFERRED RECOVERABLE VALUE` |
| **5. Day 28 Wheat Churn Spread** | Desynchronized simultaneous buy/sell orders | 453 units bought / 468 sold on Day 28 | \$500.00 | **+\$150.00 – \$300.00** | `MEASURED FACT` (Direct) |
| **6. Freed Worker Labor (Crops)** | 64.85% transit overhead (4,783 moves) | 400–600 moves recoverable via route bundling | \$6,000.00 | **+\$800.00 – \$1,500.00** | `INFERRED RECOVERABLE VALUE` |
| **7. "Living Storage" Tile Turnover** | Crops held mature for 679.5 tile-days (51.5%) | 51.5% of farm occupied by mature plants | \$12,000.00 | **\$0.00 (Structural)** | `NOT A REAL OPPORTUNITY` (In isolation) |
| **TOTALS** | — | **\$101,035.79 Baseline** | **\$34,387.32** | **+\$7,650.00 – \$10,850.00** | — |

---

## 3. Reconciliation Against the $130,000 Target

```
[Baseline Current Mean: $101,035.79]
       │
       ├─► +$4,200.00 (Eliminate Shed Discards: Strawberries, Wool, Milk)
       ├─► +$1,500.00 (100% Livestock Care Adherence via Priority Dispatch)
       ├─► +$1,100.00 (Harvest Day-29 Season-End Field Output)
       ├─► +$1,100.00 (Liquidate Fertilizer Backlog)
       ├─► +$1,150.00 (Freed Labor into Incremental Crops)
       ├─► +$200.00   (Day 28 Wheat Churn Brokerage Spread)
       │
       ▼
[Realistic Optimized Baseline Ceiling: ~$110,300.00 / game]
       │
       ▼  Remaining Gap to $130,000 Target: ~$19,700.00 / game
```

### Critical Epistemic Conclusion
Fixing the measurable inefficiencies and bugs in the current production baseline recovers **+$7,650 to +$10,850 / game**, lifting performance from **~$101.0k to ~$109k–$112k**.

> [!WARNING]
> **The $130k Target Cannot Be Reached by "Bug Fixes" Alone**:
> Anyone claiming that the baseline can reach $130,000 solely by fixing shed discards and worker transit is mathematically mistaken. 
> To bridge the remaining **~$19,700 gap** between ~$110k and $130k requires **Macro-Architectural Expansion**:
> 1. Profitable activation of the **SW Quadrant** ($2,000 land cost; requires dedicated squad logistics).
> 2. High-density animal scaling (expanding herd beyond 7 cows / 5 sheep).
> 3. Introducing an automated multi-crop scheduler that operates outside the core wheat quadrant.
