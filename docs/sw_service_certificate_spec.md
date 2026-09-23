# SW Service Certificate Specification

**Module:** `strategy/service_certificate.py`  
**Status:** Implemented & Verified in Phase A  

---

## 1. Multi-Day Rolling Horizon Architecture

Single-day labor models (such as `EFFECTIVE_ACTIONS_PER_UNIT = 12`) fail because actions have hard calendar deadlines and multi-day dependencies. A planting decision on Day 8 creates a peak watering and harvest wave on Days 10–12.

The `ServiceCertificate` operates over a **rolling 72-96 hour horizon** evaluated in three distinct fidelity zones:

```text
H0 ----------- H24 ----------- H48 ----------- H72+
     Zone 1          Zone 2          Zone 3
  Exact Routes    Cohort Deadlines   Capacity
  & Placement     + Regional Transit Envelopes
```

- **Zone 1 (H0–H24, Current Day)**: Exact worker positions, individual task coordinates, travel overhead factor (1.35x direct operations), and sequential hourly action queues.
- **Zone 2 (H24–H48, Next Day)**: Exact cohort deadlines, paired watering requirements, and regional transit buffers (1.25x direct operations).
- **Zone 3 (H48–H72+, Days 2–3)**: Conservative capacity envelopes (1.15x direct operations) ensuring long-term feasibility.

---

## 2. Mathematical Formulation & Outputs

For every hour $h \in [0, H_{\text{horizon}}]$:
$$\text{Budget}(h) = \text{EffectiveWorkers}(h) \times 1 \text{ action/hour}$$
$$\text{Demand}(h) = \left\lceil \sum_{t \in \text{Tasks}(h)} \text{Duration}(t) \times \text{TravelFactor}(h) \right\rceil$$
$$\text{Slack}(h) = \text{Budget}(h) - \text{Demand}(h)$$

### Task Definition & Causal Dependency Model
```python
@dataclass
class ServiceTask:
    task_id: str
    op: str                          # WATER, HARVEST, FEED, PLANT, BUY, SELL, DEPOSIT
    pos: Tuple[int, int]
    region: str                      # NW, NE, SW, SE
    day: int
    hour_deadline: int               # Hour within the day when task MUST complete
    tier: CommitmentTier = CommitmentTier.HARD
    estimated_duration_actions: int = 1
    cohort_id: Optional[str] = None
    value: float = 0.0
    prerequisite_task_id: Optional[str] = None   # Causal dependency
    earliest_start_hour: int = 0                 # Cannot start before this hour
    task_type: str = "GENERIC"                   # HARVEST, FEED, DEPOSIT, SELL, etc.
```

### Causal Ordering Invariants
Phase A-R enforces physical operation sequences:
1. **Harvest-to-Feed Causality**: When grain is harvested to feed livestock on the same day, `FEED` tasks declare `prerequisite_task_id = harvest_task.task_id` and cannot execute earlier than `harvest_task.earliest_completion_hour`.
2. **Deposit-to-Sell Causality**: Market `SELL` orders cannot execute on carried goods until a `DEPOSIT` task has transferred the inventory into the shed.
3. **Earliest Start Constraints**: Tasks cannot be scheduled earlier than their physical availability hour (e.g. dawn, unlock turn, or prerequisite completion).

### Certificate Output Record
```python
@dataclass
class CertificateResult:
    feasible: bool                   # True iff all Hard tasks execute before deadline and min_slack >= 0
    minimum_slack: int               # Lowest slack across the entire horizon
    peak_workload: int               # Highest hourly action demand observed
    binding_day: int                 # Day of lowest slack / failure
    binding_hour: int                # Hour of lowest slack / failure
    binding_resource: str            # "WORKER_HOURS", "FEED_CARRIER", "SHED_SPACE", "CASH"
    failing_tasks: List[ServiceTask]
    repair_options: List[RepairOption]
    horizon_hours: int = 72
```

---

## 3. Commitment Priority Tiers

Tasks and commitments are partitioned into three strict tiers:

1. **HARD Tier**:
   - Immediate animal survival feeding (starvation prevention).
   - Crop survival watering (`consecutive_unwatered >= 1`).
   - Imminent decay harvest (`turns_until_decay <= 1`).
   - Mandatory daily wage obligations (H0 hire batch).
   - Committed land purchase settlement.
2. **STRATEGIC Tier**:
   - Planned SW tranche crop cohorts (planting and routine watering).
   - Growth-maximizing bonus watering.
   - High-ROI fertilizer application.
   - Planned livestock cohort purchases.
3. **DISCRETIONARY Tier**:
   - Marginal endgame replants.
   - Low-value animal care (e.g. late goose care).
   - Routine weed clearing.

---

## 4. Structured Repair Engine

When `feasible == False` or `minimum_slack < 2`, the certificate automatically compiles structured `RepairOption` records:

```python
@dataclass
class RepairOption:
    type: str                        # "DROP_COHORT", "DELAY_COHORT", "DOWNSIZE_TRANCHE", "HIRE_EXTRA_WORKER"
    target: str                      # Identifier of affected cohort or parameter
    actions_freed: int               # Actions recovered in the binding bottleneck window
    cash_freed: float                # Immediate cash saved
    expected_value_lost: float       # Economic opportunity cost of adopting this repair
    deadline_slack_gained: int       # Improvement in binding window slack
    resolves_certificate: bool       # Whether this single repair fully restores feasibility
    reason: str
```

### Algorithmic Repair Selection
1. Rank repairs by:
   - `resolves_certificate == True` first.
   - `expected_value_lost` ascending (cheapest economic sacrifice).
2. Shed lowest-value discretionary cohort before affecting strategic cohorts.
3. Downsize SW tranche (e.g. from 16 to 12 tiles) before considering cancellation.
4. Add peak-day hiring ($13^{\text{th}}$ hand for \$233) if incremental crop value exceeds wage cost.
