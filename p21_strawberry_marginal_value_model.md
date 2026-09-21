# Kaggriculture P2.1 — Strawberry Marginal Value & Portfolio Economic Model

**Author**: Antigravity  
**Commit Baseline**: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`  
**Current HEAD**: `18740e0e6b2c02bd547b411eb08214edb03acbd4`  
**Target Scope**: Phases C & D (Realized Strawberry Economics & Comparative Marginal Valuation)

---

## 1. The Economic Challenge of Strawberry Monoculture

In the True Production Baseline (`237cf5e...`), the agent allocates up to **18–20 tiles** to strawberries between Days 3 and 13.
While strawberries have the highest nominal base price ($120) among recurring crops, allocating 20 tiles introduces three severe economic penalties:

1. **Own-Supply Market Glut Crash**:
   - Strawberry market parameters: $I_0 = 10,000, T = 100, \text{above\_target} = 1.60$.
   - The price above $I_0$ drops linearly:
     $$P(I) = 120 - 1.92 \times (I - 10000)$$
   - At $I = 10,063$, the price drops to the absolute floor of **$1.00**.
   - 20 tiles producing 6 units each injects **120 units** of supply. If town shops consume only 60–80 units across the mid-game, dumping 120 units crashes spot price from ~$280 straight into single digits!
2. **Extensive Full-Season Occupancy & Maintenance Labor**:
   - A strawberry planted on Day 13 produces on Days 23, 25, 27, and 29.
   - It occupies the tile for **17 consecutive days** and requires **17 daily watering actions**.
   - At a conservative shadow cost of $5/worker action, maintaining one strawberry plant through Day 29 consumes **$85 in watering labor** + $20 in harvest/delivery actions + $100 seed cost = **$205 total cost per tile**!
3. **Displacement of High-Yield Alternative Crops**:
   - On that same tile, a sequence of **Wheat** crops (5 days per cycle, 3 units per harvest, seed cost $10) could cycle 3 times between Day 13 and Day 28:
     - 3 harvests $\times$ 3 units = 9 wheat units.
     - If consumed by cows, 9 wheat units avoids purchasing 9 wheat at $25/unit = **$225 in avoided feed purchase** for only $30 in seeds!
     - Wheat only requires 15 watering actions (3 cycles $\times$ 5 days) and releases the tile between cycles.
   - Alternatively, **Carrots** (4 days per cycle, 2 units per harvest at ~$35/unit) cycle 4 times, generating ~$280 gross revenue at $40 seed cost with rapid capital recycling.

---

## 2. Realized Strawberry Economics Formulation

For each prospective strawberry tile $k$ considered for planting on Day $D$ ($3 \le D \le 13$):

### A. Attainable Production Events
From the authoritative engine audit:
$$h(D) = \min\left(4, \left\lfloor \frac{29 - D - 10}{2} \right\rfloor + 1\right) = 4 \quad \text{for } D \le 13$$
For all valid planting days $D \le 13$, all 4 scheduled production events occur before season end.

### B. Expected Output per Tile ($V_{\text{straw}}$)
Each event produces 1 unit base. If fertilized and watered, yield is 2 units.
Based on baseline empirical herd fertilizer output:
$$y_e = 1.0 + p_{\text{fert}} \approx 1.0 + 0.50 = 1.50 \text{ units/event}$$
$$V_{\text{straw}} = 4 \times 1.50 = 6.0 \text{ units per tile}$$

### C. Market Price & Own-Supply Impact
Let $I_{\text{curr}}$ be current strawberry inventory in the market.
Let $S_{\text{committed}}$ be the total strawberry tiles already planted or queued.
Let $D_{\text{town}}$ be conservative projected town shop consumption of strawberries through Day 30 ($~15\text{ units/day}$ when fruit/ice cream shops are active).
Projected market inventory when the $k$-th tile's harvest sells:
$$I_{\text{proj}}(k) = I_{\text{curr}} - D_{\text{town}} + (S_{\text{committed}} + k) \times V_{\text{straw}} + \text{ShedStock}$$

Realized unit selling price is computed using the authoritative integer-rounded engine formula:
$$P_{\text{realized}}(k) = \text{market\_price}(\text{"STRAWBERRY"}, I_{\text{proj}}(k))$$
Expected strawberry revenue from tile $k$:
$$\text{Rev}_{\text{straw}}(k) = V_{\text{straw}} \times P_{\text{realized}}(k)$$

### D. Full Maintenance & Action Costs
- Seed Cost: $C_{\text{seed}} = \$100$.
- Calendar Days of Maintenance: $M(D) = 29 - D + 1$ (for $D=13$, $M(13) = 17$ days; for $D=3$, $M(3) = 17$ days before weed decay on Day 20).
  $$\text{DaysActive}(D) = \min(17, 30 - D)$$
- Watering Cost: $\text{DaysActive}(D) \times c_{\text{action}}$ (where $c_{\text{action}} \approx \$5.00$).
- Harvest & Delivery Cost: $4 \times c_{\text{action}} + 2 \times c_{\text{action}} = 6 \times c_{\text{action}} = \$30.00$.
- Total Cost:
  $$\text{Cost}_{\text{straw}}(D) = 100 + (\text{DaysActive}(D) \times 5.0) + 30.0$$
  For $D \le 13$, $\text{Cost}_{\text{straw}} = 100 + 85 + 30 = \$215.00$.

### E. Net Marginal Strawberry Value
$$\text{MV}_{\text{straw}}(k, D) = \text{Rev}_{\text{straw}}(k) - \text{Cost}_{\text{straw}}(D)$$

Notice that as $k$ increases, $I_{\text{proj}}(k)$ increases, $P_{\text{realized}}(k)$ decreases, and $\text{MV}_{\text{straw}}(k, D)$ strictly diminishes!

---

## 3. Comparative Evaluation Against Next-Best Crop Alternatives

To ensure an unbiased economic comparison, alternatives are evaluated on the **exact same tile and labor window** spanning from Day $D$ to Day 29:

### A. Wheat (Continuous Food / Feed Engine)
- Cycle: 5 days.
- Number of complete cycles possible: $N_{\text{wheat}} = \lfloor (29 - D) / 5 \rfloor$.
  - At Day 3: 5 cycles (25 days).
  - At Day 9: 4 cycles (20 days).
  - At Day 13: 3 cycles (15 days).
- Total wheat produced: $N_{\text{wheat}} \times 3 \text{ units}$.
- **Valuation**:
  - If dairy herd is expanding and wheat shed inventory < 30 units, each wheat unit saves an emergency market purchase at $25.0/unit.
    $$\text{Value}_{\text{unit}} = \max(25.0, P_{\text{spot\_wheat}})$$
  - Gross Value: $N_{\text{wheat}} \times 3 \times \text{Value}_{\text{unit}}$.
  - Costs: $N_{\text{wheat}} \times (10 \text{ seed} + 5 \times 5 \text{ water} + 5 \text{ harvest}) = N_{\text{wheat}} \times \$40$.
  - Net Marginal Wheat Value:
    $$\text{MV}_{\text{wheat}}(D) = N_{\text{wheat}} \times (3 \times \text{Value}_{\text{unit}} - 40)$$
    For $D=13$, $N_{\text{wheat}} = 3$:
    If $\text{Value}_{\text{unit}} = 25.0$: $\text{MV}_{\text{wheat}} = 3 \times (75 - 40) = \$105.00$.
    If $\text{Value}_{\text{unit}} = 40.0$ (elevated market): $\text{MV}_{\text{wheat}} = 3 \times (120 - 40) = \$240.00$!

### B. Carrot (Fast Cash Liquidity)
- Cycle: 4 days.
- Number of cycles: $N_{\text{carrot}} = \lfloor (29 - D) / 4 \rfloor$.
  - At Day 13: 4 cycles (16 days).
- Total carrots produced: $N_{\text{carrot}} \times 2 \text{ units}$.
- Selling price: $P_{\text{carrot}} \approx \$30–\$35$.
- Net Marginal Carrot Value:
  $$\text{MV}_{\text{carrot}}(D) = N_{\text{carrot}} \times (2 \times P_{\text{carrot}} - (10 \text{ seed} + 4 \times 5 \text{ water} + 5 \text{ harvest})) = N_{\text{carrot}} \times (70 - 35) \approx \$140.00$$

### C. Fallow / Empty Tile
- Gross Revenue: $0.
- Costs: $0.
- Preserves $85+ in worker actions for cow feeding and caring (critical if labor is constrained).
$$\text{MV}_{\text{fallow}} = 0$$

---

## 4. Unified Sequential Admission Algorithm

The dynamic strawberry evaluator calculates the optimal dynamic strawberry cap $S^* \in [0, 20]$ for Day $D$:

```python
def compute_dynamic_strawberry_cap(farm, market, day, committed_strawberries, remaining_money, empty_tiles_count):
    if day > STRAWBERRY_PLANT_DEADLINE or "NE" not in farm.unlocked:
        return 0
    
    baseline_cap = get_strawberry_cap(day, True)
    
    # Next-best alternative value per tile
    mv_alt = compute_next_best_crop_mv(farm, market, day)
    
    admitted = 0
    risk_buffer = 15.0  # Require strawberry to exceed alternative by $15/tile
    
    for k in range(1, baseline_cap + 1):
        # Marginal strawberry value for the k-th committed strawberry tile
        mv_straw = evaluate_marginal_strawberry(farm, market, day, k)
        
        if mv_straw >= mv_alt + risk_buffer:
            admitted = k
        else:
            break
            
    # Non-retroactive guarantee:
    # Cannot unplant existing strawberries, but caps future plantings
    return max(committed_strawberries, admitted)
```

### Key Architectural Invariants
1. **Governs Both Paths**: The returned dynamic cap $S^*$ replaces `s_cap` in the dedicated strawberry wave AND sets the cap in the Phase 2b fallback crop scoring loop (`exp_priorities` and standard scoring).
2. **Strict Baseline Identity when Disabled**: When `P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED = False`, both paths use the exact Control baseline `get_strawberry_cap(day, "NE" in farm.unlocked)`.
3. **Treasury & Feed Safety**: Wheat replanting executes *before* strawberry allocation, so dairy feed security is 100% safeguarded.
