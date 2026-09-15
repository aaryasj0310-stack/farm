# Point 2 — Feed/Herd Sustainability Implementation Plan

Baseline code commit:

`547357a91d22260435e961dedc24f292e846e713`

Frozen Phase-A baseline commit:

`484244083aea694af29459995546d120e7063194`

Authoritative architecture:

`architecture/point2_feed_herd_design.md`

Implementation must proceed in four independently reversible phases:

```text
Phase A — Shadow evaluator
        ↓
Phase B — DynamicHerdPlan authority
        ↓
Phase C — Live ArmC authority
        ↓
Phase D — Cleanup
```

Do not combine these into one large patch.

---

# 1. Architectural contract

Point 2 introduces one shared feed/cash feasibility model.

It answers:

> Can the current herd remain safe, and can one additional candidate animal be supported without spending resources already committed elsewhere?

It does NOT answer:

> Is the candidate economically profitable?

That remains the responsibility of:

`strategy/marginal_livestock_valuator.py`

The final candidate decision becomes:

```text
species / herd cap
        ↓
housing/serviceability
        ↓
feed + cash feasibility
        ↓
marginal livestock EV
        ↓
candidate accepted
        ↓
reserve candidate resources
        ↓
evaluate next candidate
```

The old scalar:

```text
projected_feed_supply
÷
remaining_feeding_days
=
sustainable_herd_size
```

may remain as telemetry during migration, but after Phase B it must no longer be the authoritative feed veto for `DynamicHerdPlan`.

The existing implementation currently feeds this scalar directly into `generate_dynamic_herd_plan(max_sustainable=...)`, and `herd_planner.py` reduces its target to `min(herd_cap, max_sustainable)`.

---

# 2. New authoritative module

## NEW FILE

`agent/strategy/feed_feasibility.py`

This should become the single owner of hard feed/cash feasibility.

Do not put the new model inside `macro_planner.py`, `herd_planner.py`, or `order_builder.py`.

The build system automatically copies new runtime strategy modules from `agent/strategy/` into `submission/strategy/`, so do not hand-maintain a separate submission implementation.

## Core data structures

Introduce lightweight dataclasses or equivalent immutable/cloneable structures.

### `TimedWheatDelivery`

Fields:

```text
day
units
source
```

Allowed v1 sources:

```text
physical_wheat_tile
market_purchase
```

Do not create delivery records from:

```text
planned wheat
empty soil
SW targets
seed intentions
future crop allocation
```

### `FeedExecutionSnapshot`

Fields should include at least:

```text
day
hour
turns_remaining_today

feeds_due_today
feeds_assigned_this_turn
wheat_pickups_assigned_this_turn

worker_wheat
shed_wheat

n_active_units

market_purchase_can_help_today
```

This is derived from the real task/assignment pipeline.

It is not a second scheduler.

### `FeedResourceLedger`

The ledger is the shared mutable shadow state used when sequential candidates are admitted.

Recommended fields:

```text
day
hour
operational_horizon_days

observed_cash

hard_cash_hold
existing_feed_cash_hold
strategic_cash_hold
candidate_feed_cash_hold

wheat_in_shed
wheat_on_workers

shed_other_units
shed_capacity

placed_herd
owned_unplaced_herd

secured_wheat_deliveries

scheduled_market_purchases
candidate_reservations

execution_snapshot

wheat_price_current
lifetime_price_policy
```

Cash must be represented as separate semantic holds rather than repeatedly subtracting unrelated values from anonymous `shadow_cash`.

Meaning:

```text
observed_cash
-
hard_cash_hold
-
existing_feed_cash_hold
-
strategic_cash_hold
-
accepted candidate purchase costs
-
candidate_feed_cash_hold
=
remaining candidate purchasing power
```

A cash hold is not an economic expense.

It is merely money that lower-priority decisions cannot spend.

### `FeedFeasibilityResult`

Return at least:

```text
feasible
existing_herd_feasible

candidate_species

near_term_feed_units
near_term_market_wheat_required

remaining_lifetime_feed_units
remaining_feed_cash_required

existing_feed_cash_hold
candidate_feed_cash_hold

minimum_wheat_slack
minimum_cash_slack

blocking_day
blocking_reason

scheduled_market_purchases

daily_timeline

price_policy
execution_confidence
```

For sequential planning, either also return:

```text
next_ledger
```

or expose an explicit:

```text
commit_candidate_reservation(...)
```

function.

Do not silently mutate the caller's ledger during a candidate test.

Candidate evaluation should work on a clone.

Only the selected candidate gets committed.

---

# 3. Functions to add to `feed_feasibility.py`

## `collect_secured_wheat_deliveries(...)`

Purpose:

Extract only physically secured wheat production.

Input:

```text
farm
current_day
operational_end_day
```

Use only live `WHEAT` plant tiles.

Use the same conservative physical timing currently used by `compute_unavoidable_feed_shortfall()`:

```text
harvest_day = placed_day + 4
```

and the existing conservative yield convention:

```text
4 units normally
6 if qualifying fertilizer state exists
```

The current survival shortfall implementation already uses this prefix-timed model.

Important:

Do NOT use `compute_authoritative_feed_capacity().planned_yield`.

That currently manufactures feed credit from expected future NW/SW planting and is exactly what the new hard-feasibility layer must avoid.

For v1, only physical harvests occurring inside the operational horizon reduce hard near-term requirements.

A physical crop harvesting after the 4-day horizon should not reduce the remaining-lifetime cash funding requirement yet.

When it moves into the 4-day window on a later observation, the ledger will naturally recognize it.

This deliberately sacrifices some aggressiveness in exchange for removing execution assumptions.

---

## `build_feed_execution_snapshot(...)`

Inputs:

```text
ctx
tasks
assignment
```

This summarizes actual scheduler output.

The task scheduler already creates:

* emergency FEED tasks;
* production-day FEED tasks;
* routine daily FEED tasks;
* wheat PICKUP staging tasks;
* increasing urgency late in the day.

It also documents that FEED consumes the worker's inventory rather than the shed.

The snapshot should count these facts rather than recreate routing.

Critical partial-day fact:

Unit actions execute before market actions.

Therefore wheat bought on the current turn cannot be used by an action that already executed that same turn. The existing runtime pipeline confirms task assignment occurs before market order construction.

At Hour 23:

```text
new market wheat
→ arrives after the day's final unit action
→ cannot rescue an unmet current-day feed deadline
```

This rule should fail closed.

---

## `build_feed_resource_ledger(...)`

Inputs should include:

```text
ctx
current_herd
hard_cash_hold
strategic_cash_hold=0
execution_snapshot=None
horizon_days=4
```

The caller supplies the relevant cash holds.

Do not let this helper rediscover land/hiring strategy.

It owns feed resources, not global treasury policy.

### Current-herd definitions

Track separately:

```text
placed_herd
owned_unplaced_herd
```

Placed herd:

Animals physically on farm tiles.

These create immediate operational feeding obligations.

Owned unplaced herd:

Animals already purchased and sitting in shed/worker inventories.

These do not need immediate FEED actions while unplaced, but they are already sunk commitments and therefore must be included conservatively in remaining-lifetime feed funding.

This avoids treating already-purchased animals as free future expansion.

---

## `evaluate_existing_herd_feasibility(...)`

First evaluate the existing herd with no candidate.

This must happen before any expansion check.

For each day inside the operational horizon:

```text
wheat available by deadline
>=
feed required by deadline
```

Use a prefix timeline.

A Day-12 harvest cannot repair a Day-11 deficit.

When physical wheat is insufficient, schedule the minimum required protected market purchase.

Every market purchase:

```text
decreases the same cash balance
occupies shed space when acquired
uses a protected market slot
must arrive before the relevant feed deadline
```

Do not recompute every future day's purchasing power from original cash.

If baseline existing-herd feasibility fails:

```text
existing_herd_feasible = False
candidate feasible = False
```

and provide a reason such as:

```text
insufficient_cash
shed_capacity
feed_deadline
late_hour_purchase
market_execution
```

The calling layers must still generate survival behavior.

Expansion failure must never suppress existing feeding.

---

## `evaluate_incremental_candidate(...)`

Inputs:

```text
ledger
candidate_species
purchase_cost
```

Process candidate on a copy of the current residual ledger.

Check:

```text
candidate purchase cash
4-day operational feed
remaining-lifetime feed funding
```

The candidate's future milk/wool/egg/fertilizer income contributes:

```text
ZERO
```

to this calculation.

Unrealized output of previously purchased animals also contributes:

```text
ZERO
```

to hard cash funding.

Candidate economics remain in `marginal_livestock_valuator`.

---

## `commit_candidate_reservation(...)`

After one candidate wins the economic selection:

```text
deduct/reserve purchase cash
reserve candidate's future feed cash
update shadow herd
record market-feed commitments
record candidate reservation
```

Then evaluate the next candidate using that residual ledger.

This is mandatory.

Never evaluate two candidate animals independently against the original wallet.

---

# 4. Pricing policy & lifetime WHEAT funding policy (`engine_stress_bound_v1`)

## Current executable market wheat

Use:

```python
market.price_math.estimate_wheat_buy_price(ctx)
```

for current executable market wheat inside the 4-day operational physical window.

This function correctly derives the live WHEAT price from parsed runtime context and applies `WHEAT_BUY_PRICE_BUFFER = 1.10`.

Remove all hard-coded `$25` calculations from the Point-2 path.

Do not alter `marginal_livestock_valuator`'s lifetime feed-cost calculation during Point 2. Its feed cost is economic opportunity cost, not admission financing.

## Lifetime WHEAT funding policy freeze: `engine_stress_bound_v1`

The Phase-A evaluator temporarily used `conditional_current_buffered_price` for lifetime funding telemetry. That was acceptable for Phase-A shadow diagnostics, but it must NOT become the authoritative Phase-B funding policy.

### Ground truth engine mechanics
```text
WHEAT base price = $25
MARKET_I0 = 10,000
scarcity shape = sqrt
T = 400
below_target = 0.80
WHEAT_BUY_PRICE_BUFFER = 1.10
```

Future lifetime feed funding beyond the 4-day operational physical window must use:

```text
engine_stress_bound_v1
```

This is a **conservative planning stress bound**, NOT a mathematically adversarial maximum. Do NOT describe it as a guaranteed maximum future market price.

### Policy definition

For remaining-lifetime feed funding, derive:

```text
stressed_wheat_inventory =
    current_observed_wheat_market_inventory
    - worst_case_remaining_town_wheat_drain
    - our_committed_future_market_feed_requirement
    - opponent_wheat_stress_allowance
```

Then evaluate:

```text
stress_raw_price =
    market_price("WHEAT", stressed_wheat_inventory)

stress_buffered_price =
    ceil(stress_raw_price * WHEAT_BUY_PRICE_BUFFER)

lifetime_wheat_price =
    max(
        current_executable_buffered_wheat_price,
        stress_buffered_price,
    )
```

where `current_executable_buffered_wheat_price = estimate_wheat_buy_price(ctx)`.

### 4A. Town WHEAT stress

Use actual engine mechanics:
* For shops already unlocked: use their actual identities and project their remaining WHEAT consumption.
* For shop instances not yet unlocked up to the engine maximum: assume every future shop instance consumes WHEAT (deliberately pessimistic).
* Also include the remaining town-center WHEAT drain over the remaining episode turns.
* The calculation must dynamically depend on the current day/hour and remaining season rather than using one global constant.
* Document that this is an engine-derived worst-case town-demand bound.

### 4B. Our own WHEAT stress

Use the future market WHEAT requirement of the full currently committed herd/resource ledger:
```text
existing-herd future market feed requirement
+
all previously accepted candidate reservations
+
the candidate currently being evaluated
```

Do NOT price each candidate independently against the original WHEAT market state.
After candidate #1 is accepted:
```text
candidate #1 increases our future WHEAT stress
→ recompute the stress price
→ candidate #2 is evaluated against that updated residual ledger
```
This is mandatory for sequential admission.

### 4C. Opponent WHEAT stress

Use a conservative but bounded v1 rule:
```text
observed_opponent_feed_liability =
    currently observed opponent placed animals
    × remaining applicable feed days
```
Then:
```text
opponent_wheat_stress_allowance =
    max(
        observed_opponent_feed_liability,
        our_committed_future_market_feed_requirement,
    )
```

Do NOT assume unlimited malicious opponent WHEAT buying.
Do NOT assume speculative future opponent livestock expansion.
The purpose is to model plausible competitive WHEAT pressure while keeping the bound operationally useful.

### 4D. Explicit classification & terminology

Document this exact distinction:
```text
engine_stress_bound_v1
= conservative planning stress bound
!= hard mathematical maximum
```
The true engine price can exceed it under sufficiently adversarial future market depletion.
Therefore:
* New observations must rebuild/reprice the ledger on every turn.
* Phase C must revalidate actual purchases before live `BUY_ANIMAL` execution.
* Do not call lifetime funding "guaranteed."
* Use terminology such as:
  ```text
  stress-funded
  conservatively funded under engine_stress_bound_v1
  ```

### 4E. Worked example: sequential repricing under stress bound

*(Note: The following numbers are illustrative to demonstrate sequential ledger progression; they are not engine-guaranteed outputs).*

For the engine WHEAT pricing parameters (base = 25, I0 = 10,000, T = 400, below_target = 0.80, below_func = "sqrt"):
```text
amp = below_target × base / sqrt(T) = 0.80 × 25 / sqrt(400) = 20 / 20 = 1.0
market_price("WHEAT", inventory) ≈ 25 + sqrt(10,000 - inventory) [for inventory < 10,000 before integer rounding]
```

```text
Assume at Day 10, Hour 0:
current_observed_wheat_market_inventory = 9,500
worst_case_remaining_town_wheat_drain = 1,200
our_committed_future_market_feed_requirement (existing herd) = 200
observed_opponent_feed_liability = 300
opponent_wheat_stress_allowance = max(300, 200) = 300

Baseline stress state before candidates:
stressed_inventory_0 = 9,500 - 1,200 - 200 - 300 = 7,800
raw price = 25 + sqrt(10,000 - 7,800) = 25 + sqrt(2,200) ≈ 71.90
stress_raw_price_0 ≈ $72 (engine integer quote)
stress_buffered_price_0 = ceil(72 × 1.10) = $80.00
lifetime_wheat_price_0 = max(current_executable_buffered_price, $80.00) = $80.00

Candidate #1 (COW):
- Needs 18 lifetime feed units beyond operational window.
- Evaluated at lifetime price $80.00 → feed hold = 18 × $80 = $1,440.00.
- Purchase cash and feed cash available → candidate #1 feasible.
- Candidate #1 accepted and committed:
  our_committed_future_market_feed_requirement rises from 200 to 218 (+18).
  opponent_wheat_stress_allowance = max(300, 218) = 300.

Candidate #2 (COW) evaluation:
- our_committed_future_market_feed_requirement is now 218.
- Candidate #2 would add another 18 units (total 236).
- stressed_inventory_1 = 9,500 - 1,200 - 236 - 300 = 7,764.
- raw price = 25 + sqrt(10,000 - 7,764) = 25 + sqrt(2,236) ≈ 72.29
- stress_raw_price_1 ≈ $72 (engine integer quote)
- stress_buffered_price_1 = ceil(72 × 1.10) = $80.00 (or higher if cumulative drain lowers inventory further).
- Candidate #2 is evaluated against the updated residual cash balance ($original - purchase_cost_1 - feed_hold_1) at the updated stress price ($80.00+).
- Sibling candidates never reuse original cash or ignore prior candidates' market impact.
```

---

# 5. Operational 4-day model

Use:

```text
FEED_WHEAT_BUFFER_DAYS = 4
```

as the default physical operational horizon.

Within these four days:

```text
current wheat
+
secured physical harvest arriving by deadline
+
executable protected market purchase
```

may cover feed.

The model should greedily purchase wheat only when a prefix deficit appears.

Example:

```text
Day 10: enough
Day 11: enough
Day 12: short by 4
```

Schedule the minimum 4-unit purchase before Day-12 feed.

Do not purchase the entire four-day requirement on Day 10 unless required.

This naturally reduces shed-capacity pressure.

---

# 6. Remaining-lifetime funding (`engine_stress_bound_v1`)

The candidate must also have its remaining feed obligation funded through the applicable feeding lifetime.

This is financial reservation, not physical wheat ownership.

Conceptually:

```text
remaining_units_after_operational_horizon
×
lifetime_wheat_price (derived via engine_stress_bound_v1)
=
remaining_feed_cash_required
```

That cash becomes unavailable to sibling candidates.

No future production revenue or unrealized animal revenue may finance it.

The physical-feed rules remain strictly preserved:
* 4-day operational physical horizon.
* Only physically existing WHEAT tiles provide secured production credit.
* Planned/unplanted WHEAT = zero hard physical credit.
* Candidate future product revenue = zero hard-funding credit.
* Unrealized existing-animal revenue = zero hard-funding credit.
* Unowned/empty SW = zero hard-feed credit.

The new `engine_stress_bound_v1` policy changes only the financial funding price beyond the operational physical window.

---

# 7. Current source logic to preserve temporarily

`compute_authoritative_feed_capacity()` remains during Phases A–C.

Do not remove it immediately.

It should continue generating:

```text
projected_wheat_supply
feeding_days_left
sustainable_herd_size
wheat_on_hand
planted_yield
planned_yield
affordable_wheat
```

for comparison telemetry.

The current function contains the known:

```text
affordable_wheat = min(100, ...)
```

and season-wide scalar calculation.

After Phase B it is telemetry only for ArmC expansion.

---

# 8. File-by-file change map

## `agent/config.py`

### Phase A

Add:

```text
POINT2_FEED_MODE
```

Allowed values:

```text
off
shadow
herd_plan
live
```

Initial default:

```text
shadow
```

Also add:

```text
FEED_OPERATIONAL_HORIZON_DAYS
```

Default it to existing:

```text
FEED_WHEAT_BUFFER_DAYS
```

Add runtime getter:

```text
get_point2_feed_mode()
```

Prefer getter usage rather than importing a stale global into many modules, because tests already switch runtime experiment settings.

### Eventually

After Phase D stabilization:

```text
POINT2_FEED_MODE = "live"
```

may become production default.

Do not modify any livestock cutoff or selective-purchase constants.

---

## `agent/strategy/macro_planner.py`

This is the largest integration file.

### Existing functions involved

```text
compute_authoritative_feed_capacity()
compute_unavoidable_feed_shortfall()
detect_wheat_deficit()
MacroPlanner.build()
```

### Phase A

Keep all current behavior.

Inside `MacroPlanner.build()`:

1. Continue computing old `feed_info` exactly as today.
2. Build a new shadow `FeedResourceLedger`.
3. Evaluate existing-herd feasibility.
4. Optionally evaluate `COW +1` / `SHEEP +1` / `GOOSE +1` only for diagnostic comparison.
5. Store results under:

```text
plan.diagnostics["point2_feed_shadow"]
```

Example contents:

```text
mode
existing_herd_feasible
old_sustainable_herd_size
shadow_candidate_feasibility
existing_feed_cash_hold
near_term_market_wheat_required
price_policy
scalar_disagreement
```

Do not alter:

```text
buy_animal
buy_wheat
build_queue
target_pastures
buy_land
buy_seed
```

in Phase A.

### Phase B

Before calling `generate_dynamic_herd_plan()`:

construct the planning ledger using the existing `cash_for_animals` budget.

That budget already protects the current strategic cash terms such as future hires/base reserve/land and seed holds.

Pass the ledger into `generate_dynamic_herd_plan()`.

Stop passing `sustainable` as the active feed authority when:

```text
POINT2_FEED_MODE >= herd_plan
```

but retain it as telemetry.

Update:

```text
requested_herd_size
final_feed_capped_herd_size
```

diagnostics.

Do not delete old field names immediately. Add explicit new fields:

```text
legacy_sustainable_herd_size
feed_feasible_herd_size
feed_authority = "ledger"
```

### Phase C

Modify the live ArmC candidate loop.

Current live candidate admission uses:

```text
$25 × 4-day feed reserve
```

before marginal valuation.

Replace that candidate affordability authority with:

```text
evaluate_incremental_candidate(shared_live_ledger, species)
```

For every economically evaluated species:

```text
candidate economic EV
+
candidate feed feasibility
```

must both exist in `cands_eval`.

Only feed-feasible candidates enter final species selection.

When candidate accepted:

```text
commit_candidate_reservation(...)
```

must mutate the shared shadow ledger.

Do not separately decrement an independent `shadow_cash` for feed after the ledger becomes authoritative.

Either eliminate `shadow_cash` from the Point-2 live path or make it a diagnostic mirror of ledger cash.

Add:

```text
buy_animal_sequence
```

to `plan.intents`.

Example:

```text
["SHEEP", "COW", "SHEEP"]
```

This preserves the actual ArmC sequential admission order.

The current `buy_animal` dictionary remains for engine-compatible quantity intents.

### Feed buying in Phase C

Replace fixed-$25 affordability calculations in the authoritative Macro feed-purchase path with:

```text
estimate_wheat_buy_price(ctx)
```

This includes:

```text
survival_floor
max affordable wheat calculation
wheat_feed_cost
```

The current late Macro budget block still uses fixed `$25` even though Point 1's market layer has a live buffered estimator.

Keep:

```text
protected_feed_wheat
optional_feed_wheat
```

semantics unchanged.

### Existing feed cash hold

Expose:

```text
existing_feed_cash_hold_remaining
```

in `plan.intents`.

This must mean:

> feed cash reserved for the existing owned herd that is not already being spent on this turn's protected wheat purchase.

This distinction prevents double counting.

---

## `agent/strategy/herd_planner.py`

### Existing classes/functions

```text
DynamicHerdPlan
generate_dynamic_herd_plan()
get_forward_housing_demand()
```

### Phase B changes

Add optional input:

```text
feed_ledger=None
```

Keep:

```text
max_sustainable=None
```

temporarily for backward compatibility and telemetry.

Current code does:

```text
target_cap = min(herd_cap, max_sustainable)
```

before evaluating candidates.

Under `herd_plan` or `live` mode:

replace active feed cap with:

```text
target_cap = herd_cap
```

subject to species caps.

At each loop iteration:

1. Build marginal EVs as today.
2. For each candidate species under cap, clone current feed ledger.
3. Run incremental feed/cash feasibility.
4. Remove infeasible candidates from economic selection.
5. Run existing guarded candidate selection over remaining feasible candidates.
6. Apply existing housing economic hurdle.
7. Commit selected candidate to:

   * `shadow_herd`
   * shared feed ledger.
8. Repeat.

Add feed fields to each `decision_records` element:

```text
feed_feasible
feed_blocking_reason
near_term_market_wheat
candidate_feed_cash_hold
minimum_cash_slack
minimum_wheat_slack
```

If no species is feed-feasible:

```text
STOP reason = "feed_feasibility"
```

Do not continue trying to manufacture feed through larger target plans.

### Must remain unchanged

The current early return at:

```text
day >= C4_LIVESTOCK_CUTOFF_DAY
```

for new forward housing remains unchanged.

Point 2 does not authorize speculative post-cutoff infrastructure.

---

## `agent/strategy/marginal_livestock_valuator.py`

### No behavioral Point-2 change

Keep:

```text
estimate_realized_marginal_animal_value()
select_guarded_livestock_candidate()
```

as the profitability layer.

Its lifetime feed expense remains an EV cost.

Do not:

* pass candidate-generated revenue into feed feasibility;
* remove feed cost from EV merely because cash was reserved;
* add feed reserve to EV again.

These are different concepts:

```text
feasibility feed cost → funding requirement
EV feed cost → economic opportunity cost
```

No Phase A–C code modification should be necessary here.

---

## `agent/strategy/pasture_planner.py`

### No initial behavioral change

Current pasture candidate economics should remain.

It generates candidate structural capacity, while `DynamicHerdPlan` ultimately determines actual forward housing demand.

Regression-test it in Phase B to ensure a feed-rejected herd candidate does not indirectly create extra housing demand.

Do not put feed feasibility into `evaluate_pasture_candidates()`.

That would create a second feed authority.

---

## `agent/strategy/animal_planner.py`

This file still contains:

```text
max_sustainable
```

plus a separate 3-day `$25` feed reserve.

Do not rewrite it during Phases A–C.

Production currently uses ArmC, while this remains relevant to legacy/experimental target-oriented arms.

Phase D must decide:

```text
retain as legacy ArmA/ArmB model
```

or:

```text
migrate those experiment arms separately
```

Do not delete it merely because ArmC no longer uses its feed model.

---

## `agent/strategy/expansion_planner.py`

### Phase A/B

No change.

### Phase C

Add a new optional argument to `should_buy_land()`:

```text
feed_funding_reserve=0.0
```

Do not overload `feed_cost`.

Why:

`feed_cost` currently represents unavoidable feed expenditure inside the treasury requirement.

A future feed cash hold is a reservation, not a second economic expense.

Land treasury should calculate:

```text
mandatory current feed spend
+
remaining existing-herd feed funding reserve
```

exactly once.

Expose both separately in land diagnostics:

```text
current_feed_spend
feed_funding_reserve
```

This ensures land cannot consume money required to keep currently owned animals funded.

Candidate feed reserves should NOT block land before the candidate is purchased, because the current priority architecture ranks land ahead of discretionary animals.

---

## `agent/market/order_builder.py`

### Existing functions

```text
reinvest_livestock()
build_intraday()
build()
```

Point 1 already provides:

```text
protected feed > land > optional feed > seeds > animals
```

and live buffered wheat pricing.

Preserve that ordering.

### Phase A/B

No behavioral change.

### Phase C

Add optional parameter:

```text
execution_snapshot=None
```

to:

```text
build()
build_intraday()
reinvest_livestock()
```

Existing callers remain compatible.

Read from intents:

```text
existing_feed_cash_hold_remaining
buy_animal_sequence
```

Before calculating discretionary land/optional/seed/animal budget:

reserve:

```text
existing_feed_cash_hold_remaining
```

after accounting for this turn's actual protected wheat purchase.

Do NOT put this hold into:

```text
spent_estimate
```

because it is not actually spent this turn.

Add ledger diagnostics:

```text
existing_feed_cash_hold
candidate_feed_cash_hold
feed_cash_hold_total
feed_revalidation
```

### Animal tier

Do not loop only over:

```text
sorted(buy_animal.items())
```

when `buy_animal_sequence` exists.

Use exact sequential ArmC order.

Fallback for legacy callers:

expand the current `buy_animal` dict deterministically.

For every candidate unit:

1. Start from remaining discretionary cash after higher-priority tiers.
2. Run the shared live evaluator.
3. Include current `execution_snapshot`.
4. If infeasible, drop with explicit reason:

   ```text
   feed_infeasible
   insufficient_lifetime_feed_funding
   current_feed_execution_risk
   shed_capacity
   ```
5. If feasible:

   * queue the animal engine order;
   * commit candidate feed reservation to local residual ledger;
   * proceed to next candidate.

Sibling animals therefore cannot reuse the same feed reserve.

### Post-Day12 rule

Keep the existing `reinvest_livestock()` physical-empty-housing logic intact.

The feed evaluator is an additional requirement.

It must never replace that gate.

---

## `agent/strategy/central_planner.py`

### No Point-2 authority

Do not run feed feasibility here.

CentralPlanner should remain global market arbitration.

Point 1 already gives protected and optional wheat explicit semantic identity, with protected wheat escalating to P0/P1 under feed danger and optional wheat staying P2.

### Phase A–C

Prefer no behavioral changes.

Only add diagnostic assertions if needed.

The correct data flow is:

```text
FeedFeasibility
        ↓
Macro intents
        ↓
OrderBuilder resource enforcement
        ↓
CentralPlanner priority arbitration
```

not:

```text
CentralPlanner
→ attempt to infer herd feasibility
```

---

## `agent/execution/task_scheduler.py`

### No scheduling redesign

Do not add a feed simulator.

Existing task creation remains authoritative for actual:

```text
FEED
PICKUP WHEAT
worker assignment
survival urgency
```

The current code already stages worker-carried wheat because FEED consumes worker inventory rather than shed inventory.

Phase A only needs to expose existing `tasks` and `assignment` to the snapshot builder from `main.py`.

No runtime scheduling behavior should change.

---

## `agent/main.py`

### Phase A

After:

```text
tasks = build_tasks(ctx, plan)
assignment = assign_tasks(tasks, ctx)
```

construct:

```text
FeedExecutionSnapshot
```

for diagnostics.

Add the Point-2 diagnostics to:

```text
_LAST_TURN_TELEMETRY
```

Suggested fields:

```text
feed_feasibility_shadow
feed_execution_snapshot
```

Phase A action output must remain identical.

### Phase C

Pass the snapshot explicitly to:

```text
builder.build(...)
builder.build_intraday(...)
```

for final live revalidation.

This is preferable to putting scheduler objects inside `MacroPlan.intents`.

The current runtime already computes assignment before purchase orders, making `main.py` the natural bridge.

---

## `market/price_math.py`

No architectural modification required.

Reuse:

```text
estimate_wheat_buy_price(ctx)
```

Do not create another wheat-price helper.

---

## `scripts/build_submission.py`

No change required.

After every phase:

```text
python scripts/build_submission.py
```

will mirror runtime modules into `submission/` and rebuild/validate the ZIP.

Do not manually implement Point 2 twice.

---

# 9. PHASE A — Shadow evaluator

## Files

Create:

```text
agent/strategy/feed_feasibility.py
agent/tests/test_feed_feasibility.py
```

Modify:

```text
agent/config.py
agent/strategy/macro_planner.py
agent/main.py
```

Possibly extend:

```text
agent/tests/test_wheat_sustainability_gate.py
agent/tests/test_macro_planner.py
agent/tests/test_pipeline_integration.py
agent/tests/test_engine_executability.py
```

The existing repository already has these relevant test suites.

## Exact change sequence

1. Add rollout mode/config.
2. Implement data structures.
3. Implement physical wheat extraction.
4. Implement resource-ledger constructor.
5. Implement existing-herd feasibility.
6. Implement incremental candidate feasibility.
7. Implement sequential reservation.
8. Add Macro shadow invocation.
9. Add execution snapshot after scheduler assignment.
10. Add telemetry.
11. Add tests.
12. Sync/build submission.

## Data flow

```text
observation
   ↓
existing MacroPlanner
   ├── old sustainable scalar → LIVE decisions unchanged
   │
   └── new FeedFeasibility → diagnostics only

task scheduler
   ↓
actual tasks/assignment
   ↓
FeedExecutionSnapshot
   ↓
telemetry only
```

## Failure modes to test

* zero cash;
* zero wheat;
* no animals;
* full shed;
* harvest after feed deadline;
* harvest inside operational horizon;
* high wheat price;
* Hour-23 shortage;
* two candidate double spend;
* speculative SW/planned wheat accidentally credited;
* candidate revenue accidentally counted.

## Phase A acceptance criteria

Mandatory:

```text
POINT2_FEED_MODE="off"
and
POINT2_FEED_MODE="shadow"
```

produce identical:

```text
Macro intents
build_queue
plant_queue
buy_animal
buy_wheat
final engine actions
market orders
```

for the same deterministic observations.

Only diagnostics may differ.

Old `sustainable_herd_size` remains authoritative.

Run a full 720-step deterministic season and verify:

```text
shadow mode decisions == baseline decisions
0 engine errors
market orders <= 10
```

## Rollback boundary

One isolated Phase-A commit.

Emergency rollback:

```text
POINT2_FEED_MODE = "off"
```

No source reversion should be required.

---

# 10. PHASE B — DynamicHerdPlan integration

## Files

Modify:

```text
agent/strategy/herd_planner.py
agent/strategy/macro_planner.py
agent/config.py
```

Tests:

```text
agent/tests/test_feed_feasibility.py
agent/tests/test_shop_conditioned_livestock.py
agent/tests/test_macro_planner.py
agent/tests/test_pasture_planner.py
```

## Exact change sequence

1. Pass planning feed ledger (`FeedResourceLedger`) from MacroPlanner into DynamicHerdPlan.
2. Preserve `max_sustainable` parameter for compatibility and comparison telemetry.
3. When `POINT2_FEED_MODE == "herd_plan"` or stronger:
   The old `target_cap = min(herd_cap, max_sustainable)` must no longer be the authoritative feed limit.
   Instead:
   `herd_cap / species caps → evaluate feed feasibility → evaluate economic EV → select candidate → commit candidate reservation → reprice / re-evaluate next candidate`.
4. `max_sustainable` remains telemetry only. Do NOT remove the old scalar yet.
5. Evaluate candidate feed feasibility inside each shadow iteration against the mutable residual ledger.
6. Select economics only among feasible species using `marginal_livestock_valuator`.
7. Commit winner's feed/cash reservation via `commit_candidate_reservation(...)`.
8. Reprice and re-evaluate subsequent candidates under `engine_stress_bound_v1`.
9. Add decision diagnostics.
10. Feed resulting desired herd into existing housing-demand path.
11. Keep live ArmC purchasing completely unchanged (Phase C remains the point where live `BUY_ANIMAL` becomes ledger-authoritative).
12. Do NOT change actual `BUY_ANIMAL` execution in Phase B.

## Execution-confidence policy in Phase B
In Phase B:
* `execution_confidence` is diagnostic/provisional information.
* It is NOT an independent veto by itself.
* A candidate must still be rejected for concrete hard failures such as:
  ```text
  existing_herd_feasible = False
  insufficient_cash
  shed_capacity
  feed_deadline failure
  late_hour_purchase
  other explicit hard feed/resource failure
  ```
* But `execution_confidence = "guarded"` or `execution_confidence = "conditional"` alone must NOT reject a Phase-B forward-planning candidate.
* If:
  ```text
  feed feasibility passes
  +
  candidate economics passes
  ```
  then Phase B may provisionally include the candidate in `DynamicHerdPlan` and record:
  ```text
  execution_status = "provisional_guarded"
  ```
* Reason: Phase B plans infrastructure and forward herd shape. It does NOT authorize the final engine `BUY_ANIMAL`.

## New data flow

```text
Macro observed resources
      ↓
planning FeedResourceLedger
      ↓
DynamicHerdPlan
      ↓
candidate COW/SHEEP/GOOSE
      ├── FeedFeasibility
      └── Marginal EV
      ↓
sequential accepted shadow herd
      ↓
forward housing demand
```

## Failure modes

* candidate profitable but feed-infeasible;
* candidate feed-feasible but economically negative;
* candidate #1 consumes resources candidate #2 needs;
* scalar says 5 but ledger safely supports >5;
* scalar says high but timed feed makes candidate unsafe;
* feed-rejected candidate accidentally creates housing demand;
* Day12+ creates new forward pasture.

## Required regression

Reproduce the original capital-insensitivity case.

For example:

```text
Day 10
0 wheat
0 physical wheat crop
$10k vs $100k
```

Old telemetry may still show:

```text
sustainable = 5
sustainable = 5
```

but new DynamicHerdPlan must no longer be stopped at five solely because of that scalar.

Actual final herd still depends on:

```text
caps
housing
feed funding
economic EV
```

Do not assert that $100k must always buy more animals; assert that the old `100-wheat` ceiling is no longer the reason it cannot.

## Acceptance criteria

* old scalar remains visible in telemetry;
* it no longer vetoes ArmC forward candidates;
* all accepted DHP candidates are individually feed-feasible;
* shared ledger prevents resource reuse;
* profitability still comes from marginal valuator;
* Day12 forward housing cutoff unchanged;
* live BUY_ANIMAL behavior remains baseline-equivalent because Phase C is not active.

## Rollback

Set:

```text
POINT2_FEED_MODE = "shadow"
```

and old DHP behavior returns.

---

# 11. PHASE C — Live ArmC integration

This is the first phase that changes actual animal purchasing.

## Files

Modify:

```text
agent/strategy/macro_planner.py
agent/market/order_builder.py
agent/strategy/expansion_planner.py
agent/main.py
agent/config.py
```

Likely no behavioral modifications:

```text
agent/strategy/central_planner.py
agent/strategy/marginal_livestock_valuator.py
agent/execution/task_scheduler.py
```

Tests:

```text
test_feed_feasibility.py
test_order_builder.py
test_cross_layer_consistency.py
test_housing_safe_reinvestment.py
test_livestock_reinvestment.py
test_land_purchase_affordability.py
test_pipeline_integration.py
test_engine_executability.py
test_feed_zoning.py
```

## Exact change sequence

1. Replace live ArmC `$25 × four-day` candidate gate with shared evaluator.
2. Keep candidate EV selection.
3. Commit feed reservations sequentially.
4. Emit `buy_animal_sequence`.
5. Compute authoritative existing-herd future feed cash hold.
6. Feed that hold into land/seed/discretionary budgeting.
7. Replace authoritative fixed-$25 Macro wheat affordability with live buffered price.
8. Pass execution snapshot from `main.py` to OrderBuilder.
9. Reserve existing feed funding before discretionary tiers in OrderBuilder.
10. Revalidate every actual animal unit at animal tier.
11. Preserve explicit protected/optional wheat semantics.
12. Preserve post-Day12 physical housing gate.
13. Keep old scalar telemetry only.

## Live data flow

```text
Observation
    ↓
MacroPlanner
    ↓
existing herd feed protection
    ↓
provisional sequential ArmC candidates
    ↓
tasks / worker assignment
    ↓
FeedExecutionSnapshot
    ↓
OrderBuilder
    ↓
hires
    ↓
protected feed
    ↓
land
    ↓
optional wheat
    ↓
seeds
    ↓
FINAL candidate-by-candidate feed revalidation
    ↓
animal orders
    ↓
CentralPlanner
```

This preserves current market priority.

## Important treasury rule

Existing-herd feed reserve:

```text
must outrank
land
optional feed
seeds
animals
```

Candidate feed reserve:

```text
must constrain
candidate + sibling candidate purchases
```

but it should not retroactively outrank land if land already has higher strategic tier.

This preserves current intended ordering rather than silently redesigning capital priorities.

## Phase C Live Execution-Confidence Policy (Fail-Closed)

Phase C must fail closed when current-day existing-herd feed execution remains unresolved.

**Frozen rule:**
```text
IF unfed_placed_today > 0:

    IF execution_snapshot is absent
    OR execution_confidence != "high":

        reject new BUY_ANIMAL
```

Use an explicit rejection reason such as:
```text
feed_execution_unverified
```
or:
```text
feed_execution_not_verified
```

Existing-herd survival actions must continue normally:
* Do NOT suppress protected wheat purchases or FEED recovery merely because livestock expansion is blocked.

If:
```text
unfed_placed_today == 0
```
then guarded/conditional execution confidence alone does NOT need to veto a new animal:
* The new animal is still treated as an unplaced commitment and does not create a current-day physical FEED obligation.
* All other gates must still pass:
  * feed/cash feasibility
  * housing/serviceability
  * marginal economic value
  * market order capacity
  * actual purchase cash
  * post-Day12 physical-pasture invariant

### Worked execution example: Phase B vs Phase C

```text
Phase B (DynamicHerdPlan):
guarded execution confidence
+ feed feasible
+ EV positive
→ provisional housing candidate allowed (execution_status = "provisional_guarded")

Phase C (OrderBuilder live BUY_ANIMAL):
existing animals still unfed today (unfed_placed_today > 0)
+ guarded confidence (execution_confidence != "high")
→ BUY_ANIMAL rejected (reason = "feed_execution_unverified")
```

## Failure modes

* Macro approves candidate, but land/seed spending makes it infeasible;
* live revalidation fails to reject it;
* existing feed funding spent by land;
* current protected wheat cost counted twice;
* candidate feed hold counted as actual spending;
* animal sequence lost by dictionary sorting;
* two sibling animals reuse same reserve;
* optional wheat consumes protected existing feed funding;
* market order cap removes protected wheat;
* Hour-23 market wheat assumed usable before it actually is;
* late animal authorized using queued pasture.

## Acceptance criteria

Every final `BUY_ANIMAL` must satisfy:

```text
physical housing rule
AND
feed/cash feasibility
AND
economic threshold
AND
order/cash feasibility
```

Existing feed protection must survive through final market order construction.

The following invariant must remain exactly true:

> After the normal Day-12 livestock cutoff, a new animal may be purchased only if a physically built, currently empty, compatible, unreserved pasture already exists for it.

Queued or planned housing remains zero credit.

Run:

```text
targeted Point-2 tests
full agent tests
720-step live engine season
submission package validation
```

## Rollback

Set:

```text
POINT2_FEED_MODE = "herd_plan"
```

DynamicHerdPlan remains improved, but old live purchase authority returns.

Keep old live gate code behind the mode switch until Phase D.

---

# 12. PHASE D — Cleanup

Do this only after Phase C has passed regression and replay analysis.

## `macro_planner.py`

Retire from authoritative ArmC use:

```text
min(100, affordable_wheat)
sustainable scalar candidate veto
season-long projected_feed_supply expansion gate
planned_yield feed authorization
fixed-$25 live candidate reserve
duplicate fixed-$25 wheat affordability
legacy placed+2 feed-risk harvest shortcut
```

Keep any useful old values under clearly named:

```text
legacy_*
```

diagnostics if useful for replay comparison.

The old feed-risk code currently uses a separate `placed_day + 2` approximation while the survival shortfall function uses conservative `placed_day + 4`; once the new timeline is authoritative, remove that conflicting source of feed safety truth.

## `herd_planner.py`

After all callers migrate:

remove `max_sustainable` as an authoritative argument.

It may be removed completely once no compatibility tests/callers need it.

## `animal_planner.py`

Do NOT blindly delete the old three-day `$25` model.

Either:

```text
retain as explicit ArmA/ArmB legacy behavior
```

or migrate those experiment arms in a separate task.

Point 2 production ArmC does not require destroying experimental baselines.

## `central_planner.py`

Do not remove Point-1 protected/optional compatibility behavior merely because Point 2 is complete.

Only remove genuinely unreachable compatibility code after caller search/tests prove it dead.

## Config

Once stable:

```text
POINT2_FEED_MODE = "live"
```

becomes default.

The `off`/`shadow` path may remain for experiments if runtime cost is negligible.

## Acceptance

Only Phase D may delete old safety code.

Before deletion:

```text
Phase C live mode
must already pass without depending on it.
```

## Rollback

Tag/retain the final Phase-C commit.

That commit is the rollback target if cleanup exposes regression.

---

# 13. Required Point-2 regression matrix

At minimum cover these scenarios.

### Resource monotonicity

```text
more usable cash must not reduce feasibility
more usable wheat must not reduce feasibility
higher wheat price must not increase feasibility
earlier secured harvest must not be worse than later secured harvest
```

### Timing

```text
wheat arriving after deadline cannot rescue earlier feed
Hour-23 purchase cannot rescue current-day unmet feed
4-day physical pass cannot authorize unfunded lifetime obligation
```

### Resource ownership

```text
unowned SW gives zero feed credit
empty SW soil gives zero credit
planned wheat gives zero credit
future seed purchases give zero credit
candidate revenue gives zero funding credit
unrealized existing-animal revenue gives zero funding credit
```

### Sequential accounting

```text
candidate #1 reserves resources
candidate #2 sees residual ledger
same wheat cannot serve both candidates
same cash cannot fund both candidates
```

### Economics separation

```text
feed-feasible + negative EV → reject
positive EV + feed-infeasible → reject
positive EV + feed-feasible → eligible
```

### Existing herd safety

```text
baseline infeasible → no expansion
baseline infeasible → survival actions still generated
protected wheat remains ahead of discretionary spending
```

### Physical execution

```text
shed full can block near-term purchase
feed consumption may free future capacity
future freed capacity cannot retroactively enable earlier purchase
market slot needed before deadline
```

### Housing

Mandatory regression:

```text
Day 12–14
planned pasture exists
physical empty pasture does NOT exist
→ BUY_ANIMAL must be rejected
```

and:

```text
physical compatible empty unreserved pasture exists
+ all other gates pass
→ late candidate may proceed
```

---

# 14. Resolution and Freeze of Architecture Ambiguities 1 & 2

The two architecture ambiguities intentionally left open during Phase A are now definitively resolved and frozen.

## Ambiguity 1 Resolution: Frozen Lifetime WHEAT Funding Policy (`engine_stress_bound_v1`)

The question of whether lifetime feed funding is guaranteed or bounded is resolved as follows:

1. **Policy Name**: `engine_stress_bound_v1`.
2. **Classification**: `engine_stress_bound_v1` is an engine-derived **conservative planning stress bound**, NOT a mathematically adversarial maximum or an absolute guarantee.
3. **Engine Mechanics Basis**:
   ```text
   WHEAT base price = $25
   MARKET_I0 = 10,000
   scarcity shape = sqrt
   T = 400
   below_target = 0.80
   WHEAT_BUY_PRICE_BUFFER = 1.10
   ```
4. **Formula**:
   ```text
   stressed_wheat_inventory =
       current_observed_wheat_market_inventory
       - worst_case_remaining_town_wheat_drain
       - our_committed_future_market_feed_requirement
       - opponent_wheat_stress_allowance

   stress_raw_price = market_price("WHEAT", stressed_wheat_inventory)
   stress_buffered_price = ceil(stress_raw_price * WHEAT_BUY_PRICE_BUFFER)
   lifetime_wheat_price = max(estimate_wheat_buy_price(ctx), stress_buffered_price)
   ```
5. **Town Drain**: Unlocked shops project remaining consumption; locked future shops assume WHEAT; town center drain included over remaining turns.
6. **Our Stress**: Full committed requirement (existing herd + committed candidates + prospective candidate). Repriced sequentially per candidate.
7. **Opponent Allowance**: `max(observed_opponent_feed_liability, our_committed_future_market_feed_requirement)`.
8. **Terminology**: Animals funded under this policy are described as **"stress-funded"** or **"conservatively funded under engine_stress_bound_v1"** (never "guaranteed"). Every new observation rebuilds/reprices the ledger.

---

## Ambiguity 2 Resolution: Frozen Execution-Confidence Policy

The question of how execution confidence interacts with forward planning and live purchasing is resolved as follows:

### Phase B — DynamicHerdPlan (Forward Planning)
* `execution_confidence` is diagnostic and provisional.
* It is NOT an independent veto by itself.
* Candidates with hard feed/cash/shed failures are rejected.
* But `execution_confidence = "guarded"` or `"conditional"` alone does NOT reject a Phase-B candidate.
* If feed feasibility and candidate EV pass, Phase B provisionally includes the candidate with `execution_status = "provisional_guarded"`.
* Reason: Phase B plans infrastructure and forward herd shape; it does NOT emit engine `BUY_ANIMAL` orders.

### Phase C — Live ArmC Execution (OrderBuilder)
* Phase C fails closed when current-day existing-herd feed execution is unresolved:
  ```text
  IF unfed_placed_today > 0:
      IF execution_snapshot is absent OR execution_confidence != "high":
          reject new BUY_ANIMAL (reason: "feed_execution_unverified")
  ```
* Existing-herd survival actions (protected wheat purchases, feed deliveries) proceed uninhibited.
* If `unfed_placed_today == 0`: guarded/conditional execution confidence alone does NOT veto new unplaced animal purchases, provided all other constraints pass (feed feasibility, housing, EV, cash, post-Day12 physical pasture invariant).

---

# 15. Deliberate conservative decisions that are NOT ambiguities

The following should be fixed rules in v1:

```text
candidate future revenue = zero hard-funding credit

unrealized existing-animal revenue = zero credit

hypothetical SW production = zero credit

unplanted planned wheat = zero credit

physical wheat outside the 4-day operational window
= no immediate physical-feed credit

new candidate is evaluated conservatively for feed
rather than assuming future profits will rescue it
```

Do not ask the coding model to optimize these away.

---

# 16. Commit boundaries

Recommended commit sequence:

```text
P2-A
feat(feed): add shadow feed resource ledger and feasibility telemetry

P2-B
feat(herd): make dynamic herd planning feed-ledger aware

P2-C
feat(livestock): enforce feed ledger on live ArmC purchases

P2-D
refactor(feed): retire obsolete scalar ArmC feed gates
```

Each commit must independently pass its targeted tests.

Do not squash these until the architecture has been replay-validated.

---

# 17. What Codex should implement first

Codex should receive:

```text
architecture/point2_feed_herd_design.md
architecture/point2_feed_herd_implementation_plan.md
```

and initially be told:

> Implement Phase A only. Do not implement Phase B, C, or D. Do not alter live decisions.

Phase A is successful only when the new model can be observed and tested while producing the same decisions as `547357a`.

After Phase A is committed, audit that commit before allowing Phase B.

---

# Final authority map

After Point 2 is complete:

```text
FeedFeasibility
    = physical feed + cash funding authority

engine_stress_bound_v1
    = lifetime funding stress-price policy

MarginalLivestockValuator
    = candidate profitability authority

DynamicHerdPlan
    = sequential provisional herd/infrastructure planner

TaskScheduler
    = physical worker execution authority

OrderBuilder / Phase-C live revalidation
    = final purchase enforcement

Observation
    = next-turn truth
```

No layer should duplicate another layer's responsibility.

Most importantly:

```text
larger herd target
must NEVER create
the feed resources used to justify that larger herd target.
```
