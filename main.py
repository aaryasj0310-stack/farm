"""Kaggriculture Root Entry Point Proxy.

Delegates all decision-making directly to the modular agent in `agent/main.py`.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

# Ensure project root and agent directory are on sys.path
_CWD = os.getcwd()
if _CWD not in sys.path:
    sys.path.insert(0, _CWD)

_AGENT_DIR = os.path.join(_CWD, "agent")
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
for _sub in ("state", "strategy", "execution", "market"):
    _sub_path = os.path.join(_AGENT_DIR, _sub)
    if os.path.exists(_sub_path) and _sub_path not in sys.path:
        sys.path.insert(0, _sub_path)

from agent.main import agent as _agent_entrypoint


def agent(obs: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Official competition entry point forwarding to agent/main.py."""
    return _agent_entrypoint(obs, config)
