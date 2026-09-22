# Kaggriculture P3.4 — Phase 5: Recoverable Feed-Logistics Value Ledger

## Executive Summary

This document establishes the dollar-denominated recoverable opportunity ledger for feed pickup and animal logistics under the authoritative production baseline ([`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`](file:///d:/website%20project/kaggri%20ox)).

---

## 1. Dollar-Denominated Opportunity Ledger

| Candidate Area | Observed Baseline Behavior | Hypothesized Inefficiency | Feasible Alternative Sequence | Net Worker Turns Saved | Incremental Final Score Realization | Risk of Economic Regression | Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C1: Repeat Wheat Pickups on Same Day** | Workers make 13.95 repeat pickups / game across season | Worker returns to shed instead of grabbing larger batch earlier | Allow chunk size 4–5 when shed wheat allows | **~4 to 8 turns / game** | **+$0 to +$50 / game** | Moderate (parallelism loss in early-game) | **Modeled Counterfactual (Economically Negligible)** |
| **C2: Daytime Feed Pre-Staging** | Staging tasks generated only when `feeds_due > held` | Staging is reactive each morning | Pre-stage wheat on workers at end-of-day | **0 turns** (EOD auto-drop empties inventory anyway) | **$0 / game** | High (interferes with EOD product deposit) | **Unsupported Hypothesis** |
| **C3: Dedicated Feed Carrier Role** | 3.74 workers share feeding daily | Multi-worker feeding duplicates travel to shed | Single dedicated carrier services all animals | **Negative** (Carrier must walk full perimeter) | **-$500 to -$2,000 / game** | Extreme (delays feeding in opposite quadrant) | **Negative Realization (Rejected)** |
| **C4: Avoiding Day-29 Deliveries** | Day 29 executes 20.15 delivery actions | Travel to shed on Day 29 costs turns | Rely on EOD auto-drop | **0 turns** (EOD auto-drop occurs after final market) | **-$20,000 / game** (all products left unsold) | Fatal (100% loss of Day 29 revenue) | **Fatal Anti-Pattern (Rejected)** |

---

## 2. Deep Dive: Why Feed Logistics Savings Do Not Monetize

### The Core Equation of Labor Monetization
$$\Delta \text{Final Score} = (\text{Turns Saved}) \times (\text{Conversion Rate to Productive Work}) \times (\text{Marginal Value of Work}) - \text{Disruption Penalty}$$

Applying this formula to Candidate C1 (Batch Size 4–5):
1. **Gross Turns Saved**:
   Across 20 games, increasing batch size from 3 to 5 saves 3.05 journeys per game. Since the average shed-to-field distance is only 1.32 tiles, eliminating 3.05 journeys saves approximately:
   $$\text{Turns Saved} \approx 3.05 \text{ journeys} \times 2 \text{ tiles/journey} \approx \mathbf{6.1\text{ turns per game}}.$$
2. **Contextual Magnitude**:
   The baseline uses **7,380 worker turns per game**, of which **4,778 turns are movement**.
   Saving 6.1 movement turns represents **0.13% of total movement turns**!
3. **Conversion to Productive Work**:
   Even if all 6.1 turns were converted into routine watering (+6 watering actions at $25/each):
   $$\text{Maximum Theoretical Upside} \le 6.1 \times \$25 = \mathbf{+\$152.50\text{ per game}}.$$
4. **Disruption Risk Penalty**:
   However, concentrating wheat reduces feeding parallelism from 3.74 to ~2.5 workers. If even **one cow or sheep** misses a single production cycle or daily care bonus due to delayed feeding, the loss is:
   $$\text{Loss per Missed Milk/Wool Cycle} \ge \mathbf{-\$160\text{ to }-\$200}.$$
   If an animal enters starvation and escapes, the loss is:
   $$\text{Loss per Animal Escape} \ge \mathbf{-\$300\text{ to }-\$500\text{ capital}} + \text{lost lifetime yield} \approx \mathbf{-\$2,500}.$$
   As demonstrated in P3.2, small disruptions to livestock feeding schedules destroyed **-$3,455/game**.

---

## 3. Causal Distinction: Action Counts vs Recoverable Value

The empirical audit unequivocally proves:
$$\text{Fewer Pickup Actions} \neq \text{Fewer Journeys} \neq \text{More Productive Work} \neq \text{Higher Score}$$

- **Fewer Pickup Actions**: Going from 3 to 5 wheat reduces action count by ~3/game, but does not meaningfully reduce travel because workers already stand adjacent to shed tiles.
- **Negligible Travel Savings**: At ~6 turns per game, the capacity recovered is statistical noise.
- **Asymmetric Risk**: The potential gain (+\$0–\$150) is dwarfed by the downside risk of livestock disruption (-\$1,000 to -\$3,500).
- **Target Comparison**: The remaining gap to the \$130,000 target is approximately **\$26,800/game**. Attempting to extract ~\$50 from feed chunking while risking livestock solvency cannot close this gap.
