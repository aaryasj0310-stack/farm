# P6 Mutually Exclusive Recoverable-Value Ledger (P6-R Corrected)

## 1. Accounting Principles & Epistemic Standards

To ensure absolute scientific rigor and avoid double-counting, every potential opportunity identified in the P6 Audit has been re-evaluated and classified under four epistemic definitions:

1. **`MEASURED FACT`**: Direct physical observation from simulation telemetry across 100 baseline games (exact units, cash spent, cash realized).
2. **`MEASURED REFERENCE VALUE`**: Calculated cash value of observed physical loss at catalog base prices or baseline realized sale prices.
3. **`UNTESTED HYPOTHESIS`**: Realistic net cash recoverable via algorithmic modification after accounting for market price elasticity, sell-timing constraints, and worker opportunity costs.
4. **`NOT A REAL OPPORTUNITY`**: Apparent paper gains that cannot be physically captured under the game rules or without causing equal or greater systemic collapse.

---

## 2. Mutually Exclusive Recoverable Ledger

| Ledger Item | Primary Root Cause | Measured Fact (Telemetry Data) | Reference Valuation | Feasible Recoverable Cash | Epistemic Classification | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **1. Shed Overflow Discards** | Shed 100-cap overflow at midnight worker drop-off | 46.31 units/game destroyed across 16.76 events | \$4,300.60 (base) / \$6,026.53 (realized) | **+\$2,500.00 – \$4,000.00** | `MEASURED FACT` / `UNTESTED HYPOTHESIS` | **PRIMARY TARGET (P6.1)**. 78% in Strawberry (9.11 u), Wool (4.80 u), Milk (4.19 u). |
| **2. Livestock Care Adherence** | Transit congestion causing late-day missed cares | 15.81 Cow / 11.39 Sheep missed production cares | \$4,809.52 (27.20 u @ realized) | **+\$800.00 – \$1,500.00** | `MEASURED FACT` / `UNTESTED HYPOTHESIS` | Secondary target. Requires tighter routing to prevent late-day care skips. |
| **3. Worker Transit Labor** | Center shed shuttling (64.85% moves / 4,783 moves) | 400–600 moves recoverable via route bundling | \$6,000.00 (labor equiv) | **+\$500.00 – \$1,200.00** | `INFERRED ESTIMATE` | Requires route bundling; high risk of secondary regressions if poorly scheduled. |
| **4. Day 28 Wheat Churn** | Simultaneous opposing buy/sell orders (20 u/hr) | 440.4 b / 466.0 s (Net +$1,040.97 cash) | \$0.00 (Already net positive) | **\$0.00 (Friction only)** | `MEASURED FACT` | Churn yields net cash. Eliminating it saves 40 slots/day but direct cash lift is ~\$0. |
| **5. Fertilizer Backlog** | Alleged market slot saturation bumping fertilizer | 218.1 col = 187.8 s + 23.7 fert + 4.7 d + 2.0 w | \$0.00 (Conservation closed) | **\$0.00 (Refuted)** | `NOT A REAL OPPORTUNITY` | **WITHDRAWN**. Ending shed is 0.00. Mathematical conservation closed ($\text{Diff}=0$). |
| **6. Final-Day Harvest** | Alleged early harvest shutdown on Day 29 | 11.53 terminal units spawned at step 719 | \$1,456.30 (Post-game) | **\$0.00 (Refuted)** | `NOT A REAL OPPORTUNITY` | **WITHDRAWN**. Pre-EOD mature = 0.00. Physically unharvestable under engine rules. |
| **7. "Living Storage" Tile Idle** | Outdoor storage buffering shed capacity cap | 51.47% tile-days holding mature crops | Structural buffer | **\$0.00 (Systemic)** | `NOT A REAL OPPORTUNITY` | Required to buffer shed cap (100). Cannot be harvested without causing discards. |
| **TOTALS** | — | **100 Games (Baseline Mean: $101,035.79)** | — | **+\$3,800.00 – \$6,700.00** | — | **Defensible Realizable Baseline Potential** |

---

## 3. Reconciliation Against the $130,000 Target

```
[Baseline Current Mean: $101,035.79]
       │
       ├─► +$3,250.00 (P6.1: Shed-Overflow Prevention via Pre-Midnight Storage Hygiene)
       ├─► +$1,150.00 (Future: Livestock Care Scheduling & Route Prioritization)
       ├─►   +$850.00 (Future: Worker Transit Reduction & Route Bundling)
       │
       ▼
[Defensible Optimized Baseline Ceiling: ~$106,200.00 – $107,800.00 / game]
       │
       ▼  Remaining Gap to $130,000 Target: ~$22,200.00 – $23,800.00 / game
```

### Critical Epistemic Conclusion
Correcting the P6 audit eliminates fictitious gains (fertilizer backlog and final-day harvest) and resets the realistic baseline recovery ceiling to **+$3,800 to +$6,700 / game**, lifting performance from **~$101.0k to ~$106k–$108k**.

> [!WARNING]
> **The $130k Target Cannot Be Reached by Baseline Bug Fixes Alone**:
> Reaching the competition target of **$130,000** strictly requires **Macro-Architectural Expansion** (profitable SW quadrant development and secondary livestock scaling) once storage hygiene is established.
