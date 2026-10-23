"""Per-agentId routing to ROLE + correct skill file, for BOTH teams.

Dynamic roles (feat/dynamic-roles): the role is NOT a fixed id->position map
anymore. player 0 is ALWAYS GK and player 1 ALWAYS DEF; players 2/3/4 take the
chosen strategy's formation distribution via formation_roles. These tests pin
the strategy to ``balanced`` (formation 2-1-1 -> roles 0=GK,1=DEF,2=DEF,3=MID,
4=FWD) and assert:
  - each player loads the role body the formation implies (via the ROLE-unique
    body marker, no cross-wiring);
  - BOTH resolution branches: (a) payload-supplied myPlayers, (b) the pinned
    MY_PLAYER_ID production branch with myPlayers omitted;
  - BOTH teams: team 0 HOME and team 1 AWAY.

Pure: no AWS, no network, no real strands.
"""

import asyncio
import copy
import json

import pytest

from test_helpers import GAME_STATE, mock_agentcore_gateway

mock_agentcore_gateway()

import constants  # noqa: E402
import formation_roles  # noqa: E402
import plugin_loader  # noqa: E402
import unified_agent  # noqa: E402
from parsing import VALID_COMMANDS  # noqa: E402


class _FakeApp:
    class logger:
        @staticmethod
        def info(msg): pass
        @staticmethod
        def warn(msg): pass
        @staticmethod
        def error(msg): pass

    def entrypoint(self, fn):
        return fn


# Role -> UNIQUE marker taken from the real plugins/<role>/balanced.md bodies.
ROLE_MARKER = {
    "GK": "Goalkeeper",
    "DEF": "Defender",
    "MID": "Midfielder",
    "FWD": "Forward (Striker)",
}

# Markers that must NOT appear (would mean cross-wiring to another role body).
OTHER_MARKERS = {
    "GK": ["Defender", "Midfielder", "Forward (Striker)"],
    "DEF": ["Goalkeeper", "Midfielder", "Forward (Striker)"],
    "MID": ["Goalkeeper", "Forward (Striker)"],
    "FWD": ["Goalkeeper"],
}

# balanced's formation (2-1-1) -> the role each player resolves to.
_BALANCED_FORMATION = plugin_loader.strategy_meta("balanced").formation
_ROLES = formation_roles.formation_roles(_BALANCED_FORMATION, flex=False)


def _collect(invoke, payload):
    async def _run():
        out = []
        async for chunk in invoke(payload, None):
            out.append(chunk)
        return out

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def _capturing_factory(captured):
    def factory(system_prompt=None, tools=None, **kwargs):
        captured["system_prompt"] = system_prompt
        return lambda prompt, **kw: '[{"commandType": "MOVE_TO", "parameters": {"target_x": 0, "target_y": 0}}]'

    return factory


def _state_for_team(team_id):
    """A game state where the ball is free, so every role has a sane tick."""
    gs = copy.deepcopy(GAME_STATE)
    gs["ball"]["isFree"] = True
    gs["ball"].pop("possessionAgentId", None)
    return gs


@pytest.mark.parametrize("player_id", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("team_id", [0, 1])
def test_routing_supplied_myplayers(player_id, team_id):
    """Branch (a): payload supplies myPlayers -> effective_pid from payload."""
    expected_role = _ROLES[player_id]
    captured = {}

    # Register pinned to a DIFFERENT id to prove myPlayers wins when present.
    pinned = (player_id + 1) % 5
    invoke = unified_agent.register(_FakeApp(), pinned, agent_factory=_capturing_factory(captured))

    payload = {
        "prompt": {
            "teamId": team_id,
            "gameState": _state_for_team(team_id),
            "myPlayers": [player_id],
            "strategy": "balanced",
        }
    }
    out = _collect(invoke, payload)

    prompt = captured["system_prompt"]
    assert ROLE_MARKER[expected_role] in prompt
    for bad in OTHER_MARKERS[expected_role]:
        assert bad not in prompt, f"{expected_role} prompt leaked marker {bad!r}"

    parsed = json.loads(out[0])
    assert parsed[0]["playerId"] == player_id
    assert parsed[0]["teamId"] == team_id
    assert parsed[0]["commandType"] in VALID_COMMANDS


@pytest.mark.parametrize("player_id", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("team_id", [0, 1])
def test_routing_pinned_id_myplayers_absent(player_id, team_id):
    """Branch (b): production wiring — myPlayers omitted, pinned id resolves."""
    expected_role = _ROLES[player_id]
    captured = {}

    invoke = unified_agent.register(_FakeApp(), player_id, agent_factory=_capturing_factory(captured))

    payload = {
        "prompt": {
            "teamId": team_id,
            "gameState": _state_for_team(team_id),
            # myPlayers deliberately omitted
            "strategy": "balanced",
        }
    }
    out = _collect(invoke, payload)

    prompt = captured["system_prompt"]
    assert ROLE_MARKER[expected_role] in prompt
    for bad in OTHER_MARKERS[expected_role]:
        assert bad not in prompt

    parsed = json.loads(out[0])
    assert parsed[0]["playerId"] == player_id
    assert parsed[0]["teamId"] == team_id


def test_player0_is_always_gk_and_player1_always_def():
    # The hard pin holds regardless of the formation the strategy declares.
    assert _ROLES[0] == "GK"
    assert _ROLES[1] == "DEF"
