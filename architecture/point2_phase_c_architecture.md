# Phase C Architecture Freeze

Baseline:

`f39b778dcb4ce83eea3c5c0456a116e79a5795f9`

## Verdict

**READY FOR PHASE C IMPLEMENTATION, split into C1 and C2.**

The key principle is:

```text
Macro decides what animals are worth considering.

FeedFeasibility decides whether feed/cash can support them.

TaskScheduler determines what unit actions will actually execute.

OrderBuilder is the final live BUY_ANIMAL authority.

CentralPlanner may arbitrate market slots,
but may not invalidate a dependency and leave its animal alive.
```

No second feed model should be created.

---

# 1. Final authority map

| Component                 | Phase-C authority                                            |
| ------------------------- | ------------------------------------------------------------ |
| Observation               | Authoritative current physical state                         |
| DynamicHerdPlan           | Forward herd/housing planning only                           |
| MarginalLivestockValuator | Economic/profitability authority                             |
| MacroPlanner              | Produces provisional ordered animal candidates               |
| FeedFeasibility           | Sole feed/funding/stress-pricing implementation              |
| TaskScheduler             | Actual unit-task/action authority                            |
| FeedExecutionSnapshot     | Evidence of what feed actions can actually execute this turn |
| OrderBuilder              | Final live cash/feed/housing/storage/candidate admission     |
| CentralPlanner            | Shared 10-slot arbitration and dependency preservation only  |
| `main.py`                 | Wiring/failure isolation only                                |

Current `FeedExecutionSnapshot` is not strong enough for final live authority because it counts assigned FEED tasks and can call the state `high` without proving the emitted action is actually FEED rather than movement.

---

# 2. Macro → OrderBuilder contract

Macro must generate an explicit ordered sequence:

```python
buy_animal_sequence = [
    "SHEEP",
    "COW",
    "SHEEP",
]
```

Keep the existing aggregate for compatibility:

```python
buy_animal = {
    "SHEEP": 2,
    "COW": 1,
}
```

But in Phase-C live mode:

```text
buy_animal_sequence
```

is authoritative for candidate ordering.

Never reconstruct it using:

```python
sorted(buy_animal.items())
```

because the present OrderBuilder does exactly that and therefore destroys interleaved admission order.

Macro approval is only provisional.

Macro candidate reservations are **not imported into the final live ledger**.

At OrderBuilder time:

```text
rebuild fresh ledger from observation
→ apply real execution snapshot
→ apply actually retained higher-priority purchases
→ replay buy_animal_sequence
```

This prevents stale Macro reservations from double-counting resources.

---

# 3. Existing-herd treasury invariant

Phase C needs two different concepts:

```text
protected WHEAT spending now
```

and:

```text
remaining existing-herd feed funding hold
```

They are not the same thing.

For every accepted purchase prefix:

```text
observed_cash
-
reserved_cost_of_retained_orders
-
other hard strategic reserve
-
remaining_existing_herd_feed_hold
-
accepted_candidate_feed_hold
>= 0
```

The same liability may appear only once.

Therefore:

```text
WHEAT bought now
→ cash becomes retained current-turn spending
→ its physical delivery is added to the feed ledger
→ corresponding future feed liability disappears/reduces
→ recompute remaining_existing_herd_feed_hold
```

Never do:

```text
protected wheat cost
+
the unchanged old feed hold
```

for the same units.

That is the exact anti-double-counting rule.

---

# 4. Correct live treasury ordering

OrderBuilder live mode should conceptually process:

```text
mandatory commitments
        ↓
existing-herd protected WHEAT
        ↓
recompute existing-herd feed hold
        ↓
land
        ↓
optional WHEAT
        ↓
seeds
        ↓
new animal candidate packages
```

The current builder protects only WHEAT actually bought this turn and then gives the remainder to land/optional wheat/seeds/animals. It does not yet preserve lifetime existing-herd funding.

So Phase C adds:

```text
remaining_existing_feed_hold
```

before any discretionary spending.

Crucially:

```text
candidate feed reserves
```

must **not** block land, optional WHEAT or seeds.

Candidates are last.

Existing-herd funding can block them.

---

# 5. Hour-1 land bypass

This must be removed as a Phase-C authority bypass.

Currently Hour 1 manually appends:

```python
["BUY_LAND"]
```

without going through OrderBuilder's treasury accounting.

In `POINT2_FEED_MODE == "live"` Hour-1 land must go through the same protected treasury calculation as every other land purchase.

Do not create a second special Phase-C cash calculation in `main.py`.

OrderBuilder owns it.

For:

```text
shadow
herd_plan
```

legacy behavior remains unchanged.

---

# 6. Live execution certification

C2 should upgrade `FeedExecutionSnapshot` so it examines:

```text
assignment
+
actual emitted unit actions
```

The scheduler already returns both `actions` and `assignment`.

For every currently unfed placed animal, pair:

```text
assigned task target
↔
actual emitted action
```

An animal is certified fed-this-turn only when the emitted action for the assigned unit is actually:

```text
FEED
```

Movement toward an animal is not certified FEED.

An assigned FEED task whose emitted action is:

```text
NORTH
SOUTH
EAST
WEST
PICKUP
PASS
```

does not count.

Therefore final `high` means:

```text
every currently due placed-animal target
has a distinct actual FEED action this turn
```

not merely an assignment.

---

# 7. Final live execution rule

Use this rule:

```python
if phase_c_evaluation_error:
    reject_new_livestock

elif unfed_placed_today > 0:
    if snapshot is None:
        reject("feed_execution_unverified")
    elif snapshot.execution_confidence != "high":
        reject("feed_execution_unverified")
    elif not every_due_target_has_actual_FEED_action:
        reject("feed_execution_unverified")
    else:
        candidate_may_continue_through_other_gates

else:
    guarded_or_conditional_confidence_alone_does_not_veto
```

This deliberately avoids creating another pathfinder.

If a current herd animal is unfed and its worker is merely travelling toward it, we do not buy another animal yet.

The agent can buy later after the existing herd is physically safe.

This is more reliable than trying to predict whether a multi-turn rescue route will finish.

---

# 8. Hour 22 / Hour 23

Engine order remains:

```text
unit actions
→ market actions
→ town
→ end-of-day
```

Therefore WHEAT bought in the current market phase cannot support the current turn's already-issued unit action.

At Hour 23:

```text
unresolved current-day feed
→ cannot be rescued by market WHEAT
→ no new animal
```

At Hour 22, if the unresolved animal would still require:

```text
market buy
→ later PICKUP
→ later FEED
```

then it also cannot be certified safe before the deadline.

Under the rule above this naturally fails because there is no actual FEED action this turn.

Protected WHEAT may still be purchased for survival.

Only new livestock is blocked.

---

# 9. Same-turn PLACE

Astra's statement that every same-turn PLACE automatically creates a current-day FEED obligation is too strong.

Do **not** add that as a generic rule without engine evidence.

Instead, the execution snapshot records actual PLACE actions separately.

For Phase C they matter immediately for:

```text
housing occupancy
owned/placed state transition
storage state
```

An actual PLACE consumes its structure before market purchases occur.

Therefore OrderBuilder's final housing calculation must subtract structures consumed by actual PLACE actions.

Do not count an assigned PLACE that emits movement.

Only actual emitted PLACE matters.

For feed timing, retain the existing conservative unplaced/placed semantics unless engine behavior proves the newly placed animal must be fed that same day.

---

# 10. Housing authority

Create one shared final live housing reservation check.

Do not keep separate subtly different logic in:

```text
build()
build_intraday()
reinvest_livestock()
```

Final candidate admission must know its required structure:

```text
COW/SHEEP → PASTURE
GOOSE → COOP
```

Available housing should be:

```text
actual physically empty compatible structures
-
structures reserved for already-owned unplaced compatible animals
-
structures consumed by actual same-turn PLACE actions
-
structures committed to accepted earlier candidates
```

For Day >= 12:

```text
planned structure credit = 0
queued structure credit = 0
reserved future structure credit = 0
candidate future structure credit = 0
```

I recommend **not** crediting a same-turn BUILD after Day 12 in Phase C even if it might technically execute before market.

Wait for the next observation.

That is slightly conservative but keeps the permanent invariant extremely clean:

> late purchases use structures physically confirmed by observation.

The current normal OrderBuilder path credits `pending_structures`, so that cannot remain part of the final post-Day12 live gate.

---

# 11. Live candidate replay

At candidate stage, start with:

```text
fresh live ledger
+
actual retained higher-priority spending
+
actual retained market WHEAT
+
remaining existing-herd feed hold
+
actual residual housing
+
actual residual shed capacity
```

Then replay:

```python
for species in buy_animal_sequence:
```

one unit at a time.

For every candidate:

```text
clone current accepted ledger
→ evaluate feed
→ evaluate cash
→ evaluate housing
→ evaluate shed capacity
→ evaluate execution rule
→ verify required market-order slots
→ commit only if every gate passes
```

If candidate #1 fails:

```text
discard clone
```

Nothing from candidate #1 is reserved.

Candidate #2 then evaluates against:

```text
existing herd
+
higher-priority actual orders
+
previous ACCEPTED candidates only
```

This answers Astra's reservation question exactly.

A rejected candidate does not poison later candidates.

---

# 12. Economic re-evaluation

Macro still determines candidate economic order.

OrderBuilder should **not implement another MarginalLivestockValuator**.

However, where candidate economics depend on cumulative herd state, accepted predecessors should be reflected in any live economic check that already exists.

The invariant is:

```text
FeedFeasibility = can safely fund/support?
MarginalLivestockValuator = is it profitable?
```

A feed cash reserve is a liquidity requirement.

`feed_cost` in marginal EV is an economic cost.

They are not duplicates and neither should be removed because the other exists.

---

# 13. Candidate-required market WHEAT

If accepting a candidate requires additional near-term market WHEAT, treat that WHEAT and the animal as a dependency package.

Conceptually:

```text
candidate COW
requires:
    candidate-feed WHEAT order X
```

OrderBuilder performs the feed mathematics and records metadata such as:

```python
candidate_id
requires_proposal_ids
dependency_group
```

CentralPlanner only preserves that dependency.

It does not calculate how much WHEAT is required.

If candidate #1 is rejected before commit, its tentative candidate-WHEAT requirement disappears as well.

---

# 14. CentralPlanner contract

CentralPlanner continues to own the shared engine limit:

```text
MAX_MARKET_ORDERS = 10
```

Current CentralPlanner independently ranks and selects the top candidates under that shared cap.

Phase C adds two rules.

First:

```text
existing-herd protected WHEAT
```

is a hard-protected purchase class.

It must rank ahead of:

```text
land
optional wheat
seeds
animals
```

and must not be displaced by new livestock.

Second, after selection apply dependency closure:

```text
if selected animal requires proposal X
and proposal X was not selected:
    drop animal
```

Dropping the animal is always safe because it releases resources.

Do not automatically restore some different animal.

Do not ask CentralPlanner to recalculate feed.

---

# 15. Reserved-WHEAT sales

Current CentralPlanner blocks WHEAT sales only when it detects a **P0 critical** feed-WHEAT purchase.

That is insufficient for Phase C.

In live mode:

```text
WHEAT reserved by FeedFeasibility for existing-herd support
```

cannot be sold merely because the shortage is P1 instead of P0.

OrderBuilder/FeedFeasibility should expose the protected quantity/semantic identity.

CentralPlanner only enforces:

```text
sellable_wheat
=
observed/releasable wheat
-
protected_wheat_reservation
```

No feed projections belong in CentralPlanner.

---

# 16. Purchase priority preservation in CentralPlanner

Land and animal orders currently can both become `P2_STRATEGIC`.

Phase C should preserve OrderBuilder's semantic purchase ordering inside arbitration.

Use metadata/subpriority rather than recalculating strategy:

```text
protected existing feed
>
land
>
optional wheat
>
seeds
>
animals
```

This ensures a candidate feed reservation can never cause an animal to survive while its higher-priority land order is arbitrated away simply because both appeared as generic P2 candidates.

CentralPlanner remains an arbitrator, not a strategist.

---

# 17. Market-stage shed capacity

OrderBuilder currently starts from the shed occupancy in the observation and subtracts incoming WHEAT/animal capacity.

C2 should use the **post-unit-action** market-stage state.

The execution snapshot should therefore expose enough deterministic information to derive:

```text
shed occupancy after actual PICKUP/DROP unit actions
actual same-turn PLACE effects
worker-carried inventory after those actions
```

No movement prediction is needed.

Only emitted actions are applied.

Seeds remain separate and do not consume shed capacity.

---

# 18. Hour-23 rollover capacity

At Hour 23, also reserve capacity for inventory that will automatically return from workers at end-of-day.

Use:

```text
post-market shed load
+
worker rollover units remaining after actual unit actions
<=
SHED_CAPACITY
```

At minimum, protected carried WHEAT must not be destroyed by a new animal purchase.

Prefer accounting for all known worker-carried items, since they share the rollover capacity.

Therefore this failure:

```text
shed = 99
worker carries 1 WHEAT
BUY_ANIMAL = 1
```

must reject the new animal at Hour 23.

The animal must not cause the worker's existing inventory to be discarded.

---

# 19. Actual retained protected WHEAT

Do not trust the originally requested protected quantity when computing the final feed hold.

Example:

```text
Macro requests 5 protected WHEAT

cash / storage / slots retain only 3
```

The live ledger must contain:

```text
3 retained WHEAT
```

not five.

Then recompute:

```text
existing-herd feasibility
remaining existing-herd feed hold
```

against three.

If the existing herd remains underfunded:

```text
new livestock = 0
```

but the three survival WHEAT units still remain in the order stream.

---

# 20. Optional WHEAT

Optional WHEAT sits above seeds/animals but below land.

Once actually retained, add it to the live ledger before candidate replay.

It may reduce future market-feed liability, but its current purchase cost must simultaneously count as current spending.

Again:

```text
physical credit
+
cash spending
```

must be applied together.

Do not add the physical WHEAT while forgetting the purchase cost.

Do not subtract its cost while leaving the old future feed liability unchanged.

---

# 21. Phase-C failure isolation

This current pattern must not survive Phase C:

```python
try:
    compile_all_purchases()
except Exception:
    purchase_orders = []
```

because the current `main.py` does exactly that.

Live behavior should instead be:

```text
core survival purchases compile
        ↓
Phase-C livestock stage runs separately
        ↓
livestock exception
        ↓
drop livestock only
        ↓
keep protected existing-herd WHEAT
```

If the live evaluator, candidate metadata or candidate pricing fails:

```text
BUY_ANIMAL = none
```

Existing-herd survival continues.

No Phase-C error may silently switch back to legacy animal authorization.

---

# 22. Catastrophic builder fallback

If even the full live builder fails unexpectedly, use a restricted recovery path:

```text
survival-only market compilation
```

It may retain:

```text
protected existing-herd WHEAT
other genuinely mandatory survival orders
```

but:

```text
no new livestock
```

Do not make the old animal buyer the exception fallback.

---

# 23. Rollback modes

Final behavior remains exactly:

```text
POINT2_FEED_MODE = "shadow"

Phase-A diagnostics
legacy forward/live livestock behavior
```

```text
POINT2_FEED_MODE = "herd_plan"

Phase-B DynamicHerdPlan ledger authority
legacy live BUY_ANIMAL behavior
```

```text
POINT2_FEED_MODE = "live"

Phase-B forward ledger authority
+
Phase-C final live BUY_ANIMAL authority
```

An exception never changes mode.

It merely fails closed for new livestock.

---

# 24. C1 / C2 implementation split

## C1 — contracts and provisional candidate preparation

C1 should modify mainly:

```text
macro_planner.py
feed_feasibility.py
tests
```

C1 creates:

```text
ordered buy_animal_sequence
provisional candidate diagnostics
candidate IDs / reservation metadata contract
existing-feed-hold diagnostics
```

C1 must **not activate new live BUY_ANIMAL enforcement**.

OrderBuilder remains old authority during C1.

This makes C1 independently auditable.

## C2 — actual live enforcement

C2 modifies mainly:

```text
feed_feasibility.py
task_scheduler.py only if needed to expose existing action evidence
main.py
order_builder.py
central_planner.py
tests
```

C2 implements:

```text
verified execution snapshot
post-unit-action state
fresh live ledger
actual retained protected-feed accounting
existing-feed treasury hold
Hour-1 treasury integration
sequential candidate replay
housing reservations
shed + rollover reservations
dependency metadata
CentralPlanner dependency preservation
failure isolation
```

Only after all C2 tests pass does:

```text
POINT2_FEED_MODE = "live"
```

represent complete Phase-C authority.

---

# 25. Essential acceptance invariants

Phase C is complete only when all of these hold:

```text
Existing herd can never lose feed funding because of:
land
optional wheat
seeds
or animals.

An assigned-but-moving FEED worker is never considered executed feed.

Candidate N can use only resources remaining after accepted candidates 1..N-1.

Rejected candidate reservations disappear completely.

Macro candidate reservations are never double-imported into OrderBuilder.

No candidate can survive if a required market dependency was removed.

Protected existing-herd WHEAT cannot be sold.

Post-Day12 buying never uses planned housing.

Current-turn protected WHEAT spending and future feed hold never fund the same units twice.

Hour-23 animal buying cannot destroy carried protected inventory at rollover.

A livestock exception removes livestock, not survival purchases.

shadow/herd_plan live behavior remains unchanged.
```

# Final Phase-C status

```text
PHASE C ARCHITECTURE: RECONCILED / READY TO IMPLEMENT

Frozen baseline:
f39b778dcb4ce83eea3c5c0456a116e79a5795f9

Next:
Phase C1 implementation only

Do not implement C2 in the same commit.
```
