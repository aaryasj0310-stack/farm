# SW-First Forward Architecture Design

**Status:** Phase A Complete (Architectural Substrate & Decoupled Shadow Planner).  
**Repository Branch:** `experiment/sw-p13-planting-gate`  
**Base Remote HEAD:** `975da5e1683f1bb57463cb9478344d0acf379d58`  
**Evidence Freeze Commit:** `f830d41e33c2a0ef881fae3492a90a8a277bcc39`  

---

## 1. Executive Summary & Architectural Motivation

Historical attempts to develop the Southwest (SW) quadrant in Kaggriculture consistently suffered from an architectural flaw: **greedy, single-turn, isolated decision-making**.

Previous implementations treated land purchase, crop selection, and animal expansion as decoupled positive-EV assets:
- `MacroPlanner` independently queued crops, animals, hires, and land.
- `land_serviceability_model` evaluated labor capacity as an aggregate daily scalar (`EFFECTIVE_ACTIONS_PER_UNIT = 12`) on a static 15-tile grid, ignoring hourly deadlines, carrier limits, travel time, and peak demand collisions.
- Shared resources—namely liquid cash, worker-hours, accessible wheat, 10-order market capacity, and 100-unit shed storage—were simultaneously double-committed by multiple independent subsystems.
- When SW was unlocked, rigid worker partitioning (e.g. reserving Hands 11 & 12 in P4.1) transferred productive core workers into SW, starving NW/NE of essential watering and harvest actions, resulting in a loss of -$4,819.10/game.

The **SW-First Forward Architecture** completely replaces this decoupled decision structure with a unified, time-indexed whole-farm planning loop:

```text
Observation / Market / Opponent State
                ↓
    Persistent FarmPlan (Observation-Driven State Machine across episode)
                ↓
  Dated Multi-Resource Commitment Ledger (Cash, Feed, Orders, Storage)
                ↓
    Crop & Livestock Cohort Plan (Counterfactual Opportunity-Cost Admission)
                ↓
  Time-Aware Service Certificate (Rolling 72-96h Hourly Feasibility & Repairs)
                ↓
    Commitment Admission Gate (Admit / Delay / Downsize / Repair / Reject)
                ↓
Deadline-Aware Regional Scheduler (Soft Locality + Global Deadline Rescue)
                ↓
  [SHADOW (Phase A): Isolated Evaluation & Telemetry Comparison]
  [LIVE (Phase B): Engine Execution & Central Market Arbitration]
```

---

## 2. Component Disposition: Preserved vs. Superseded

| Component | Status | Role in Forward Architecture |
|---|---|---|
| `state/observation_parser.py` | **Preserved** | Authoritative ground truth observation parser. |
| `state/state_tracker.py` | **Preserved** | Transaction memory, opponent history, and reset hooks. |
| `strategy/price_forecast.py` | **Preserved** | Pre-computed price distribution and shop-conditioned trajectories. |
| `market/order_builder.py` | **Preserved** | Encodes specific market operations under 10-order cap. |
| `market/market_brain.py` | **Preserved** | Drip-selling mathematics and spot-price preservation. |
| `strategy/central_planner.py` | **Preserved** | 10-order priority arbitration and conflict resolution. |
| `execution/pathfinding.py` | **Preserved** | BFS grid transit and movement primitives. |
| Emergency / Survival Fallback | **Preserved** | Safe, deterministic fallback protecting animal/crop life. |
| `strategy/macro_planner.py` | **Superseded** | Replaced by `WholeFarmPlanner` (active in shadow for Phase A). |
| `strategy/expansion_planner.py` | **Superseded** | Replaced by `FarmPlan` + `CohortPlanner`. |
| `strategy/land_serviceability_model.py` | **Superseded** | Replaced by multi-day hourly `ServiceCertificate`. |

---

## 3. Strict Decoupling of Shadow Mode

To prevent any possibility of shadow execution contaminating live gameplay:
1. **Mode Switch**: Controlled via `SW_FORWARD_ARCHITECTURE_MODE` (values: `"OFF"`, `"SHADOW"`, `"LIVE"`), defaulting to `"OFF"`. Boolean string evaluation bugs (`bool("OFF") == True`) are prevented by requiring explicit getters (`get_sw_forward_architecture_mode()`).
2. **Snapshot Boundary**: In `SHADOW` mode, the live baseline planner executes completely and constructs the authoritative engine action dictionary.
3. **Immutable Input**: A frozen `ShadowSnapshot` (deep-copied tuples of money, shed, inventories, prices, intents) is passed to `WholeFarmPlanner.evaluate()`.
4. **Isolated Output**: `WholeFarmPlanner` returns only `ShadowResult` (containing `ShadowDecision`, `ShadowCertificate`, and `ShadowDiagnostics`). It emits no engine commands and mutates no live variables.

---

## 4. Key Architectural Pillars

### Pillar I: Persistent Whole-Farm Planning (`FarmPlan`)
Survives across turns within an episode. States progress via observed engine facts:
`SW_NOT_COMMITTED` (D0-D4) $\to$ `SW_PREPARING` (D4-D7) $\to$ `SW_READY` (D7-D10) $\to$ `SW_PURCHASED` (engine unlock) $\to$ `SW_RAMPING` (active planting) $\to$ `THREE_QUADRANT_OPERATION` ($\ge 20$ tiles).
Cancellation is strictly constrained: permitted only if $D > 14$ or in unrepairable feed/cash insolvency. Downsizing, delaying, and repairing are strictly prioritized over cancelling.

### Pillar II: Dated Multi-Resource Commitment Ledger (`ResourceLedger`)
- **Cash**: Inflows classified into `HARD` (settled), `CONSERVATIVE` (realizable inventory), and `SPECULATIVE` (future unharvested yields). Hard liabilities (feed, land, wages) cannot rely on speculative inflows. Zero double-reservation across dated checkpoints.
- **Feed**: Strict harvest causality. In-ground wheat maturing on Day 10 cannot satisfy Day 8-9 animal feed obligations.
- **Market Orders**: Actual command slot semantics. 10 HIRE orders consume all 10 slots; concurrent land/seed buys must be scheduled across turns.
- **Storage**: Sequential execution modeling (harvest $\to$ worker inventory $\to$ shed deposit $\to$ market sale $\to$ midnight drop $\to$ discard).

### Pillar III: Counterfactual Opportunity-Cost Admission (`CohortPlanner`)
Replaces isolated $EV > 0$ with:
$$\Delta FC = \mathbb{E}[\text{FinalCash} \mid \text{Plan WITH candidate}] - \mathbb{E}[\text{FinalCash} \mid \text{Plan WITHOUT candidate}]$$
Everything is inside the trajectories: candidate gross, seed costs, displaced core output, incremental wages, feed impact, and nonlinear own-supply price depression.

### Pillar IV: Multi-Day Time-Aware Service Certificate (`ServiceCertificate`)
Evaluates feasibility across a rolling 72-96 hour horizon:
- Zone 1 (H0-H24): Exact unit actions and BFS transit.
- Zone 2 (H24-H48): Exact cohort deadlines and regional transit buffers.
- Zone 3 (H48-H72+): Capacity envelopes.
Detects multi-day task collisions (e.g. Day 8 planting causing a Day 11 service crisis) and outputs structured `RepairOption` records sorted by lowest economic loss.

---

## 5. Summary of Phase A Accomplishments

1. Complete substrate implemented in clean, modular files:
   - `agent/strategy/farm_plan.py`
   - `agent/strategy/resource_ledger.py`
   - `agent/strategy/cohort_planner.py`
   - `agent/strategy/service_certificate.py`
   - `agent/strategy/whole_farm_planner.py`
2. Exact 1:1 byte-for-byte mirroring in `submission/strategy/`.
3. Decoupled shadow hook and reset mechanisms wired into `main.py`.
4. Comprehensive test suites passing with 100% success rate:
   - Unit tests: `test_sw_forward_architecture.py` (12/12 passed).
   - Historical failure replays: `test_sw_historical_failure_scenarios.py` (4/4 passed).
5. Baseline test fixture cleanup in `test_production_no_sw.py` eliminating global state leakage.
