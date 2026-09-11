"""Summarize SW acquisition and occupancy in the archived leader matches."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    results = []
    seen = set()
    for path in sorted((ROOT / "replays/crop_dusta").rglob("*.json")):
        if path.stem in seen or not path.stem.isdigit():
            continue
        replay = json.loads(path.read_text(encoding="utf-8-sig"))
        steps = replay.get("steps", [])
        if not steps:
            continue
        seen.add(path.stem)
        info = replay.get("info", {})
        players = []
        for player in (0, 1):
            samples, purchase = [], None
            for step in steps:
                obs = step[0].get("observation", {})
                farms = obs.get("farms", [])
                if len(farms) <= player:
                    continue
                farm = farms[player]
                if "SW" not in farm.get("unlocked_quadrants", []):
                    continue
                if purchase is None:
                    purchase = [obs.get("day"), obs.get("hour")]
                tiles = [farm["tiles"][y][x] for y in range(5, 10) for x in range(5)]
                samples.append(sum(isinstance(t, dict) and t.get("kind") in
                                   ("PLANT", "PASTURE", "COOP") for t in tiles) / 25)
            players.append({"seat": player, "first_sw_observation": purchase,
                            "sw_utilization": sum(samples) / len(samples) if samples else None})
        results.append({"replay": str(path.relative_to(ROOT)), "info": info, "players": players})
    output = ROOT / "simulations/results/sw_timing_20260911/leader_replays.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
