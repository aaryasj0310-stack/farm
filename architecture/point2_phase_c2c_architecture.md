# Point 2 — Phase C2C Architecture

## Arbitration Dependency Closure

---

# 1. Status

```text
Phase A      COMPLETE / FROZEN
Phase B      COMPLETE / FROZEN
Phase C1     COMPLETE / FROZEN
Phase C2A    COMPLETE / FROZEN
Phase C2B    COMPLETE / FROZEN

Phase C2C    READY TO IMPLEMENT
```

Frozen C2B base:

`70050356e838a0dc67221b44de1fbd773b4a1bf9`

Authoritative earlier documents:

```text
architecture/point2_phase_c_architecture.md
architecture/point2_phase_c2_implementation_plan.md
architecture/point2_phase_c2b_architecture.md
```

C2C is the final **Point-2 safety-closure phase**.

Do not redesign C2B.

---

# 2. Purpose

C2B makes `OrderBuilder` produce a safe set of livestock purchases.

C2C guarantees that downstream global market arbitration cannot invalidate those decisions.

The final pipeline becomes:

```text
Observation
    ↓
MacroPlanner
    ↓
C2B OrderBuilder
    ↓
safe purchase proposals
+ explicit resource dependencies
+ protected feed reservation
    ↓
C2C CentralPlanner
    ↓
global 10-slot arbitration
    ↓
dependency closure
    ↓
protected-WHEAT sale enforcement
    ↓
final engine market orders
```

The central invariant is:

> A BUY_ANIMAL order may reach the engine only if every current-turn resource proposal that C2B relied upon also reaches the engine, and market sales must not consume physical WHEAT reserved by the authoritative feed ledger.

---

# 3. Problem C2C Solves

C2B can approve an animal using:

```text
post-unit physical WHEAT
retained protected WHEAT purchase
retained optional WHEAT purchase
cash residual
housing
shed capacity
market-slot assumptions
```

But CentralPlanner subsequently sees:

```text
purchase orders
+
sell orders
```

and applies its own global 10-order arbitration.

Without dependency closure it can produce:

```text
C2B:
optional WHEAT retained
SHEEP accepted because that WHEAT exists

CentralPlanner:
drops optional WHEAT because of slot pressure
keeps SHEEP

Engine:
SHEEP purchased without the feed plan used to authorize it
```

That is forbidden.

Likewise:

```text
C2B:
physical WHEAT is reserved for herd

MarketBrain:
proposes SELL WHEAT

CentralPlanner:
allows sale because protected BUY WHEAT is not P0

Engine:
reserved physical feed is sold
```

That is also forbidden.

---

# 4. C2C Is Not Another Feed Planner

CentralPlanner must not:

```text
re-run FeedFeasibility
re-price lifetime feed
re-evaluate candidate economics
change housing decisions
reorder candidate sequence
replace rejected candidates
search for alternative WHEAT plans
```

C2C operates only on declarations produced by upstream authority.

Authority remains:

```text
FeedFeasibility
    feed / funding truth

MarginalLivestockValuator
    economic truth

C2B OrderBuilder
    candidate admission truth

CentralPlanner
    dependency preservation
    global slot arbitration
    protected-sale enforcement
```

CentralPlanner answers:

```text
"Can this already-approved package survive final arbitration?"
```

not:

```text
"Should this animal have been approved?"
```

---

# 5. Production Rollout Boundary

During C2C implementation keep:

```python
POINT2_FEED_MODE = "shadow"
```

Do not enable production `live` in the C2C implementation commit.

C2C must first be:

```text
implemented
tested
audited
PASS / FROZEN
```

Only after that should production activation be considered in a separate minimal rollout commit.

---

# 6. C2C Activation Boundary

C2C dependency rules apply only when:

```text
POINT2_FEED_MODE == "live"
```

For:

```text
shadow
herd_plan
```

preserve existing CentralPlanner behavior.

Do not change historical experiment behavior outside `live`.

---

# 7. Live Mode May Not Bypass C2C

This is mandatory.

Current market composition can choose between:

```text
legacy composition
CentralPlanner
```

depending on arbitration mode.

Once:

```text
POINT2_FEED_MODE == "live"
```

new livestock safety depends on C2C.

Therefore live Point-2 mode may not execute through an unsafe legacy composition path.

Required rule:

```text
IF POINT2_FEED_MODE == "live":
    dependency-safe CentralPlanner path is mandatory
ELSE:
    preserve existing arbitration-mode behavior
```

Do not silently route live C2B livestock through:

```text
legacy_compose_market(...)
```

---

# 8. C2C Dependency Contract Version

OrderBuilder must expose an explicit contract:

```python
dependency_contract_version = "point2_c2c_v1"
```

Only live mode emits this contract.

Example ledger:

```python
ledger["dependency_contract_version"] = "point2_c2c_v1"
```

CentralPlanner treats:

```text
live mode + missing/invalid C2C contract
```

as a fail-closed condition for livestock.

Do not interpret missing metadata as:

```text
"animal has no dependencies"
```

---

# 9. Stable Resource Keys

CentralPlanner proposal IDs are assigned after proposals arrive.

Therefore OrderBuilder must not try to predict:

```text
purchase:0
purchase:1
...
```

Instead use stable upstream resource keys.

C2C v1 defines:

```text
wheat:protected
wheat:optional
```

These identify the current-turn WHEAT proposals retained by C2B.

---

# 10. Protected WHEAT Resource Metadata

The emitted protected WHEAT order metadata should include:

```python
{
    "kind": "wheat_protected",
    "feed_class": "protected",
    "is_protected": True,
    "resource_key": "wheat:protected",
    "resource_role": "feed_resource",
    "hard_required": True,
    "reservation_scope": "feed_authority",
    ...
}
```

There should be at most one current-turn:

```text
resource_key = wheat:protected
```

proposal.

---

# 11. Optional WHEAT Resource Metadata

The optional retained WHEAT order should include:

```python
{
    "kind": "wheat_optional",
    "feed_class": "optional",
    "is_protected": False,
    "resource_key": "wheat:optional",
    "resource_role": "feed_resource",
    "hard_required": False,
    ...
}
```

There should be at most one:

```text
resource_key = wheat:optional
```

proposal.

---

# 12. Why Stable Resource Keys Instead of Proposal IDs

OrderBuilder runs before CentralPlanner.

OrderBuilder knows:

```text
what the resource means
```

but not:

```text
what CentralPlanner index it will receive
```

CentralPlanner later resolves:

```text
resource_key
    ↓
proposal_id
```

Example:

```text
wheat:protected → purchase:4
wheat:optional  → purchase:6
```

CentralPlanner may expose resolved:

```python
requires_proposal_ids
```

in diagnostics, but that mapping is downstream-only.

---

# 13. Candidate Dependency Metadata

Every C2B-accepted candidate should internally carry:

```text
candidate_id
species
requires_resource_keys
```

Example:

```python
{
    "candidate_id": "cand_2_SHEEP",
    "species": "SHEEP",
    "requires_resource_keys": [
        "wheat:protected",
        "wheat:optional",
    ],
}
```

---

# 14. C2C v1 Uses Conservative Dependencies

Do not perform a new counterfactual feed optimization to ask:

```text
"Would this candidate still have passed without optional WHEAT?"
```

That would turn C2C into another feed planner.

Instead:

> If a candidate was evaluated against a live C2B ledger containing a retained current-turn WHEAT resource, C2C v1 conservatively declares that resource a dependency.

Therefore:

```text
retained protected WHEAT > 0
→ accepted candidate requires wheat:protected

retained optional WHEAT > 0
→ accepted candidate requires wheat:optional
```

This may occasionally be over-conservative.

It is safe.

Optimization can happen later with separate evidence.

---

# 15. Candidate Dependency Capture Occurs at Acceptance

When C2B accepts candidate N:

```python
candidate_dependencies = []

if w_protected_buyable > 0:
    candidate_dependencies.append("wheat:protected")

if w_opt_buyable > 0:
    candidate_dependencies.append("wheat:optional")
```

Store that on:

```text
accepted_candidates
candidate_decisions
```

Do not reconstruct dependencies later from species.

---

# 16. Grouped BUY_ANIMAL Metadata

C2B consolidates accepted candidates of one species into one engine order.

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

Each grouped order must expose:

```python
{
    "kind": "animal",
    "animal": "SHEEP",
    "n": 2,
    "candidate_ids": [
        "cand_0_SHEEP",
        "cand_2_SHEEP",
    ],
    "dependency_group": "animal:SHEEP:0",
    "requires_resource_keys": [
        ...
    ],
}
```

---

# 17. Group Dependency Is the Union

If two same-species candidates are grouped:

```text
candidate A requires wheat:protected
candidate B requires wheat:protected + wheat:optional
```

the grouped order requires:

```text
wheat:protected
wheat:optional
```

If optional WHEAT disappears, the **entire grouped animal order is dropped**.

Do not partially reduce:

```text
BUY_ANIMAL SHEEP 2
```

to:

```text
BUY_ANIMAL SHEEP 1
```

inside C2C.

That would require replaying C2B accounting and market-slot semantics.

C2C v1 intentionally chooses conservative whole-group rejection.

---

# 18. Non-Feed Purchases Are Not Animal Dependencies

Do not make animals depend on:

```text
land
seeds
hires
fertilizer
```

merely because those purchases were part of C2B's cash prefix.

Why:

```text
dropping them releases cash
```

which cannot make the accepted livestock less financially feasible.

The only current-turn positive resource proposals requiring closure in C2C v1 are retained WHEAT resources.

---

# 19. Physical WHEAT Is Also a Resource

Candidate safety may rely on WHEAT already physically owned.

That dependency cannot be represented as a market proposal.

Therefore C2C also needs a:

```text
feed sale reservation
```

that prevents final WHEAT sales from removing physical feed that C2B relied upon.

---

# 20. Feed Sale Reservation Authority

FeedFeasibility / OrderBuilder, not CentralPlanner, computes:

```text
how much post-unit shed WHEAT is releasable
```

CentralPlanner only enforces the number.

Create a helper in:

```text
feed_feasibility.py
```

conceptually:

```python
derive_feed_sale_reservation(...)
```

No equivalent formula should be reimplemented in CentralPlanner.

---

# 21. Reservation Must Include Accepted Candidates

Do not protect only the existing herd.

C2B candidates may be feasible partly because of current physical WHEAT.

Therefore the final reservation represents:

```text
existing herd
+
all C2B-accepted candidates
```

under the final C2B operational feed plan.

---

# 22. Final Operational Minimum Slack

Track:

```text
final_operational_min_wheat_slack
```

during C2B.

Initialize it from the final existing-herd prefix result.

If candidate N is accepted:

```text
final_operational_min_wheat_slack
    = candidate_N_result.minimum_wheat_slack
```

Because candidate N was evaluated after all prior accepted candidates, the last accepted candidate's slack represents the cumulative accepted set.

If no candidate is accepted:

```text
use existing-herd result minimum_wheat_slack
```

If candidate replay is rolled back due exception:

```text
restore baseline existing-herd slack
```

---

# 23. Deriving Releasable On-Hand WHEAT

Let:

```text
current_total_wheat_on_hand =
    post_unit_shed_wheat
    +
    post_unit_worker_wheat
```

Let:

```text
slack =
    final_operational_min_wheat_slack
```

The maximum existing on-hand quantity safely releasable is:

```text
releasable_total_on_hand =
    min(
        current_total_wheat_on_hand,
        max(0, floor(slack))
    )
```

Use a tiny numeric tolerance if required.

---

# 24. Required On-Hand WHEAT

Then:

```text
required_total_on_hand =
    current_total_wheat_on_hand
    -
    releasable_total_on_hand
```

This is the physical on-hand WHEAT still participating in the accepted feed plan.

---

# 25. Worker WHEAT Gets First Protection

Worker-held WHEAT is not sellable from the shed.

Therefore assign required physical WHEAT to workers first.

```text
protected_worker_wheat =
    min(
        post_unit_worker_wheat,
        required_total_on_hand
    )
```

Then:

```text
protected_shed_wheat =
    required_total_on_hand
    -
    protected_worker_wheat
```

Clamp:

```text
0 <= protected_shed_wheat <= post_unit_shed_wheat
```

---

# 26. Authoritative Sellable WHEAT

Finally:

```text
sellable_shed_wheat =
    post_unit_shed_wheat
    -
    protected_shed_wheat
```

This is the only WHEAT quantity CentralPlanner may permit to be sold during live C2C.

---

# 27. Feed Sale Reservation Contract

OrderBuilder should expose:

```python
ledger["feed_sale_reservation"] = {
    "version": "point2_c2c_v1",
    "valid": True,

    "post_unit_shed_wheat": ...,
    "post_unit_worker_wheat": ...,
    "current_total_wheat_on_hand": ...,

    "final_operational_min_wheat_slack": ...,

    "releasable_total_on_hand": ...,
    "required_total_on_hand": ...,

    "protected_worker_wheat": ...,
    "protected_shed_wheat": ...,
    "sellable_shed_wheat": ...,

    "source": "feed_feasibility",
}
```

---

# 28. Invalid Reservation Must Fail Closed

Before Day 29:

```text
live mode
+
feed reservation missing/invalid/unverifiable
```

means:

```text
WHEAT sale allowed = 0
```

Do not guess a safe quantity.

New livestock must also fail dependency safety when the C2C contract is invalid.

---

# 29. Day 29 Exception

Feeding ends after Day 28 under the current feed cutoff.

Therefore on Day 29:

```text
protected feed reservation = 0
```

and final liquidation may sell WHEAT normally.

Do not leave economically worthless WHEAT protected after the feeding horizon has ended.

---

# 30. Candidate Rejection Does Not Release Reservation Mid-Turn

Suppose C2B accepted a candidate and therefore reserved physical WHEAT.

C2C later drops that candidate because an optional WHEAT dependency was not selected.

Do **not** recompute:

```text
protected_shed_wheat
```

inside C2C.

Keep the original C2B reservation for that turn.

This is conservative but preserves the architectural boundary:

```text
CentralPlanner does not rerun feed math
```

---

# 31. Order Metadata Alignment

`purchase_ledger["order_metadata"]` must remain index-aligned with:

```text
purchase_orders
```

For every emitted purchase:

```text
len(order_metadata) == len(purchase_orders)
```

in live mode.

Misalignment means:

```text
dependency contract invalid
```

for livestock safety.

---

# 32. CentralPlanner Metadata Extraction

Add a single helper such as:

```python
_get_upstream_purchase_metadata(
    idx,
    purchase_ledger,
)
```

All purchase classification paths should use it.

Do not implement separate metadata extraction for:

```text
WHEAT
animals
land
seeds
```

where avoidable.

---

# 33. Preserve Upstream Dependency Fields

When constructing `ProposalCandidate.metadata`, preserve validated upstream fields such as:

```text
resource_key
resource_role
hard_required
candidate_ids
dependency_group
requires_resource_keys
tier
feed_class
is_protected
```

CentralPlanner may add its own classification metadata.

It must not erase the dependency contract.

---

# 34. Metadata Must Not Override Structural Truth

Never trust metadata to transform:

```text
BUY_SEED
```

into:

```text
wheat:protected
```

Validate that:

```text
resource_key wheat:protected / wheat:optional
```

belongs only to:

```text
BUY_PRODUCT WHEAT
```

Likewise:

```text
requires_resource_keys
```

only has authority on:

```text
BUY_ANIMAL
```

---

# 35. Dependency Contract Validation

In live mode validate:

```text
dependency_contract_version
order_metadata alignment
resource-key uniqueness
resource-key opcode compatibility
requires_resource_keys type
candidate IDs type
dependency group type
feed sale reservation
```

If dependency metadata is malformed:

```text
contract_valid = False
```

Do not crash.

---

# 36. Duplicate Resource Keys

There must not be two independent proposals with:

```text
resource_key = wheat:protected
```

or:

```text
resource_key = wheat:optional
```

after normalization.

If duplicate keys appear unexpectedly:

```text
dependency contract invalid
```

Do not arbitrarily pick one and authorize animals.

---

# 37. Combined WHEAT Compatibility Fallback

CentralPlanner currently has compatibility logic that may split one combined WHEAT proposal into:

```text
protected
optional
```

C2C must preserve dependency keys during that transformation.

Protected split:

```text
resource_key = wheat:protected
hard_required = True
```

Optional split:

```text
resource_key = wheat:optional
hard_required = False
```

Order metadata must stay aligned after insertion.

---

# 38. OrderBuilder Should Normally Emit Semantically Split WHEAT

The preferred normal C2C path remains:

```text
one protected WHEAT proposal
one optional WHEAT proposal
```

when both exist.

CentralPlanner splitting is compatibility fallback only.

---

# 39. Resolved Proposal IDs

After classification CentralPlanner creates:

```text
resource_key → proposal_id
```

mapping.

Example:

```python
{
    "wheat:protected": "purchase:3",
    "wheat:optional": "purchase:5",
}
```

For animal diagnostics resolve:

```python
requires_proposal_ids = [
    resource_key_to_proposal_id[k]
    for k in requires_resource_keys
    if k exists
]
```

Missing resource keys are recorded explicitly.

---

# 40. Hard Resource Root

The protected existing-feed WHEAT proposal is not merely another P2 proposal.

If valid and present:

```text
wheat:protected
```

is a **hard selection root**.

It must be selected before discretionary ranking subject only to the actual engine cap.

---

# 41. Why Protected WHEAT Cannot Depend Only on P0/P1 Classification

A protected WHEAT buy may be:

```text
routine today
but required by the accepted multi-day feed plan
```

Its feed-survival role is therefore not equivalent to:

```text
immediate starvation urgency
```

C2C separates:

```text
priority
```

from:

```text
dependency protection
```

A protected WHEAT order may remain P2 for diagnostics while still being a hard root.

---

# 42. Hard Root Selection Algorithm

Conceptually:

```text
valid hard roots
    ↓
select first
    ↓
remaining capacity =
    cap - hard roots selected
    ↓
rank remaining independent proposals
    ↓
fill remaining capacity
```

The hard root participates in the engine cap.

It does not create an 11th slot.

---

# 43. At Most One Protected WHEAT Root

C2C v1 expects:

```text
0 or 1
```

protected WHEAT resource proposals.

If more than one appears unexpectedly:

```text
contract invalid
```

rather than silently consuming multiple protected slots.

---

# 44. Cap = 0

If:

```text
cap == 0
```

nothing may execute.

Animals obviously fail dependency closure.

Do not violate the engine cap to preserve a dependency.

---

# 45. General Ranking Remains Intact

C2C is not a general CentralPlanner rewrite.

Preserve existing:

```text
P0
P1
P2
P3
P4
```

global semantics for non-hard-root proposals.

Do not re-tune sale urgency in this phase.

---

# 46. Explicit Purchase Semantic Subpriority

Do not rely only on list position for equal-priority purchase ordering.

Expose a stable purchase semantic subpriority, for example:

```text
protected feed    0
land              1
optional WHEAT    2
seeds             3
animals           4
other             5
```

Protected feed is already a hard root.

For remaining equal-priority purchases this subpriority is an explicit tiebreak.

---

# 47. Hires

Do not redesign hire policy in C2C.

Hires retain their existing priority classification.

The new semantic subpriority mainly exists to preserve the C2B purchase prefix among comparable purchase proposals.

---

# 48. Dependency Closure Happens After Initial Selection

Once initial selected proposals have been chosen:

```text
selected_resources =
    resource keys present in selected proposals
```

Then inspect every selected animal.

For each animal group:

```text
missing =
    requires_resource_keys
    -
    selected_resources
```

If:

```text
missing == empty
```

animal survives.

Otherwise:

```text
drop animal
```

---

# 49. Dependency Rejection Reason

Use explicit:

```text
missing_dependency
```

with metadata:

```python
{
    "missing_resource_keys": [...],
    "required_resource_keys": [...],
    "resolved_required_proposal_ids": [...],
}
```

Do not use generic:

```text
slot_cap
```

for the dependent animal itself.

The resource may have been lost because of `slot_cap`, but the animal is lost because of:

```text
missing_dependency
```

---

# 50. No Replacement Animal

After an animal is removed by dependency closure:

```text
do not promote another animal
do not replay C2B
do not ask Macro for a substitute
```

This was already frozen in the Phase-C architecture.

---

# 51. Do Not Backfill the Vacated Slot

C2C v1 should leave the vacated slot unused.

Example:

```text
initial selection = 10
animal dependency missing
animal removed

final selection = 9
```

Do not automatically select candidate #11.

Why:

```text
candidate #11 was ranked under a different selected-resource set
```

and filling the slot would create another hidden optimization stage.

Conservative unused slot is acceptable.

---

# 52. No Feed Recalculation After Closure

If an animal is dropped:

```text
do not release feed cash
do not release WHEAT sale reservation
do not change stress price
do not re-run FeedFeasibility
```

The whole turn stays conservative.

---

# 53. Optional WHEAT Can Survive Without the Animal

Dependency direction is:

```text
animal → WHEAT
```

not:

```text
WHEAT → animal
```

Therefore if an animal is dropped:

```text
optional WHEAT may remain selected
```

if CentralPlanner selected it independently.

Do not drop resources merely because a dependent was removed.

---

# 54. Protected WHEAT Can Never Be Removed Because Animal Was Removed

Protected WHEAT exists primarily for feed authority.

It remains selected according to hard-root semantics even if:

```text
zero new animals survive
```

---

# 55. Protected WHEAT Sale Enforcement

Replace the old live safety concept:

```text
reject SELL WHEAT only when critical P0 wheat buy exists
```

with:

```text
never sell more than authoritative sellable_shed_wheat
```

in live C2C.

This is independent of whether the protected BUY WHEAT order is classified:

```text
P0
P1
P2
```

---

# 56. Existing P0 Conflict Rule Becomes Secondary

The existing P0 critical WHEAT-buy versus WHEAT-sell conflict may remain as diagnostic/backwards-compatible logic outside live C2C.

Inside live C2C:

```text
feed_sale_reservation
```

is authoritative.

---

# 57. WHEAT Sell Normalization

Before final ranking/selection, process WHEAT sell proposals in original order.

Let:

```text
remaining_sellable_wheat =
    feed_sale_reservation.sellable_shed_wheat
```

For each:

```text
SELL WHEAT q
```

compute:

```text
allowed = min(q, remaining_sellable_wheat)
```

---

# 58. Full WHEAT Sell Rejection

If:

```text
allowed == 0
```

reject the WHEAT sell proposal.

Reason:

```text
protected_feed_reservation
```

---

# 59. Partial WHEAT Sell Trim

If:

```text
0 < allowed < requested
```

normalize the proposal to:

```text
SELL WHEAT allowed
```

and record:

```python
{
    "trimmed_from": requested,
    "trimmed_to": allowed,
    "reason": "protected_feed_reservation",
}
```

Then:

```text
remaining_sellable_wheat -= allowed
```

---

# 60. Multiple WHEAT Sell Proposals

The sum across all normalized WHEAT sell proposals must satisfy:

```text
Σ sell_wheat_qty
<= sellable_shed_wheat
```

This is true even if they came from separate upstream slices.

---

# 61. Use Post-Unit WHEAT State

Do not calculate live sellability from stale:

```text
ctx.private.shed["WHEAT"]
```

when an authoritative C2B post-unit reservation exists.

Use:

```text
feed_sale_reservation.post_unit_shed_wheat
```

because unit actions already executed before market arbitration.

---

# 62. MarketBrain Is Not the Final Feed-Sale Authority

MarketBrain may continue using its existing WHEAT reserve as an upstream heuristic.

C2C correctness does not depend on it.

Final authority is:

```text
C2B feed_sale_reservation
    ↓
CentralPlanner clamp
```

Do not require a MarketBrain redesign in C2C.

---

# 63. Other Product Sales

C2C does not alter sale protection for:

```text
CARROT
TOMATO
STRAWBERRY
MELON
EGG
MILK
WOOL
FERTILIZER
```

unless required by existing CentralPlanner behavior.

Point 2 is feed-WHEAT closure.

---

# 64. Candidate-Required Current-Turn WHEAT

C2B may authorize candidates while retained WHEAT is present.

Animal metadata therefore carries:

```text
requires_resource_keys
```

C2C does not independently inspect:

```text
candidate feed timeline
candidate cash hold
candidate stress price
```

Those were already handled by C2B.

---

# 65. Future Candidate WHEAT Is Not a Current Market Dependency

C2B may schedule future candidate feed requirements in the ledger.

Do not emit all future scheduled purchases immediately.

C2C closure only operates on:

```text
current-turn market proposals
```

Future feed stays a funding reservation handled on later observations.

---

# 66. Candidate Purchase Is Itself Not a Resource

Do not create circular dependency such as:

```text
animal A requires animal A
```

Animal proposal is the dependent.

Current-turn WHEAT proposals are resources.

---

# 67. Final Selection Pipeline

The live C2C pipeline should be:

```text
1. normalize proposals
2. structural validation
3. dependency-contract validation
4. WHEAT sell reservation enforcement
5. ordinary early filters
6. identify hard protected feed root
7. classify/rank remaining proposals
8. select <= global cap
9. resolve resource keys → selected proposal IDs
10. dependency closure on selected animals
11. freeze final selected set
12. safe execution ordering
13. optional WHEAT-buy consolidation
14. diagnostics
```

---

# 68. Dependency Closure Must Precede Execution Reordering

Dependency decisions concern:

```text
selection
```

not:

```text
execution order
```

Therefore complete closure before deciding:

```text
sells first
purchases first
```

---

# 69. Preserve OrderBuilder Purchase Relative Order

For surviving purchase proposals retain upstream order among purchases.

C2C should not turn:

```text
protected WHEAT
land
optional WHEAT
seeds
animals
```

into an arbitrary purchase execution order.

---

# 70. WHEAT Consolidation Happens After Closure

If both:

```text
wheat:protected
wheat:optional
```

are selected, CentralPlanner may continue to consolidate them into:

```text
BUY_PRODUCT WHEAT total
```

for engine execution.

But dependency closure must have already verified both semantic proposals separately.

---

# 71. Consolidation Must Not Erase Diagnostics

Diagnostics must continue to show:

```text
protected proposal selected
optional proposal selected
animal required both
dependency closure passed
```

even if final engine output contains only one combined WHEAT order.

---

# 72. Do Not Backfill Slots Freed by Consolidation

If two semantic WHEAT proposals become one engine order:

```text
do not use the newly freed engine slot to admit another previously rejected proposal
```

in C2C v1.

Again: no hidden secondary optimization.

---

# 73. Global Engine Cap

Before consolidation:

```text
semantic selected proposals <= MAX_MARKET_ORDERS
```

After consolidation:

```text
engine orders <= semantic selected proposals
```

Therefore:

```text
engine orders <= 10
```

must always hold.

---

# 74. Final Animal Dependency Invariant

For every final emitted:

```text
BUY_ANIMAL
```

all of its required resource keys must correspond to semantic proposals that survived arbitration.

Formally:

```text
∀ animal a in final animals:
    requires(a) ⊆ selected_resource_keys
```

This should be asserted in tests and optionally runtime diagnostics.

---

# 75. No Orphan Animal Invariant

Never allow:

```text
animal selected
+
required WHEAT rejected
```

under any rejection reason, including:

```text
slot_cap
invalid_order
duplicate
endgame block
metadata error
planner exception
```

---

# 76. Protected Buy Invariant

If a valid live protected WHEAT proposal exists and:

```text
cap > 0
```

it must not be rejected merely because:

```text
P0/P1/P2 ranking
source ordering
sell pressure
normal slot competition
```

It is a hard root.

---

# 77. Protected Sale Invariant

Before Day 29:

```text
final SELL WHEAT quantity
<= feed_sale_reservation.sellable_shed_wheat
```

always.

---

# 78. Dependency Metadata Failure

If live mode receives an animal proposal but:

```text
animal metadata missing
requires_resource_keys malformed
dependency group malformed
order_metadata alignment broken
contract version missing
```

drop the animal.

Reason:

```text
invalid_dependency_contract
```

Do not assume no dependencies.

---

# 79. Missing Resource Key

If animal metadata says:

```text
requires wheat:optional
```

but there is no corresponding current-turn resource proposal:

```text
drop animal
```

Reason:

```text
missing_dependency
```

Do not synthesize a WHEAT order.

---

# 80. Hard Protected Resource Missing

If the contract says a protected WHEAT purchase was required but no valid corresponding proposal exists:

```text
new livestock = zero
```

and diagnostics should include:

```text
missing_hard_resource
```

Do not invent or reconstruct the missing engine order in CentralPlanner.

---

# 81. Live CentralPlanner Exception Policy

Current CentralPlanner can fall back to legacy composition after exceptions.

That is unsafe once C2C becomes live authority.

In live mode:

```text
CentralPlanner exception
```

must not produce legacy animal purchases.

---

# 82. Dependency-Safe Live Fallback

Create a deterministic helper such as:

```python
dependency_safe_live_fallback(...)
```

Its purpose is survival, not optimal strategy.

It must:

```text
drop every BUY_ANIMAL
preserve valid protected WHEAT purchases first
enforce protected WHEAT sale reservation
never sell protected feed
respect global cap
```

---

# 83. Safe Fallback May Preserve Independent Orders

After protected WHEAT is secured, the fallback may retain validated independent proposals such as:

```text
HIRE
BUY_LAND
optional WHEAT
BUY_SEED
non-WHEAT SELL
```

using deterministic existing ordering rules.

But:

```text
BUY_ANIMAL = always dropped
```

during the C2C failure fallback.

---

# 84. Safe Fallback WHEAT Sale

If the feed sale reservation is valid:

```text
clamp WHEAT sales to sellable_shed_wheat
```

If invalid and:

```text
day < 29
```

then:

```text
SELL WHEAT = 0
```

Day 29 may liquidate normally.

---

# 85. Main-Level Exception Must Use the Same Safe Fallback

Even if `CentralPlanner.plan_market()` unexpectedly escapes its own exception handler, `main.py` must not do:

```text
live mode
→ legacy_compose_market
```

Use the same dependency-safe fallback.

There must be only one live market failure policy.

---

# 86. Exceptions Never Change Point-2 Mode

Do not turn:

```text
live
```

into:

```text
shadow
legacy
```

because an exception occurred.

Fail closed for livestock.

Preserve survival resources.

---

# 87. Legacy Arbitration Modes in Live Point-2

When Point-2 is live:

```text
legacy
historical_stack
expanded_legacy
```

must not bypass C2C.

Recommended behavior:

```text
if Point2 live:
    always use dependency-safe CentralPlanner
else:
    respect configured arbitration mode
```

This is simpler and safer than trying to retrofit dependency closure into every historical composer.

---

# 88. Shadow / Herd-Plan Compatibility

When Point-2 mode is:

```text
shadow
herd_plan
```

existing arbitration mode selection remains unchanged.

This must be regression-tested.

---

# 89. Feed Reservation Failure Isolation

If OrderBuilder cannot compute:

```text
feed_sale_reservation
```

in live mode:

```text
contract valid = False
new animals cannot survive final arbitration
WHEAT sales blocked before Day29
protected survival purchases remain
```

Do not release unknown feed to the market.

---

# 90. Upstream Builder Failure

Existing main-level OrderBuilder failure isolation already tries to preserve survival purchases.

C2C must preserve that principle.

If purchase ledger lacks a normal dependency contract because OrderBuilder catastrophically failed:

```text
do not authorize animals
do not sell WHEAT before Day29 unless safe quantity is proven
```

---

# 91. Proposed C2C Diagnostics

Add:

```text
c2c_active
dependency_contract_version
dependency_contract_valid
dependency_contract_errors

resource_key_map

hard_resource_keys
selected_resource_keys
rejected_resource_keys

dependency_groups_requested
dependency_groups_selected
dependency_groups_rejected

dependency_rejections

protected_wheat_root_present
protected_wheat_root_selected

feed_sale_reservation_valid
post_unit_shed_wheat
protected_shed_wheat
sellable_shed_wheat

wheat_sell_requested
wheat_sell_allowed
wheat_sell_trimmed
wheat_sell_blocked

dependency_safe_fallback_used

semantic_slots_selected
compiled_engine_slots
```

---

# 92. Animal Diagnostic Detail

For every animal proposal expose:

```python
{
    "proposal_id": ...,
    "animal": ...,
    "qty": ...,
    "candidate_ids": [...],
    "dependency_group": ...,
    "requires_resource_keys": [...],
    "requires_proposal_ids": [...],
    "missing_resource_keys": [...],
    "dependency_satisfied": True/False,
    "selected": True/False,
    "rejection_reason": ...,
}
```

---

# 93. Resource Diagnostic Detail

For every resource proposal expose:

```python
{
    "proposal_id": ...,
    "resource_key": ...,
    "hard_required": ...,
    "selected": ...,
    "rejection_reason": ...,
}
```

---

# 94. WHEAT Sale Diagnostic Detail

Expose:

```python
{
    "requested_total": ...,
    "post_unit_shed_wheat": ...,
    "protected_shed_wheat": ...,
    "sellable_shed_wheat": ...,
    "normalized_total": ...,
    "selected_total": ...,
}
```

This makes feed-sale bugs visible in replay telemetry.

---

# 95. Proposed FeedFeasibility Helper

Prefer a single helper:

```text
derive_feed_sale_reservation(
    ledger,
    operational_min_wheat_slack,
    valid=True,
)
```

It should contain the physical reservation arithmetic.

Do not scatter that calculation through:

```text
OrderBuilder
CentralPlanner
MarketBrain
```

---

# 96. Proposed OrderBuilder Responsibilities

In live mode OrderBuilder should:

```text
1. preserve C2B behavior
2. assign stable WHEAT resource keys
3. attach candidate dependency keys
4. group dependency metadata by emitted animal order
5. track final operational minimum wheat slack
6. derive authoritative feed-sale reservation
7. emit point2_c2c_v1 dependency contract
```

It does not perform global buy/sell arbitration.

---

# 97. Proposed CentralPlanner Responsibilities

CentralPlanner should:

```text
1. validate dependency contract
2. preserve upstream metadata
3. protect hard WHEAT root
4. clamp WHEAT sale quantity
5. apply existing global ranking
6. perform dependency closure
7. freeze selected set
8. compile engine orders
9. use safe live fallback on failure
```

No feed/economic logic.

---

# 98. Proposed Main Responsibilities

`main.py` should:

```text
1. pass purchase ledger to CentralPlanner
2. require C2C-safe arbitration in live Point-2 mode
3. use dependency-safe fallback if CentralPlanner fails
4. preserve current behavior outside live mode
```

Nothing else.

---

# 99. CentralPlanner Must Not Inspect Candidate Profit

Do not add:

```text
EV
marginal profit
payback
animal revenue
animal product price
```

to dependency closure.

C2B already received candidates from the economic authority.

---

# 100. CentralPlanner Must Not Inspect Housing

Do not recheck:

```text
pastures
coops
post-Day12 physical housing
```

in C2C.

C2B already finalized housing.

---

# 101. CentralPlanner Must Not Inspect Future Feed Timeline

Do not call:

```text
evaluate_incremental_candidate
evaluate_existing_herd_feasibility
```

from CentralPlanner.

C2C only consumes:

```text
resource dependencies
feed sale reservation
```

---

# 102. Required Metadata Test — Protected WHEAT

Generate a live OrderBuilder result with protected WHEAT.

Verify:

```text
resource_key == wheat:protected
hard_required == True
feed_class == protected
```

and correct order-metadata alignment.

---

# 103. Required Metadata Test — Optional WHEAT

With optional feed retained verify:

```text
resource_key == wheat:optional
hard_required == False
feed_class == optional
```

---

# 104. Required Metadata Test — Animal Group

Accepted:

```text
SHEEP
COW
SHEEP
```

Verify grouped SHEEP order includes both SHEEP candidate IDs and union of dependencies.

---

# 105. Grouped Dependency Conservative Test

Candidate #1 SHEEP dependency:

```text
wheat:protected
```

Candidate #2 SHEEP dependency:

```text
wheat:protected
wheat:optional
```

Grouped order must require both.

If optional WHEAT is lost:

```text
whole SHEEP order rejected
```

---

# 106. Hard Protected Root Slot Test

Create more than 10 proposals.

Protected WHEAT is otherwise only P2.

Verify:

```text
protected WHEAT selected
lower-ranked proposal displaced
total <= 10
```

---

# 107. Optional WHEAT Slot Test

Optional WHEAT receives no hard-root status.

Under slot pressure it may be rejected normally.

---

# 108. Dependency Closure Test

Selected animal requires:

```text
wheat:optional
```

Optional proposal loses the slot.

Expected:

```text
animal removed
reason = missing_dependency
```

---

# 109. No Backfill Test

Initial selected count:

```text
10
```

Dependency closure removes one animal.

Expected final semantic selection:

```text
9
```

Candidate #11 must remain rejected.

---

# 110. Protected Dependency Pass Test

Animal requires only:

```text
wheat:protected
```

Protected root selected.

Other gates satisfied.

Animal remains selected.

---

# 111. Missing Resource Proposal Test

Animal requires:

```text
wheat:optional
```

but no resource proposal exists.

Expected:

```text
animal rejected
missing_resource_keys = ["wheat:optional"]
```

---

# 112. Invalid Contract Test

Live mode:

```text
BUY_ANIMAL exists
order_metadata missing
```

Expected:

```text
zero final BUY_ANIMAL
reason = invalid_dependency_contract
```

---

# 113. Duplicate Resource-Key Test

Two purchases claim:

```text
resource_key = wheat:optional
```

Expected:

```text
contract invalid for animal safety
zero dependent BUY_ANIMAL
```

Do not arbitrarily choose one.

---

# 114. Feed Reservation Existing-Herd Test

Example:

```text
post-unit shed WHEAT = 20
worker WHEAT = 0
final minimum slack = 8
```

Expected:

```text
releasable = 8
protected shed = 12
sellable shed = 8
```

---

# 115. Worker-First Reservation Test

Example:

```text
shed WHEAT = 15
worker WHEAT = 5
total = 20
required total on-hand = 12
```

Expected:

```text
protected worker = 5
protected shed = 7
sellable shed = 8
```

---

# 116. Candidate Raises Physical Reservation Test

Existing-herd slack:

```text
8
```

Final accepted-candidate slack:

```text
3
```

C2C feed-sale reservation must use:

```text
3
```

not the earlier existing-herd slack.

---

# 117. Candidate Later Dropped Test

C2B accepts candidate and reservation rises.

C2C later drops candidate due missing optional WHEAT.

Expected:

```text
feed sale reservation remains unchanged for this turn
```

No recalculation.

---

# 118. Full WHEAT Sale Block Test

Example:

```text
post-unit shed WHEAT = 10
protected shed WHEAT = 10
MarketBrain proposes SELL WHEAT 5
```

Expected:

```text
SELL WHEAT rejected
reason = protected_feed_reservation
```

---

# 119. Partial WHEAT Sale Test

Example:

```text
shed WHEAT = 20
protected = 14
sellable = 6
proposed SELL WHEAT 10
```

Expected normalized proposal:

```text
SELL WHEAT 6
```

with trim diagnostics.

---

# 120. Multiple WHEAT Sales Aggregate Test

Proposals:

```text
SELL WHEAT 4
SELL WHEAT 4
```

Sellable:

```text
6
```

Expected total normalized WHEAT sale:

```text
<= 6
```

---

# 121. P2 Protected Buy + WHEAT Sale Test

Protected BUY WHEAT is only classified P2.

There is a WHEAT sell proposal.

Feed sale reservation says:

```text
sellable = 0
```

Expected:

```text
WHEAT buy remains protected
WHEAT sell rejected
```

This proves C2C no longer depends on P0 classification for feed protection.

---

# 122. Day 29 Liquidation Test

Day 29 with shed WHEAT.

Expected:

```text
protected_shed_wheat = 0
WHEAT may liquidate
```

subject to ordinary final-day arbitration.

---

# 123. Post-Unit Source Test

Observation:

```text
shed WHEAT = 20
```

Actual unit action PICKUP changes post-unit:

```text
shed WHEAT = 15
worker WHEAT = 5
```

C2C reservation and sell clamp must use:

```text
15 shed / 5 worker
```

not stale 20-shed observation.

---

# 124. Dependency + Consolidation Test

Protected and optional WHEAT both selected.

Animal requires both.

Dependency closure passes.

Final engine compilation consolidates:

```text
BUY_PRODUCT WHEAT protected+optional
```

Animal remains.

Diagnostics still identify both semantic resource proposals.

---

# 125. Consolidation No Backfill Test

Semantic selection consumes:

```text
protected WHEAT slot
optional WHEAT slot
```

Consolidation reduces two engine orders to one.

Do not promote another rejected proposal into the freed compiled slot.

---

# 126. CentralPlanner Exception Test

Inject exception after proposals are available.

Live mode expected:

```text
zero BUY_ANIMAL
protected WHEAT retained if structurally valid
WHEAT sell does not violate reservation
global cap respected
dependency_safe_fallback_used = True
```

---

# 127. Main-Level Exception Test

Force `CentralPlanner.plan_market()` itself to raise past its normal internal handling.

Live mode must still not execute:

```text
legacy unsafe animal composition
```

Expected:

```text
zero BUY_ANIMAL
safe feed behavior
```

---

# 128. Live + Legacy Arbitration Configuration Test

Configure historical/legacy arbitration mode while:

```text
POINT2_FEED_MODE = live
```

Expected:

```text
C2C-safe arbitration still used
```

No dependency bypass.

---

# 129. Shadow Legacy Regression

Same legacy arbitration configuration under:

```text
POINT2_FEED_MODE = shadow
```

must preserve historical behavior.

---

# 130. Herd-Plan Legacy Regression

Same under:

```text
POINT2_FEED_MODE = herd_plan
```

must preserve historical behavior.

---

# 131. No Feed Evaluator Call in CentralPlanner Test

Monkeypatch:

```text
evaluate_existing_herd_feasibility
evaluate_incremental_candidate
```

to raise if called from C2C arbitration.

CentralPlanner should still operate because it must not call them.

---

# 132. Hard Root Does Not Exceed Cap Test

With:

```text
cap = 1
```

and protected WHEAT plus animal:

```text
protected WHEAT selected
animal rejected
```

Final count:

```text
1
```

---

# 133. Cap Zero Test

With:

```text
cap = 0
```

expected:

```text
no orders
no cap violation
no animal
```

---

# 134. Invalid Protected Resource Order Test

Dependency metadata says protected WHEAT exists but its engine order is malformed.

Expected:

```text
resource rejected as invalid
dependent animals rejected
no synthesized WHEAT order
```

---

# 135. Sale Reservation Missing Test

Live mode, Day < 29:

```text
feed_sale_reservation missing
```

Expected:

```text
WHEAT sales blocked
animals fail contract safety
```

Independent non-WHEAT actions may continue.

---

# 136. Sale Reservation Missing Day-29 Test

Day 29:

```text
feed reservation missing
```

No feed obligation remains.

WHEAT liquidation may proceed under normal final-day rules.

---

# 137. Protected WHEAT Survives Sell Pressure Test

Create:

```text
hard shed pressure
many high-priority SELL proposals
protected WHEAT purchase
```

Protected feed root must still survive global selection when cap permits.

---

# 138. No Orphan Animal Under Every Rejection Reason

Parameterize resource rejection:

```text
slot_cap
invalid_order
contract_invalid
hard filter
```

Every dependent animal must disappear.

---

# 139. Engine Order Conservation

After C2C:

```text
no duplicated animal quantities
no duplicated WHEAT quantities
no invented proposals
no quantity inflation
```

WHEAT partial-sale trim and WHEAT-buy consolidation are explicit allowed transformations.

---

# 140. Diagnostics Conservation

Every original proposal must end as exactly one of:

```text
selected
rejected
normalized then selected
normalized then rejected
```

Do not silently lose proposals during dependency closure.

---

# 141. Submission Mirror

All modified runtime files must be synchronized to:

```text
submission/
```

and:

```text
dist/submission.zip
```

must be rebuilt.

---

# 142. Expected Runtime Files to Change

Likely:

```text
agent/strategy/feed_feasibility.py
agent/market/order_builder.py
agent/strategy/central_planner.py
agent/main.py
agent/tests/...
```

and corresponding submission mirrors.

Possibly no MarketBrain changes are required.

---

# 143. Do Not Modify C2B Economics

Do not touch:

```text
MarginalLivestockValuator thresholds
late-selective $500 gate
candidate order
housing logic
Day12 physical housing invariant
stress-price formula
opponent stress policy
```

unless required solely to expose metadata without changing results.

---

# 144. Do Not Modify Feed Pricing Policy

Keep:

```text
engine_stress_bound_v1
```

exactly frozen.

No new clamp.

No new opponent assumption.

No new town-demand assumption.

---

# 145. Do Not Modify Post-Unit Verification

C2B post-unit state authority is frozen.

C2C consumes its output.

Do not redesign:

```text
HARVEST
PLACE
BUILD
PICKUP
DROP
FEED
```

verification.

---

# 146. Do Not Modify Candidate Sequence

Keep:

```text
buy_animal_sequence
```

and Day-12–14 late-selective generation frozen.

C2C does not reorder candidates.

---

# 147. Do Not Modify Housing

The permanent invariant remains:

> After Day 12, new livestock receives housing credit only from compatible housing physically present before the turn.

C2C does not reopen this decision.

---

# 148. C2C Regression Suite

Run focused:

```bash
pytest agent/tests/test_feed_feasibility.py -q
```

Run CentralPlanner tests.

Run OrderBuilder tests.

Run:

```bash
pytest agent/tests/ -q -m "not slow"
```

Run packaging:

```bash
python scripts/build_submission.py
```

---

# 149. Frozen Regression Requirements

Re-run the existing:

```text
shadow
herd_plan
historical arbitration
submission packaging
720-step
```

regressions.

C2C changes must not alter non-live Point-2 behavior.

---

# 150. Live C2C 720-Step Diagnostic Season

Run at least one full season with:

```text
POINT2_FEED_MODE = live
```

and dependency-safe CentralPlanner active.

Capture:

```text
animal groups proposed
animal groups selected
animal groups dependency-dropped

protected WHEAT roots proposed
protected WHEAT roots selected

optional WHEAT proposed
optional WHEAT selected

WHEAT sells proposed
WHEAT sells trimmed
WHEAT sells blocked

protected shed WHEAT over time
sellable shed WHEAT over time

dependency contract failures
safe fallback count

final herd
animal escapes
feed failures
final reward / money
```

---

# 151. Zero Orphan Dependency Audit

During live simulation assert or audit:

```text
orphan_animal_count == 0
```

where an orphan is:

```text
final BUY_ANIMAL
whose required semantic resource proposal did not survive
```

This must be a hard C2C acceptance criterion.

---

# 152. Zero Protected WHEAT Sale Violation Audit

Assert:

```text
wheat_sell_violation_count == 0
```

where violation means:

```text
final WHEAT sale quantity
>
authoritative sellable_shed_wheat
```

---

# 153. Zero Live Legacy Fallback Animal Audit

Assert:

```text
unsafe_legacy_live_animal_fallback_count == 0
```

Any market-stage exception under live Point-2 must produce no new animals through fallback.

---

# 154. C2C Acceptance Invariants

C2C passes only if all are true:

```text
CentralPlanner does not recompute feed feasibility

live animal orders carry dependency metadata

protected and optional WHEAT carry stable resource keys

protected existing-feed WHEAT is a hard selection root

global cap is still respected

selected animals cannot survive missing required WHEAT

dependency rejection does not trigger candidate replacement

dependency rejection does not trigger feed recomputation

WHEAT sales cannot consume authoritative reserved feed

physical reservation includes accepted C2B candidates

reservation uses post-unit state

invalid reservation fails closed

live CentralPlanner failure cannot invoke unsafe animal fallback

live Point-2 cannot bypass C2C via legacy arbitration mode

shadow behavior remains frozen

herd_plan behavior remains frozen

Day12 housing invariant remains frozen

engine_stress_bound_v1 remains frozen
```

---

# 155. C2C Freeze Boundary

After implementation:

```text
C2C must be independently audited.
```

If audit verdict is:

```text
PASS — FREEZE PHASE C2C
```

then the entire Point-2 decision architecture is technically closed:

```text
Feed feasibility
+
funding
+
execution
+
housing
+
sequential candidate admission
+
global arbitration dependencies
+
protected physical feed sales
```

---

# 156. Production Activation Is Separate

Do not combine:

```text
C2C implementation
```

with:

```text
POINT2_FEED_MODE = live
```

activation.

After C2C freeze, make a separate rollout decision.

Recommended sequence:

```text
C2C implementation
↓
audit
↓
PASS / FREEZE
↓
live diagnostic seasons / replay comparison
↓
separate minimal production activation commit
```

---

# 157. Suggested C2C Commit

Suggested commit message:

```text
feat(feed): implement Phase C2C arbitration dependency closure
```

One isolated C2C commit is preferred.

Do not mix unrelated strategy changes.

---

# 158. Implementation Stop Condition

After implementing this architecture:

```text
run tests
build submission
run live diagnostic
commit
report SHA
STOP
```

Do not:

```text
enable production live
retune livestock economics
change land policy
start another strategic optimization
```

until the C2C SHA has been independently audited.

---

# 159. Final Point-2 Architecture After C2C

The complete chain should then be:

```text
Observation
    ↓
verified post-unit state
    ↓
FeedFeasibility
    ↓
existing-herd first claim
    ↓
engine_stress_bound_v1 funding
    ↓
Macro ordered candidate sequence
    ↓
C2B sequential live candidate authority
    ↓
physical housing + shed + rollover checks
    ↓
explicit WHEAT resource dependencies
    ↓
authoritative physical WHEAT sale reservation
    ↓
C2C global 10-slot arbitration
    ↓
hard protected-feed root
    ↓
animal dependency closure
    ↓
protected WHEAT sell clamp
    ↓
dependency-safe failure isolation
    ↓
engine market actions
```

The final safety statement is:

> No new livestock purchase may survive final market arbitration unless every current-turn WHEAT proposal used by its C2B authorization also survives, and no WHEAT sale may consume physical feed reserved by the accepted herd plan.
