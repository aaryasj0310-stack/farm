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

### Invariant: No Double-Subtraction of Displaced Core Value
All trade-offs exist *inside* the respective trajectories:
- The `WITH` trajectory includes candidate revenue, candidate seed/purchase costs, and any necessary modifications to core crops/livestock to fit labor and feed constraints.
- The `WITHOUT` trajectory retains incumbent core production and historical revenue.

### Diagnostic Decomposition
For audit and telemetry, $\Delta FC$ is reported as:
$$\Delta FC = \text{GrossRevenue}_{\text{cand}} - \text{SeedCost}_{\text{cand}} - \text{DisplacedCoreNet} - \text{MarketCannibalization} - \text{FeedCost} - \text{IncrementalWages}$$

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

## 4. Own-Supply Market Impact Formulation

Because a three-quadrant farm produces significantly higher volume, market prices cannot be assumed exogenous. Adding supply depresses the marginal realized price across both new units and incumbent inventory.

The price depression impact $\Delta P$ is modeled along product-specific curves:
- **Melon & Wool** (Logarithmic / Square curves): Highly sensitive to sudden volume gluts.
- **Strawberry & Milk** (Square root / Linear curves): Moderate volume resilience.
- **Wheat & Carrot** (Hinge / Sqrt curves): High volume absorption capacity.

$$\text{CannibalizationLoss} \approx \Delta P \times \min(100, \text{TotalUnitsSold})$$
This prevents the planner from over-planting high-volume crops that crash market prices below economic viability.
