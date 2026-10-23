"""Shared test setup: path wiring + fixtures.

Centralizes the sys.path manipulation so individual test files don't repeat it,
and re-exports the GAME_STATE fixture and AgentCore mocks from the shared lib.
"""

import copy
import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
_SRC = os.path.normpath(os.path.join(_HERE, "..", "src"))

# Shared kernel (state, parsing, fallback, agent_base)
sys.path.insert(0, os.path.join(_SRC, "commons"))
# tests/ dir itself → `from test_helpers import ...`
sys.path.insert(0, _HERE)
# src root → `from plugins import registry`
sys.path.insert(0, _SRC)
# unified agent package (constants, planner, plugin_loader)
sys.path.insert(0, os.path.join(_SRC, "agents", "players"))
# general plugin scripts
sys.path.insert(0, os.path.join(_SRC, "plugins", "general", "scripts"))

from test_helpers import GAME_STATE, TEAM_ID  # noqa: E402


@pytest.fixture
def game_state():
    """A fresh deep copy of the shared game-state fixture per test."""
    return copy.deepcopy(GAME_STATE)


@pytest.fixture
def team_id():
    return TEAM_ID
