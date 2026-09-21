# Kaggriculture P2.3 — Marginal Wheat Value Model & Economic Evaluation

## Mathematical Formulation of Marginal Wheat Value

For any empty farm tile considered for wheat planting on day $d \in [0, 27]$:

$$\text{MV}(\text{Wheat}, d) = V_{\text{feed}}(d) + V_{\text{sale}}(d) - C_{\text{direct}}(d)$$

Where:
- $Y(d)$: Expected confirmed yield of a wheat tile planted on day $d$. For wheat, $Y(d) = 4$ to $6$ units if $d + 4 \le 29$, else $0$.
- Harvest arrives on day $H = d + 4$.

---

## 1. Feed Replacement Value $V_{\text{feed}}(d)$

A newly planted wheat tile only provides **feed value** if its harvest units directly satisfy a future feed obligation that would otherwise require purchasing wheat from the market at spot price $P_{\text{buy}} = \$25.00$.

Let:
- $D_{\text{rem}}(H, 28) = \sum_{t=H}^{28} \text{Animals}(t) \times 1.0$: Cumulative feed demand from harvest day $H$ through Day 28 (the final feed day).
- $S_{\text{proj}}(H, 28) = \text{ShedWheat}(d) + \sum_{\text{existing wheat } w} Y_w$: All already secured wheat available on or after day $H$.

Then the feed deficit that this candidate tile can satisfy is:

$$U_{\text{feed}}(d) = \min\Big(Y(d), \max\big(0, D_{\text{rem}}(H, 28) - S_{\text{proj}}(H, 28)\big)\Big)$$

The feed value is:

$$V_{\text{feed}}(d) = U_{\text{feed}}(d) \times P_{\text{buy}} \quad (P_{\text{buy}} = \$25.00)$$

> [!IMPORTANT]
> If $S_{\text{proj}}(H, 28) \ge D_{\text{rem}}(H, 28)$, the existing wheat inventory and in-flight crops already fully cover all remaining animal feed through Day 28. In this condition:
> $$U_{\text{feed}}(d) = 0 \implies V_{\text{feed}}(d) = \$0.00$$
> Any incremental wheat planted has **zero feed value** and must compete purely on commercial market-sale merit.

---

## 2. Commercial Sale Value $V_{\text{sale}}(d)$

Any units not allocated to feed are commercial surplus sold to the town shop or general market:

$$U_{\text{sale}}(d) = Y(d) - U_{\text{feed}}(d)$$

$$V_{\text{sale}}(d) = U_{\text{sale}}(d) \times P_{\text{sell}}(H, \text{Inv}_{\text{market}})$$

Where $P_{\text{sell}}$ is the realized market spot price on harvest day $H$, which for wheat ranges between $\$23.00$ and $\$25.00$ given town demand and market inventory.

---

## 3. Direct Production Costs $C_{\text{direct}}(d)$

- **Seed Cost**: $\$10.00$
- **Labor Requirement**:
  - 1 planting action
  - 4 daily watering actions
  - 1 harvest action
  - 1 delivery/carrying action to shed
- **Total Operational Labor**: $7 \text{ actions} \times \$5.00/\text{action} = \$35.00$.
- **Total Cost**: $C_{\text{direct}} = \$10.00 \text{ (capital)} + \$35.00 \text{ (labor)} = \$45.00$.

---

## 4. Net Marginal Economic Return by Role

### Case 1: Tile serves Mandatory Feed ($U_{\text{feed}} = 4$)
- Gross feed replacement value: $4 \times \$25 = \$100.00$ (or $6 \times \$25 = \$150.00$ if 6 yield).
- Direct costs: $-\$45.00$.
- Net value: **+$55.00 to +$105.00 per tile** (plus saving the livestock enterprise!).
- **Conclusion**: Whenever $U_{\text{feed}} > 0$, wheat planting is mandatory and non-negotiable.

### Case 2: Tile is Purely Commercial Wheat ($U_{\text{feed}} = 0, U_{\text{sale}} = 4$)
- Gross sale value: $4 \times \$25 = \$100.00$.
- Direct costs: $-\$45.00$.
- Net profit: **+$55.00 over 5 days = +$11.00 / tile / day**.
- **Conclusion**: Positive in isolation, but strictly subject to opportunity cost against alternative crops.

### Case 3: Tile is Terminal Planting ($d \ge 26$, $Y(d) = 0$)
- Maturation day $H = d + 4 \ge 30$. Game ends at Day 30 Hour 0.
- Gross value: $\$0.00$.
- Costs: $-\$10.00$ (seed) $-\$5.00$ (plant action) $= -\$15.00$.
- Net value: **-$15.00 (Pure loss)**.

---

## 5. Opportunity Cost Against Feasible Alternative Crops

On any empty tile where $U_{\text{feed}}(d) = 0$, what could the farm grow instead?

### Alternative A: CARROT
- **Parameters**: Seed $\$20.00$, cycle $3 \text{ days}$ (matures at $d+3$), yield $4 \text{ units}$, market price $\$35.00$.
- **Gross Revenue**: $4 \times \$35 = \$140.00$.
- **Direct Costs**: $\$20 \text{ (seed)} + 5 \text{ actions} \times \$5 = \$45.00$.
- **Net Profit**: **+$95.00 over 4 days = +$23.75 / tile / day**.
- **Comparison to Commercial Wheat**:
  $$\text{MV}(\text{Carrot}) = \$23.75/\text{day} \gg \text{MV}(\text{Commercial Wheat}) = \$11.00/\text{day}$$
  **Carrot generates +$12.75 more profit per tile-day than commercial wheat!**

### Alternative B: FALLOW / EMPTY
- If seed capital is constrained or labor is near bottleneck:
  $$\text{MV}(\text{Empty}) = \$0.00/\text{day} > \text{MV}(\text{Terminal Wheat on Days 26–27}) = -\$15.00$$

---

## Summary Matrix: The Marginal Decision Rule

$$\text{Plant Wheat if and only if: } U_{\text{feed}}(d) > 0 \quad \text{OR} \quad \Big(d \le 25 \text{ AND } \text{MV}(\text{Wheat}, d) \ge \text{MV}(\text{Carrot}, d)\Big)$$

1. **If wheat is needed for feed ($U_{\text{feed}} > 0$)**: Plant Wheat immediately.
2. **If feed is already fully secured ($U_{\text{feed}} = 0$)**:
   - On Days 26–27: **NEVER plant wheat** (it cannot mature). Plant Carrot if $d \le 27$, else leave Empty.
   - On Days 10–25: Do NOT forcibly reserve 20 tiles for commercial wheat. Allow CARROT to compete on equal economic footing via `_crop_score`.
