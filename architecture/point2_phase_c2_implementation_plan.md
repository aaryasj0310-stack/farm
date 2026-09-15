# Point 2 — Phase C2 Implementation Plan

Base commit:

`7425240682bdadaea6e2f1ee9258bf63150057c1`

Phase C1 is frozen.

Phase C2 activates the new feed-ledger architecture for **real live `BUY_ANIMAL` execution**.

---

# 1. Phase C2 Goal

Make new livestock purchases pass a final live safety check using:

```text
current observation
+
actual scheduler actions
+
actual retained market commitments
+
fresh FeedResourceLedger
+
actual residual housing/storage/cash
```

The final path becomes:

```text
MacroPlanner
→ provisional buy_animal_sequence
→ build_tasks
→ assign_tasks
→ verified FeedExecutionSnapshot
→ OrderBuilder live ledger
→ higher-priority purchases
→ sequential animal revalidation
→ CentralPlanner dependency-preserving arbitration
→ final market orders
```

Macro remains provisional.

OrderBuilder becomes the final `BUY_ANIMAL` authority.

---

# 2. Files Expected to Change

Main runtime files:

```text
agent/strategy/feed_feasibility.py
agent/market/order_builder.py
agent/strategy/central_planner.py
agent/main.py
```

Possibly:

```text
agent/execution/task_scheduler.py
```

but only if additional existing scheduler output must be exposed for snapshot construction.

Tests:

```text
agent/tests/test_feed_feasibility.py
agent/tests/test_order_builder.py
agent/tests/test_central_planner.py
```

or equivalent existing suites.

Then synchronize:

```text
submission/
dist/submission.zip
```

Do not modify Phase-B planning logic unless required for wiring.

---

# 3. Rollout Boundary

Preserve exact behavior:

```text
POINT2_FEED_MODE = "shadow"
→ legacy live BUY_ANIMAL

POINT2_FEED_MODE = "herd_plan"
→ Phase-B forward ledger authority
→ legacy live BUY_ANIMAL

POINT2_FEED_MODE = "live"
→ Phase-B forward ledger authority
→ Phase-C2 live BUY_ANIMAL authority
```

Only `live` activates C2.

An exception must never silently fall back to legacy animal buying.

---

# 4. C2.1 — Strengthen FeedExecutionSnapshot

Current snapshot is not trustworthy enough for live authorization because an assigned FEED task may emit movement rather than `FEED`.

Extend snapshot construction to inspect:

```text
assignment
+
actual emitted actions
```

For each currently unfed placed animal determine whether a distinct unit actually emits:

```text
FEED
```

toward that animal this turn.

Add diagnostics such as:

```text
unfed_placed_today
verified_feed_targets
verified_feed_count
feed_assignments
feed_actions_emitted
actual_place_actions
actual_pickups
actual_drops
post_unit_worker_inventory
post_unit_shed_delta
snapshot_stale / snapshot_valid
```

Do not create another pathfinder.

A worker moving toward an animal is not certified feeding.

---

# 5. Live Execution Rule

In `POINT2_FEED_MODE == "live"`:

```text
if Phase-C evaluation fails:
    reject new livestock

elif unfed_placed_today > 0:
    if snapshot missing:
        reject new livestock
    elif execution_confidence != "high":
        reject new livestock
    elif not every due feed target has an actual emitted FEED action:
        reject new livestock

else:
    execution confidence alone does not veto expansion
```

Reason:

```text
feed_execution_unverified
```

Existing-herd survival actions continue regardless.

---

# 6. Hour 22 / Hour 23 Timing

Preserve engine order:

```text
unit actions
→ market actions
→ town
→ end-of-day
```

Therefore:

```text
market WHEAT bought at Hour H
cannot help the unit action already emitted at Hour H
```

At Hour 23:

```text
unresolved current-day feed
→ cannot be rescued by market WHEAT
→ no new BUY_ANIMAL
```

At Hour 22, if rescue still requires:

```text
BUY_WHEAT
→ future PICKUP
→ future FEED
```

do not certify current herd as safe.

---

# 7. C2.2 — Build Fresh Live Feed Ledger

OrderBuilder must not import Macro's provisional candidate reservations.

When live livestock evaluation starts:

```text
build fresh FeedResourceLedger
from current observation
```

Use:

```text
engine_stress_bound_v1
```

for lifetime funding.

Use:

```text
estimate_wheat_buy_price(ctx)
```

for current executable WHEAT.

Attach the real `FeedExecutionSnapshot`.

Macro C1 diagnostics remain telemetry only.

---

# 8. Existing-Herd First Claim

Before evaluating any new animal:

```text
evaluate_existing_herd_feasibility(live_ledger)
```

If existing herd is infeasible:

```text
BUY_ANIMAL = 0
```

but:

```text
protected WHEAT recovery orders remain active
```

No new livestock may be used to justify or repair existing-herd feed funding.

---

# 9. Existing-Herd Treasury Hold

Introduce live treasury handling for:

```text
remaining_existing_feed_hold
```

The invariant is:

```text
observed_cash
-
actual retained current-turn spending
-
other hard reserves
-
remaining_existing_feed_hold
-
accepted_candidate_feed_holds
>= 0
```

Important distinction:

```text
protected WHEAT purchased now
!=
remaining future feed hold
```

When protected WHEAT is actually retained:

```text
cash decreases
physical feed supply increases
future feed liability is recomputed
remaining_existing_feed_hold is recomputed
```

Never charge the same liability twice.

---

# 10. Higher-Priority Purchase Order

Before evaluating animals, process the authoritative non-animal purchase prefix:

```text
mandatory commitments
→ protected existing-herd WHEAT
→ recompute existing-herd hold
→ land
→ optional WHEAT
→ seeds
→ animals
```

Candidate feed reservations must not block higher-priority land/seeds.

Existing-herd feed funding may block them.

---

# 11. Remove Hour-1 Treasury Bypass

Current Hour-1 land logic must not bypass Phase-C treasury protection.

In `live` mode:

```text
BUY_LAND
```

must go through the same OrderBuilder protected-cash calculation.

Do not duplicate feed accounting in `main.py`.

For `shadow` and `herd_plan`, preserve historical Hour-1 behavior.

---

# 12. Actual Retained Protected WHEAT

Do not build livestock feasibility from requested WHEAT.

Use only the quantity that survives:

```text
cash trimming
shed capacity
order-slot constraints
```

Example:

```text
requested protected wheat = 5
retained = 3
```

The live ledger gets:

```text
3 market WHEAT units
```

Then recompute existing-herd feasibility.

If the herd remains underfunded:

```text
animals = rejected
protected 3 WHEAT still executes
```

---

# 13. Optional WHEAT

Optional WHEAT is below land and above seeds/animals.

If retained:

```text
add its physical supply
subtract its actual current cost
recompute applicable future feed liability
```

Do not give physical feed credit without charging the cash.

Do not charge the cash and leave the old liability unchanged.

---

# 14. Sequential Candidate Replay

Use C1:

```text
plan.intents["buy_animal_sequence"]
```

as the provisional ordering.

Do not sort species.

Replay candidates one unit at a time:

```text
for species in buy_animal_sequence:
    clone accepted live ledger
    evaluate candidate
    check economics
    check execution safety
    check housing
    check shed capacity
    check cash
    check market order slots
    commit only if all gates pass
```

Only accepted predecessors affect later candidates.

---

# 15. Candidate Rejection Semantics

Candidate evaluation must be transactional.

For candidate N:

```text
trial = accepted_ledger.clone()
```

If candidate fails:

```text
discard trial
```

Therefore rejection releases:

```text
purchase cash
feed hold
market feed requirement
shed slot
housing slot
stress repricing delta
```

Candidate N+1 evaluates against:

```text
existing herd
+
higher-priority actual orders
+
accepted candidates only
```

Never allow stale reservations from rejected candidates.

---

# 16. Candidate Feed Stress Repricing

After every accepted candidate:

```text
recompute engine_stress_bound_v1
```

The new stress price must apply to all still-unfunded committed feed liabilities.

Invariant:

```text
total existing + accepted-candidate feed reserve
>=
total applicable feed funding requirement
at latest stress price
```

Candidate #2 cannot raise the stress price while leaving candidate #1 underfunded.

---

# 17. Candidate Economic Authority

Do not move economics into FeedFeasibility.

Keep:

```text
FeedFeasibility
→ physical/cash supportability

MarginalLivestockValuator
→ profitability
```

Feed reserve and EV feed cost are different concepts.

Do not remove feed cost from EV because feed cash is reserved.

Do not subtract feed opportunity cost twice.

---

# 18. Final Housing Gate

Create one shared final live housing check.

For each candidate determine compatible structure:

```text
COW   → PASTURE
SHEEP → PASTURE
GOOSE → COOP
```

Available housing:

```text
physically empty compatible structures
-
structures reserved for existing unplaced compatible animals
-
structures consumed by actual PLACE actions this turn
-
structures committed to earlier accepted candidates
```

At Day >= 12:

```text
planned structures = zero credit
queued structures = zero credit
future structures = zero credit
same-turn BUILD = zero late-purchase credit
```

Late housing must already exist in the observation.

---

# 19. Same-Turn PLACE Handling

Use actual emitted PLACE actions, not assigned PLACE intentions.

Actual PLACE changes:

```text
housing occupancy
animal storage
placed/unplaced state
```

before the market phase.

Reflect these changes in the live OrderBuilder state.

Do not automatically classify every same-turn PLACE as requiring same-day feeding unless engine evidence explicitly requires it.

---

# 20. Shed Capacity

Final candidate admission must use residual shed capacity after:

```text
current shed contents
actual unit PICKUP/DROP effects
retained protected WHEAT
retained optional WHEAT
accepted earlier animals
other incoming shed products
```

A candidate animal reserves one shed slot until placement.

Example:

```text
shed = 99
retained WHEAT = 1
candidate animal = 1
```

Candidate must fail.

---

# 21. Hour-23 Rollover Protection

At Hour 23 workers automatically return carried inventory to the shed.

Therefore require:

```text
post-market shed occupancy
+
worker inventory that will roll over
<= SHED_CAPACITY
```

At minimum, protected carried WHEAT must never be destroyed by a new animal purchase.

Prefer accounting for all known worker-carried shed items.

Example:

```text
shed = 99
worker carries 1 WHEAT
animal purchase = 1
```

Reject animal.

---

# 22. Candidate Market-WHEAT Dependency

If a candidate requires extra near-term WHEAT, treat:

```text
candidate
+
candidate-required WHEAT
```

as a dependency group.

OrderBuilder owns the feed mathematics.

Attach metadata such as:

```text
candidate_id
dependency_group
requires_proposal_ids
```

Do not make CentralPlanner calculate WHEAT requirements.

---

# 23. CentralPlanner Dependency Preservation

CentralPlanner still owns the shared:

```text
MAX_MARKET_ORDERS = 10
```

After selecting market proposals:

```text
if animal selected
and required dependency not selected:
    drop animal
```

Never retain the animal while dropping required WHEAT.

Dropping an animal is allowed.

Do not automatically replace it with a later rejected animal during arbitration.

---

# 24. Protected WHEAT Sales

Existing-herd reserved WHEAT cannot be sold.

Current behavior only blocks some critical-WHEAT conflicts.

C2 should expose a protected WHEAT quantity or reservation identity.

CentralPlanner then enforces:

```text
sellable_wheat
=
available_wheat
-
protected_existing_herd_wheat
```

CentralPlanner must not calculate future feed demand itself.

---

# 25. Arbitration Priority

Preserve semantic order:

```text
existing-herd protected feed
>
land
>
optional WHEAT
>
seeds
>
animals
```

Do not let generic `P2_STRATEGIC` classification erase that ordering.

Use explicit metadata/subpriority if necessary.

A new animal must never displace existing-herd survival feed.

---

# 26. Market Order Slot Accounting

Candidate admission must know whether an actual slot is available.

If accepting a candidate requires:

```text
1 animal order
+
1 candidate-feed WHEAT order
```

both required slots must be available.

Do not reserve feed/cash for a candidate whose actual dependency package cannot fit under the shared market-order cap.

---

# 27. Main.py Wiring

After:

```text
build_tasks
assign_tasks
```

construct the enhanced snapshot using:

```text
ctx
tasks
assignment
actual emitted actions
```

Pass the snapshot into the live market build path.

Do not duplicate feasibility logic in `main.py`.

`main.py` should only:

```text
wire data
select mode
isolate failures
```

---

# 28. Failure Isolation

Phase C must isolate livestock evaluation from survival purchase compilation.

Do not keep:

```text
try:
    build all purchases
except:
    purchase_orders = []
```

for live C2.

Instead:

```text
compile survival / protected purchases
↓
attempt live livestock stage
↓
if livestock stage fails:
    drop new livestock
    keep survival purchases
```

Any of these failures:

```text
ledger construction failure
execution snapshot failure
candidate evaluation exception
pricing exception
bad sequence metadata
housing evaluation exception
dependency metadata failure
```

must result in:

```text
no new BUY_ANIMAL
```

not:

```text
no protected WHEAT
```

---

# 29. No Legacy Fallback in Live Mode

In `POINT2_FEED_MODE == "live"`:

```text
Phase-C failure
```

must never activate:

```text
legacy animal buying
```

Correct fallback:

```text
survival-only / non-livestock safe path
```

For `shadow` and `herd_plan`, legacy live animal behavior remains intentionally unchanged.

---

# 30. Required Diagnostics

Expose enough telemetry to audit live decisions:

```text
point2_live_authority
existing_herd_feasible
remaining_existing_feed_hold
retained_protected_wheat
retained_optional_wheat
execution_confidence
verified_feed_targets
candidate_sequence_requested
candidate_sequence_accepted
candidate_sequence_rejected
candidate_rejection_reasons
candidate_feed_holds
candidate_purchase_cash
candidate_required_wheat
housing_remaining
shed_capacity_remaining
market_slots_remaining
dependency_drops
live_failure_reason
```

Diagnostics must not become authority themselves.

---

# 31. Essential Unit Tests

Add tests for at least:

### Execution

```text
assigned FEED but emitted MOVE → not high
actual FEED → certified
missing snapshot + unfed herd → no animal
guarded snapshot + unfed herd → no animal
all currently fed → guarded alone does not veto
Hour 23 unresolved feed → no animal
Hour 22 requires buy→pickup→feed → no animal
```

### Treasury

```text
existing-feed hold blocks land
existing-feed hold blocks Hour-1 land
existing-feed hold blocks seeds/animals
protected WHEAT purchase reduces future hold correctly
no double reservation of same WHEAT liability
```

### Sequential candidates

```text
candidate #1 accepted reduces #2 resources
candidate #1 rejected releases everything
candidate #2 cannot reuse #1 cash/feed/storage/housing
candidate #2 stress repricing also re-funds prior liabilities
interleaved SHEEP/COW/SHEEP order preserved
```

### Housing

```text
post-Day12 planned pasture gives zero credit
physical empty pasture permits candidate
shed animal reserves compatible pasture
carried animal reserves compatible pasture
actual same-turn PLACE consumes structure
COW/SHEEP share pasture capacity correctly
GOOSE uses coop only
```

### Shed

```text
99/100 + WHEAT + animal cannot both fit
retained WHEAT consumes shed room
accepted candidate consumes shed room
Hour23 worker rollover prevents animal overflow
seeds do not consume shed storage
```

### Arbitration

```text
protected feed outranks animals
reserved WHEAT cannot be sold
dependency WHEAT dropped → animal dropped
shared cap cannot drop survival feed for animal
animal dependency closure does not invoke feed math
```

### Failure behavior

Inject failures in:

```text
snapshot
ledger build
candidate evaluation
price helper
housing check
dependency processing
```

and verify:

```text
new animals = 0
protected survival orders remain
```

---

# 32. Regression Tests

Mandatory:

```text
POINT2_FEED_MODE=shadow
→ exact frozen live behavior

POINT2_FEED_MODE=herd_plan
→ exact frozen Phase-B live behavior
```

Run existing Point-2 tests.

Run full non-slow suite.

Run 720-step regression.

Also run at least one `live` 720-step season and capture diagnostics for:

```text
animal purchases
feed failures
candidate rejection reasons
protected wheat retention
land timing
final herd
reward
```

---

# 33. Implementation Split Inside C2

Do not implement all C2 in one uncontrolled change.

Recommended:

## C2A — Execution + Treasury Foundation

Implement:

```text
verified FeedExecutionSnapshot
main snapshot wiring
fresh live ledger
existing-herd hold
Hour-1 treasury integration
failure isolation
```

No candidate dependency/arbitration changes yet.

Freeze after audit.

## C2B — Sequential Live Candidate Authority

Implement:

```text
buy_animal_sequence replay
candidate transaction semantics
housing
shed
rollover
stress repricing
actual BUY_ANIMAL authorization
```

Freeze after audit.

## C2C — Arbitration Dependency Closure

Implement:

```text
candidate dependency metadata
protected-WHEAT sale protection
market-slot dependency closure
semantic priority preservation
```

Then perform final Phase-C regression.

---

# 34. Final Phase-C Acceptance

Phase C is complete only when:

```text
existing herd cannot lose feed because of expansion

assigned-but-moving FEED is never certified as executed

live animal buying uses a fresh ledger

Macro candidate reservations are never imported as live commitments

rejected candidates release all resources

later candidates use only residual resources

post-Day12 housing is physically observed

shed overflow cannot destroy protected inventory

candidate dependencies survive arbitration or candidate is dropped

reserved existing-herd WHEAT cannot be sold

Phase-C failures block animals but preserve survival

shadow/herd_plan remain behaviorally frozen
```

---

# 35. Stop Conditions

Do not proceed to C2B if C2A changes `shadow` or `herd_plan` live behavior.

Do not proceed to C2C if sequential candidate accounting is not transactionally correct.

Do not enable `POINT2_FEED_MODE="live"` for production until C2A+C2B+C2C are all audited and frozen.

---

# Phase C2 Starting Status

```text
Phase A
FROZEN

Phase B
FROZEN

Phase C1
FROZEN
7425240682bdadaea6e2f1ee9258bf63150057c1

Phase C2
READY TO IMPLEMENT

Recommended next commit:
C2A — Execution + Treasury Foundation
```
