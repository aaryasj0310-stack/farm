# SW Scheduler Redesign Specification: Soft Locality & Deadline Rescue

**Module:** `execution/task_scheduler.py`  
**Status:** Architecture Designed in Phase A; Execution Integration in Phase B  

---

## 1. Architectural Diagnosis of Previous Dispatch Failures

Previous experiments demonstrated two fatal failure modes in dispatching workers across multiple quadrants:
1. **Unconstrained Global Sharing (P1, P1.2)**: Workers bounced between NE and SW, wasting 35–45% of available turns in transit steps rather than productive farming operations.
2. **Rigid Home-Zone Partitioning (P4.1)**: Permanently locking Hands 11 and 12 into SW starved the core farm (NW/NE) of labor, causing core agricultural attempts to fall by 111.6/game and core watering compliance to drop by 4.45 percentage points.

---

## 2. Target Design: Soft Locality + Global Deadline Rescue

The redesigned scheduler operates on two complementary principles:
- **Soft Regional Locality**: Routine tasks (planting, regular watering, fertilizer collection) prefer workers already situated in or near that quadrant.
- **Hard Global Deadline Rescue**: Critical survival tasks (starvation feeding, crop survival watering, decay harvesting) can recruit *any* worker on the farm regardless of regional preference.

### Mathematical Task Assignment Scoring
For worker $u$ at position $p_u$ evaluating task $t$ at target position $p_t$ in region $R_t$:

$$\text{Score}(u, t) = \text{Priority}(t) + \text{EconomicValue}(t) - \alpha \cdot \text{Distance}(p_u, p_t) - \beta \cdot \text{RegionSwitchPenalty}(u, R_t)$$

Where:
- $\text{Priority}(t)$:
  - Urgent survival feed: $+100$
  - Imminent decay harvest: $+90$
  - Feed staging: $+86$
  - Crop survival water: $+85$
  - Routine planting / watering: $+70$
- $\alpha$: Transit penalty per Manhattan step ($\sim 1.0$).
- $\beta$: Regional switch penalty ($\sim 5.0$) applied only if $R_t \ne \text{CurrentRegion}(u)$.
- **Global Rescue Override**: If $\text{Priority}(t) \ge 85$ (Hard tier), $\beta$ is set to $0$, allowing any unit to rescue an expiring crop or starving animal.

---

## 3. Dynamic Roster Allocation (13 Total Workers)

Rather than fixing arbitrary worker IDs to SW:
1. **Morning Assignment**:
   At Hour 1 (after hire settlement), units are assigned initial operational anchors based on certified regional workload:
   - Core (NW + NE): $\sim 9\text{--}10$ workers.
   - SW Expansion: $\sim 3\text{--}4$ workers.
2. **Intraday Flow**:
   Workers transit to the shed for product deposits or wheat pickups, serving as natural transfer points between quadrants.
3. **Midgame/Endgame Flexibility**:
   As crop maturity shifts across the season, regional weightings automatically rebalance without requiring manual code changes.
