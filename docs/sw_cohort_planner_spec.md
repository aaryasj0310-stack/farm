# SW Cohort Planner & Opportunity-Cost Admission Specification

**Module:** `strategy/cohort_planner.py`  
**Status:** Implemented & Verified in Phase A  

---

## 1. Principles & Purpose

The `CohortPlanner` replaces isolated, positive-EV asset selection with **whole-farm counterfactual trajectory evaluation**. Assets are grouped into coherent `CropCohort` and `LivestockCohort` structures that track full lifecycles, watering schedules, labor obligations, and market outputs.

---

## 2. Counterfactual Optimization Objective

Admission is governed strictly by the net incremental final cash across the whole farm:

$$\boxed{ \Delta FC = \mathbb{E}[\text{FinalCash} \mid \text{Plan WITH candidate}] - \mathbb{E}[\text{FinalCash} \mid \text{Plan WITHOUT candidate}] }$$

### Invariant: Zero Double-Subtraction of Displaced Core Value and Cannibalization
All trade-offs exist *inside* the respective trajectories:
- The `WITH` trajectory includes candidate realized revenue (evaluated sequentially via `total_revenue_estimate`), candidate seed/purchase costs, and any necessary modifications to core crops/livestock to fit labor and feed constraints.
- The `WITHOUT` trajectory retains incumbent core production and historical revenue.
- **Cannibalization is NOT double-subtracted**: Because `total_revenue_estimate(product, current_inv, total_units)` integrates sequentially along the exact engine price curve $P(I)$, price depression is already strictly embedded within the gross revenue of the `WITH` trajectory. Cannibalization loss is recorded purely as a diagnostic decomposition metric for observability.

### Diagnostic Decomposition
For audit and telemetry, $\Delta FC$ is reported as:
$$\Delta FC = (\text{RealizedRevenue}_{\text{cand}} - \text{SeedCost}_{\text{cand}}) - \text{DisplacedCoreNet} - \text{FeedCost} - \text{IncrementalWages}$$
$$\text{CannibalizationDiagnostic} = \max(0, \text{NominalRevenue} - \text{RealizedRevenue})$$

---

## 3. Dynamic SW Layout & Portfolio Generation

The architecture rejects fixed spatial assumptions (such as the legacy 15 crop / 9 pasture partition). Candidate portfolios are dynamically generated and compared:

1. **Balanced Commercial Portfolio**:
   - $10 \text{ Wheat} + 10 \text{ Strawberry} + 4 \text{ Melon}$.
   - High commercial value with on-farm grain buffer.
2. **Feed & High-Margin Strawberry Portfolio**:
   - $14 \text{ Wheat} + 10 \text{ Strawberry}$.
   - Heavy grain production solving whole-farm feed constraints while monetizing repeat strawberries.
3. **Rapid Tranche 1 Starter**:
   - $4 \text{ Wheat} + 4 \text{ Strawberry}$ (first 8 tiles).
   - Minimal labor footprint during startup; expands rapidly via Tranche 2 and 3.

---

## 4. Own-Supply Market Impact & Engine-Exact Economics

In Phase A-R, all economic calculations directly consume `market/price_math.py` (`market_price`, `total_revenue_estimate`, `MARKET_PARAMS`), replacing all generic formulas.

The exact engine price curve for product $p$ given town inventory $I$:
$$P_p(I) = \text{base\_price} \times \left(1 + \text{sensitivity} \cdot \left(\frac{I_0 - I}{I_0}\right)^k\right)$$

- **Melon** ($k = 0.5$ / Square root curve, high base price): Highly sensitive to sudden supply waves.
- **Strawberry & Milk** ($k = 0.5$, moderate price): Moderate volume resilience.
- **Wheat & Carrot** ($k = 0.5$, low base price): High volume absorption capacity.

Every batch of $N$ units sold at once receives total revenue equal to $\sum_{i=0}^{N-1} P_p(I + i)$, exactly matching `total_revenue_estimate`.
$$\text{DepressionLoss} = (N \times P_p(I)) - \text{total\_revenue\_estimate}(p, I, N)$$
This provides exact foresight into marginal returns without arbitrary approximations.
