"""
Phase SW-C2: P2 Global Coordinated Regional Dispatch Controller
Implements two-stage global prioritization (Stage 1: Deadline Feasibility Protection,
Stage 2: Economic Capacity Allocation with Dynamic Regional Budgets) and deterministic
next-action matching without external dependencies.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from config import (
        SHED_ACCESS_TILES,
        PORT_SW,
        PRIORITY_URGENT_SURVIVAL,
        PRIORITY_PRODUCT_DELIVERY_PRESSURE,
        PRIORITY_PROD_DAY_FEED,
        PRIORITY_STANDARD_HARVEST,
        PRIORITY_BONUS_WATER,
        PRIORITY_CARE_ANIMAL,
        PRIORITY_FERT_COLLECT,
        C2_MAX_SPILLOVER_DIST,
        C6_CLUSTER_RADIUS,
        C6_CLUSTER_BONUS,
        C6_PRIORITY_BAND,
        C6_TRAVEL_WEIGHT,
        ANIMALS,
    )
except ImportError:
    from agent.config import (
        SHED_ACCESS_TILES,
        PORT_SW,
        PRIORITY_URGENT_SURVIVAL,
        PRIORITY_PRODUCT_DELIVERY_PRESSURE,
        PRIORITY_PROD_DAY_FEED,
        PRIORITY_STANDARD_HARVEST,
        PRIORITY_BONUS_WATER,
        PRIORITY_CARE_ANIMAL,
        PRIORITY_FERT_COLLECT,
        C2_MAX_SPILLOVER_DIST,
        C6_CLUSTER_RADIUS,
        C6_CLUSTER_BONUS,
        C6_PRIORITY_BAND,
        C6_TRAVEL_WEIGHT,
        ANIMALS,
    )


def manhattan_dist(p1: Tuple[int, int], p2: Tuple[int, int]) -> int:
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])


class CoordinatedDispatchController:
    """Orchestrates multi-worker regional dispatch across NW, NE, and SW.
    
    Invariants:
    1. Stage 1 guarantees deadline feasibility: animals facing starvation/escape,
       crops facing unwatered death, and irreversible decay harvests are assigned
       before discretionary work.
    2. Stage 2 optimizes next actions using deterministic joint assignment with
       regional budget awareness, route continuity, and immediate same-tile follow-up.
    3. Regional boundaries are treated as soft preferences: workers cross regions
       only if origin protection is preserved and destination has net profitable work.
    4. Prohibits diagonal traversals between SW and NE.
    """

    def __init__(self) -> None:
        self._telemetry = {
            "stage1_protected_assignments": 0,
            "stage2_economic_assignments": 0,
            "fallback_assignments": 0,
            "cross_region_transfers_authorized": 0,
            "cross_region_transfers_denied": 0,
            "regional_worker_distribution": {"NW": 0, "NE": 0, "SW": 0},
            "deadlines_protected_count": 0,
        }

    def reset(self) -> None:
        self._telemetry = {
            "stage1_protected_assignments": 0,
            "stage2_economic_assignments": 0,
            "fallback_assignments": 0,
            "cross_region_transfers_authorized": 0,
            "cross_region_transfers_denied": 0,
            "regional_worker_distribution": {"NW": 0, "NE": 0, "SW": 0},
            "deadlines_protected_count": 0,
        }

    def get_telemetry(self) -> Dict[str, Any]:
        return copy.deepcopy(self._telemetry)

    def plan_coordinated_dispatch(
        self,
        tasks: List[Dict[str, Any]],
        ctx: Dict[str, Any],
        units: List[Tuple[int, Tuple[int, int]]],
        holders: Dict[str, List[int]],
        eligible_fn: Any,
        home_quads: Dict[int, str],
        active_missions: Dict[int, Any],
        tracker: Any,
    ) -> Tuple[Dict[int, Dict[str, Any]], Set[int], List[Dict[str, Any]]]:
        """Execute two-stage coordinated dispatch.
        
        Returns:
            assignment: Dict[worker_idx, task_dict]
            busy: Set[worker_idx]
            remaining_tasks: List[task_dict]
        """
        farm = ctx["farm"]
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)
        step = ctx.get("step", day * 24 + hour)
        pos_by_idx = dict(units)
        all_workers = [u[0] for u in units]
        sw_units = {u for u, q in home_quads.items() if q == "SW"}
        unlocked = set(getattr(farm, "unlocked", ("NW",)))

        assignment: Dict[int, Dict[str, Any]] = {}
        busy: Set[int] = set()

        # Update regional worker distribution telemetry
        reg_dist = {"NW": 0, "NE": 0, "SW": 0}
        for u in all_workers:
            u_quad = farm.quadrant_of(pos_by_idx[u]) if hasattr(farm, "quadrant_of") else "NW"
            if u_quad in reg_dist:
                reg_dist[u_quad] += 1
        self._telemetry["regional_worker_distribution"] = reg_dist

        # Filter out tasks targeting locked quadrants (except shed PICKUP and PASS)
        valid_tasks = []
        for t in tasks:
            tgt = t.get("target") or (0, 0)
            tgt_tuple = tuple(tgt)
            t_quad = farm.quadrant_of(tgt_tuple) if hasattr(farm, "quadrant_of") else "NW"
            if t.get("op") not in ("PICKUP", "PASS") and t_quad not in unlocked:
                continue
            valid_tasks.append(t)

        # =====================================================================
        # STAGE 1: Deadline Feasibility Protection
        # =====================================================================
        stage1_candidates = []
        stage2_candidates = []

        for t in valid_tasks:
            prio = float(t.get("priority", 0.0))
            kind = t.get("kind", "")
            op = t.get("op", "PASS")
            args = t.get("args") or []

            is_survival_feed = (kind in ("feed_rescue", "feed_prod") or prio >= PRIORITY_URGENT_SURVIVAL)
            is_survival_water = (op == "WATER" and (prio >= 80 or t.get("meta", {}).get("urgent", False)))
            is_decay_harvest = (kind == "harvest_decay")
            is_critical_pickup = (kind == "pickup_wheat" and prio >= PRIORITY_URGENT_SURVIVAL)
            is_livestock_place = (op == "PLACE" and args and args[0] in ANIMALS)
            is_product_delivery = (kind == "deposit_product" and prio >= PRIORITY_PRODUCT_DELIVERY_PRESSURE)

            if (is_survival_feed or is_survival_water or is_decay_harvest or
                is_critical_pickup or is_livestock_place or is_product_delivery):
                stage1_candidates.append(t)
            else:
                stage2_candidates.append(t)

        # Sort Stage 1 by priority descending
        stage1_candidates.sort(key=lambda t: -float(t.get("priority", 0.0)))

        for task in stage1_candidates:
            free_workers = [u for u in all_workers if u not in busy]
            if not free_workers:
                break

            eligible = eligible_fn(task)
            if eligible is not None:
                free_workers = [u for u in free_workers if u in eligible]
            if not free_workers:
                continue

            target = tuple(task.get("target") or pos_by_idx[free_workers[0]])

            # Check if active mission already owns this obligation and worker is free
            chosen_u = None
            obl_id = None
            if tracker is not None:
                try:
                    from execution.mission_ownership_tracker import compute_task_obligation_id
                except ImportError:
                    from agent.execution.mission_ownership_tracker import compute_task_obligation_id
                obl_id = compute_task_obligation_id(day, task.get("op", "PASS"), target, task.get("kind", ""), task.get("args"), task.get("meta"))
                existing_m = tracker.get_mission_for_obligation(obl_id)
                if existing_m and existing_m.worker_idx in free_workers:
                    chosen_u = existing_m.worker_idx

            if chosen_u is None:
                # Prefer workers without active mission, closest to target
                non_mission = [u for u in free_workers if u not in active_missions]
                pool = non_mission if non_mission else free_workers
                chosen_u = min(pool, key=lambda u: manhattan_dist(pos_by_idx[u], target))

            if chosen_u in active_missions:
                # Only preempt if chosen_u had a different mission
                m_existing = active_missions[chosen_u]
                if m_existing.get("op") != task.get("op") or tuple(m_existing.get("target", (-1, -1))) != target:
                    if tracker is not None:
                        tracker.preempt_worker_mission(chosen_u, reason="STAGE1_DEADLINE_PREEMPTION", step=step)
                    active_missions.pop(chosen_u, None)

            # Rule W2: SW squad workers anchor shed PICKUP at PORT_SW
            if chosen_u in sw_units and task.get("op") == "PICKUP" and task.get("target") in SHED_ACCESS_TILES:
                task["target"] = PORT_SW

            busy.add(chosen_u)
            task["unit_pos"] = pos_by_idx[chosen_u]
            assignment[chosen_u] = task
            self._telemetry["stage1_protected_assignments"] += 1
            self._telemetry["deadlines_protected_count"] += 1

            # Register sticky mission if multi-turn travel is required
            if manhattan_dist(pos_by_idx[chosen_u], target) > 0 and task.get("op") != "PASS":
                init_d = manhattan_dist(pos_by_idx[chosen_u], target)
                active_missions[chosen_u] = {
                    "task": dict(task),
                    "target": task.get("target"),
                    "op": task["op"],
                    "kind": task.get("kind", ""),
                    "args": task.get("args", []),
                    "priority": task.get("priority", 0),
                    "prev_distance": init_d,
                    "consecutive_no_progress": 0,
                    "mission_age": 0,
                    "steps_active": 0,
                }
                if tracker is not None:
                    if obl_id is None:
                        try:
                            from execution.mission_ownership_tracker import compute_task_obligation_id
                        except ImportError:
                            from agent.execution.mission_ownership_tracker import compute_task_obligation_id
                        obl_id = compute_task_obligation_id(day, task.get("op", "PASS"), target, task.get("kind", ""), task.get("args"), task.get("meta"))
                    tracker.claim_or_continue_mission(chosen_u, obl_id, task, pos_by_idx[chosen_u], step)

        # =====================================================================
        # STAGE 2: Economic Capacity Allocation with Dynamic Regional Budgets
        # =====================================================================
        # Re-assign surviving active missions to their sticky workers
        for u in list(active_missions.keys()):
            if u not in busy:
                m = active_missions[u]
                m_task = dict(m["task"])
                tgt = m_task.get("target")
                tgt_tuple = tuple(tgt) if tgt else pos_by_idx[u]

                m_task["unit_pos"] = pos_by_idx[u]
                assignment[u] = m_task
                busy.add(u)
                if tracker is not None:
                    try:
                        from execution.mission_ownership_tracker import compute_task_obligation_id
                    except ImportError:
                        from agent.execution.mission_ownership_tracker import compute_task_obligation_id
                    obl_id = compute_task_obligation_id(day, m["op"], tgt_tuple, m.get("kind", ""), m.get("args"))
                    tracker.claim_or_continue_mission(u, obl_id, m_task, pos_by_idx[u], step)

                # Remove matching task from stage2_candidates
                for st in list(stage2_candidates):
                    if st.get("op") == m["op"] and tuple(st.get("target", (-1, -1))) == tgt_tuple:
                        stage2_candidates.remove(st)
                        break

        # Remaining free workers and tasks
        tasks_by_quad = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
        for t in stage2_candidates:
            tgt = t.get("target") or (0, 0)
            q = farm.quadrant_of(tuple(tgt)) if hasattr(farm, "quadrant_of") else "NW"
            tasks_by_quad[q] = tasks_by_quad.get(q, 0) + 1
        unassigned_home_tasks = dict(tasks_by_quad)

        remaining_tasks = list(stage2_candidates)
        unassigned_tasks: List[Dict[str, Any]] = []

        try:
            from config import (
                get_sw_core_first_task_admission_enabled,
                get_sw_urgency_aware_admission_enabled,
            )
            sw_admission_enabled = (
                get_sw_core_first_task_admission_enabled() or
                get_sw_urgency_aware_admission_enabled()
            )
        except Exception:
            sw_admission_enabled = False

        # Bounded deterministic matching loop
        while remaining_tasks and len(busy) < len(all_workers):
            free_workers = [u for u in all_workers if u not in busy]
            if not free_workers:
                break

            best_match = None  # (score, d, target, u, task, target_quad)

            top_prio = max(float(t.get("priority", 0.0)) for t in remaining_tasks)
            band_tasks = [t for t in remaining_tasks if float(t.get("priority", 0.0)) >= top_prio - C6_PRIORITY_BAND]

            for task in band_tasks:
                eligible = eligible_fn(task)
                cand_workers = free_workers if eligible is None else [u for u in free_workers if u in eligible]
                if not cand_workers:
                    continue

                tgt = tuple(task.get("target") or (0, 0))
                tgt_quad = farm.quadrant_of(tgt) if hasattr(farm, "quadrant_of") else "NW"
                prio = float(task.get("priority", 0.0))

                # SW task admission check
                if tgt_quad == "SW" and tgt not in SHED_ACCESS_TILES and sw_admission_enabled:
                    try:
                        from execution.sw_task_admission_controller import (
                            evaluate_sw_task_admission,
                            get_sw_task_admission_telemetry,
                        )
                        telem = get_sw_task_admission_telemetry()
                        t_op = task.get("op", "")
                        t_item = (task.get("args") or [None])[0]
                        task_id = f"SW_{step}_{t_op}_{tgt}_{t_item}"
                        telem.record_sw_task_lifecycle_start(
                            task_id, step, day, hour, t_op, tgt, t_item, prio
                        )
                        admitted_cands = []
                        last_reason = "REJECTED"
                        for u in cand_workers:
                            admit, reason = evaluate_sw_task_admission(
                                ctx=ctx,
                                worker_idx=u,
                                worker_pos=pos_by_idx[u],
                                task=task,
                                current_assignments=assignment,
                                remaining_free_units=[fu for fu in free_workers if fu != u],
                                all_tasks=tasks,
                            )
                            telem.record_candidate_evaluation(admit, reason)
                            if admit:
                                admitted_cands.append(u)
                            else:
                                last_reason = reason
                        cand_workers = admitted_cands
                        if not cand_workers:
                            telem.record_sw_task_disposition(task_id, "REJECTED_BY_GATE", last_reason)
                            continue
                    except Exception:
                        pass

                # Check anti-duplicate pursuit
                if tracker is not None:
                    try:
                        from execution.mission_ownership_tracker import compute_task_obligation_id
                    except ImportError:
                        from agent.execution.mission_ownership_tracker import compute_task_obligation_id
                    obl_id = compute_task_obligation_id(day, task.get("op", "PASS"), tgt, task.get("kind", ""), task.get("args"), task.get("meta"))
                    existing_owner = tracker.get_mission_for_obligation(obl_id)
                    if existing_owner is not None and existing_owner.worker_idx not in cand_workers:
                        continue

                free_in_target = sum(1 for fu in free_workers if farm.quadrant_of(pos_by_idx[fu]) == tgt_quad)
                rem_target_tasks = unassigned_home_tasks.get(tgt_quad, 0)
                target_needs_assistance = (rem_target_tasks > free_in_target)

                for u in cand_workers:
                    u_pos = pos_by_idx[u]
                    u_quad = farm.quadrant_of(u_pos) if hasattr(farm, "quadrant_of") else "NW"
                    d = manhattan_dist(u_pos, tgt)

                    # Invariant: Prohibit diagonal cross-regional traversal (SW <-> NE)
                    if (u_quad == "SW" and tgt_quad == "NE") or (u_quad == "NE" and tgt_quad == "SW"):
                        if tgt not in SHED_ACCESS_TILES:
                            continue

                    # Invariant: Distance cap for cross-quadrant spillover
                    if u_quad != tgt_quad and tgt not in SHED_ACCESS_TILES and d > C2_MAX_SPILLOVER_DIST:
                        continue

                    # Dynamic regional budget check:
                    # Workers in NW/NE should not cross to SW unless origin core commitments are safe
                    is_cross_quad = (u_quad in ("NW", "NE") and tgt_quad == "SW" and tgt not in SHED_ACCESS_TILES)
                    if is_cross_quad:
                        origin_tasks_count = sum(
                            1 for rem_t in remaining_tasks
                            if farm.quadrant_of(tuple(rem_t.get("target") or (0, 0))) in ("NW", "NE")
                        )
                        if origin_tasks_count > 0:
                            self._telemetry["cross_region_transfers_denied"] += 1
                            continue
                        self._telemetry["cross_region_transfers_authorized"] += 1

                    # Locality penalty
                    is_local = (u_quad == tgt_quad) or (tgt in SHED_ACCESS_TILES)
                    if is_local:
                        locality_penalty = 0.0
                    else:
                        rem_local_tasks = unassigned_home_tasks.get(u_quad, 0)
                        if rem_local_tasks <= 0:
                            locality_penalty = 0.0
                        elif target_needs_assistance:
                            locality_penalty = 3.0
                        else:
                            locality_penalty = 10.0

                    # Route continuity bonus
                    continuity_bonus = 0.0
                    if u in active_missions:
                        m = active_missions[u]
                        if tuple(m.get("target", (-1, -1))) == tgt and m.get("op") == task.get("op"):
                            continuity_bonus = 6.0

                    # Same-tile & immediate cluster bonus
                    cluster_bonus = 0
                    if d <= C6_CLUSTER_RADIUS:
                        cluster_bonus += C6_CLUSTER_BONUS
                    if d == 0:
                        cluster_bonus += C6_CLUSTER_BONUS

                    effective_score = -prio + locality_penalty - continuity_bonus + C6_TRAVEL_WEIGHT * (d - cluster_bonus)
                    match_key = (effective_score, d, tgt, u)
                    if best_match is None or match_key < best_match[0]:
                        best_match = (match_key, u, task, tgt_quad)

            if best_match is None:
                # No more valid assignments in this band
                for t in band_tasks:
                    remaining_tasks.remove(t)
                    unassigned_tasks.append(t)
                continue

            _, chosen_u, chosen_task, t_quad = best_match
            busy.add(chosen_u)
            remaining_tasks.remove(chosen_task)
            if t_quad in unassigned_home_tasks:
                unassigned_home_tasks[t_quad] = max(0, unassigned_home_tasks[t_quad] - 1)

            # SW task admission disposition
            if t_quad == "SW" and chosen_task.get("target") not in SHED_ACCESS_TILES and sw_admission_enabled:
                try:
                    from execution.sw_task_admission_controller import get_sw_task_admission_telemetry
                    telem = get_sw_task_admission_telemetry()
                    c_op = chosen_task.get("op", "")
                    c_tgt = tuple(chosen_task.get("target") or (0, 0))
                    c_item = (chosen_task.get("args") or [None])[0]
                    c_task_id = f"SW_{step}_{c_op}_{c_tgt}_{c_item}"
                    telem.record_sw_task_disposition(c_task_id, "SELECTED_AND_ASSIGNED")
                except Exception:
                    pass

            # Rule W2: SW squad workers anchor shed PICKUP at PORT_SW
            if chosen_u in sw_units and chosen_task.get("op") == "PICKUP" and chosen_task.get("target") in SHED_ACCESS_TILES:
                chosen_task["target"] = PORT_SW

            chosen_task["unit_pos"] = pos_by_idx[chosen_u]
            assignment[chosen_u] = chosen_task
            self._telemetry["stage2_economic_assignments"] += 1

            # Record mission if multi-turn travel is required
            tgt_pos = tuple(chosen_task.get("target") or pos_by_idx[chosen_u])
            if (chosen_task.get("op") != "PASS" and
                chosen_task.get("kind") not in ("sw_anchor", "fallback_fert", "fallback_water", "fallback_dig") and
                pos_by_idx[chosen_u] != tgt_pos):
                init_d = manhattan_dist(pos_by_idx[chosen_u], tgt_pos)
                active_missions[chosen_u] = {
                    "task": dict(chosen_task),
                    "target": chosen_task.get("target"),
                    "op": chosen_task["op"],
                    "kind": chosen_task.get("kind", ""),
                    "args": chosen_task.get("args", []),
                    "priority": chosen_task.get("priority", 0),
                    "prev_distance": init_d,
                    "consecutive_no_progress": 0,
                    "mission_age": 0,
                    "steps_active": 0,
                }
                if tracker is not None:
                    try:
                        from execution.mission_ownership_tracker import compute_task_obligation_id
                    except ImportError:
                        from agent.execution.mission_ownership_tracker import compute_task_obligation_id
                    obl_id = compute_task_obligation_id(
                        day, chosen_task.get("op", "PASS"), tgt_pos, chosen_task.get("kind", ""), chosen_task.get("args"), chosen_task.get("meta")
                    )
                    tracker.claim_or_continue_mission(chosen_u, obl_id, chosen_task, pos_by_idx[chosen_u], step)

        return assignment, busy, unassigned_tasks + remaining_tasks


# Singleton controller
_COORDINATED_DISPATCH_CONTROLLER: Optional[CoordinatedDispatchController] = None


def get_coordinated_dispatch_controller() -> CoordinatedDispatchController:
    global _COORDINATED_DISPATCH_CONTROLLER
    if _COORDINATED_DISPATCH_CONTROLLER is None:
        _COORDINATED_DISPATCH_CONTROLLER = CoordinatedDispatchController()
    return _COORDINATED_DISPATCH_CONTROLLER


def reset_coordinated_dispatch_controller() -> None:
    global _COORDINATED_DISPATCH_CONTROLLER
    if _COORDINATED_DISPATCH_CONTROLLER is not None:
        _COORDINATED_DISPATCH_CONTROLLER.reset()
