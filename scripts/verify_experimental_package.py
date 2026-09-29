"""Build/test experimental source in temp storage without changing production artifacts."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def validate_seed(seed):
    if 98001 <= seed <= 98050:
        raise ValueError("Protected validation seeds must not be used")


def engine_gate(result):
    return (result["statuses"] == ["DONE", "DONE"] and result["steps"] == 720
            and not result["errors"] and not result["fallbacks"]
            and result["max_market_orders"] <= 10 and not result["escapes"])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def child(package, output, seed):
    # -I removes cwd/PYTHONPATH; only the extracted package is added.
    sys.path.insert(0, str(package))
    import main
    import config
    from kaggle_environments import make
    import kaggle_environments.envs.kaggriculture.kaggriculture as engine

    flags = {k: v for k, v in vars(config).items()
             if k.isupper() and "SW" in k and isinstance(v, bool)}
    assert flags and not any(flags.values()), flags
    assert config.SW_FORWARD_ARCHITECTURE_MODE == "OFF"
    calls, fallbacks = [], []

    def checked_agent(obs, configuration):
        action = main.agent(obs, configuration)
        calls.append(len(action.get("market", [])))
        if action.get("_emergency_fallback"):
            fallbacks.append({"step": obs.get("step"),
                              "diagnostic": main.get_last_fallback_diagnostic()})
        return action

    env = make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720}, debug=True)
    env.run([checked_agent, "random"])
    escapes, unfed = [], []
    previous = {}
    for index, state in enumerate(env.steps):
        tiles = state[0].observation["farms"][0]["tiles"]
        animals = {(x, y): t for y, row in enumerate(tiles) for x, t in enumerate(row)
                   if isinstance(t, dict) and t.get("animal")}
        for pos, old in previous.items():
            if pos not in animals and old.get("consecutive_unfed", 0) >= 1 and not old.get("fed_today"):
                escapes.append({"step": index, "position": pos, "animal": old["animal"]})
        unfed.extend({"step": index, "position": pos} for pos, tile in animals.items()
                     if tile.get("consecutive_unfed", 0) >= 1)
        previous = animals
    origins = {}
    for name, module in list(sys.modules.items()):
        source = getattr(module, "__file__", None)
        if not source:
            continue
        path = Path(source).resolve()
        if path.is_relative_to(package):
            origins[name] = str(path)
        elif name in ("main", "config") or name.split(".")[0] in ("agent", "state", "strategy", "execution", "market", "diagnostics"):
            raise AssertionError(f"Runtime import escaped package: {name}: {path}")
    assert Path(main.__file__).resolve().is_relative_to(package)
    result = {
        "seed": seed, "opponent": "random", "steps": len(env.steps), "calls": len(calls),
        "statuses": [s.status for s in env.steps[-1]],
        "errors": [{"step": i, "player": p, "status": s.status}
                   for i, states in enumerate(env.steps) for p, s in enumerate(states)
                   if s.status in ("ERROR", "INVALID", "TIMEOUT")],
        "fallbacks": fallbacks, "max_market_orders": max(calls, default=0),
        "escapes": escapes, "unfed_animal_hours": len(unfed),
        "unfed_note": "Observed consecutive_unfed >= 1; single unfed days are not classified as escapes.",
        "final_cash": [f["money"] for f in env.steps[-1][0].observation["farms"]],
        "sw_boolean_flags": flags, "sw_architecture_mode": config.SW_FORWARD_ARCHITECTURE_MODE,
        "runtime_module_origins": origins, "engine_file": engine.__file__,
        "engine_sha256": digest(engine.__file__),
    }
    result["passed"] = engine_gate(result)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1


def run(output, seed):
    validate_seed(seed)
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("experimental_builder", repo / "scripts/build_submission.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    # Experimental diagnostics are not included in the canonical builder's list.
    # Extend this private imported instance; canonical build behavior is untouched.
    builder.RUNTIME_SUBPACKAGES = [*builder.RUNTIME_SUBPACKAGES, "diagnostics"]
    protected = [repo / "dist/submission.zip", *sorted((repo / "submission").rglob("*.py"))]
    before = {p.relative_to(repo).as_posix(): digest(p) for p in protected}
    with tempfile.TemporaryDirectory(prefix="kaggri-g0-") as temp:
        temp = Path(temp)
        package = temp / "package"
        files = builder.sync_agent_to_submission(str(repo / "agent"), str(package))
        artifact = Path(builder.package_submission_zip(str(package), str(temp / "dist")))
        extracted = temp / "extracted"
        with zipfile.ZipFile(artifact) as archive:
            archive.extractall(extracted)
        manifest = {p.replace("\\", "/"): digest(repo / "agent" / p) for p in sorted(files)}
        for p in files:
            assert (extracted / p).read_bytes() == (repo / "agent" / p).read_bytes().removeprefix(b"\xef\xbb\xbf")
            compile((extracted / p).read_bytes(), p, "exec")
        child_output = temp / "result.json"
        completed = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()),
                                    "--child", str(extracted), "--output", str(child_output),
                                    "--seed", str(seed)], cwd=temp, capture_output=True, text=True)
        result = json.loads(child_output.read_text()) if child_output.exists() else {"passed": False}
        result.update(source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                      runtime_source_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                      source_file_sha256=manifest, package_sha256=digest(artifact),
                      subprocess_returncode=completed.returncode,
                      subprocess_stdout_tail=completed.stdout[-4000:], subprocess_stderr=completed.stderr)
    after = {p.relative_to(repo).as_posix(): digest(p) for p in protected}
    result["protected_files_unchanged"] = before == after
    result["production_zip_sha256"] = after["dist/submission.zip"]
    result["passed"] = bool(result["passed"] and completed.returncode == 0 and before == after)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result.get(k) for k in ("passed", "steps", "statuses", "final_cash", "protected_files_unchanged")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--output", type=Path, default=Path("reports/phase_sw_c2/g0_experimental_package.json"))
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    validate_seed(args.seed)
    sys.exit(child(args.child.resolve(), args.output, args.seed) if args.child else run(args.output, args.seed))
