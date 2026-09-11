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
| `EXEC-*` | Spatial Dispatch & Pathfinding Operations | `DEC-EXEC-01`, `ARCH-EXEC-01`, `ARCH-EXEC-02` | [architecture_dataflow.md: Section 4](file:///d:/website%20project/kaggri%20ox/architecture/architecture_dataflow.md#4-execution-layer-task-scheduling--spatial-assignment) |
| `MKT-*` | Order Compilation & Price Math Clearing | `DEC-SLOT-01`, `DEC-MKT-SELL-01`, `MKT_COMP` | [architecture_dataflow.md: Section 3](file:///d:/website%20project/kaggri%20ox/architecture/architecture_dataflow.md#3-market-layer-purchase--sell-order-compilation) |
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
| **Runtime Modules Inspected** | **20** | All 20 non-`__init__.py` Python files within `submission/` (`config`, `main`, 3 `execution/*`, 3 `market/*`, 3 `state/*`, 9 `strategy/*`). |
| **Top-Level Components Mapped** | **20** | 18 `ARCH-*` subsystem modules plus 2 `ARCH-DATA-*` precomputed data tables (`ARCH-CORE-01` through `ARCH-DATA-02`). |
| **Decision Gates Formally Modeled** | **9** | Strategic expansion, hiring, slot reservation, crop portfolio, herd sizing, feed deficit, sell execution, and task dispatch (`DEC-*`). |
| **Dynamic Formulas Extracted** | **33** | 28 active runtime formulas, 3 active-calculation/uncoupled diagnostics/signals (`FORM-HERD-01`, `FORM-LOAD-01`, `FORM-PLANNING-CAPACITY-01`), 1 theoretical reference (`FORM-CAPACITY-01`), 1 dormant design formula (`FORM-CARRY-01`). |
| **Static Policy Rules Extracted** | **29** | 25 active rules and 4 dormant/dead/superseded/configured-only constants (`RULE-LAND-04`, `RULE-LAND-05`, `RULE-CROP-03B`, `RULE-MKT-04`), including tactical advisor (`RULE-ADV-01` through `RULE-ADV-04`) and feed rules. |
| **Dead / Dormant Rules & Helpers** | **10** | Documented constants/helpers that are uncalled or dead in runtime (`LAND_ROI_THRESHOLD`, `LAND_BUY_LAST_DAY`, `BUY_WHEAT_TRIGGER_DAYS`, `RULE-CROP-03B`, `FINAL_DUMP_DAYS`, carry checks, `should_liquidate_now`, etc.). |
| **Persistent State Objects Identified** | **8** | Module-level memory, opponent snapshots, sticky missions, blocked tasks, diagnostics, SW tracker (`STATE-*`). |
| **Failure Propagation Chains Created** | **10** | Complete causal graphs covering land starvation, animal death, shed overflow, worker churn, etc. (`FAIL-*`). |

---

## 5. Potential Issues & Codebase Anomalies Discovered

During this rigorous architectural audit of `submission/`, the following anomalies were identified:

1. **Documentation Convention on Code-Doc Drift & Stale Source Comments**:
   When source code comments conflict with executable Python branches, architecture documents represent executable behavior as ground truth and separately flag stale comments as **CODE-DOC DRIFT**. For example, `macro_planner.py:L717` contains a stale comment claiming: `# Whitelist: strictly WHEAT (D9-24) or CARROT (D25-27), 0 strawberries/melons/tomatoes`, whereas the actual executable function `sw_plant_decision()` dynamically allocates free SW soil tiles to Wheat to satisfy net feed deficits, and dedicates all remaining free SW soil tiles to Carrot starting from early days (Days 0–27).
2. **Active Hard Cutoff Blocker in `expansion_planner.py:L471`**:
   The check `if next_quadrant == 3 and current_day > 13: return False, "sw_window_closed_after_day_13"` is an active hard blocker that permanently locks out SW expansion from Day 14 onward (`day <= 13` allowed, `current_day > 13` blocked, `RULE-LAND-06`). This directly conflicts with `opportunity_window_factor()` comments claiming late crops (Tomato/Carrot) remain viable through Day 25.
3. **SW Land ROI Valuation vs SW Planting Policy Mismatch**:
   `compute_land_roi()` assumes 25 crop-capable tiles. Runtime SW provides 15 crop-capable soil tiles (`SW_SOIL_TILES`), 9 pasture tiles (`SW_PASTURE_TILES`), and 1 shed portal tile (`PORT_SW = (4, 5)`). This is 10 extra assumed crop tiles:
   - 40% of the full 25-tile quadrant is incorrectly treated as crop land, and
   - Modeled crop capacity is 66.7% higher than actual crop capacity (25 vs 15).
   Furthermore, `compute_land_roi()` evaluates profitability assuming the additional tiles will be planted with high-margin strawberry/melon/tomato cycles, whereas runtime SW planting policy (`sw_plant_decision()`) strictly enforces `RULE-CROP-04`, dedicating SW exclusively to Wheat (feed deficit) and Carrots (remainder).
4. **Projected Wheat Sustainability Signal Uncoupled from Livestock Sizing (`FORM-HERD-01`)**:
   `macro_planner.py:L431-L433` computes `sustainable = compute_sustainable_animals(wheat_cap, days_left)` (and boosts it on Day $\le 2$ by `PHASE1_GEESE_DAY0_2`), but this signal does not close the control loop into livestock target sizing: `sustainable` is never passed to or applied by `get_animal_targets()`, which calculates herd sizes based purely on available money, current inventory, and pasture limits without being constrained by `sustainable`.
5. **Workload Load Estimation Duplication & Shadowing (`FORM-PLANNING-CAPACITY-01`)**:
   `estimate_daily_load()` is duplicated verbatim (all 79 lines of executable function body match) between `macro_planner.py:L1035` (called at line 900) and `task_scheduler.py:L1305` (defined but never called internally). Furthermore, when evaluating `water_budget_exceeded = load > (units_now + hires) * EFFECTIVE_ACTIONS_PER_UNIT`, `macro_planner.py:L455` locally defines `EFFECTIVE_ACTIONS_PER_UNIT = 18`, shadowing `config.py:L116` (`EFFECTIVE_ACTIONS_PER_UNIT = 12`). The resulting `water_budget_exceeded` flag is stored in `MacroPlan` but never read by any decision gate or hiring schedule.
6. **Dormant `BUY_WHEAT_TRIGGER_DAYS` Constant**:
   `config.py:L97` defines `BUY_WHEAT_TRIGGER_DAYS = 2.0`, but this constant is never imported or referenced in runtime execution. The actual live survival floor in `macro_planner.py:L635` is hardcoded directly as `(n_animals * 2) - wheat_have`.
7. **Dormant Sell-Side Carry & Non-Melon Floor Logic**:
   `MarketBrain.sell_orders()` does not evaluate forecast carry gain (`_reason()` is uncalled dead code receiving a precomputed parameter), and floor-price holds apply exclusively to `MELON` (when not in endgame or urgency 2). For non-Melon commodities, `spot <= 1` elevates candidate priority to 0.95 rather than holding. Furthermore, curve-safe drip budgeting (`_drip_budget`) is active only for Melon; all other commodities sell in phase-indexed batch targets (15, 7, 4, or 20).
8. **`main._build_opp_advice` Silent Diagnostic Suppression**:
   Exceptions during opponent modeling are caught and recorded in `_OPPONENT_MODEL_DIAGNOSTICS`, returning an empty advice object. This prevents crashes, but suppresses error visibility unless `DEBUG` is active.
9. **Semantic Duplication in `get_animal_targets`**:
   `config.py:L306` provides a wrapper `get_animal_targets()` delegating to `strategy.animal_planner`, while `macro_planner.py` directly imports `from strategy.animal_planner import get_animal_targets`.

