# P5.0-R Labor Opportunity Reconciliation & Dispatch Contention

## 1. Worker Action Accounting per Unit Crop

A rigorous economic model cannot assume that worker labor is an infinite, zero-cost resource. Every crop substitution alters the number and temporal distribution of physical worker actions (`PLANT`, `WATER`, `HARVEST`).

### 1.1 Action Ledger per Tile Lifecycle

| Crop Lifecycle | Plant Actions | Water Actions | Harvest Actions | Total Actions | Maturation Span | Actions/Day |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Wheat (1 Cycle)** | 1 | 4 (Days $P, P+2, P+3, P+4$) | 1 (Day $P+4$) | **6 actions** | 4 days | 1.50 |
| **Carrot (1 Cycle)** | 1 | 3 (Days $P, P+2, P+3$) | 1 (Day $P+3$) | **5 actions** | 3 days | 1.67 |
| **Carrot (2 Cycles)** | 2 | 6 ($2 \times 3$) | 2 ($2 \times 1$) | **10 actions** | 6 days | 1.67 |

### 1.2 Net Labor Demand Deltas
- **Single-Cycle Substitution (Days 24–25)**:
  $$\Delta_{\text{actions}} = 5 - 6 = \mathbf{-1\text{ action}}$$
  *Paradoxical Finding*: A single carrot cycle requires *less* labor than a wheat cycle. It consumes 1 fewer watering turn. However, as shown in the economic analysis, it generates lower net revenue.
- **Two-Cycle Substitution (Days 21–23)**:
  $$\Delta_{\text{actions}} = 10 - 6 = \mathbf{+4\text{ actions over 6 calendar days}}$$
  Spread across 6 days, this represents an additional labor load of only **+0.67 actions per day per substituted tile**.

---

## 2. Intraday Contention & Shadow Wage Profiles

Worker hours are not interchangeable. In Kaggriculture, the value of worker time depends heavily on the hour of the day:

1. **Morning Peak (Hours 0–5)**:
   - *Obligations*: Urgent survival watering of unwatered crops, animal feeding before production windows, emergency market pickups.
   - *Congestion*: High. Workers often traverse across quadrants.
   - *Empirical Shadow Value*: **$35.00 per action**.
2. **Midday Operational Window (Hours 6–11)**:
   - *Obligations*: Normal bonus watering, animal care, standard crop harvesting.
   - *Congestion*: Moderate.
   - *Empirical Shadow Value*: **$20.00 per action**.
3. **Afternoon / Evening Slack (Hours 12–23)**:
   - *Obligations*: Replanting empty tiles, discretionary deposits, idle staging.
   - *Congestion*: Very Low. Workers frequently execute `PASS` or low-priority movements.
   - *Empirical Shadow Value*: **$8.00 per action**.

---

## 3. Why Two Carrot Cycles Do Not Cause Labor Starvation

A key operational concern is whether adding +4 worker actions per tile over Days 21–29 could starve critical animal feeding or cause crop decay. 

Empirical analysis of our 100 discovery games reveals why labor starvation does not occur:
1. **Late-Season Workforce Size**:
   By Day 21, the farm has hired between 10 and 13 farm hands, yielding a total workforce of **11 to 14 workers** ($264\text{ to }336\text{ worker turns per day}$).
2. **Post-Strawberry Slack**:
   Early strawberry beds (which require intensive daily care) are cleared by Days 20–22. Total daily watering demand drops by 30–40% precisely when T1 activates.
3. **Afternoon Planting Execution**:
   Planting queue actions run primarily during Hours 1–17. The 2nd cycle of carrot planting occurs in afternoon slack hours once morning harvests complete.

---

## 4. Labor Stressed Sensitivity Analysis

To rigorously stress-test the policy, we evaluated the joint shadow delta under full labor penalization:
$$\text{Penalty}_{\text{labor}} = \Delta_{\text{actions}} \times w(h)$$
where $w(h) \in \{\$35, \$20, \$8\}$ depending on the hour of decision.

### Results Across 100 Discovery Games (Days 21–23 Refined Boundary):
- **Raw Crop Economic Delta (Zero Labor Cost)**: **+$1,049.33 / game** (Median: +$1,063.00)
- **Primary Task-Displaced Delta ($12/action slack penalty)**: **+$655.25 / game** (Median: +$500.00)
- **Extreme Labor-Stressed Delta ($35/$20/$8 peak penalties)**: **+$642.37 / game** (Median: +$459.00)

### Conclusion:
Even under the most aggressive labor penalty model, the refined Day 21–23 T1 opportunity retains **over 98% of its task-displaced value** (+$642.37 vs +$655.25). Labor contention is a negligible headwind for this specific operational window.
