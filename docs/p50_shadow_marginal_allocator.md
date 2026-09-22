# P5.0 Shadow Marginal Allocator Architecture

## Baseline Shadow Allocator Evaluation

The baseline currently relies on a hybrid static-heuristic macro planner:
- Day 0: Hardcoded pasture and initial melon/wheat layout.
- Days 1–15: Fixed quota expansion into NE.
- Days 16–25: Reactive replanting when tiles become empty, using feed projections to trigger wheat.

### Architectural Vulnerability
The baseline's feed projection evaluates:
$$\text{Buffer} = \text{Shed Wheat} + \text{Held Wheat} + 6 \times (\text{In-Ground Wheat}) - \text{Remaining Feed Burn}$$
However, when `Buffer >= 0`, the allocator defaults to a generic fallback score where Wheat ranks above Carrots because of higher gross yield (6 units vs 2 units), ignoring:
1. Growth cycle length (5 days vs 3 days).
2. Market price depression from 6 units flooding the shed.
3. Imminent Day 30 season cutoff.

---

## Proposed P5.1 Marginal Allocator Architecture

```
                      +-----------------------------+
                      |   Hourly State Observation   |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |   Feed Security Evaluator   |
                      +--------------+--------------+
                                     |
               +---------------------+---------------------+
               | Buffer < 0 (Critical)                     | Buffer >= 0 (Surplus)
               v                                           v
    +----------------------+                    +----------------------+
    | W1: Plant Wheat      |                    | Evaluate Season Day  |
    +----------------------+                    +----------+-----------+
                                                           |
                                      +--------------------+--------------------+
                                      | Day <= 20                               | Day 21-25
                                      v                                         v
                           +----------------------+                  +----------------------+
                           | W2: Regular Wheat OK |                  | T1 Gate: FORBID WHEAT|
                           +----------------------+                  | Divert to 3-day CARROT|
                                                                     +----------------------+
```
