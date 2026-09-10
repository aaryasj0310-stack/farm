# Kaggriculture Architecture & Decision Inventory Index

> **Primary Source of Truth**: `submission/` (Multi-File Package for Kaggle Environments)  
> **Reference & Parity Checker**: `dist/submission.py` / root `submission.py`  
> **Target Audience**: Astra & AI Pair Programmers navigating the Kaggriculture production codebase

---

## 1. Document Directory & Purpose

```text
architecture/
├── runtime_inventory.md        # Step 1: Complete module, class, function, state, and rule catalogue
├── architecture_dataflow.md    # Step 2: High-level data-flow and end-to-end subsystem Mermaid graph
├── decision_formula.md         # Step 3: Exact mathematical formulas, decision trees, and static rules
├── failure_propagation.md      # Step 4: Causal failure propagation chains and severity ratings
└── architecture_index.md       # Step 5: Master navigation index, reading order, and audit summary
```

---

## 2. Recommended Reading Order for Astra

To quickly achieve full mental model alignment without getting lost in implementation minutiae, follow this exact sequence:

1. **[runtime_inventory.md](file:///d:/website%20project/kaggri%20ox/architecture/runtime_inventory.md)**:
   *Read first to understand every architectural component, its responsibilities, inputs, outputs, side effects, and stable ID.*
2. **[architecture_dataflow.md](file:///d:/website%20project/kaggri%20ox/architecture/architecture_dataflow.md)**:
   *Read second to visualize where observations enter, how data transforms across strategic, market, and execution boundaries, and how engine actions are produced.*
3. **[decision_formula.md](file:///d:/website%20project/kaggri%20ox/architecture/decision_formula.md)**:
   *Read third to inspect the exact mathematical formulas, portfolio scoring models, drip curves, and decision gates.*
4. **[failure_propagation.md](file:///d:/website%20project/kaggri%20ox/architecture/failure_propagation.md)**:
   *Read fourth to trace causal ripple effects when any gate, assumption, or execution constraint fails.*

---

## 3. How Stable IDs Link Across Graphs

Every runtime entity is indexed using a stable, searchable identifier across all architecture documents:

| Prefix | Category | Example IDs | Where to Look |
|---|---|---|---|
| `ARCH-*` | Architectural Modules & Classes | `ARCH-MAIN-01`, `ARCH-STRAT-03`, `ARCH-MKT-03` | [runtime_inventory.md: Section 1](file:///d:/website%20project/kaggri%20ox/architecture/runtime_inventory.md#1-top-level-architectural-modules-arch-) |
| `STATE-*` | Persistent Module & Cross-Turn State | `STATE-MEM-01`, `STATE-STICKY`, `STATE-OPP-SHED` | [runtime_inventory.md: Section 2](file:///d:/website%20project/kaggri%20ox/architecture/runtime_inventory.md#2-persistent--cross-turn-state-objects-state-) |
| `FORM-*` | Exact Dynamic Mathematical Formulas | `FORM-LAND-01`, `FORM-CROP-02`, `FORM-DRIP-01` | [decision_formula.md](file:///d:/website%20project/kaggri%20ox/architecture/decision_formula.md) |
| `RULE-*` | Static Engine Constants & Policy Caps | `RULE-LAND-02`, `RULE-HIRE-01`, `RULE-CROP-01` | [runtime_inventory.md: Section 4](file:///d:/website%20project/kaggri%20ox/architecture/runtime_inventory.md#4-static-policy-rules--system-constraints-rule-) |
| `DEC-*` | Decision Trees & Optimization Gates | `DEC-LAND-SW-01`, `DEC-CROP-01`, `DEC-SLOT-01` | [decision_formula.md](file:///d:/website%20project/kaggri%20ox/architecture/decision_formula.md) |
| `EXEC-*` | Spatial Dispatch & Pathfinding Operations | `EXEC-DISPATCH-01`, `EXEC-STICKY-01` | [architecture_dataflow.md: Section 4](file:///d:/website%20project/kaggri%20ox/architecture/architecture_dataflow.md#4-execution-layer-task-scheduling--spatial-assignment) |
| `MKT-*` | Order Compilation & Price Math Clearing | `MKT-BUILD-01`, `MKT-DRIP-01`, `MKT-COMP-01` | [architecture_dataflow.md: Section 3](file:///d:/website%20project/kaggri%20ox/architecture/architecture_dataflow.md#3-market-layer-purchase--sell-order-compilation) |
| `FAIL-*` | Failure Modes & Hazard States | `FAIL-MKT-01`, `FAIL-LAND-01`, `FAIL-FEED-01` | [failure_propagation.md](file:///d:/website%20project/kaggri%20ox/architecture/failure_propagation.md) |

### Tracing Workflow Example: The SW Land Decision
To trace why SW land was purchased or blocked:
1. Start in **[architecture_dataflow.md](file:///d:/website%20project/kaggri%20ox/architecture/architecture_dataflow.md#2-strategic-planning-data-flow-macroplanner)** at node `EXP_PLAN`.
2. Look up `DEC-LAND-SW-01` in **[decision_formula.md](file:///d:/website%20project/kaggri%20ox/architecture/decision_formula.md#decision-buy-quadrant-3-sw-land-unlock--dec-land-sw-01)**: review `FORM-LAND-01` (raw ROI), `FORM-LAND-02` (adjusted ROI), and `FORM-LAND-03` (treasury hurdle).
3. Trace down to [order_builder.py](file:///d:/website%20project/kaggri%20ox/submission/market/order_builder.py) at `DEC-SLOT-01` and formula `FORM-SLOT-01` to verify market slot reservation.
4. Check **[failure_propagation.md: Chain 1](file:///d:/website%20project/kaggri%20ox/architecture/failure_propagation.md#chain-1-market-order-saturation--land-starvation-fail-land-01)** (`FAIL-LAND-01`) to understand how 10 HIRE orders previously starved `BUY_LAND` and how the fix restored execution.

---

## 4. Comprehensive Inventory Summary Statistics

| Metric | Measured Count | Details |
|---|:---:|---|
| **Runtime Modules Inspected** | **15** | All Python modules within `submission/` (`main`, `config`, `state/*`, `strategy/*`, `market/*`, `execution/*`). |
| **Major Functions & Classes Mapped** | **42** | Primary classes (`MacroPlanner`, `OrderBuilder`, `MarketBrain`, `PriceForecast`, etc.) and core functions. |
| **Dynamic Formulas Extracted** | **16** | Mathematical formulas for ROI, crop marginal scoring, drip sizing, wheat deficit, care bonuses, etc. |
| **Static Policy Rules Extracted** | **18** | Engine limits, crop caps, hiring schedules, deadlines, and urgency thresholds. |
| **Persistent State Objects Identified** | **8** | Module-level memory, opponent snapshots, sticky missions, blocked tasks, diagnostics. |
| **Failure Propagation Chains Created** | **10** | Complete causal graphs covering land starvation, animal death, shed overflow, worker churn, etc. |

---

## 5. Potential Issues & Codebase Anomalies Discovered

During this rigorous architectural audit of `submission/`, the following anomalies were identified:

1. **Unreachable Logic in `expansion_planner.py:L471`**:
   The check `if next_quadrant == 3 and current_day > 13: return False, "sw_window_closed_after_day_13"` is redundant when SW is unlocked on Day 10–11, but acts as a hard blocker if cash is delayed past Day 13 even when late crops (Tomato/Carrot) still have strong positive ROI ($+8.50$).
2. **`main._build_opp_advice` Silent Diagnostic Suppression**:
   Exceptions during opponent modeling are caught and recorded in `_OPPONENT_MODEL_DIAGNOSTICS`, returning an empty advice object. This prevents crashes, but suppresses error visibility unless `DEBUG` is active.
3. **Semantic Duplication in `get_animal_targets`**:
   `config.py:L306` provides a wrapper `get_animal_targets()` delegating to `strategy.animal_planner`, while `macro_planner.py` directly imports `from strategy.animal_planner import get_animal_targets`. Both share identical signatures.
