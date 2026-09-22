# P5.0-R Secondary Report Corrections & Errata Catalog

## 1. Executive Summary

Inspection of the diagnostic commit `a1d58aae78e2fbc19585fb702808d42537dc8825` and prior secondary documentation revealed several material discrepancies in crop parameters, lifecycle mechanics, economic multipliers, and statistical assumptions.

This document provides a line-by-line reconciliation and formal errata to supersede all erroneous claims in earlier documentation.

---

## 2. Itemized Reconciliation Catalog

### Correction 1: T1 Headline Opportunity Sizing
- **Prior Claim (Commit `a1d58aa`)**:
  Claimed a headline opportunity of **+$1,121.85 / game** for T1 late-wheat substitution across Days 21–25.
- **Root Cause**:
  The calculation hardcoded `t1_unit_gain = 45.0` for all wheat plantings on Days 21–25 without evaluating whether carrots were profitable, whether multiple decisions hit the same tile, or whether the second cycle fit.
- **Corrected Finding (P5.0-R)**:
  - Days 24–25 substitutions are **unprofitable (-$24.50 per event)**.
  - Sizing must be restricted to **Days 21–23**.
  - Enforcing joint physical feasibility and causal market pricing yields:
    - **Raw Crop Economic Delta**: **+$1,049.33 / game**
    - **Primary Task-Displaced Delta**: **+$655.25 / game**
    - **Labor-Stressed Delta**: **+$642.37 / game**

---

### Correction 2: Feed Security Classification Methodology
- **Prior Claim (Commit `a1d58aa`)**:
  Classified wheat as surplus using static aggregate formula:
  $$\text{expected\_incoming} = \text{in\_ground\_wheat} \times 6$$
- **Root Cause**:
  Ignored physical unfertilized yield caps (4, not 6) and temporal distribution. A static sum cannot detect intermediate day starvation gaps.
- **Corrected Finding (P5.0-R)**:
  Replaced by the **Time-Indexed Dynamic Feed Ledger**:
  $$B_d = B_{d-1} + H_d - F_d \quad \forall d \in [D, 28]$$
  Under this exact model, out of 2,493 observed events:
  - **RW3 (Genuine Economic Surplus)**: 2,489 (99.8%)
  - **RW2 (Feed Buffer Support)**: 4 (0.2%)
  - **RW1 (Feed Critical Deficit)**: 0 (0.0%)

---

### Correction 3: Production & Economic Constants
- **Prior Claims**:
  - Wheat Seed: $20.00
  - Carrot Seed: $35.00
  - Wheat Max Unfertilized Yield: 6 units
  - Carrot Max Unfertilized Yield: 2 units
  - Wheat Maturation: 5 days
- **Engine Ground Truth (`kaggriculture.py`)**:
  - Wheat Seed: **$10.00**
  - Carrot Seed: **$20.00**
  - Wheat Max Unfertilized Yield: **4 units** ($1 + 1 + 1 + 1$)
  - Carrot Max Unfertilized Yield: **3 units** ($1 + 1 + 1$)
  - Wheat Maturation: **4 days** (Day $P \rightarrow P+4$)
  - Carrot Maturation: **3 days** (Day $P \rightarrow P+3$)

---

### Correction 4: Feed Obligation Horizon
- **Prior Claim**:
  Calculated feed requirements through Day 29 or Day 30.
- **Engine Ground Truth**:
  Animals fed on Day 28 produce products on Day 29 that are collected and sold. Animals fed on Day 29 produce product at Step 720 (game end), which can never be collected or liquidated. Therefore, all feed obligations strictly terminate at the end of **Day 28**.

---

### Correction 5: Usable Core Land Capacity
- **Prior Claim**:
  Cited 46 cultivable tiles in the core quadrants.
- **Engine Ground Truth**:
  Physical core tiles: $25\text{ (NW)} + 25\text{ (NE)} = 50\text{ tiles}$. 
  Shed access transit tiles: $(4,4)$ and $(5,4)$ ($2\text{ tiles}$).
  Policy-cultivable core tiles: $50 - 2 = \mathbf{48\text{ tiles}}$.
  The prior figure of 46 double-counted two transit borders.

---

### Correction 6: Livestock Purchase Pricing
- **Prior Claim**:
  Sheep cost cited as $300.00.
- **Engine Ground Truth**:
  - `COW`: **$400.00**
  - `SHEEP`: **$500.00**
  - `GOOSE`: **$300.00**

---

### Correction 7: Statistical Detectability & Sample Size
- **Prior Claim**:
  Assumed an arbitrary standard deviation of $\sigma = \$1,200$ and asserted that $N=100$ games was universally sufficient.
- **Corrected Methodology (P5.0-R)**:
  Statistical power and minimum detectable effect (MDE) are calculated from the empirically measured paired standard deviation $\sigma_\Delta = \$801.01$ using standard two-sided power formulations ($\alpha = 0.05, 1 - \beta = 0.80$).
