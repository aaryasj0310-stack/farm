# P6 Next Experiment Recommendation: P6.1 Shed-Overflow Prevention via Pre-Midnight Storage Hygiene

## 1. Executive Summary & Epistemic Justification

The P6-R audit verified with mathematical closure ($\epsilon = 0.000000$) that shed overflows destroy:
$$\mathbf{46.31 \text{ units/game}} \quad (\mathbf{\$4,300.60 \text{ base}} \; / \; \mathbf{\$6,026.53 \text{ realized price reference value}})$$
Over 78% of this destruction is concentrated in three high-value goods:
- **Strawberry**: 9.11 units discarded (\$2,266.63)
- **Wool**: 4.80 units discarded (\$1,047.17)
- **Milk**: 4.19 units discarded (\$1,013.91)

Crucially, the audit proved that other hypothesized gains were either fictitious (fertilizer backlog = $0, final-day terminal harvest = $0) or financially net-positive (Day 28 wheat churn = +$1,040 net cash).

Therefore, the next experiment must **NOT** be a bundled multi-variable reform. In strict adherence to scientific isolation principles, the next experiment is:

$$\mathbf{P6.1: \text{ Shed-Overflow Prevention via Pre-Midnight Storage Hygiene}}$$

> [!IMPORTANT]
> **Strict Single-Variable Scope**:
> P6.1 tests **strictly one mechanism**: pre-midnight storage headroom preservation.
> Do **NOT** combine with Day 28 feed harmonization, Day 29 endgame harvesting, crop substitution, or worker routing refactors.

---

## 2. Hypothesis P6.1

> **Hypothesis P6.1 (Pre-Midnight Storage Hygiene)**:
> *By monitoring shed inventory during late evening hours (Hours 20–22) and proactively liquidating surplus buffer items to maintain at least 25 units of shed headroom before workers execute their midnight inventory drops, physical shed overflow discards will decrease by $\ge 70\%$ ($\ge 32$ units preserved per game), delivering a net paired cash lift of $\ge +\$2,000.00 / \text{game}$ on the discovery panel without increasing animal feed starvation.*

---

## 3. Implementation Specification for P6.1

### 1. Architectural Placement
All changes will be isolated behind an explicit feature flag in `agent/config.py`:
```python
P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False  # Disabled by default
```

### 2. Algorithmic Mechanism
During late evening hours (`ctx["hour"] in (20, 21, 22)`):
1. **Compute Expected Midnight Influx**:
   $$\text{carried\_load} = \sum_{\text{workers}} \sum \text{inventory\_units}$$
   $$\text{projected\_midnight\_shed} = \text{current\_shed\_occupancy} + \text{carried\_load}$$
2. **Headroom Trigger**:
   If $\text{projected\_midnight\_shed} > 75$ (headroom $< 25$ units):
   Identify surplus liquidation candidates in strict priority:
   - **Tier 1 (Excess Fertilizer)**: Sell fertilizer exceeding immediate farm needs (`shed["FERTILIZER"] > 5`).
   - **Tier 2 (Excess Cash Crops)**: Drip-sell strawberries, wool, milk, or melons already deposited in shed.
   - **Tier 3 (Discretionary Wheat)**: Sell surplus wheat strictly above the safe feed reserve floor:
     $$\text{safe\_reserve\_floor} = \max(15, 2.0 \times \text{daily\_feed\_need})$$
3. **Safety Safeguards**:
   - **Hard Invariant 1 (Feed Protection)**: Never sell wheat if remaining shed wheat $\le \text{safe\_reserve\_floor}$.
   - **Hard Invariant 2 (Priority Domination)**: Never displace `P0_CRITICAL` market orders (emergency feed wheat purchases).
   - **Hard Invariant 3 (Time Window Lock)**: Storage hygiene flushes are active strictly during Hours 20–22, preventing disruption to intraday market operations.

---

## 4. Experimental Design & Go / No-Go Decision Gates

### Evaluation Protocol
- **Panel**: 100 matched pairs (10 discovery seeds `96,401`–`96,410` $\times$ 5 opponents $\times$ 2 balanced seats = 200 live games).
- **Control**: Production baseline commit `536f1e7` ($101,035.79 mean cash).
- **Treatment**: Production baseline with `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = True`.
- **Protected Verification**: Held-out tournament seeds `98,001`–`98,050` remain 100% untouched.

### Quantitative Decision Gates

```
                            P6.1 DECISION GATES
  ┌────────────────────────────────────────────────────────────────────────┐
  │ 1. GO (Pass to Pre-Merge Audit):                                       │
  │    - Mean Paired Cash Delta >= +$2,000.00 / game (p < 0.01)            │
  │    - Physical shed discards reduced by >= 70% (<= 14 units vs 46.31)   │
  │    - Animal feed starvation rate strictly 0.0% (zero missed feeds)     │
  ├────────────────────────────────────────────────────────────────────────┤
  │ 2. ITERATE:                                                            │
  │    - Mean Paired Cash Delta between +$800.00 and +$2,000.00 / game      │
  │    - Discard reduction between 40% and 70%                             │
  │    - Zero animal feed starvation                                       │
  ├────────────────────────────────────────────────────────────────────────┤
  │ 3. NO-GO (Reject):                                                     │
  │    - Mean Paired Cash Delta < +$800.00 / game                          │
  │    - Any increase in animal feed starvation or missed feeds            │
  │    - Significant price collapse (>15%) on liquidated cash crops        │
  └────────────────────────────────────────────────────────────────────────┘
```
