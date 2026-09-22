# P6.1-C Final Outcome Verdict & Recommendation

## 1. Formal Decision & Classification

### Mechanism Verdict: **MECHANISM NO-GO**
The physical mechanism designed in P6.1 — *Shed-Overflow Prevention via Pre-Midnight Storage Hygiene* — is a definitive **NO-GO**:
- Discard Reduction Target: **$\ge 70.0\%$** (reduce discards to $<12$ units/game).
- Discard Reduction Achieved: **$2.80\%$** (reduced discards from 42.08 to 40.90 units/game, saving only 1.18 units).
- **Failure Cause**: Fundamental physical decoupling between shed inventory and worker backpacks in the simulation engine. The items causing midnight overflow reside in field backpacks, which the engine's market processor cannot sell. Pre-midnight shed sales were idle in 43.9% of windows and only sold 7.57 times per 30-day game.

### Strategic Treatment Recommendation: **TREATMENT ITERATE (NO-GO ON MECHANISM, PIVOT TO P6.2)**
The P6.1 implementation must **remain disabled** (`P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False`). It must not be promoted to production or merged into baseline.

---

## 2. Evaluation of the Three Candidate Classifications

| Candidate Taxonomy | Assessment | Decision |
| :--- | :--- | :---: |
| **Option A: Repeatable Early-Liquidity Effect (P6.1b)** | **REJECTED**. The forensic reconciliation proved that early liquidity compounding is a myth. Cash curves are 100% identical through Day 10. The unexplained +$778.16 was simply feed wheat expenditure savings ($749.18), not compounding. Furthermore, against the strongest benchmark (`full_production_agent`), Treatment suffered a severe -$1,543.55 loss. | **NO** |
| **Option B: Storage Mechanism Failed, Cash Signal Mostly Incidental (P6.2)** | **SELECTED (PRIMARY)**. The storage mechanism failed completely (2.8% vs 70% target). The +$1,439.86 cash gain was heavily concentrated in 10 right-tail outlier games (89.6% of total gain), while median gain was only +$642.50, win rate was only 57%, and Treatment lost badly against full-production opponents. The positive cash delta was primarily an incidental byproduct of preserving feed wheat and random harvest timing shifts. | **YES** |
| **Option C: Mixed Result / Partial Attribution** | **SUPPORTING INSIGHT**. P6.1-C proved that preserving on-farm feed wheat via a safety buffer generated an authentic +$17.69 transfer arbitrage and improved cow feeding continuity (+1.26 milk = +$511.26). This feed preservation insight should be salvaged and re-architected cleanly in a future milestone (P6.2). | **PARTIAL** |

---

## 3. Comprehensive Synthesis of Findings

### 1. The Cash Delta Waterfall ($\epsilon = 0.000000$)
$$\Delta \text{Final Cash} = \Delta \text{Sales Revenue} - \Delta \text{Expenditures}$$
$$+\$1,439.86 = (+\$661.70) - (-\$778.16)$$
- **Sales Revenue Inflow**: **+$661.70** (Milk +$799.35, Melon +$535.48, Strawberry +$115.62, Wheat -$731.49, Wool -$137.40, Others +$80.14).
- **Expenditures Outflow**: **-$778.16** (Feed Wheat -$749.18, Seeds -$4.90, Animals -$14.00, Wages -$10.08, Land $0.00).
- **Closure**: Max residual across all 100 scenario pairs is exactly **0.000000**.

### 2. De-Mythologizing "Early Liquidity Compounding"
- The +$778.16 was **not** compounding returns from early sales.
- **$749.18 (96.3%)** was avoided purchases of feed wheat from the town store.
- Treatment retained 24.24 units of wheat on-farm (forfeiting -$731.49 in wholesale sales revenue), which directly displaced 23.16 units of retail feed wheat purchases from town (saving +$749.18). Net internal arbitrage: **+$17.69**.

### 3. Outlier and Opponent Fragility
- **Heavy Outlier Skew**: Just 10 pairs generated **89.6%** ($129,000 / $143,986) of the net gain.
- **Median vs Mean**: Median cash delta is **+$642.50** (less than half the mean).
- **Competitor Fragility**: Against `full_production_agent`, Treatment lost by **-$1,543.55/game** with a **35.0% win rate**, suffering a **-$19.95/unit price collapse** in wool due to town market desynchronization.

### 4. Storage Decoupling & Intraday Infeasibility
- At H20–22, the shed holds only ~31 units (nearly all protected feed wheat), while worker backpacks hold ~35 units (peaking at 60–85 units on harvest days).
- Market sell orders cannot access backpacks.
- Manual intraday worker deposits are economically non-viable: transit step costs (16–30 hours round trip) cause massive labor destruction that dwarfs the value of saved discards.
- Discarding low-value wheat/fertilizer during midnight teleportation is mathematically superior to walking workers back and forth to the shed.

---

## 4. Next Step Recommendations

1. **Permanently Retire P6.1**:
   - Keep `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False`.
   - Update knowledge base and experiment logs to archive P6.1 as a Mechanism No-Go.
2. **Design P6.2 Based on Validated Causal Drivers**:
   - Rather than attempting to prevent midnight shed discards, focus future optimizations on:
     - **Dynamic Feed Buffer Optimization**: Systematize the internal wheat transfer pricing benefit without disrupting market sales.
     - **Market-Aware Selling against Competing Agents**: Prevent price erosion in town shops when playing against aggressive multi-product opponents like `full_production_agent`.
