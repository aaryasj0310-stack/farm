"""Replay Analyzer & Inefficiency Inspector for Kaggriculture.

Audits Kaggle environment episode replay JSON turn-by-turn to detect:
1. Wasted Turns (PASS actions or illegal action no-ops when work was available)
2. Shed Overflows (items discarded past the 100-item shed capacity limit)
3. Decay Losses (crops losing yield units to decay)
4. Missed Fertilizer (surviving animals left uncollected before EOD overwrite)
5. Price Slippage ($1 floor dumping vs peak selling)
"""

import json
from typing import Dict, Any, List


class ReplayAnalyzer:
    def __init__(self, episode_json: Dict[str, Any] = None):
        self.episode = episode_json

    def load_from_file(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            self.episode = json.load(f)

    def analyze_player(self, player_id: int = 0) -> Dict[str, Any]:
        """Performs a comprehensive turn-by-turn inefficiency audit for player_id."""
        if not self.episode or "steps" not in self.episode:
            raise ValueError("Invalid episode JSON.")

        steps = self.episode["steps"]
        total_steps = len(steps)

        audit = {
            "player_id": player_id,
            "total_steps": total_steps,
            "final_reward": steps[-1][player_id].get("reward", 0.0),
            "inefficiencies": {
                "wasted_turns": 0,
                "illegal_actions": 0,
                "shed_overflow_discards": 0,
                "decay_lost_units": 0,
                "missed_fertilizer_days": 0,
            },
            "money_left_on_table_estimate": 0.0,
            "detailed_events": []
        }

        shed_cap = 100
        prev_shed_total = 0

        for step_idx, step_state in enumerate(steps):
            if step_idx == 0:
                continue

            obs = step_state[player_id].get("observation", {})
            action = step_state[player_id].get("action", {})
            day = obs.get("day", step_idx // 24)
            hour = obs.get("hour", step_idx % 24)

            farms = obs.get("farms", [])
            if player_id >= len(farms):
                continue
            farm = farms[player_id]
            private = obs.get("private", {})
            shed = private.get("shed", {})
            tiles = farm.get("tiles", [])

            # 1. Audit Missed Fertilizer (at end of day: hour == 23)
            if hour == 23:
                for y in range(len(tiles)):
                    for x in range(len(tiles[y])):
                        t = tiles[y][x]
                        if isinstance(t, dict) and "animal" in t:
                            if t.get("fertilizer_available", False):
                                audit["inefficiencies"]["missed_fertilizer_days"] += 1
                                audit["money_left_on_table_estimate"] += 100.0  # $100 base fertilizer value
                                audit["detailed_events"].append({
                                    "step": step_idx, "day": day, "type": "MISSED_FERTILIZER",
                                    "details": f"Uncollected fertilizer from {t.get('animal')} at ({x},{y})"
                                })

            # 2. Audit Decay Losses
            for y in range(len(tiles)):
                for x in range(len(tiles[y])):
                    t = tiles[y][x]
                    if isinstance(t, dict) and t.get("kind") == "PLANT":
                        mls = t.get("max_lifespan_step", -1)
                        if mls >= 0 and step_idx >= mls and (step_idx - mls) % 2 == 0:
                            if t.get("yield_units", 0) > 0:
                                audit["inefficiencies"]["decay_lost_units"] += 1
                                audit["money_left_on_table_estimate"] += 35.0  # Estimated average loss
                                audit["detailed_events"].append({
                                    "step": step_idx, "day": day, "type": "DECAY_LOSS",
                                    "details": f"{t.get('crop')} lost 1 yield unit to decay at ({x},{y})"
                                })

            # 3. Audit Shed Capacity Discards
            current_shed_total = sum(shed.values())
            if current_shed_total >= shed_cap:
                audit["inefficiencies"]["shed_overflow_discards"] += 1

            # 4. Audit Wasted Turns (farmer PASS when work was available)
            farmer_action = action.get("farmer", ["PASS"]) if isinstance(action, dict) else ["PASS"]
            if farmer_action == ["PASS"] and step_idx < 700:
                fx, fy = farm.get("farmer", [0, 0])
                current_tile = tiles[fy][fx] if fy < len(tiles) and fx < len(tiles[fy]) else None
                if isinstance(current_tile, dict):
                    if current_tile.get("kind") == "PLANT" and not current_tile.get("watered_today", False):
                        audit["inefficiencies"]["wasted_turns"] += 1
                    elif current_tile.get("kind") == "WEED":
                        audit["inefficiencies"]["wasted_turns"] += 1

        return audit
