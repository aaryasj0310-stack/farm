# Point 2 — Phase C2B Architecture

## Status

```text
Phase A     FROZEN
Phase B     FROZEN
Phase C1    FROZEN
Phase C2A   FROZEN

Phase C2B   READY TO IMPLEMENT
```

Base commit:

`22c04d816f725f724e2c94fa0305f2dd22b58f1a`

Phase C2B activates the **sequential live livestock-admission authority inside OrderBuilder**.

C2B does **not** implement final CentralPlanner dependency preservation. That remains C2C.

Default production mode must remain:

```python
POINT2_FEED_MODE = "shadow"
```

Do not switch production to `live` until C2C is complete and audited.

---

# 1. C2B Goal

Replace the legacy live animal-purchase path in:

```text
POINT2_FEED_MODE == "live"
```

with:

```text
ordered Macro candidate sequence
        ↓
verified existing-herd execution state
        ↓
fresh post-unit live FeedResourceLedger
        ↓
higher-priority committed spending/resources
        ↓
candidate 1 transactional evaluation
        ↓
commit only if all gates pass
        ↓
candidate 2 sees residual resources
        ↓
...
        ↓
final accepted animal orders
```

The central invariant is:

> A new animal may execute only if it remains safe after all higher-priority commitments and all previously accepted candidates.

---

# 2. C2B Authority Boundary

The final authority split is:

```text
MacroPlanner
    economics + provisional ordering

FeedFeasibility
    physical feed + feed funding + stress repricing

FeedExecutionSnapshot
    actual unit-action evidence

OrderBuilder
    final live sequential admission
    cash residual
    housing
    storage
    market slots

CentralPlanner
    NOT changed in C2B
```

OrderBuilder may call FeedFeasibility.

OrderBuilder must not implement another feed model.

OrderBuilder must not implement another animal-economic model.

CentralPlanner must not gain feed mathematics in C2B.

---

# 3. Rollout Modes

Preserve:

```text
shadow
→ legacy live animal purchasing

herd_plan
→ Phase-B forward ledger authority
→ legacy live animal purchasing

live
→ Phase-B forward planning
→ C2A treasury/execution foundation
→ C2B sequential live animal authority
```

Only `live` changes animal authorization.

`shadow` and `herd_plan` must remain behaviorally frozen.

---

# 4. Candidate Economics Remain a Macro Responsibility

C2B does not choose which species is economically best.

Macro supplies an ordered provisional sequence.

For example:

```python
[
    "SHEEP",
    "COW",
    "SHEEP",
]
```

This means:

```text
try SHEEP first
then COW
then SHEEP
```

OrderBuilder may:

```text
accept
reject
```

a candidate.

It may not:

```text
reorder
invent a different species
sort alphabetically
replace a rejected candidate with its own optimizer
```

A later candidate may still be tested after an earlier candidate is rejected.

---

# 5. Day 12–14 Sequence Gap Must Be Fixed

C1's `DynamicHerdPlan` intentionally stops new forward expansion at:

```text
day >= C4_LIVESTOCK_CUTOFF_DAY
```

which currently means Day 12+ produces no forward candidate sequence.

However production policy intentionally allows selective late livestock through Day 14.

Therefore C2B must extend the **live-mode provisional sequence contract**.

Do not reconstruct the late sequence from:

```python
sorted(buy_animal.items())
```

and do not use the old scalar feed model as late feed authority.

---

# 6. Late Selective Candidate Generation

For `POINT2_FEED_MODE == "live"` only, extend `DynamicHerdPlan` with an explicit late-selective mode.

Conceptually:

```python
generate_dynamic_herd_plan(
    ...,
    late_selective_mode=True,
    physical_housing_capacity=...,
)
```

Use this only when:

```text
Day >= C4_LIVESTOCK_CUTOFF_DAY
AND
Day <= SELECTIVE_LIVESTOCK_MAX_DAY
```

Late selective planning must use:

```text
existing physical housing only
+
MarginalLivestockValuator
+
FeedResourceLedger
+
SELECTIVE_LIVESTOCK_GATE_THRESHOLD
```

It must not use future housing.

---

# 7. Late Selective Economics

Late candidates still require:

```text
marginal value >= SELECTIVE_LIVESTOCK_GATE_THRESHOLD
```

Current production value:

```text
$500
```

Late candidate economics stay in:

```text
MarginalLivestockValuator
```

FeedFeasibility determines feed/funding.

Do not retain the old fixed `$25 × feed` reserve as hard authority.

Do not retain scalar `sustainable` as final feed authority.

Those may remain untouched for `shadow` / `herd_plan` legacy behavior.

---

# 8. Late Physical Housing Planning Capacity

For late sequence generation, Macro may only give preliminary credit for physically observed housing.

Planning capacity:

```text
available pasture =
    observed empty PASTURE
    -
    currently owned unplaced COW/SHEEP

available coop =
    observed empty COOP
    -
    currently owned unplaced GOOSE
```

Owned unplaced animals include:

```text
shed
+
worker inventories
```

Do not credit:

```text
build queue
planned pasture
reserved future pasture
candidate pasture
same-turn planned BUILD
dynamic housing capacity
```

This is only Macro's provisional housing bound.

OrderBuilder revalidates everything later.

---

# 9. Permanent Post-Day-12 Invariant

This remains absolute:

> After Day 12, a candidate gets housing credit only from compatible housing physically present in the observation before the turn.

Therefore even if a worker actually executes:

```text
BUILD_PASTURE
```

earlier in that same turn, C2B should **not** use that newly built structure to authorize a Day-12+ animal purchase.

Wait until the next observation.

This keeps the permanent invariant simple and auditable.

---

# 10. Pre-Day-12 Same-Turn BUILD

Before Day 12, C2B may give final housing credit for a structure that is actually built during the unit-action phase of the same turn.

But only if:

```text
actual emitted action == BUILD_PASTURE / BUILD_COOP
```

and the action can be deterministically validated.

A queued or assigned BUILD that emitted movement receives zero credit.

Thus:

```text
planned BUILD       = zero
assigned BUILD      = zero
movement toward it  = zero
actual BUILD        = possible credit before Day 12
```

---

# 11. Unified Candidate Sequence

The live Macro output should ultimately expose one sequence:

```python
plan.intents["buy_animal_sequence"]
```

Semantics:

```text
Day < 12:
    normal Phase-B/C1 DynamicHerdPlan sequence

Day 12–14:
    live-mode late-selective DynamicHerdPlan sequence

Day > 14:
    []
```

Do not require final C2B authority to consult:

```python
plan.intents["buy_animal"]
```

for species order or quantity.

`buy_animal` remains compatibility/legacy data.

In live mode:

```text
buy_animal_sequence = candidate authority input
buy_animal          = ignored for final candidate ordering
```

---

# 12. Missing or Invalid Sequence

In `live` mode:

```text
non-empty legacy buy_animal
+
missing/invalid buy_animal_sequence
```

must **not** trigger a sorted-dictionary fallback.

Fail closed for new livestock.

Reason:

```text
invalid_candidate_sequence
```

Survival and non-livestock purchases continue.

---

# 13. Candidate Identity

Every candidate should receive a deterministic current-turn identity:

```text
candidate_id
sequence_index
species
```

Prefer C1 candidate IDs where available.

Otherwise generate deterministic IDs such as:

```text
live_{day}_{sequence_index}_{species}
```

These IDs become useful for C2C dependency metadata.

Candidate IDs carry no authority themselves.

---

# 14. C2B Must Replace the Current Sorted Animal Loop

The current live path:

```python
for animal, k_anim in sorted(intents["buy_animal"].items()):
```

must remain for:

```text
shadow
herd_plan
```

but must not be used in:

```text
live
```

In `live`, replace it with sequential candidate replay.

---

# 15. One Shared Live Animal Authority

Current code has multiple animal paths:

```text
OrderBuilder.build()
build_intraday()
reinvest_livestock()
```

C2B must stop them from independently deciding livestock safety in live mode.

Use one shared final C2B admission path.

For `live`:

```text
build()
build_intraday()
reinvest path
```

must ultimately delegate to the same candidate-admission logic.

No separate post-cutoff animal authority.

---

# 16. Preserve Legacy Paths Outside Live Mode

Do not delete the existing `reinvest_livestock()` behavior yet.

For:

```text
shadow
herd_plan
```

it remains unchanged.

For:

```text
live
```

its separate animal/housing authority must be bypassed or delegated to the common C2B path.

C2B live housing must have exactly one final implementation.

---

# 17. Existing-Herd Global Gate

Before candidate #1:

```text
existing_herd_feasible
```

must be true.

If false:

```text
accept zero new animals
```

Reason:

```text
existing_herd_infeasible
```

Protected survival purchases still continue.

---

# 18. Execution Global Gate

C2A made the execution result diagnostic-only.

C2B activates it.

If currently placed animals remain unfed:

```text
snapshot missing
OR
execution_confidence != "high"
OR
not every due target has an exact verified FEED action
```

then:

```text
accept zero new animals
```

Reason:

```text
feed_execution_unverified
```

If all currently placed animals are already fed:

```text
guarded/conditional confidence alone
```

does not automatically block candidate admission.

---

# 19. Catastrophic C2B Failure

Any unexpected failure in the final candidate authority must result in:

```text
zero new animal orders
```

while preserving already-safe higher-priority orders.

Do not fall back to legacy animal purchasing.

Do not change rollout mode.

---

# 20. Candidate Stage Should Be Transactional as a Whole on Exceptions

Ordinary candidate rejection is normal.

Example:

```text
candidate 1 housing failure
→ candidate 1 rejected
→ candidate 2 may still be tested
```

But an unexpected evaluator/runtime exception is different.

If C2B candidate processing throws unexpectedly:

```text
discard ALL new animal admissions for that turn
```

even if an earlier candidate had already tentatively passed.

Keep:

```text
hires
protected feed
land
optional wheat
seeds
```

that were independently validated.

This prevents partially executed livestock decisions after a corrupted authority stage.

---

# 21. Higher-Priority Prefix

Animals are evaluated only after higher-priority commitments.

Semantic order:

```text
mandatory hires / hard commitments
        ↓
protected existing-herd WHEAT
        ↓
existing-herd feed hold
        ↓
land
        ↓
optional WHEAT
        ↓
seeds
        ↓
animals
```

Candidate feed holds never outrank land/seeds.

Existing-herd feed funding does.

---

# 22. Build Candidate Ledger from Retained Prefix

The C2B candidate ledger must represent the state after all higher-priority OrderBuilder commitments.

It must account for:

```text
cash reserve
mandatory hire hold
retained protected-WHEAT spending
retained protected-WHEAT physical delivery
retained land spending
retained optional-WHEAT spending
retained optional-WHEAT physical delivery
retained seed spending
SW strategic animal reserve if active
```

Only then begin candidate replay.

---

# 23. Current-Turn WHEAT Accounting

When a WHEAT order is retained:

```text
cash spending is committed
+
physical WHEAT delivery is scheduled
```

both must enter the candidate ledger.

Do not add physical WHEAT without charging its cost.

Do not charge the cost without giving its physical feed credit.

---

# 24. Recommended Ledger Representation

For retained current-turn WHEAT:

```text
append scheduled market delivery
+
increase hard current-turn spending/hold
```

Then recompute existing-herd feasibility.

This produces:

```text
remaining existing-herd feed hold
```

after the actual retained WHEAT.

Do not reuse stale C2A hold values after optional WHEAT changes the feed position.

---

# 25. Existing-Herd Hold Must Be Recomputed Before Candidates

Once the actual higher-priority prefix is known:

```text
recompute existing herd feasibility
recompute remaining existing feed hold
```

Candidate #1 sees that updated state.

If recomputation fails:

```text
new livestock = zero
```

---

# 26. Land and Seed Spending

Land and seed purchases provide no feed resource.

Their retained cost must reduce candidate purchasing power.

They should appear as:

```text
hard committed current-turn spending
```

in the candidate ledger.

A candidate cannot spend the same money already committed to land or seeds.

---

# 27. SW Capital Protection

Preserve existing SW animal-capital protection.

Do not encode it as existing-herd feed funding.

For candidate evaluation, represent it as:

```text
strategic_cash_hold
```

or an equivalent animal-only residual hold.

Existing-herd survival still outranks SW protection.

New animals may not spend protected SW capital when that existing policy is active.

---

# 28. Do Not Double-Gate Candidate Cash

Once C2B uses `FeedResourceLedger` as the live candidate cash authority, do not independently reject candidates through a second divergent:

```text
remaining_discretionary // animal_cost
```

model.

The higher-priority prefix establishes the candidate ledger.

After that:

```text
FeedResourceLedger
```

is candidate feed/cash authority.

---

# 29. Post-Unit / Pre-Market State

Candidate admission occurs after unit actions execute but before market orders.

Therefore C2B needs a deterministic:

```text
post-unit / pre-market state
```

derived from:

```text
observation
+
assignment
+
actual emitted actions
```

Do not predict future worker actions.

Only apply actions actually emitted this turn.

---

# 30. Extend FeedExecutionSnapshot

Keep all C2A fields.

Add enough structured evidence to derive post-unit state, for example:

```text
actual_action_records
actual_place_records
actual_build_records
post_unit_shed_inventory
post_unit_worker_inventories
post_unit_shed_occupancy
post_unit_total_storable_inventory
post_unit_state_verified
post_unit_state_reason
```

Exact field names may differ.

The semantics must not.

---

# 31. Post-Unit Action Simulation

Start from observed:

```text
shed
worker inventories
physical structures
placed animals
```

Apply only actual emitted operations.

Relevant changes include:

```text
FEED
PICKUP
DROP
PLACE
BUILD_PASTURE
BUILD_COOP
FERTILIZE
HARVEST
COLLECT_FERTILIZER
```

Movement actions have no inventory/structure effect.

PASS has no effect.

Seeds remain separate storage.

---

# 32. Fail Closed on Unverifiable Post-Unit State

If an emitted inventory-changing action cannot be deterministically interpreted:

```text
post_unit_state_verified = False
```

Then:

```text
new livestock = zero
```

Do not guess inventory effects.

Existing survival purchases continue.

---

# 33. FEED Post-Unit Effect

A verified actual FEED:

```text
worker WHEAT -= 1
```

and resolves that animal's current-day feed action.

It must not be counted twice.

---

# 34. PLACE Post-Unit Effect

A verified actual PLACE:

```text
worker animal inventory -= 1
compatible empty structure becomes occupied
existing unplaced herd decreases by 1
placed herd increases by 1
```

For future feed days, the animal now belongs to the placed herd.

Do **not** automatically add a new same-day feed requirement.

That rule remains frozen unless engine evidence explicitly changes it.

---

# 35. BUILD Post-Unit Effect

Before Day 12:

```text
verified actual BUILD_PASTURE
verified actual BUILD_COOP
```

may add one compatible physical empty structure to the post-unit state.

Day 12+:

```text
zero candidate housing credit
```

from same-turn BUILD.

---

# 36. PICKUP / DROP

Verified:

```text
PICKUP(item, n)
```

moves units:

```text
shed → worker
```

Verified:

```text
DROP(item, n)
```

moves units:

```text
worker → shed
```

They change immediate market-phase shed occupancy.

They do not create or destroy total storable inventory.

---

# 37. Other Worker Inventory Effects

The post-unit simulator should include deterministic additions/removals from:

```text
HARVEST
COLLECT_FERTILIZER
FERTILIZE
```

when their quantities can be proven from the observation/task.

If exact quantity cannot be proven:

```text
use conservative capacity accounting
```

rather than optimistic credit.

---

# 38. Candidate Feed Ledger Uses Post-Unit State

Before candidate replay, update the live ledger so its inventory matches the post-unit state.

At minimum:

```text
wheat_in_shed
wheat_on_workers
shed_other_units
placed_herd
owned_unplaced_herd
unfed_placed_today
```

must match the verified market-phase state.

Do not evaluate candidates against stale pre-unit storage.

---

# 39. Current-Day Feed Count After Verified FEED

For candidate-stage ledger purposes:

```text
unfed_placed_today
```

must reflect verified actual FEED actions.

Do not make the candidate ledger fund today's obligation again after that obligation has actually been serviced by the unit phase.

---

# 40. Same-Turn PLACE Future Feed

A same-turn placed animal:

```text
does not automatically eat today
```

but must contribute to:

```text
future operational feed
remaining lifetime feed
```

because it is now physically placed for future days.

---

# 41. Final Housing State

Create one shared C2B housing state.

Conceptually:

```text
LiveHousingState
```

with:

```text
post_unit_empty_pastures
post_unit_empty_coops

existing_unplaced_pasture_claims
existing_unplaced_coop_claims

accepted_candidate_pasture_claims
accepted_candidate_coop_claims
```

---

# 42. Existing Animals Get Housing First Claim

Before candidate #1:

```text
COW/SHEEP already in shed/workers
```

reserve PASTURE capacity.

```text
GOOSE already in shed/workers
```

reserve COOP capacity.

Candidate animals may only use residual compatible structures.

---

# 43. Shared Pasture Pool

COW and SHEEP share:

```text
PASTURE
```

Therefore:

```text
COW accepted
```

reduces the same residual housing pool later considered by SHEEP.

Do not maintain independent Cow and Sheep pasture capacities.

---

# 44. Goose Housing

GOOSE requires:

```text
COOP
```

only.

Pasture cannot satisfy Goose housing.

Coop cannot satisfy Cow/Sheep housing.

---

# 45. Pending Structures Are Not Final Housing

In C2B live mode, remove:

```python
pending_structures
```

as direct housing credit from the final animal gate.

Macro can still use planned structures for forward planning before Day 12.

Final live admission uses:

```text
verified post-unit physical capacity
```

only.

---

# 46. Candidate Housing Transaction

For candidate N:

```text
trial_housing = accepted_housing_state.clone()
```

If compatible housing unavailable:

```text
reject candidate
discard trial
```

If candidate passes all gates:

```text
commit one compatible housing claim
```

Candidate N+1 sees residual housing.

---

# 47. Immediate Shed Capacity

An animal purchase initially lands in the shed.

Therefore every accepted candidate requires:

```text
1 immediate shed slot
```

Use:

```text
post-unit shed occupancy
+
retained incoming market products
+
previously accepted animal purchases
```

to determine room.

---

# 48. Feed Ledger Storage Reservation

Reuse:

```text
candidate_storage_slots_reserved
```

inside `FeedResourceLedger`.

Do not create a second independent feed-storage counter.

OrderBuilder may maintain a market-phase capacity view, but both must reconcile.

---

# 49. Hour-23 Rollover Protection

At Hour 23 also require:

```text
post-market shed inventory
+
post-unit worker-carried shed inventory
<= SHED_CAPACITY
```

after accounting for candidate purchases.

This protects worker inventory that will roll back into the shed at day end.

---

# 50. Seeds Are Separate

Seed inventory does not consume shed slots.

Never include seeds in:

```text
shed occupancy
worker rollover shed requirement
candidate storage calculation
```

---

# 51. Rollover Uses All Known Shed-Storable Worker Inventory

Do not protect only WHEAT if the full post-unit worker inventory is known.

Use all shed-storable worker items.

At minimum, protected carried WHEAT must never be lost because of a new animal purchase.

---

# 52. Example Rollover Failure

At Hour 23:

```text
shed after unit actions = 99
worker carries 1 WHEAT
candidate requires 1 shed slot
```

Candidate must fail.

Reason:

```text
end_of_day_rollover_capacity
```

---

# 53. Candidate Replay Algorithm

For each species in:

```python
buy_animal_sequence
```

execute:

```text
1. validate candidate metadata/species
2. clone accepted feed ledger
3. clone accepted housing state
4. clone accepted market/storage state
5. check compatible housing
6. check immediate shed capacity
7. check Hour-23 rollover capacity if applicable
8. evaluate_incremental_candidate()
9. check required market-order slot capacity
10. if every gate passes:
       commit_candidate_reservation()
       commit housing reservation
       commit storage reservation
       record candidate accepted
   else:
       discard all trial state
       record candidate rejected
```

No partial commit.

---

# 54. FeedFeasibility Is the Cash/Feed Gate

Use:

```python
evaluate_incremental_candidate()
```

for one candidate at a time.

Do not copy its formulas into OrderBuilder.

It already handles:

```text
candidate purchase cost
operational feed
future feed funding
engine_stress_bound_v1
candidate storage reservation
stress repricing
prior candidate liabilities
```

---

# 55. Candidate Commit

Only after all external gates pass call:

```python
commit_candidate_reservation()
```

This commit should remain the authoritative feed-ledger mutation.

It updates:

```text
existing feed hold
candidate feed hold
candidate purchase spending
candidate storage reservations
scheduled future feed purchases
stress price
candidate reservations
```

---

# 56. Stress Repricing Invariant

After candidate N is accepted:

```text
engine_stress_bound_v1
```

may increase the required WHEAT stress price.

The resulting higher price must re-fund:

```text
existing herd liability
+
all prior accepted candidate liability
+
candidate N liability
```

before candidate N+1 is considered.

Candidate N+1 cannot benefit from stale cheaper pricing.

---

# 57. Rejected Candidate Releases Everything

If candidate N fails:

```text
cash = unchanged
feed holds = unchanged
stress price = unchanged
scheduled feed = unchanged
housing = unchanged
shed reservation = unchanged
order slots = unchanged
```

Candidate N+1 sees only accepted predecessors.

---

# 58. Continue After Ordinary Candidate Rejection

A normal candidate rejection does not terminate the sequence.

Example:

```text
SHEEP
COW
SHEEP
```

If first SHEEP fails because no pasture:

```text
COW may also fail same pool
```

but the later candidates are still evaluated in original order.

A Goose later in the sequence may still pass if a Coop exists.

Do not reorder.

---

# 59. Do Not Re-run the Species Optimizer

If candidate #1 fails, do not ask OrderBuilder:

```text
what species should replace it?
```

Candidate #2 remains the next Macro-provided candidate.

Macro owns candidate ordering.

---

# 60. Candidate Economics Are Provisional, Feed/Serviceability Are Final

C2B interpretation:

```text
Macro:
    worth considering

OrderBuilder:
    can actually execute safely now
```

A Macro-approved candidate can still fail C2B.

OrderBuilder does not turn a Macro-rejected species into a purchase.

---

# 61. Market Order Slots

The engine cap is per order, not per animal unit.

Therefore sequential admission should distinguish:

```text
candidate count
```

from:

```text
animal market-order count
```

---

# 62. Group Accepted Same-Species Candidates

After sequential admission, accepted candidates may be consolidated by species for engine emission.

Example accepted sequence:

```text
SHEEP
COW
SHEEP
```

may emit:

```text
BUY_ANIMAL SHEEP 2
BUY_ANIMAL COW 1
```

provided the admission ledger preserves the original candidate sequence.

---

# 63. Preserve First-Appearance Species Order

For deterministic emission:

```text
SHEEP
COW
SHEEP
```

should group as:

```text
SHEEP ×2
COW ×1
```

not alphabetically.

This also prepares clean metadata for C2C.

---

# 64. Slot Reservation Rule

A candidate requires a new animal order slot only if its species has not already created an accepted animal order group.

Example:

```text
accepted SHEEP #1 → consumes one order slot
accepted SHEEP #2 → consumes zero additional order slots
accepted COW #1   → consumes one new order slot
```

Do not pessimistically charge one slot per animal.

---

# 65. Higher-Priority Slots Come First

Animal order groups may use only market slots remaining after the higher-priority OrderBuilder prefix.

A candidate cannot displace:

```text
protected feed
land
optional wheat
seeds
```

inside OrderBuilder.

C2C will later reconcile this with global buy+sell arbitration.

---

# 66. Candidate-Specific Future WHEAT

`evaluate_incremental_candidate()` may schedule future WHEAT purchases.

C2B should treat these as:

```text
feed funding reservations / future requirements
```

not automatically emit all of them as current-turn market orders.

The candidate is unplaced at purchase and does not eat today.

On the next observation, if purchased, it becomes an owned animal and its feed liability moves into existing-herd authority.

---

# 67. Current-Turn WHEAT Dependencies

C2B must record when candidate safety relied on a current-turn retained WHEAT order.

This is diagnostic metadata in C2B.

C2C will make those dependencies arbitration-safe.

For example:

```text
candidate_id
relies_on_retained_protected_wheat
relies_on_retained_optional_wheat
```

Do not implement CentralPlanner closure yet.

---

# 68. C2B / C2C Safety Boundary

C2B makes **OrderBuilder's output** correct.

C2C will ensure downstream global arbitration cannot invalidate that output.

Therefore:

```text
C2B pass
```

does not mean:

```text
production live mode is ready
```

Production `live` remains disabled until C2C passes.

---

# 69. Actual Accepted Aggregate

Once C2B replay finishes:

```text
accepted sequence
```

becomes the source of truth.

Derive:

```python
queued["animal"]
```

and final:

```text
BUY_ANIMAL
```

orders from accepted candidates.

Do not use legacy `buy_animal` aggregate to reconstruct them.

---

# 70. Diagnostics

Add live C2B diagnostics:

```text
live_animal_authority = "c2b_sequential"

candidate_sequence_requested
candidate_sequence_source
candidate_sequence_accepted
candidate_sequence_rejected

candidate_decisions:
    candidate_id
    sequence_index
    species
    accepted
    rejection_reason
    feed_feasible
    feed_blocking_reason
    purchase_cost
    candidate_feed_hold
    existing_feed_hold_after
    candidate_feed_hold_after
    stress_price_after
    housing_before
    housing_after
    shed_room_before
    shed_room_after
    rollover_room_after
    slot_delta

final_existing_feed_hold
final_candidate_feed_hold
final_candidate_purchase_spend
final_stress_wheat_price

post_unit_state_verified
post_unit_shed_occupancy
post_unit_worker_inventory_total

housing_state_final
animal_order_slots_used
```

Diagnostics remain observational.

---

# 71. Candidate Rejection Reasons

Use explicit reasons such as:

```text
existing_herd_infeasible
feed_execution_unverified
invalid_candidate_sequence
invalid_species
feed_infeasible
insufficient_cash
shed_capacity
end_of_day_rollover_capacity
no_physical_housing
post_cutoff_physical_housing_required
market_order_slots
post_unit_state_unverified
live_candidate_exception
```

Avoid generic `"budget"` when the actual gate is known.

---

# 72. C2B Files Expected to Change

Likely:

```text
agent/strategy/herd_planner.py
agent/strategy/macro_planner.py
agent/strategy/feed_feasibility.py
agent/market/order_builder.py
agent/tests/...
```

Possibly:

```text
agent/main.py
```

only if additional already-produced scheduler evidence needs wiring.

Avoid modifying:

```text
central_planner.py
```

in C2B.

TaskScheduler should not need strategy changes; it already emits `actions` and `assignment`.

---

# 73. No New Pathfinder

Do not add:

```text
future worker route simulation
future task assignment prediction
future feed-path optimizer
```

C2B uses actual current-turn actions and conservative future feed funding.

---

# 74. Required Sequence Tests

Test:

```text
live mode uses buy_animal_sequence, not sorted buy_animal
```

Use a mismatch:

```text
buy_animal_sequence = [SHEEP, COW, SHEEP]
buy_animal = {COW: 10}
```

Final live consideration must follow:

```text
SHEEP, COW, SHEEP
```

not the aggregate.

---

# 75. Interleaving Test

Verify:

```text
[SHEEP, COW, SHEEP]
```

is evaluated exactly in that order.

Record decision sequence explicitly.

---

# 76. Missing Sequence Test

In live mode:

```text
buy_animal = {SHEEP: 1}
buy_animal_sequence missing
```

must not use sorted aggregate fallback.

No animal.

Reason:

```text
invalid_candidate_sequence
```

---

# 77. Shadow / Herd-Plan Regression

The exact same malformed/missing sequence must not affect legacy behavior in:

```text
shadow
herd_plan
```

Those modes retain old aggregate authority.

---

# 78. Late Selective Tests

Test Day 12–14:

```text
forward-build mode would produce no candidates
but live late-selective mode may produce a candidate
```

when:

```text
physical empty compatible housing exists
marginal EV >= $500
feed ledger passes
```

---

# 79. Late Housing Negative Test

Day 12–14:

```text
planned pasture exists
physical pasture does not
```

must produce:

```text
zero late candidate credit
```

---

# 80. Late Cutoff Test

Day > `SELECTIVE_LIVESTOCK_MAX_DAY`:

```text
buy_animal_sequence == []
```

regardless of feed/cash/housing.

---

# 81. Existing-Herd Gate Tests

In live mode:

```text
existing herd infeasible
```

must result in:

```text
zero accepted candidates
```

with protected survival orders retained.

---

# 82. Execution Gate Tests

Test:

```text
unfed existing animal
assigned FEED but emitted MOVE
```

→ zero candidates.

Test:

```text
all due animals have exact emitted FEED
```

→ candidate stage may proceed.

Test:

```text
all placed animals already fed
guarded confidence
```

→ guarded alone does not block candidates.

---

# 83. Transaction Tests

Candidate #1 accepted:

```text
candidate #2 sees less cash
candidate #2 sees more feed liability
candidate #2 sees updated stress price
candidate #2 sees less housing
candidate #2 sees less storage
```

---

# 84. Rejection Rollback Test

Candidate #1 trial fails.

Verify before candidate #2:

```text
candidate_purchase_cash_spent unchanged
candidate_feed_cash_hold unchanged
candidate_storage_slots_reserved unchanged
housing unchanged
stress price unchanged
order slots unchanged
```

---

# 85. Stress Repricing Test

Candidate #1 accepted.

Candidate #2 raises `engine_stress_bound_v1`.

Verify:

```text
existing herd hold
+
candidate #1 liability
```

are repriced before candidate #2 is accepted.

---

# 86. Higher-Priority Cash Test

Create enough money for:

```text
land
```

or:

```text
animal
```

but not both.

If land is retained first:

```text
candidate must not reuse that money
```

---

# 87. Retained WHEAT Test

Retain current-turn optional/protected WHEAT.

Verify candidate ledger receives:

```text
physical WHEAT credit
AND
exact current purchase cost
```

once.

No double hold.

---

# 88. Post-Unit PICKUP Test

Observed shed nearly full.

Actual emitted:

```text
PICKUP WHEAT
```

frees immediate shed capacity.

Verify market-stage capacity reflects the actual pickup.

---

# 89. Post-Unit FEED Test

Worker carries WHEAT.

Actual FEED consumes one.

Verify:

```text
post-unit worker WHEAT
```

decreases and rollover accounting reflects it.

---

# 90. Post-Unit PLACE Test

Worker carries COW.

Actual PLACE succeeds.

Verify:

```text
worker COW decreases
empty pasture decreases
placed COW increases for future feed
unplaced COW decreases
```

Do not create an automatic same-day feed obligation.

---

# 91. Pre-Cutoff BUILD Test

Day 10:

```text
actual emitted BUILD_PASTURE
```

may provide one final housing slot.

Assigned-but-moving BUILD cannot.

---

# 92. Post-Cutoff BUILD Test

Day 12:

```text
actual emitted BUILD_PASTURE
```

must still provide zero late purchase credit that turn.

Candidate waits for next observation.

---

# 93. Existing Unplaced Housing Test

Physical empty pastures:

```text
2
```

Shed COW:

```text
1
```

Candidate SHEEP:

```text
1
```

Only one candidate pasture slot remains.

---

# 94. Shared Pasture Sequence Test

Sequence:

```text
COW
SHEEP
```

One residual pasture.

First accepted candidate reserves it.

Second candidate fails housing.

---

# 95. Coop Separation Test

Available:

```text
1 COOP
0 PASTURE
```

GOOSE may pass.

COW/SHEEP must fail housing.

---

# 96. Immediate Shed Test

Post-unit shed occupancy:

```text
100
```

Candidate must fail.

Post-unit shed occupancy:

```text
99
```

one candidate may fit if no other incoming product consumes the slot.

---

# 97. Retained WHEAT + Animal Shed Test

Post-unit shed occupancy:

```text
98
```

Retained WHEAT:

```text
1
```

Accepted animal:

```text
1
```

fits exactly.

One more candidate fails.

---

# 98. Hour-23 Rollover Test

Hour 23:

```text
post-unit shed = 99
worker inventory = 1
```

new animal:

```text
reject
```

Reason:

```text
end_of_day_rollover_capacity
```

---

# 99. Seeds Storage Test

Large seed inventory must not reduce shed animal capacity.

---

# 100. Animal Slot Grouping Test

Accepted:

```text
SHEEP
SHEEP
SHEEP
```

must require:

```text
1 BUY_ANIMAL market slot
```

not three.

---

# 101. Interleaved Slot Grouping Test

Accepted:

```text
SHEEP
COW
SHEEP
```

requires:

```text
2 animal market slots
```

and preserves first-species appearance order:

```text
SHEEP ×2
COW ×1
```

---

# 102. Slot Exhaustion Test

If higher-priority orders consume every available OrderBuilder market slot:

```text
no animal candidate can execute
```

even if cash/feed/housing pass.

---

# 103. Candidate Exception Test

Inject exception while processing candidate #2 after candidate #1 tentatively passed.

Final output for that turn:

```text
zero BUY_ANIMAL orders
```

Higher-priority non-animal orders remain.

---

# 104. Fresh Observation Test

Macro candidate feed diagnostics must not become live reservations.

Verify the C2B live ledger begins from:

```text
observation
+
actual unit actions
+
retained higher-priority orders
```

not Macro's candidate ledger.

---

# 105. Intraday Shared Authority Test

At an intraday reinvestment hour:

```text
live
```

must use exactly the same sequential C2B authority as the normal live builder.

No separate `reinvest_livestock()` final housing decision.

---

# 106. Post-Cutoff Intraday Test

Day 12–14 intraday:

```text
physically observed empty pasture
+
late candidate
+
feed safe
```

may purchase.

Planned future pasture cannot.

---

# 107. Full Regression Requirements

Run:

```text
Point-2 feed tests
OrderBuilder tests
Macro/herd planner tests
full non-slow agent suite
submission package tests
```

Also run frozen regressions proving:

```text
shadow unchanged
herd_plan unchanged
```

Run the 720-step frozen regression if available.

---

# 108. C2B Live Simulation

Run at least one full 720-step test with:

```text
POINT2_FEED_MODE = "live"
```

for diagnostic purposes only.

Capture:

```text
animal candidates requested
accepted candidates
rejection reasons
feed hold trajectory
stress WHEAT price
physical housing use
shed-capacity rejects
rollover rejects
final herd
final money/reward
```

Do not make production `live` the default.

---

# 109. Submission Build

After tests:

```bash
python scripts/build_submission.py
```

Verify:

```text
agent source
submission mirror
dist/submission.zip
```

are synchronized.

---

# 110. C2B Scope Exclusions

Do NOT implement:

```text
CentralPlanner dependency closure
protected-WHEAT sale protection
global buy/sell dependency arbitration
candidate-resource proposal IDs for final arbitration
C2C
```

C2B may expose metadata that C2C will later consume.

It must not implement the C2C policy itself.

---

# 111. C2B Acceptance Invariants

C2B passes only if all are true:

```text
live mode no longer uses sorted aggregate animal authority

candidate order comes from Macro

Day12–14 selective candidates remain possible
without planned-housing credit

existing herd must pass before expansion

existing unfed herd must have verified execution before expansion

candidate feed/cash uses fresh live residual ledger

higher-priority spending cannot be reused

candidate failures mutate nothing

candidate acceptances reprice prior liabilities

housing is species-compatible and sequentially reserved

existing unplaced animals get housing first claim

post-Day12 same-turn/future housing gets zero credit

actual post-unit shed state drives acquisition capacity

Hour23 rollover cannot destroy carried inventory

same-species accepted animals share one engine order slot

live evaluator failure produces zero new animals

shadow/herd_plan remain frozen
```

---

# 112. C2B Freeze Boundary

When C2B passes:

```text
OrderBuilder sequential animal authority
```

is frozen.

But Phase C is **not complete**.

The remaining vulnerability is:

```text
CentralPlanner may later arbitrate away a resource order
that a retained animal decision relied upon.
```

That is C2C.

Therefore after C2B:

```text
DO NOT enable live production yet.
```

---

# 113. Implementation Checkpoint

Recommended next commit:

```text
Phase C2B
Sequential Live Candidate Authority
```

Suggested commit message:

```text
feat(feed): implement Phase C2B sequential live livestock authority
```

After implementation:

```text
commit
stop
report SHA
```

Do not begin C2C until the C2B SHA has been independently audited and frozen.
