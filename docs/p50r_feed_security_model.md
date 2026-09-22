# P5.0-R Feed Security Model: Time-Indexed Dynamic Ledger

## 1. Executive Summary & Problem Formulation

In P5.0, late-season wheat plantings were audited using a static, day-blind heuristic:
$$\text{Expected Incoming} = \text{In-Ground Wheat} \times 6$$
$$\text{Surplus} = \text{Liquid Stock} + \text{Expected Incoming} - \text{Total Unfed Need}$$

This static heuristic suffered from three fatal theoretical and empirical flaws:
1. **Unrealistic Yield Multiplier**: Unfertilized wheat yield is physically capped at **4 units** by the game engine (`kaggle_environments.envs.kaggriculture.kaggriculture`), not 6.
2. **Temporal Disconnect (The Starvation Gap)**: Even if 10 wheat tiles are planted and will produce 40 wheat on Day 26, a herd of 8 cows requiring 8 wheat/day on Days 22, 23, 24, and 25 will starve to death if the current liquid stock is 0. A static aggregate total completely ignores intermediate insolvency.
3. **Erronous Obligation Horizon**: Static models counted feed obligations through Day 29 or Day 30. In engine truth, animals fed on Day 28 produce products on Day 29 that are collected and sold; feeding on Day 29 only produces goods at Step 720 (game end), which are uncollectable and worthless. Therefore, feed obligations terminate strictly at the end of **Day 28**.

P5.0-R replaces this flawed approach with a **Time-Indexed Dynamic Feed Ledger** that models exact day-by-day feed inventory, maturation timelines, and consumption.

---

## 2. Mathematical Formulation of the Dynamic Ledger

For any decision point $(D, H)$ during Days 21–25, we evaluate farm feed solvency across the entire remaining feeding horizon $d \in [D, 28]$ under two counterfactual states:
- **State A (Baseline)**: Retain the candidate wheat planting.
- **State B (Counterfactual)**: Do not plant candidate wheat (or divert the tile to an alternative crop).

### 2.1 State Variables
- $B_d$: Feed wheat balance at the end of day $d$.
- $H_d$: Realizable wheat harvests arriving into inventory on day $d$.
- $F_d$: Total herd feed obligation on day $d$.
- $S_0$: Total liquid wheat available at hour $H$ of day $D$ (sum of shed inventory and all worker carried inventories):
  $$S_0 = \text{Shed}[\text{WHEAT}] + \sum_{w} \text{Inv}_w[\text{WHEAT}]$$

### 2.2 Dynamic Transition Equation
The ledger evolves sequentially for every day $d$ from $D$ to 28:
$$B_D = S_0 + H_D - F_D$$
$$B_d = B_{d-1} + H_d - F_d \quad \forall d \in [D+1, 28]$$

---

## 3. Realizable Harvest Modeling ($H_d$)

Harvests arrive on day $d = P + 4$, where $P$ is the planting day of an in-ground wheat tile.

For each existing in-ground wheat tile $i$ at coordinate $(x_i, y_i)$ with planting day $P_i$:
1. **Harvest Day**: $d_{\text{harvest}, i} = P_i + 4$.
2. **Maturation Window**: The bonus watering window spans days $P_i + 2$, $P_i + 3$, and $P_i + 4$.
3. **Conservative Yield Realization**:
   - Initial yield at planting: $Y_0 = 1$.
   - Bonus increments: For each day $k \in \{2, 3, 4\}$, if $P_i + k \le 28$ and the tile was watered (or can be serviced before Day 28):
     $$\Delta Y_k = \begin{cases} 2 & \text{if tile is fertilized until Day } P_i + 4 \\ 1 & \text{otherwise} \end{cases}$$
   - Capped yield:
     $$Y_i = \min(M_i, 1 + \sum_k \Delta Y_k)$$
     where $M_i = 6$ if fertilized, else $4$.
4. **Aggregate Daily Harvest**:
   $$H_d = \sum_{i: P_i + 4 = d} Y_i$$

Under Counterfactual A (retaining candidate wheat at $(D, H)$), candidate wheat matures on Day $D+4$ (if $D+4 \le 28$), contributing $Y_{\text{cand}} = 4.0$ to $H_{D+4}$. Under Counterfactual B (removing candidate wheat), candidate contribution is exactly 0.

---

## 4. Feed Obligation Modeling ($F_d$)

The livestock herd requiring wheat consists of all placed `COW` and `SHEEP` animals:
$$N_{\text{herd}} = \sum_{a \in \text{Animals}} \mathbf{1}_{\{a.\text{type} \in \{\text{COW}, \text{SHEEP}\}\}}$$

- **Day $D$ (Decision Day)**: Some animals may already have been fed earlier in the day prior to hour $H$:
  $$F_D = \sum_{a \in \text{Herd}} \mathbf{1}_{\{\neg a.\text{fed\_today}\}}$$
- **Days $d \in [D+1, 28]$**: Each placed animal consumes exactly 1 wheat per day:
  $$F_d = N_{\text{herd}}$$

---

## 5. Formal Feed Safety Classification (RW1 – RW4)

Using the trajectory of daily balances under Counterfactual B (candidate wheat removed), $\{B_d^{(B)}\}_{d=D}^{28}$:

### Minimum Horizon Balance
$$B_{\min}^{(B)} = \min_{d \in [D, 28]} B_d^{(B)}$$

### Safety Buffer Floor ($\beta$)
To insulate the herd against unforeseen execution delays, pathing contention, or missed morning watering, we enforce a mandatory safety floor:
$$\beta = 1.0 \times N_{\text{herd}}$$
(equivalent to 1 full day of total herd consumption).

### Reclassification Taxonomy
1. **RW1 — Feed Critical (Insolvent Deficit)**:
   $$\exists d \in [D, 28] \text{ such that } B_d^{(B)} < 0 \iff B_{\min}^{(B)} < 0$$
   *Meaning*: Removing this wheat planting directly creates a feed deficit on at least one day before Day 29. The wheat is mandatory for herd survival.

2. **RW2 — Feed Buffer Support (Vulnerable Margin)**:
   $$0 \le B_{\min}^{(B)} < \beta$$
   *Meaning*: Removing this wheat leaves the herd theoretically non-negative, but breaches the safety buffer $\beta$. A single operational disruption could cause animal escape.

3. **RW3 — Genuine Economic Surplus (Provably Safe)**:
   $$B_{\min}^{(B)} \ge \beta$$
   *Meaning*: Even after completely removing this candidate wheat planting, the farm maintains at least $\beta$ surplus feed on every single future day through Day 28. This wheat is **100% economically discretionary**.

4. **RW4 — Terminal Non-Maturing**:
   $$D + 4 > 29 \iff D \ge 26$$
   *Meaning*: Wheat planted on or after Day 26 cannot mature before the season ends at Step 720, producing 0 harvestable yield.

---

## 6. Mathematical Proof: End of Feeding Obligations at Day 28

Let $t$ denote the global step in the Kaggle simulation ($t = 24 \times d + h$).
The season duration is exactly $T = 720$ steps (Days 0 to 29, Hours 0 to 23).

1. In `kaggriculture.py`, line 586:
   ```python
   # Daily animal refresh: fed animals yield products at EOD transition
   if d < 29:
       _daily_refresh_animals(farm)
   ```
2. Feeding an animal on Day 28 ($t \in [672, 695]$):
   - Animal transitions `fed_today = True`.
   - At transition $t = 696$ (Day 28 Hour 23 $\rightarrow$ Day 29 Hour 0), `_daily_refresh_animals` executes.
   - The animal increments its produce counter (e.g. Milk or Wool) and resets `cared_today = False`, `fed_today = False`.
   - On Day 29 ($t \in [696, 719]$), workers can `HARVEST` the animal, deposit into shed, and `SELL` on the market.
3. Feeding an animal on Day 29 ($t \in [696, 719]$):
   - Animal transitions `fed_today = True`.
   - At Step 720, the episode terminates immediately (`state[0].status = "DONE"`).
   - `_daily_refresh_animals` at Step 720 never allows subsequent worker interaction turns.
   - Any yield generated at Step 720 cannot be harvested, deposited, or liquidated.

$$\therefore \text{Marginal value of feeding on Day 29} \equiv \$0.00$$

Thus, setting the final feeding obligation day to **Day 28** is an exact mathematical consequence of the Kaggle simulation engine rules.
