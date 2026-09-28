# Kaggriculture — SW-C2 Complete Implementation Plan

**Title:** Diagnostic Integrity, Shared Service Commitments, Coordinated Workforce Dispatch, and Capacity-Aware SW Expansion  
**Document status:** Proposed implementation blueprint; no code changes are authorized by the document itself.  
**Prepared from:** Astra's SW-C2 architecture report, the subsequent independent architecture review, and the previously archived SW-C1 evidence.  
**Repository:** `https://github.com/aaryasj0310-stack/farm`  
**Starting experimental branch:** `experiment/sw-c1-adaptive-acreage-expansion`  
**Last independently reviewed HEAD:** `ec16d96fa19efc5f7f7f33bb416ff9778bccb0d7`  
**Protected canonical production commit:** `faa6cb99f66b2066e639806d0eabc72a0c7d7982`  
**Previously recorded protected production submission SHA-256:** `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41`  
**Long-term objective:** A reproducible mean final cash of at least **$130,000** against the preregistered evaluation distribution, without sacrificing essential safety.

> **Source and uncertainty convention:** Historical figures below are reported results, not predictions. Module names under “Proposed new modules” and release thresholds marked *proposed* are design choices for SW-C2. In particular, the exact terminal executable step and detailed causes of SW-C1 livestock losses require engine-level verification. Before work begins, recheck HEAD, runtime flags, engine identity, and artifacts; do not assume the repository remains at the reviewed commit.

---

## 1. Executive decision

Implement **Architecture D: a hierarchical whole-farm scheduler with one global capacity coordinator**, reusing the existing task generator, pathfinding, action emitter, market arbitration, and safety controllers.

Do **not** replace the existing task scheduler in a single change. Build and validate three logically separate capabilities:

1. **Service Obligation Ledger:** The authoritative identity, dependency, state, and confirmation record for crop, livestock, and logistics work.
2. **Workforce Capacity Forecaster:** A deterministic, observation-grounded estimate of whether current and future obligations can finish within their actual service windows given worker availability, worker positions, travel, carried inventory, and shared resources.
3. **WorkforceCoordinator:** The eventual behavioral layer that allocates workers globally, maintains mission ownership, coordinates regional staffing, and sends executable assignments through existing interfaces.

The obligation ledger and forecaster must run **observation-only/shadow mode** before either is permitted to control execution. Expansion admissions must eventually use the **same obligation IDs, resource reservations, and capacity evaluator** as dispatch, avoiding the present disconnect between optimistic planning and actual service delivery.

### Required phase order

`P0 diagnostic repair + shadow foundation → P1 ownership/resource-chain correction → P2 coordinated dispatch at fixed acreage → P3 transactional crop-cycle reservations → P4 acreage ladder → P5 independent confirmation and release → P6 isolated follow-on economics/portfolio experiments (only if warranted).`

Do not skip directly to P3/P4 because a more elaborate admission model is only useful if its service predictions are credible and executable.

---

## 2. Evidence baseline and problem statement

### 2.1 Historical comparison to freeze

The archived SW-C1 pooled panel used **four seeds × five opponents × two seats = 40 matched scenario cells per arm**. These are **not 40 independent environment seeds**.

| Historical arm | Mean final cash | Notes |
|---|---:|---|
| A — canonical production, SW off | $113,368.88 | Frozen canonical comparison |
| B — frozen B3C, eight SW tiles | $109,302.50 | Eight-tile reference |
| C — adaptive control, cap eight | $109,302.50 | Exact archived parity with B |
| D — adaptive cap 12 | $106,449.05 | Historical SW-C1 |
| E — adaptive cap 16 | $103,794.80 | Historical SW-C1 |
| F — adaptive cap 20 | $102,013.50 | Historical SW-C1 |
| G — adaptive cap 24 | $99,915.12 | Cap is not actual acreage; mean admitted SW acreage was reported as about 18.2 |

Relative to eight-tile B, maximum-24 G lost **$9,387.38** in mean final cash. The archived B→G accounting includes approximately +$4,629.21 attributed SW crop sales, −$3,737.71 attributed core crop sales, −$7,580.83 livestock-product sales, +$766.50 seed spending, and +$1,931.55 feed spending. Regional crop sales are attribution estimates; reconciled whole-farm cash is the primary economic fact.

The difference between historical canonical production and the $130,000 target is **$16,631.12**. Improving on the weaker eight-tile control alone is insufficient to establish overall project success.

### 2.2 Actual architectural gap

The present adaptive acreage decision uses simplified aggregate daily capacity and a crop-heavy marginal valuation. Current execution combines priority, distance, locality, urgency admission, and sticky missions, but it does **not** share a binding future service schedule with the acreage planner. Extra SW crops can therefore acquire planting authorization even when their watering, harvest, transport, storage, or liquidation later compete with incumbent NW/NE crops or animal production.

The core hypothesis for SW-C2 is **not** that more acreage necessarily raises cash. It is that a serviceability-aware global dispatcher may preserve whole-farm production and reveal when additional SW acreage has positive realized incremental contribution. The hypothesis requires controlled experiments.

### 2.3 Important confirmed implementation facts

- Soft worker locality already exists and was enabled in SW-C1. Do not present simply enabling locality as a new optimization.
- The existing `assign_tasks()` uses joint greedy worker–task selection, urgent handling, sticky missions, SW-specific gates, fallback work, and pathfinding. Preserve and extend this infrastructure.
- The current `ServiceCertificate.evaluate_multi_day()` accepts a worker count rather than actual individual worker positions. Its capacity estimates use aggregate action budgets and travel multipliers, not exact worker routing, notwithstanding some descriptive comments.
- SW-C1 instrumentation lacks a successful PLANT outcome in the audit wrapper; it conflates some attempted operations with success; its `care_actions` increments on `COLLECT_FERTILIZER`; and its HARD-obligation completion path is disconnected. These defects preclude strong regional-margin or task-completion conclusions.
- WholeFarmPlanner contains a melon-yield inconsistency (hardcoded multiplier of two in some projections versus `CROPS['MELON']['max_yield'] == 6` in config). The correct model must be derived from engine rules and specific production/harvest semantics, not fixed by assuming either value is universally correct.
- Hired hands disappear at midnight and are rehired. A market hire does not perform an earlier unit action in that same turn. Future workforce must not be credited until actually available.
- Engine terminal action and sale timing must be verified against the pinned engine. Astra reports a possible final executable decision of step 718/D29H22 for a nominal 720-step episode; this is a verification item, **not yet an independently established fact**.

---

## 3. Scope, non-goals, and protected assets

### In scope

- Correct engine-confirmed diagnostics and resource reconciliation.
- Stable operation-specific service obligations and actual outcome verification.
- Forecast of hourly worker availability, route/service dependencies, regional bottlenecks, and cohort lifecycle demand.
- Consistent ownership for urgent/regular missions, explicit handoffs, and inventory-aware service chains.
- One globally coordinated dispatcher with dynamic NW/NE/SW regional capacity and shared shed logistics.
- Transactional, complete crop-cycle reservations for new SW acreage and subsequent replants.
- Matched real-engine experiments and independent validation, preserving incumbent production and safety.

### Out of scope until the dispatcher is isolated and validated

- Broad crop-portfolio retuning; different seed/crop scores for selected acreage caps.
- Changing livestock targets, feed policy, hiring schedule, land-buy timing, market strategy, or storage rescue behavior to rescue a dispatch result.
- Replacing shortest-path BFS, rewriting the command emitter, or introducing three independent quadrant schedulers.
- Arbitrary hard pinning of workers to NW/NE/SW.
- Assuming leader replay trajectories reveal their internal scheduling algorithms.

### Non-negotiable repository safeguards

1. Make all changes on a **new experimental SW-C2 branch**, not the canonical production branch. Reconfirm branch HEAD before editing.
2. Do not overwrite the canonical production commit, submission zip, or stored hashes.
3. Do not use protected seed range **98001–98050** during development/discovery; retain it for its documented intended final validation stage.
4. Keep any behavior-changing feature flags **OFF by default** until a separately approved promotion.
5. Each experimental arm must pin code SHA, engine SHA/version, effective runtime flags after initialization, opponent identities/versions, scenario seeds, seats, game horizon, and submission artifact hash.
6. No code changes are implied by acceptance of this planning document. Authorize and implement phases separately.

---

## 4. Target architecture and ownership boundaries

### 4.1 Logical data flow

```text
Observation
   |
   v
Parse observed state + reconcile previous engine-confirmed outcomes
   |
   +--> Shared Service Obligation Ledger <----- committed crop cycles, animals, logistics
   |                |
   |                v
   |        Workforce Capacity Forecaster <---- actual workers / inventory / missions
   |                |
   |                +----> diagnostics (always)
   |                +----> trial reservations (P3 onwards, flag-gated)
   |                |
   +--> Existing MacroPlanner and candidate crop proposal
   |                |
   |                v
   |        Transactional admission (P3 onwards): propose / trial / commit
   |                |
   +--> Existing build_tasks()
                    |
                    v
          WorkforceCoordinator (P2 onwards, flag-gated)
          | protected deadline coverage / shared resource prerequisites
          | regional allocation / mission ownership / economic slack
                    |
                    v
          Existing task execution, pathfinding, and command emission
                    |
          Existing market ordering and arbitration
                    |
                    v
                 Engine
                    |
          Next observation/outcome reconciliation
```

**Integration correction:** Existing `MacroPlanner.build()` can call `maybe_evaluate_adaptive_expansion()`, which already mutates admitted SW tiles and crop targets. At P3, convert this into a side-effect-free proposal followed by trial reservation and explicit commit. Merely inserting a validator after the old macro call risks approving acreage before capacity is checked.

### 4.2 Proposed new modules (names may be adjusted to established repository conventions)

| Proposed component | Primary responsibility | Permitted behavior in initial phase |
|---|---|---|
| `agent/execution/obligation_types.py` | Typed identity, statuses, dependencies, forecast results | Data-only |
| `agent/execution/service_obligation_ledger.py` | Create, merge, reconcile, expire, and report obligations | Shadow only |
| `agent/execution/workforce_capacity_forecast.py` | Worker-by-hour and regional serviceability projections | Shadow only |
| `agent/execution/workforce_coordinator.py` | Later global allocation and mission ownership | Not active during P0 |
| `scripts/run_phase_sw_c2_experiment.py` | Pinned real-engine arms, diagnostics, output manifests | Instrumentation only initially |

Existing modules remain authoritative for task generation, engine action legality, pathfinding, and market orders. Do not create a second competing farm-state store.

### 4.3 Obligation identity and lifecycle

A service obligation must be identified by **more than a target coordinate**. Suggested identity fields:

`(episode_id, cohort_or_entity_id, crop_cycle_or_service_day, operation_type, operation_sequence)`.

Preserve `pos`, `region`, and human-readable description as attributes rather than the sole identity. Distinguish multiple valid operations at the same location, e.g. animal FEED, CARE, HARVEST and COLLECT_FERTILIZER.

Each obligation should capture:

- `obligation_id`, optional `parent_chain_id`, source/provenance, entity/crop-cycle ID;
- operation, target, region, prerequisites, resource-carrier requirement;
- release/earliest start, deadline, **latest feasible start**, expected duration and travel;
- tier (`HARD`, `STRATEGIC`, `DISCRETIONARY`) and economic value where modeled;
- current owner, owner assignment timestamp, projected arrival and completion;
- lifecycle (`PROPOSED`, `RESERVED`, `READY`, `ISSUED`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `EXPIRED`, `CANCELLED`);
- observed confirmation record and cancellation/failure reason.

Separate **crop-cohort lifecycle** (`proposed → reserved → planted → serviced → harvested → realized`, with explicit cancellation/loss) from the lifecycle of each individual service obligation. Never mark a complete crop as realized on a mere HARVEST request.

### 4.4 Resource reservations

Use one reservation namespace linking labor/time windows to the existing cash, feed, storage, and market-slot ledger. A reservation needs stable ID, parent cohort, resource type, quantity, time window, state (`trial`, `committed`, `fulfilled`, `released`, `failed`) and conflict reason.

A trial must be **side-effect free**, deterministic, and leave previous commitments untouched on failure. Committing a crop cohort must reserve its entire expected executable chain, not only planting-day capacity. On overload, release unfulfilled discretionary future commitments first, but **never erase maintenance obligations of crops already planted**.

### 4.5 Workforce identity and availability

- Scope hired-worker identity and owned missions to the correct game day because hires are recreated daily.
- Current-day supply = **actual observed active workers**, not target staffing or a planned hire count.
- Future workers count only after their hire orders are funded, accepted, settled and executable under engine ordering.
- Model H0/H1/H2 from the actual observation and pinned engine rather than hard-coding a universally fixed morning headcount.
- Deduct movement, acquisition/pickup, already-owned missions, inventory constraints, and service duration from nominal worker-hours.
- Distinguish a worker assigned toward a tile from a confirmed finished operation.

---

## 5. Cross-cutting invariants

Apply these invariants throughout every phase and test suite.

### Execution and safety

1. At most one legal worker command per actually observed active worker per executable turn.
2. Preserve one authoritative market arbitration cap; do not permit separate buy-side/sell-side caps to create excess market orders.
3. Respect engine operation ordering: worker action versus market settlement, purchase availability, inventory pickup, deposit, and final sale.
4. An obligation counts as completed only after engine-confirmed state transition or an unambiguous reconciled observation delta.
5. One owner per obligation at a time, but allow multiple **different** obligations and legal sequences on the same tile.
6. Never count a physically held resource twice; a unit of wheat cannot simultaneously be sold and counted as internal feed substitution.
7. No illegal/no-op regression, duplicate owner, unexplained cash residual, or untracked inventory loss.
8. Preserve livestock survival, feed feasibility, crop survival, shed/storage rescue, and terminal liquidation safeguards.
9. Preempted work remains in the ledger and is reconsidered with any associated resource holds.
10. Flag-OFF execution stays bit-for-bit compatible with the chosen reference (including action stream and final cash where instrumentation is pure).

### Forecasting

- Do not label a conservative/optimistic capacity envelope as an exact executable route proof.
- Record unmet or forecast-missed obligations and the specific constraint, not just a global boolean.
- Derive crop yield, watering, care, production, saturation, and expiry from pinned engine semantics.
- Use a verified last executable worker/market turn for every terminal decision.
- Current, committed future, and speculative future resources must be distinct.
- Maintain deterministic iteration ordering and deterministic tie-breaking independent of SciPy or optional installed packages.

### Measurement

- Separate `requested`, `engine_accepted`, `successful_state_change`, and `realized_cash` counters.
- Preserve both whole-farm economic results and physical output/service completion.
- Separate cap, admitted coordinates, planted area, productive tile-hours, harvested output, inventory, and actual sale/consumption.
- Attribute fungible regional product sales only under an explicit inventory-lot convention. Whole-farm cash remains the primary financial result.

---

## 6. P0 — Diagnostic integrity and shadow forecasting foundation

**Objective:** Build trustworthy measurements and a shared forecast without changing a single gameplay decision.

**Flags:** Any proposed ledger/forecast flags may enable observation-only logging, but no P0 output can modify MacroPlanner, `assign_tasks`, market orders, purchases, crop selection, or acreage admission.

### P0-A. Reference freeze and reproduction

**Tasks**

1. Confirm actual branch HEAD and describe any commits after the last reviewed SHA.
2. Pin source, full effective flags (not just config defaults), submission zip/hash, engine identity, opponents, seats, seed sets, horizon, and runner command.
3. Preserve original A/B/C SW-C1 outputs and reproduce the chosen frozen reference before modifying instrumentation.
4. Verify which code paths and imported modules the harness actually executes; avoid testing an unused duplicate module.
5. Confirm morning hired-worker settlement order and **last executable worker and market decision** through minimal real-engine boundary tests.
6. Save an immutable reproducibility manifest with engine and policy version information.

**Deliverables:** `reports/phase_sw_c2/p0_reference_manifest.md` and machine-readable manifest, exact reference action/final-cash fingerprints, terminal boundary evidence.

### P0-B. Repair the SW-C1 diagnostic harness

**Tasks**

1. Make PLANT result reporting identify successful planting by post-action tile transition/engine-confirmed outcome and debit the correct seed lot.
2. Wire HARD obligation registration, completion, expiry and cancellation to actual operation/obligation identity. Do not count zero telemetry as proof of zero successful service.
3. Fix `care_actions` to count CARE, while maintaining a separate `collect_fertilizer_actions` field.
4. Split WATER/FEED/HARVEST/FERTILIZE/PLACE/PICKUP/DROP into attempted versus actual successful outcomes and actual inventory deltas.
5. Confirm HARVEST using actual crop/animal state transition and inventory/held-output movement; avoid counting positive pre-action yield alone as success.
6. Retain, for diagnostic runs, hourly worker roster/positions/inventories, animal status and held yield, crop state, issued commands, outcomes, mission state, transactions, deposits, discards, market inventory and realized sale values.
7. Repair acreage reporting: distinguish **authorization**, **successful planting**, **productive occupancy**, harvest and realization.
8. Reconcile product mass balance: opening + verified production/purchase − consumption − sale − discard = closing inventory, with explicit internal feed transfers.
9. Reconcile cash against engine wallet exactly; preserve native/cash-ledger totals separate from optional regional lot-attribution estimates.
10. Document known limitations when exact source lots cannot be recovered for fungible inventory.

**Important:** The telemetry patch must not adjust gameplay decisions to make counters easier to observe. Prefer engine hooks and immutable snapshots; if only observation deltas are available, mark ambiguous cases as unconfirmed, not successful.

**Gate P0-B:** Reference actions, operations, final cash and outcomes remain bit-exact; all tracked accounting conservation assertions pass; classification tests cover PLANT/CARE/HARD and each core operation.

### P0-C. Build stable obligation ledger in shadow mode

**Tasks**

1. Normalize existing `build_tasks()` outputs, crop cohort schedules, animal services, feed pickup chains and relevant storage/market dependencies into stable operation-specific IDs.
2. Link dependent events (e.g. shed wheat → particular carrier pickup → animal FEED; planting → planting-day WATER → later watering → HARVEST → possible deposit/sale).
3. Record releases, service windows, deadlines, prerequisites and expected completion without altering task priorities.
4. Keep current and previously committed crops/animals in the ledger, including future work not present in today's task list.
5. Reconcile expected outcomes against each subsequent engine observation; record false positives, missed tasks, orphaned commitments, duplicate ownership claims and forecast errors.
6. Expire previous-day worker ownership while preserving unpaid/unfinished entity obligations and legitimate inventory state.
7. Validate legal coexistence of different operations on identical coordinates.

**Gate P0-C:** No new gameplay actions; all generated task categories represented; identities stable across turns; no silent disappearance of planted-crop/animal service obligations.

### P0-D. Build the shadow hourly capacity forecaster

**Resolution and horizon**

- **Rest of current day:** actual workers, positions, carried inventory, current missions, prerequisites, service duration and explicit estimated routes.
- **Next two days:** funded/expected worker availability, midnight reset/redeployment, region-level obligations, conservative travel windows and dated service peaks.
- **Remaining season:** cohort maturity/harvest, repeat-crop peaks, animal recurring demand, storage occupancy and actual terminal sale feasibility.

**Forecast inputs:** `observation`, `obligation_ledger`, existing mission snapshots, verified engine timing, confirmed/pending purchases, `ResourceLedger`, actual workers, and crop/animal rules.

**Forecast outputs:**

```text
forecast_id / source_step / engine_fingerprint
feasible_tier / uncertainty_level
by_worker_hour_capability and by_region_hour_supply
by_region_hour_required_capacity
obligation_id -> estimated_arrival, latest_feasible_start, projected_completion
unserviceable_obligation_ids
binding_region, binding_day, binding_hour, binding_resource
assumed_funded_future_hires and availability steps
predicted versus observed completion/travel/action burden
```

**Rules:** Identify chain prerequisites; do not subtract all wheat held on distant workers as though instantly usable; do not credit incomplete or pending hiring; count forecasted non-survival economic services separately from mandatory survival; report uncertainty instead of claiming exactness from travel factors.

**Gate P0-D:** Strong shadow diagnostic agreement with actual outcomes; every false-negative and false-positive serviceability claim logged and classified; no systematic optimism from uncounted travel, omitted livestock services, or workforce timing. Set quantitative calibration tolerances from a frozen discovery sample **before** behavioral activation.

### P0-E. Engine and model correctness tests

- Melon and other crop production/harvest semantics: reconcile `config`, WholeFarmPlanner, cohort model and the actual engine.
- Crop bonus/survival watering days and same-day planting prerequisites.
- Animal feed/care/harvest, held-yield saturation and two-day unfed escape semantics as implemented in the pinned engine.
- Last executable turn, worker/market order timing, terminal harvest-to-sale path, and Day 29 late liquidation.
- Worker hiring, disappearance and day-scoped identity.
- Midnight storage rescue and no fabricated shed capacity.

**P0 exit:** The entire diagnostic harness, ledger and forecasting model operate in shadow mode with exact flag-off behavior and reliable, versioned output. No behavioral-dispatch work begins before this gate.

---

## 7. P1 — Mission ownership and resource-chain correctness

**Objective:** Repair isolated execution defects before broad regional allocation. Make this a separate experimental treatment.

### Work packages

**P1-A: Unique service ownership**

- Index mission ownership by stable `obligation_id`, not solely target location.
- Validate owner availability, target relevance, prerequisites, carried inventory, no-progress counters, expected completion, and time remaining.
- Carry ownership consistently across urgent and regular tasks, while keeping emergency survival preemption authoritative.
- Make transfer explicit: reason, old/new worker, travel already spent, release of stale resource holds, and resumed obligation state.
- Avoid duplicate travel pursuit unless the operation explicitly allows parallel prerequisites.

**P1-B: Preemption and continuation**

- Retain a valid mission where finishing it remains feasible/useful; do not indiscriminately privilege unassigned workers if doing so delays a deadline.
- Preempt for true emergency, invalidated target, impossible prerequisite, exceeded age/no progress, or material net benefit after switching cost.
- Preserve preempted obligations and prevent abandoned workers or resource carriers from being treated as free capacity until reconciled.
- Instrument wasted travel before cancellation, mission transfer count and ownership thrashing.

**P1-C: Feeding as an executable chain**

- Reserve specific wheat location and carrier; include PICKUP if needed, travel and FEED before deadline.
- Check actual carrier inventory, shed access and dependency ordering.
- Account for multi-animal routing and optionally pair feeding with CARE, HARVEST and COLLECT_FERTILIZER when legal and serviceable.
- Do not count distant worker-held wheat as proof every unfed animal can be served.

**P1-D: Consistent fallback eligibility**

- Prevent fallback planting/watering/weed work or idle SW port-anchoring from consuming capacity reserved for imminent core obligations.
- Preserve useful existing fallback behavior when there is genuinely no valuable near-term task.
- Do not impose a universal morning SW ban; authorize discretionary work only when protected service chains remain executable.

### Isolation and gates

- Add an experimental selector, **default OFF**. With it OFF, the old dispatcher must remain bit-exact.
- Compare old versus ownership-corrected dispatch under **fixed eight-SW-tile** rules, identical crop mix, hiring, market behavior and acreage.
- Test cross-worker transfers, same-tile different-operation tasks, day-boundary IDs, missing wheat, mid-route cancellation, and urgencies arising while existing missions are underway.
- Require no duplicate ownership, no new illegal/no-op behavior, no additional avoidable survival failures, and clear execution evidence of any claimed improvement.
- Do not silently bundle P1 with P2; retain a standalone P1 experimental arm.

---

## 8. P2 — Global coordinated regional dispatch

**Objective:** Activate one coordinator controlling existing workers and ready tasks while preserving reference acreage/economics.

### P2-A. Global prioritization in two stages

**Stage 1 — protect deadline feasibility:** Animal survival; crop survival; irreversible decay; actual feed/pickup prerequisites; terminal delivery and sale. Evaluate **latest feasible start**, not just raw task priority or target location.

**Stage 2 — economic capacity allocation:** For remaining feasible options, compare incremental expected realized contribution, consumables, incremental hires only if actually changed, travel/restart opportunity cost, and displaced incumbent work. Care, bonus watering, fertilizer, animal harvest and other non-survival production work must not become invisible.

Maintain reference core commitments in the initial experiment. A new dispatcher must not “improve” SW output by quietly dropping profitable NW/NE or livestock work.

### P2-B. Dynamic regional budgets

For NW, NE, SW, and shared shed/logistics, calculate:

1. Protected work required before dated deadlines.
2. Additional profitable ready/near-future work.
3. Actual positions, inventory and earliest arrival of potential workers.
4. Transfer and mission-abandonment cost.
5. Useful future work after regional arrival.
6. Impact of removing each worker from its present region and obligations.

Allocate all workers **jointly**; treat regional membership as soft deployment preference rather than an irrevocable quota. A worker may cross regions only if origin protection remains feasible, the destination has sufficient net work after travel, or global emergency demands recall. A currently empty regional queue does not necessarily justify relocating a worker shortly before scheduled local work.

### P2-C. Deterministic next-action matching

- Use a deterministic joint assignment for ready operations after protected coverage and service-chain prerequisites are resolved.
- With the actual small workforce, evaluate a bounded matching algorithm; avoid branch-dependent SciPy availability or nondeterministic tie-breaking.
- Include priority tier, operation deadline slack, distance/route, carried resource, mission continuation, regional opportunity and downstream task sequence in assignment cost.
- Matching optimizes **next actions**, not a claim to solve globally optimal multi-day routing.
- Reuse `build_tasks()`, pathfinding and the existing emission path; leave market order arbitration authoritative.

### P2-D. Rollout and tests

1. Run unchanged P0/P1 reference arms.
2. Enable coordinator on the **frozen eight-SW-tile crop portfolio** with fixed hiring, feed, market and land policies.
3. Record both execution mechanism metrics and paired final cash.
4. Only after its own evidence gate, run a **capped-12** fixed-policy dispatch experiment.
5. Do not alter strategy parameters per acreage cap during confirmation.

**P2 advancement gate (proposed):** Better paired cash, or a preregistered demonstrable execution benefit with credible cash non-inferiority; no added avoidable feed/escape/death failures; reference-valued core output preservation; no unexplained inventory/cash regression; acceptable deterministic runtime. Do not promote a dispatcher simply because it issues fewer moves.

---

## 9. P3 — Transactional acreage and complete crop-cycle reservations

**Objective:** Make new planting and replanting commitments contingent on the same serviceability model used by execution.

### P3-A. Remove eager admission side effects

Current expansion evaluation can change `admitted_sw_tiles` and `admitted_sw_crop_targets` inside MacroPlanner before a downstream trial. Refactor behind an experimental feature flag into:

```text
candidate = propose_expansion(current_observation, current_commitments)
trial = evaluate_complete_crop_cycle(candidate, ledger_snapshot, capacity_forecast)
if trial.feasible and trial.expected_whole_farm_delta > frozen_safety_margin:
    commit_reservation(trial)       # Atomic: labor, inventory, cash, slots, geometry
    commit_authorized_crop_cycle(candidate, trial.reservation_id)
else:
    record_binding_rejection(trial) # No mutation of existing approved acreage/crops
```

Preserve the old admission path unchanged when the feature is OFF. Avoid additional acreage being planted through a separate replant path that bypasses reservation approval.

### P3-B. Reserve full crop lifecycle

Every candidate four-tile tranche, and each subsequent replant, must reserve relevant:

- tile availability, preparation and weed clearing where required;
- seeds, seed funding, market slots, and actual purchase settlement;
- planting and same-day watering;
- necessary and economically valued later watering/fertilization;
- dated harvest windows, including repeated harvests;
- worker and carried-inventory logistics, and late-day storage/overflow safety;
- deposit/delivery when mechanically necessary;
- sale/verified internal feed usage before the **verified terminal executable deadline**;
- protection of all existing NW/NE/SW crop and livestock commitments.

An authorization to use a land coordinate is **not** authorization for every future crop cycle. Store both area authorization and distinct crop-cycle/reservation IDs.

### P3-C. Admission economics

Compute incremental **whole-farm**, not SW-only, expected value:

`E[final_cash_with_candidate] − E[final_cash_without_candidate]`.

Use the same forecast model and market-price dynamics in both arms, including candidate supply's impact on incumbent prices. Account for displaced productive work and storage/market capacity **inside** the with/without comparison; do not deduct those effects again as independent penalties. Use conservative assumptions and a measured safety buffer, and return the binding failure cause for rejected candidates.

Required trial result:

```text
accepted / reservation_id / candidate_tiles / crop_cycle_id
expected_whole_farm_increment / uncertainty / safety_margin
binding_region / binding_day_hour / binding_resource
required_worker_transfers / protected_obligations_remaining_feasible
service_schedule / prerequisites / resource_holds / rejection_reason
```

### P3-D. Runtime reconciliation and overload recovery

If actual service runs behind forecast: reconcile outcome; recompute service availability; stop new commitments; reassign workers; postpone safe discretionary work; release only valid unused discretionary holds; protect existing crops and animals; log the binding forecast error. Do not retroactively pretend rejected or unfulfilled work completed.

**P3 gate:** Trial is side-effect free; committed resources are conserved; admission and executor share obligation/reservation IDs; accepted cohorts receive feasible service through harvest/realization; any new failure is explicitly visible. Reconfirm flag-OFF bit-exact parity.

---

## 10. P4 — Incremental acreage ladder with architecture frozen

**Objective:** Test whether the validated dispatcher and reservation system allow additional **profitable** SW production without reducing whole-farm output.

### Experiment ladder

- First reproduce fixed **eight-tile** new-architecture control.
- Run otherwise identical maximum SW acreage caps of **12, 16, 20, 24**.
- Distinguish maximum cap from land owned, approved coordinates, crops successfully planted, tile-hours occupied, services completed, harvested/consumed output and final realized sales.
- Do **not** force each maximum cap to be reached. A cap-24 system may rationally stop at 12 or 16 if further expansion has negative incremental contribution.
- Keep dispatcher, reservation formulas, crop portfolio/candidate selection, hiring schedule, feed policy, market logic and price model frozen across the ladder.
- If a larger cap declines, report both economic and execution causes without changing policies within that trial.

### Questions by cap

| Cap | Required diagnostic question |
|---:|---|
| 8 | Does the new architecture preserve or improve incumbent output without an acreage confound? |
| 12 | Can the first new four-tile cohort complete planting, same-day water, maturity and realization? |
| 16 | Can overlapping existing/new watering and harvest peaks be served on time? |
| 20 | Do regional transfer and logistics costs exceed productive capacity gained? |
| 24 | Can nearly full SW occupancy avoid core displacement, congestion, storage loss and missed terminal sales? |

A standard 8→24 establishment calculation adds 32 direct PLANT+WATER operations relative to eight tiles, plus up to 16 actions for each complete additional four-by-four maintenance or harvest sweep; this excludes travel, pickup, repeated harvests, fertility, storage and sale obligations. Use crop-accurate dated calendars rather than assuming a fixed watering requirement per tile/day.

**P4 economic gate:** Additional acreage must increase **whole-farm final cash relative to the same new eight-tile dispatcher**, while also being compared to canonical production. More SW attributed sales, fewer moves, or more planted tiles alone are not proof of benefit.

---

## 11. P5 — Experimental design, independent confirmation and release

### 11.1 Control matrix

Retain separately identifiable arms:

| Arm | Meaning | Purpose |
|---|---|---|
| A | Protected canonical production, SW off | Overall economic reference |
| B | Frozen B3C eight-tile reference | SW historical control |
| C | SW-C1 adaptive-eight parity | Instrumentation/control reproduction |
| D | P1 ownership-only at eight tiles | Isolate ownership/feeding-chain effects |
| E | P2 coordinator at eight tiles | Isolate global dispatch effect |
| F | P2 coordinator + P3 reservations at eight tiles | Isolate reservation overhead/parity before growth |
| G12/G16/G20/G24 | Frozen E/F architecture with max-acreage caps | Measure incremental expansion |

Where needed, use direct matched contrasts **D versus B/C**, **E versus D**, **F versus E**, and each **Gcap versus F**, as well as **every candidate versus A**. Do not mix different historical baselines into a single change estimate.

### 11.2 Discovery and confirmation

- Historical four-seed panel is suitable for regression/reproduction, not strong generalization.
- Use at least **ten verified unused discovery seeds**, all five opponents and both seats: nominally 100 paired cells per arm, clustered by seed for uncertainty. Record opponent versions.
- Define experiment arms and release criteria **before** running discovery.
- Select at most a preregistered candidate/frozen configuration on discovery, then confirm it on a **separate untouched, preferably larger** panel. Do not recycle confirmation scenarios for iterative retuning.
- Keep protected 98001–98050 excluded until its preassigned final-validation purpose.
- Report mean/median paired final cash, confidence interval/uncertainty clustered by seed, lower-tail quantiles, worst regressions, both seats, each opponent, realized acreage and safety events.
- Check runtime determinism, engine compatibility and submission packaging in addition to tournament results.

### 11.3 Required metrics

**Economics:** Whole-farm final cash (primary), paired delta versus A/B/new-eight, cash closure, sale revenue by product, feed/seed spending, physical/referenced-price output, internal wheat use, storage loss, actual terminal unsold inventory.

**Workforce:** Hourly observed workforce, worker coordinates/inventories, assigned task region, successful operations, idle/move/failed requests, distance, mission starts/completions/transfers/preemptions, travel before abandoned assignment, regional staffing, worker-hours consumed by each cohort and core/SW operations.

**Service quality:** Released/assigned/completed/expired obligations, arrival versus latest start, feasible but unassigned work, feeding and care, animal output/held-yield saturation, animal escapes, crop watering/harvest delay/death, storage and delivery failures, forecast versus realized service demand.

**Acreage:** Cap, land bought, coordinates authorized, actual active crop tiles by day/hour, productive tile-hours, number of complete harvest cycles, sales/consumption realization. Avoid reporting authorization alone as utilization.

### 11.4 Prospective release gates

Freeze exact numeric thresholds before the experiments. The following is a starting policy, not a proven optimum:

1. **Telemetry:** P0 action/final-cash parity and exact cash/product conservation; no unexplained missing event.
2. **Model:** Forecasts show calibrated error and no systematic optimism due to omitted travel/hiring/animal services.
3. **Legality:** No new illegal/no-op operations, duplicate ownership or order-cap violation.
4. **Livestock/crop survival:** No additional avoidable animal escapes, crop deaths or required feed violations; inspect every failure cell.
5. **Core preservation:** Compare physical and fixed-reference-price-valued NW/NE/livestock output. A proposed floor is at least **98%** of corresponding reference-valued core output, but preregister and justify it before execution; never conceal a serious tail failure behind the average.
6. **Cash:** New architecture's paired whole-farm economics clear the relevant control; no release based only on better SW attribution or movement statistics.
7. **Independent repeatability:** Results persist outside discovery, with clustered uncertainty and downside diagnostics.
8. **Production:** Behavior-changing flags OFF unless expressly approved; canonical artifacts untouched; final promoted package and hashes independently reproducible.

If the new dispatcher improves eight-tile service but fails cash non-inferiority, retain as an experimental result, diagnose it, and do not silently promote. If extra acreage reduces cash, stop at the smaller cap rather than forcing 24.

### 11.5 Definition of the $130k goal

Report distinctly:

1. Gain/loss relative to frozen eight-tile B3C.
2. Gain/loss relative to canonical A.
3. Whether the preregistered **independent** evaluation achieves mean final cash **≥$130,000**, with uncertainty and downside disclosed.

Progress on criterion 1 is not completion of criteria 2–3. Do not predict that this architecture alone will reach $130k.

---

## 12. P6 — Subsequent isolated economic/portfolio research (conditional)

Begin only after the dispatch/reservation effect is isolated and confirmed.

Potential separate treatments:

- SW crop mix and cohort staggering versus harvest/window collisions.
- Internal wheat feed substitution versus crop sales, counted exactly once.
- Supply-aware expected prices and impact of SW products on incumbent output.
- Hiring timing and actual next-turn workforce availability.
- Land purchase lead time and capital opportunity cost.
- Fertilizer/bonus-watering economics and animal-service scheduling.

Optimize **realized incremental whole-farm contribution per constrained worker/service-window unit**, not headline crop revenue or tile count. Evaluate each strategic change separately with new discovery and independent confirmation.

---

## 13. File-level work map

| Existing/planned file | Work scope | Earliest phase |
|---|---|---|
| `scripts/run_phase_sw_c1_experiment.py` or new `scripts/run_phase_sw_c2_experiment.py` | Correct outcome instrumentation; pin experiments; retain hourly traces and reconciled ledgers | P0 |
| `agent/execution/obligation_types.py` *(new)* | Typed obligation, mission, reservation and forecast results | P0 |
| `agent/execution/service_obligation_ledger.py` *(new)* | Stable IDs, chains, observed completion and lifecycle | P0 |
| `agent/execution/workforce_capacity_forecast.py` *(new)* | Shadow hourly capacity, future staffing, binding constraints | P0 |
| `agent/strategy/cohort_planner.py` | Complete crop-service chain and engine timing; avoid false yield constants | P0 shadow / P3 authority |
| `agent/strategy/service_certificate.py` | Compare/reconcile existing aggregate certificate with new model; replace authoritative usage only when validated | P0 diagnostics / P3 |
| `agent/strategy/whole_farm_planner.py` | Engine-derived crop/livestock forecast and consistent service budget/economics | P0 shadow / P3 |
| `agent/execution/task_scheduler.py` | Expose tasks/mission outcomes; later integrate ownership and coordinator via existing emitter | P0 read-only / P1–P2 behavior |
| `agent/execution/sw_task_admission_controller.py` | Map protected services to operation IDs; integrate approved reservations, no coordinate-only completion | P1 / P3 |
| `agent/execution/workforce_coordinator.py` *(new)* | Joint regional staffing, assignment, mission transfers, deadline rescue | P1–P2 |
| `agent/strategy/resource_ledger.py` | Link dated labor and service holds to cash/feed/storage/market reservations | P0 observation / P3 authority |
| `agent/strategy/adaptive_acreage_planner.py` | Replace coarse labor/crop-only check with side-effect-free whole-farm trial | P3 |
| `agent/strategy/sw_tranche_controller.py` | Propose/commit split; land vs crop-cycle authorization; reservation IDs | P3 |
| `agent/strategy/macro_planner.py` | Materialize only committed cohorts; replant requires new authorization | P3 |
| `agent/main.py` | Reconcile previous outcomes, supply shadow inputs, gate coordinator, preserve action/market order | P0–P3 in isolated stages |
| `agent/config.py` | Explicit default-OFF experimental selectors; freeze existing policy flags | P0/P1 onwards |
| Tests under repository's established test layout | Per-component invariants, flag-off parity, real-engine integration, economic/terminal edge cases | Every phase |

Do not blindly edit all listed files in one commit. Each phase should touch the smallest justified set and record its resulting behavioral delta.

---

## 14. Test plan and hard edge cases

### Pure unit tests

- Identity does not merge FEED/CARE/HARVEST/FERTILIZER at same target.
- Obligation lifecycle: proposed, reserved, issued, completed, failed, expired, canceled; duplicate confirmation idempotent.
- Trial reservation has no side effects; atomic success/failure; rollback retains planted-crop maintenance.
- Actual observed worker count, day rollover, H0 hiring delay, unavailable carrier, transfer time.
- Worker cannot perform or own conflicting tasks on the same hour.
- Seed/feed/sales ledger counts each unit once; inventory-lot attribution documented.
- Deterministic matching and tie-breaking without optional libraries.
- Empty queue with near-future local demand, cross-region emergency recall, port staging.
- Replant after crop death/harvest requires distinct cycle authorization.
- Unfunded future hire and unsettled purchase excluded from guaranteed capacity.

### Real-engine integration and boundary tests

- Same-day PLANT→WATER and harvesting confirmed through state deltas.
- Multiple animals sharing region; shed-to-feed chain and distant held wheat.
- CARE versus COLLECT_FERTILIZER classification; held milk/wool/eggs saturation.
- Two consecutive unfed days and midnight escape behavior.
- Midnight worker inventory dump/storage rescue and overflow.
- Market ten-order shared arbitration cap and worker/market execution ordering.
- D29H21/H22/H23 boundary and real last executable sale.
- Day-boundary worker recreation/mission cleanup and obligation persistence.
- Eight-tile action-stream parity with instrumented and uninstrumented runner.
- SW 12–24 cap cases with correlated crop maturity peaks and core livestock deadlines.

### Regression and performance tests

- Repeat the existing full suite; do not lower its baseline pass count.
- Include a complete engine season and fixed regression replays.
- Check deterministic repeatability with fixed seed/opponent/seat/configuration.
- Measure per-turn latency, total simulation runtime, memory use and submission limits against the pinned baseline. Freeze acceptable performance bounds before candidate selection.
- Verify single-file/package import paths and runtime flags; do not ship a feature only exercised in the local modular path.

---

## 15. Phase artifacts and reviewer handoffs

Every phase ends with a stand-alone review package:

```text
reports/phase_sw_c2/
  p0_reference_manifest.md
  p0_diagnostic_integrity.md
  p0_forecast_calibration.md
  p1_mission_ownership.md
  p2_coordinated_dispatch.md
  p3_reservation_integrity.md
  p4_acreage_ladder.md
  p5_independent_confirmation.md
  release_decision.md

simulations/results/phase_sw_c2/
  manifests/
  reference/
  discovery/
  confirmation/
  hourly_traces/
  reconciliations/
```

Use repository naming conventions if they differ. Reports should contain: source SHA, exact config matrix, engine and runner hashes, seed/opponent/seat identities, test commands and results, paired statistical summaries, cash/inventory reconciliation, mechanism metrics, worst cells, known instrumentation limits, release-gate verdict, and next-phase decision.

**Review protocol:** At the end of P0, P1, P2, P3, P4 and P5, request an independent read-only audit before beginning the next phase. Any reviewer finding that changes measurement semantics or invalidates a control comparison triggers a corrected artifact and rerun, not a narrative reinterpretation of old data.

---

## 16. Change-control, rollback and stop conditions

- One conceptual change per commit/experimental treatment; pin parent SHA and store diff summary.
- Each behavior feature has a tested OFF path with reference parity.
- Do not promote solely on partial/selected opponents or seeds, a headline best run, local travel metrics, or unverified regional attribution.
- A cash shortfall or newly observed avoidable survival failure is a stop-and-diagnose event, not a reason to retune several policies simultaneously.
- If P0 telemetry changes gameplay, fix P0 first; all later comparisons are blocked.
- If P0 shadow predictions are persistently optimistic, keep the forecaster advisory and repair assumptions; do not let it reject/approve acreage.
- If P1 or P2 fails paired cash/safety gates, disable that treatment and preserve its traces for causal analysis.
- If P3 reservations create deadlocks or false feasibility, revert admission to the old default-OFF policy and retain existing planted-crop duties.
- If cap 12/16/20/24 yields negative whole-farm incremental contribution, retain the last independently validated cap or current best gated policy; do not force acreage.
- Only an explicitly approved promotion may update production flags and regenerate the single-file/submission package. Verify that the previous production zip checksum is unchanged unless promotion deliberately creates a separately named new artifact.

---

## 17. Immediate execution checklist — authorize P0 only

1. Create a new experimental branch off the verified SW-C1 HEAD; record SHA and working-tree state.
2. Produce immutable P0 baseline and engine terminal-timing reproduction.
3. Repair PLANT, HARD, CARE and attempted-versus-confirmed instrumentation without affecting action generation.
4. Establish exact cash and product conservation traces.
5. Create obligation types and a stable shared service ledger in shadow mode.
6. Build hourly workforce capacity forecast using actual observed positions, inventory, employment timing, deadlines, and service prerequisites.
7. Reconcile forecast versus confirmed real-engine outcomes; inspect false feasibility/false infeasibility and season-end assumptions.
8. Run all unit/integration/parity tests and report performance.
9. Commit P0 only and request independent read-only verification of artifacts, flags, action parity, and coverage.
10. **Do not implement P1/P2/P3/P4 in the same handoff or promotion.**

### Final implementation principle

**Commitments must be evaluated by the same resource and service model that execution uses, and their value must be measured in realized whole-farm final cash.** The target is not twenty-four authorized SW tiles; the target is an agent that can recognize and execute additional profitable agricultural commitments without damaging incumbent NW/NE or livestock production.
