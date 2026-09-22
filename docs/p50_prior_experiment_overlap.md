# P5.0 Orthogonality & Prior Experiment Overlap Analysis

## Interaction Matrix with Prior Experiments

A vital requirement of P5.0 is ensuring that proposed improvements do not re-introduce bugs or conflicts with prior experimental features:

| Experiment | Status | P5.0 Finding & Orthogonality Assessment |
| :--- | :--- | :--- |
| **P2.3 (Terminal Wheat Fix)** | **PROMOTED** | P5.0 confirms W4 terminal wheat is 100% eliminated (0 occurrences). T1 builds directly on top of P2.3 by extending the gate backwards to Days 21–25. |
| **P3.1 (Harvest Priority)** | EXPERIMENTAL | P5.0 confirms morning harvest contention is real. T1 does not modify worker priority logic; fully orthogonal. |
| **P3.2 (Care Opportunity)** | EXPERIMENTAL | T2 fertilizer pruning frees worker turns, reducing care contention. Synergistic. |
| **P3.3 (Physical Locality)** | EXPERIMENTAL | T5 shed corridor protection directly supports physical locality by eliminating bottlenecks. Synergistic. |
| **P4.1 (SW Zonal Expansion)**| REJECTED | P5.0 confirms core NW+NE capacity (50 tiles) contains 132.6 idle tile-days. Unlocking SW is unnecessary before core slack is fully utilized. |
| **P4.2 (Transaction Telemetry)**| COMPLETED | P5.0 directly utilizes P4.2 transaction pricing curves to value marginal yield deltas. |
