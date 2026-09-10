"""CI Regression Test: Multi-file vs Standalone Single-file Submission Parity.

Verifies bit-for-bit identical actions between:
- submission/main.py (multi-file package)
- dist/submission.py (standalone bundled submission)
across all 720 steps under deterministic engine conditions.
"""

import copy
import importlib.util
import os
import sys
import pytest
import kaggle_environments


def _load_agent_module(module_name: str, file_path: str):
    """Safely load an agent module and register in sys.modules for dataclass compatibility."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_submission_action_parity_720_turns():
    """Verify 100% exact action equivalence between multi-file and standalone agent over 720 turns."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    multi_file_path = os.path.join(repo_root, "submission", "main.py")
    dist_file_path = os.path.join(repo_root, "dist", "submission.py")

    assert os.path.exists(multi_file_path), f"Missing {multi_file_path}"
    assert os.path.exists(dist_file_path), f"Missing {dist_file_path}"

    mod_multi = _load_agent_module("parity_multi", multi_file_path)
    mod_dist = _load_agent_module("parity_dist", dist_file_path)

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": 11},
    )
    env.reset(2)

    step = 0
    while not env.done and step < 720:
        obs = env.state[0].observation
        obs_copy1 = copy.deepcopy(obs)
        obs_copy2 = copy.deepcopy(obs)

        act_multi = mod_multi.agent(obs_copy1, env.configuration)
        act_dist = mod_dist.agent(obs_copy2, env.configuration)

        if act_multi != act_dist:
            day = step // 24
            hour = step % 24
            pytest.fail(
                f"Parity mismatch at step {step} (Day {day}, Hour {hour:02d})!\n"
                f"Multi-file action: {act_multi}\n"
                f"Standalone action: {act_dist}\n"
                f"Multi-file fallback: {getattr(mod_multi, 'get_last_fallback_diagnostic', lambda: None)()}\n"
                f"Standalone fallback: {getattr(mod_dist, 'get_last_fallback_diagnostic', lambda: None)()}\n"
                f"Multi-file opp diag: {getattr(mod_multi, 'get_opponent_model_diagnostics', lambda: None)()}\n"
                f"Standalone opp diag: {getattr(mod_dist, 'get_opponent_model_diagnostics', lambda: None)()}"
            )

        env.step([act_multi, None])
        step += 1

    assert step >= 719, f"Match terminated prematurely at step {step}"
