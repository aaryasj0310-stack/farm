"""Authoritative Post-Transition Animal Survival and Starvation Telemetry Tracker.

Monitors animal survival, feeding compliance, rollover transitions, and feed buffer integrity.
Reconciles pre-rollover state (Hour 23) with post-rollover observation (Hour 0) using engine ground truth:
- Engine rule: In _daily_refresh_animals(farm, day), consecutive_unfed is incremented if fed_today is False.
- If consecutive_unfed >= 2, the animal escapes/dies: tile['animal'] is deleted, structure remains.
- Distinguishes:
  1. Hourly unfed observations (normal intraday work queue before feeding)
  2. Missed feeding days (animal reached Hour 23 without being fed)
  3. Confirmed starvation deaths / escapes (animal removed at midnight after consecutive_unfed >= 2)
  4. Ambiguous disappearances (animal disappeared without consecutive_unfed explanation)
  5. Continuous feed-floor preservation (whether wheat buffer >= max(10, animals * 2) at every turn)
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set, Tuple


class AnimalSurvivalTracker:
    """Rigorous turn-by-turn tracker for animal survival and feed floor preservation."""

    def __init__(self, seat: int = 0) -> None:
        self.seat = seat
        self.reset()

    def reset(self) -> None:
        """Reset all tracking metrics for a new game episode."""
        self.total_turns = 0
        self.peak_herd_size = 0
        self.final_herd_size = 0
        self.confirmed_starvation_deaths = 0
        self.confirmed_escapes = 0
        self.ambiguous_disappearances = 0
        self.missed_feeding_days = 0
        self.hourly_unfed_observations = 0

        self.min_shed_wheat_observed = 999
        self.min_total_feed_wheat_observed = 999
        self.feed_floor_breach_turns = 0
        self.rollover_reconciliations_count = 0

        self.loss_events: List[Dict[str, Any]] = []
        self.feed_breach_events: List[Dict[str, Any]] = []

        # Internal state for rollover reconciliation
        self._last_day: int = -1
        self._last_hour: int = -1
        self._pre_rollover_snapshot: Optional[Dict[Tuple[int, int], Dict[str, Any]]] = None
        self._pre_rollover_day: int = -1

    def observe_turn(self, obs: Dict[str, Any]) -> None:
        """Process turn observation for the monitored player farm."""
        self.total_turns += 1
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        step = obs.get("step", day * 24 + hour)

        farms = obs.get("farms", [])
        if self.seat >= len(farms):
            return
        my_farm = farms[self.seat]
        tiles = my_farm.get("tiles", [])
        private = obs.get("private", {})
        shed = private.get("shed", {})
        inventories = private.get("inventories", [])

        # 1. Inspect current living animals on farm
        current_animals: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for y, row in enumerate(tiles):
            for x, cell in enumerate(row):
                if isinstance(cell, dict) and "animal" in cell and cell.get("animal"):
                    pos = (x, y)
                    current_animals[pos] = {
                        "pos": pos,
                        "animal": cell.get("animal"),
                        "kind": cell.get("kind"),
                        "consecutive_unfed": cell.get("consecutive_unfed", 0),
                        "fed_today": bool(cell.get("fed_today", False)),
                        "placed_day": cell.get("placed_day", 0),
                    }
                    if not cell.get("fed_today", False):
                        self.hourly_unfed_observations += 1

        herd_size = len(current_animals)
        self.peak_herd_size = max(self.peak_herd_size, herd_size)
        self.final_herd_size = herd_size

        # 2. Track feed wheat buffer
        shed_wheat = int(shed.get("WHEAT", 0))
        carried_wheat = sum(int(inv.get("WHEAT", 0)) for inv in inventories if isinstance(inv, dict))
        total_wheat = shed_wheat + carried_wheat

        self.min_shed_wheat_observed = min(self.min_shed_wheat_observed, shed_wheat)
        self.min_total_feed_wheat_observed = min(self.min_total_feed_wheat_observed, total_wheat)

        safe_feed_reserve = max(10, herd_size * 2) if herd_size > 0 else 0
        if herd_size > 0 and total_wheat < safe_feed_reserve:
            self.feed_floor_breach_turns += 1
            if len(self.feed_breach_events) < 50:
                self.feed_breach_events.append({
                    "step": step,
                    "day": day,
                    "hour": hour,
                    "herd_size": herd_size,
                    "total_wheat": total_wheat,
                    "shed_wheat": shed_wheat,
                    "safe_feed_reserve": safe_feed_reserve,
                    "deficit": safe_feed_reserve - total_wheat,
                })

        # 3. Post-Rollover Reconciliation (at Hour 0 of new day)
        if hour == 0 and self._pre_rollover_snapshot is not None and day == (self._pre_rollover_day + 1):
            self.rollover_reconciliations_count += 1
            for pos, pre_data in self._pre_rollover_snapshot.items():
                if pos in current_animals:
                    # Animal is still present
                    cur_data = current_animals[pos]
                    if cur_data["animal"] != pre_data["animal"]:
                        # Mismatched species at same position
                        self.ambiguous_disappearances += 1
                        self.loss_events.append({
                            "type": "SPECIES_MUTATION",
                            "step": step,
                            "day": day,
                            "pos": list(pos),
                            "expected_species": pre_data["animal"],
                            "actual_species": cur_data["animal"],
                        })
                else:
                    # Animal disappeared across midnight rollover!
                    # Inspect what is at (x, y) now
                    x, y = pos
                    post_tile = tiles[y][x] if y < len(tiles) and x < len(tiles[y]) else None
                    was_unfed = not pre_data["fed_today"]
                    pre_unfed_count = pre_data["consecutive_unfed"]

                    if was_unfed and pre_unfed_count >= 1:
                        # Engine rule: consecutive_unfed reached >= 2 -> escape / death!
                        self.confirmed_starvation_deaths += 1
                        self.confirmed_escapes += 1
                        self.loss_events.append({
                            "type": "CONFIRMED_STARVATION_DEATH",
                            "step": step,
                            "day": day,
                            "pos": list(pos),
                            "species": pre_data["animal"],
                            "pre_consecutive_unfed": pre_unfed_count,
                            "post_tile": copy.deepcopy(post_tile),
                            "reason": f"Animal reached consecutive_unfed >= 2 at rollover from Day {self._pre_rollover_day} to Day {day}",
                        })
                    elif isinstance(post_tile, dict) and post_tile.get("kind") in ("PASTURE", "COOP"):
                        # Structure remains, but animal is missing
                        self.confirmed_escapes += 1
                        self.loss_events.append({
                            "type": "STRUCTURE_WITHOUT_ANIMAL",
                            "step": step,
                            "day": day,
                            "pos": list(pos),
                            "species": pre_data["animal"],
                            "pre_unfed_count": pre_unfed_count,
                            "post_tile": copy.deepcopy(post_tile),
                            "reason": f"Structure {post_tile.get('kind')} remains without animal",
                        })
                    else:
                        # Tile changed unexpectedly
                        self.ambiguous_disappearances += 1
                        self.loss_events.append({
                            "type": "AMBIGUOUS_DISAPPEARANCE",
                            "step": step,
                            "day": day,
                            "pos": list(pos),
                            "species": pre_data["animal"],
                            "pre_unfed_count": pre_unfed_count,
                            "post_tile": copy.deepcopy(post_tile),
                            "reason": f"Animal tile mutated or vanished to {post_tile}",
                        })
            self._pre_rollover_snapshot = None

        # 4. Pre-Rollover Snapshot (at Hour 23)
        if hour == 23:
            self._pre_rollover_snapshot = copy.deepcopy(current_animals)
            self._pre_rollover_day = day
            for anim in current_animals.values():
                if not anim["fed_today"]:
                    self.missed_feeding_days += 1

        self._last_day = day
        self._last_hour = hour

    def get_summary(self) -> Dict[str, Any]:
        """Compile complete animal survival and feed floor preservation metrics."""
        # confirmed_escapes includes confirmed_starvation_deaths and any non-starvation structural escapes
        total_losses = self.confirmed_escapes + self.ambiguous_disappearances
        continuous_feed_floor = (self.feed_floor_breach_turns == 0)

        return {
            "monitored_seat": self.seat,
            "total_turns": self.total_turns,
            "peak_herd_size": self.peak_herd_size,
            "final_herd_size": self.final_herd_size,
            "confirmed_starvation_deaths": self.confirmed_starvation_deaths,
            "confirmed_escapes": self.confirmed_escapes,
            "ambiguous_disappearances": self.ambiguous_disappearances,
            "total_animal_losses": total_losses,
            "missed_feeding_days": self.missed_feeding_days,
            "hourly_unfed_observations": self.hourly_unfed_observations,
            "rollover_reconciliations_count": self.rollover_reconciliations_count,
            "min_shed_wheat_observed": self.min_shed_wheat_observed if self.min_shed_wheat_observed < 999 else 0,
            "min_total_feed_wheat_observed": self.min_total_feed_wheat_observed if self.min_total_feed_wheat_observed < 999 else 0,
            "feed_floor_breach_turns": self.feed_floor_breach_turns,
            "continuous_feed_floor_preserved": continuous_feed_floor,
            "loss_events_count": len(self.loss_events),
            "loss_events": self.loss_events,
        }
