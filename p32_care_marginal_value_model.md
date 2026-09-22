# Kaggriculture P3.2 — State-Dependent Animal Care Marginal Value Model

## 1. Mathematical Formulation of CARE Marginal Value

The expected realizable marginal value of an animal `CARE` action at day $d$, hour $h$ on tile $(x, y)$ is defined as:

$$\text{CARE\_MV}(t, d, h) = P(\text{Banked}) \times P(\text{Harvested \& Sold}) \times \text{Spot\_Price}(\text{Product}) - \text{Opportunity\_Cost}$$

### Parameter Definitions
1. **$P(\text{Banked})$**: Probability that this CARE action increments `pending_care_bonus` at end of day:
   - In engine: `if tile["cared_today"] and tile["fed_today"]: pending += 1`.
   - If `tile["fed_today"] == True`: $P(\text{Banked}) = 1.0$.
   - If `tile["fed_today"] == False`: $P(\text{Banked}) \le P(\text{Fed by Hour 23})$. If feed cannot be secured, $P(\text{Banked}) = 0.0$.
2. **Cycle Saturation Gate**:
   - For **Cow** (`interval = 2`): At most 2 care bonuses can be consumed per production cycle.
     $$\text{Marginal Bonus} = \begin{cases} 1 & \text{if } \text{pending\_care\_bonus} < 2 \\ 0 & \text{if } \text{pending\_care\_bonus} \ge 2 \end{cases}$$
   - For **Sheep** (`interval = 3`): At most 3 care bonuses can be consumed per production cycle.
     $$\text{Marginal Bonus} = \begin{cases} 1 & \text{if } \text{pending\_care\_bonus} < 3 \\ 0 & \text{if } \text{pending\_care\_bonus} \ge 3 \end{cases}$$
3. **Holding Capacity Gate**:
   - `max_held = 6` for both Cow and Sheep.
   - If $\text{yield\_units} + 1 + \text{pending\_care\_bonus} \ge 6$:
     Any bonus beyond holding capacity is permanently discarded by `min(6, yield + base + bonus)`.
     $$\text{Capacity Available} = \max(0, 6 - \text{yield\_units} - 1 - \text{pending\_care\_bonus})$$
4. **Terminal Season Realizability**:
   - Let $d_{\text{next}}$ be the next scheduled production day for this animal.
   - If $d_{\text{next}} > 29$ or $d \ge 29$:
     The product will produce after the season ends (Day 30+).
     $$\text{CARE\_MV} = \$0.00$$

---

## 2. Comparison: CARE vs. Competing Scheduler Tasks

| Scheduler Task | Baseline Priority | Marginal Output | Physical Realized Value |
| :--- | :---: | :--- | :---: |
| **Urgent Survival Water / Feed** | **100** | Prevents plant death / animal escape | $100–$1,000 |
| **Decay Harvest** | **90** | Rescues ripe crop before decay | $25–$250 |
| **Feed Animal (Prod Day)** | **85** | Enables production + unlocks care bonus | $50–$200 |
| **Max-Day Bonus Water** | **76** (`70 + 6`) | Final watering before one-time harvest | $25–$150 |
| **Collect Fertilizer** | **75** | +1 Fertilizer (sold for cash or applied) | $100 |
| **Plant & Water** | **75** | Founds new crop cycle | $50–$250 |
| **Routine Bonus Water (Wheat)** | **70** | **+1 Wheat yield unit** | **$25.00** |
| **Routine Bonus Water (Carrot)** | **70** | +1 Carrot yield unit | $35.00 |
| **Standard Harvest** | **65** | Harvests mature produce | $25–$250 |
| **Baseline Animal CARE** | **65** | **+1 Milk ($160) or +1 Wool ($200)** | **$160.00–$200.00** |

### The Core Economic Inversion
At baseline:
- Routine wheat watering has priority **70**, generating **+$25.00**.
- Realizable Cow/Sheep care has priority **65**, generating **+$160.00 to +$200.00**.
- The ratio of marginal values is **6.4$\times$ to 8.0$\times$** in favor of CARE!
- Setting high-value realizable CARE to **Priority 72** places it directly above routine wheat watering (70) while leaving max-day decay water (76), fertilizer collection (75), planting (75), and feeding (85) completely dominant.
